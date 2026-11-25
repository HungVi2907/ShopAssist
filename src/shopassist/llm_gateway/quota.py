"""Worker-local quota admission and reservation accounting."""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from shopassist.llm_gateway.config import Limits
from shopassist.llm_gateway.errors import ReasonCode
from shopassist.llm_gateway.schemas import GatewayUsage


@dataclass
class _ProfileBudget:
    day: int
    requests: deque[float] = field(default_factory=deque)
    tokens_used: int = 0
    cost_used: Decimal = Decimal(0)


@dataclass
class QuotaReservation:
    token: str
    profile_id: str
    limits: Limits
    reserved_tokens: int | None
    reserved_cost: Decimal | None
    day: int
    dispatched: bool = False
    finished: bool = False


class ProviderQuotaManager:
    """Atomically reserve request, concurrency, token and cost budgets.

    The profile key must identify a configured provider profile without
    containing credential material. Accounting is per worker and deliberately
    does not claim to know upstream vendor quota.
    """

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic,
                 utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.monotonic = monotonic
        self.utc_now = utc_now
        self._lock = threading.RLock()
        self._budgets: dict[str, _ProfileBudget] = {}
        self._reservations: dict[str, QuotaReservation] = {}

    def _now(self) -> tuple[float, int]:
        now_utc = self.utc_now()
        if now_utc.tzinfo is None:
            raise ValueError("UTC clock must be timezone-aware")
        return self.monotonic(), now_utc.astimezone(timezone.utc).date().toordinal()

    def _budget(self, profile_id: str, day: int) -> _ProfileBudget:
        state = self._budgets.get(profile_id)
        if state is None or state.day != day:
            # UTC day rollover resets token/cost totals, but request-rate
            # admission remains a true rolling 60-second window.
            state = _ProfileBudget(day=day, requests=state.requests if state is not None else deque())
            self._budgets[profile_id] = state
        return state

    def _active(self, profile_id: str) -> list[QuotaReservation]:
        return [item for item in self._reservations.values() if item.profile_id == profile_id and not item.finished]

    def reserve(self, profile_id: str, limits: Limits, *, estimated_max_tokens: int | None = None,
                estimated_max_cost_usd: Decimal | None = None) -> QuotaReservation | ReasonCode:
        """Reserve admission atomically; deny hard caps without an estimate."""
        if not isinstance(profile_id, str) or not profile_id or len(profile_id) > 128:
            raise ValueError("Invalid provider profile")
        if estimated_max_tokens is not None and (isinstance(estimated_max_tokens, bool) or estimated_max_tokens < 0):
            raise ValueError("Invalid token estimate")
        if estimated_max_cost_usd is not None and (not estimated_max_cost_usd.is_finite() or estimated_max_cost_usd < 0):
            raise ValueError("Invalid cost estimate")
        now_mono, day = self._now()
        with self._lock:
            budget = self._budget(profile_id, day)
            while budget.requests and now_mono - budget.requests[0] >= 60:
                budget.requests.popleft()
            active = self._active(profile_id)
            pending_requests = sum(not reservation.dispatched for reservation in active)
            if limits.requests_per_minute is not None and len(budget.requests) + pending_requests >= limits.requests_per_minute:
                return ReasonCode.QUOTA_EXHAUSTED
            if limits.max_in_flight is not None and len(active) >= limits.max_in_flight:
                return ReasonCode.CAPACITY_EXHAUSTED
            if limits.tokens_per_day is not None:
                if estimated_max_tokens is None:
                    return ReasonCode.QUOTA_EXHAUSTED
                held = sum(r.reserved_tokens or 0 for r in active if r.day == day)
                if budget.tokens_used + held + estimated_max_tokens > limits.tokens_per_day:
                    return ReasonCode.QUOTA_EXHAUSTED
            if limits.cost_per_day_usd is not None:
                if estimated_max_cost_usd is None:
                    return ReasonCode.QUOTA_EXHAUSTED
                held_cost = sum((r.reserved_cost or Decimal(0) for r in active if r.day == day), Decimal(0))
                if budget.cost_used + held_cost + estimated_max_cost_usd > Decimal(str(limits.cost_per_day_usd)):
                    return ReasonCode.QUOTA_EXHAUSTED
            reservation = QuotaReservation(
                token=uuid.uuid4().hex,
                profile_id=profile_id,
                limits=limits,
                reserved_tokens=estimated_max_tokens,
                reserved_cost=estimated_max_cost_usd,
                day=day,
            )
            self._reservations[reservation.token] = reservation
            return reservation

    def mark_dispatched(self, reservation: QuotaReservation) -> bool:
        """Commit one rate-window request immediately before transport send."""
        with self._lock:
            current = self._reservations.get(reservation.token)
            if current is not reservation or reservation.finished or reservation.dispatched:
                return False
            now_mono, day = self._now()
            budget = self._budget(reservation.profile_id, day)
            while budget.requests and now_mono - budget.requests[0] >= 60:
                budget.requests.popleft()
            if reservation.limits.requests_per_minute is not None and len(budget.requests) >= reservation.limits.requests_per_minute:
                return False
            budget.requests.append(now_mono)
            reservation.dispatched = True
            return True

    def release(self, reservation: QuotaReservation, *, usage: GatewayUsage | None = None) -> bool:
        """Release pre-dispatch reservations or settle dispatched usage once."""
        with self._lock:
            current = self._reservations.get(reservation.token)
            if current is not reservation or reservation.finished:
                return False
            reservation.finished = True
            del self._reservations[reservation.token]
            if not reservation.dispatched:
                return True
            _, current_day = self._now()
            if reservation.day != current_day:
                return True  # Daily reservation expired at UTC midnight.
            budget = self._budget(reservation.profile_id, current_day)
            if usage is not None:
                actual_tokens = usage.total_tokens
                if actual_tokens is None and usage.input_tokens is not None and usage.output_tokens is not None:
                    actual_tokens = usage.input_tokens + usage.output_tokens
            else:
                actual_tokens = None
            tokens_to_charge = actual_tokens if actual_tokens is not None else reservation.reserved_tokens
            if tokens_to_charge is not None:
                budget.tokens_used += tokens_to_charge
            actual_cost = usage.estimated_cost_usd if usage is not None else None
            cost_to_charge = actual_cost if actual_cost is not None else reservation.reserved_cost
            if cost_to_charge is not None:
                budget.cost_used += cost_to_charge
            return True

    def snapshot(self, profile_id: str) -> dict[str, int | str]:
        """Return safe local counters for health/readiness inspection."""
        _, day = self._now()
        with self._lock:
            budget = self._budget(profile_id, day)
            now_mono = self.monotonic()
            while budget.requests and now_mono - budget.requests[0] >= 60:
                budget.requests.popleft()
            active = self._active(profile_id)
            return {
                "requests_last_minute": len(budget.requests),
                "in_flight": len(active),
                "tokens_used_today": budget.tokens_used,
                "cost_used_today_usd": str(budget.cost_used),
            }
