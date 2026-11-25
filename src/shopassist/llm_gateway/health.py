"""Worker-local provider-profile and route/schema health state."""
from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

from shopassist.llm_gateway.errors import ErrorCategory, ReasonCode

TRANSIENT = {
    ErrorCategory.RATE_LIMITED,
    ErrorCategory.PROVIDER_UNAVAILABLE,
    ErrorCategory.NETWORK_ERROR,
    ErrorCategory.ATTEMPT_TIMEOUT,
}


def retry_after_deadline(value: str | int | float | None, *, now_utc: datetime,
                         now_mono: float) -> float | None:
    """Convert Retry-After delta seconds or HTTP date once to monotonic time."""
    if value is None:
        return None
    delay: float | None = None
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            delay = float(value)
        else:
            text = value.strip()
            if not text:
                return None
            try:
                delay = float(text)
            except ValueError:
                target = parsedate_to_datetime(text)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                if now_utc.tzinfo is None:
                    return None
                delay = (target.astimezone(timezone.utc) - now_utc.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if delay is None or not math.isfinite(delay) or delay < 0:
        return None
    return now_mono + delay


@dataclass
class _HealthState:
    generation: int = 0
    consecutive_failures: int = 0
    cooldown_until: float | None = None
    blocked_reason: ReasonCode | None = None
    half_open_token: str | None = None


@dataclass(frozen=True)
class HealthReservation:
    profile_id: str
    route_id: str
    schema_id: str
    token: str
    profile_generation: int
    route_generation: int
    profile_probe: bool
    route_probe: bool


@dataclass(frozen=True)
class HealthSnapshot:
    status: str
    cooldown_remaining_s: float
    consecutive_failures: int
    blocked_reason: ReasonCode | None


class ProviderHealthManager:
    """Atomic local cooldown and one-probe half-open state manager.

    `profile_id` is an operator/config identifier, never a raw credential.
    The manager deliberately has no provider probe or network behavior.
    """

    def __init__(self, *, default_cooldown_s: float = 60.0, cooldown_cap_s: float = 900.0,
                 clock: Callable[[], float] = time.monotonic):
        if not math.isfinite(default_cooldown_s) or default_cooldown_s <= 0:
            raise ValueError("Invalid default cooldown")
        if not math.isfinite(cooldown_cap_s) or cooldown_cap_s < default_cooldown_s:
            raise ValueError("Invalid cooldown cap")
        self.default_cooldown_s = default_cooldown_s
        self.cooldown_cap_s = cooldown_cap_s
        self.clock = clock
        self._lock = threading.RLock()
        self._profiles: dict[str, _HealthState] = {}
        self._routes: dict[tuple[str, str], _HealthState] = {}

    def _state(self, profile_id: str, route_id: str | None = None, schema_id: str | None = None) -> _HealthState:
        if route_id is None:
            return self._profiles.setdefault(profile_id, _HealthState())
        return self._routes.setdefault((route_id, schema_id or ""), _HealthState())

    def _reserve_scope(self, state: _HealthState, token: str) -> tuple[ReasonCode | None, bool]:
        now = self.clock()
        if state.blocked_reason is not None:
            return state.blocked_reason, False
        if state.cooldown_until is not None:
            if now < state.cooldown_until:
                return ReasonCode.COOLDOWN, False
            if state.half_open_token is not None:
                return ReasonCode.COOLDOWN, False
            state.half_open_token = token
            return None, True
        return None, False

    def reserve(self, profile_id: str, route_id: str, schema_id: str) -> HealthReservation | ReasonCode:
        """Reserve health admission for profile and route/schema atomically."""
        if not all(isinstance(value, str) and value and len(value) <= 128 for value in (profile_id, route_id, schema_id)):
            raise ValueError("Invalid health scope")
        with self._lock:
            token = uuid.uuid4().hex
            profile = self._state(profile_id)
            route = self._state(profile_id, route_id, schema_id)
            denied, profile_probe = self._reserve_scope(profile, token)
            if denied is not None:
                return denied
            denied, route_probe = self._reserve_scope(route, token)
            if denied is not None:
                if profile_probe and profile.half_open_token == token:
                    profile.half_open_token = None
                return denied
            return HealthReservation(
                profile_id, route_id, schema_id, token, profile.generation, route.generation,
                profile_probe, route_probe,
            )

    @staticmethod
    def _release_probe(state: _HealthState, token: str, was_probe: bool) -> None:
        if was_probe and state.half_open_token == token:
            state.half_open_token = None

    def _release(self, lease: HealthReservation) -> None:
        profile = self._state(lease.profile_id)
        route = self._state(lease.profile_id, lease.route_id, lease.schema_id)
        self._release_probe(profile, lease.token, lease.profile_probe)
        self._release_probe(route, lease.token, lease.route_probe)

    def record_success(self, lease: HealthReservation) -> None:
        with self._lock:
            profile = self._state(lease.profile_id)
            route = self._state(lease.profile_id, lease.route_id, lease.schema_id)
            for state, generation in ((profile, lease.profile_generation), (route, lease.route_generation)):
                if state.generation == generation:
                    state.consecutive_failures = 0
                    state.cooldown_until = None
                    state.blocked_reason = None
                    state.generation += 1
            self._release(lease)

    def record_failure(self, lease: HealthReservation, category: ErrorCategory, *,
                       retry_after_deadline_mono: float | None = None) -> None:
        with self._lock:
            profile = self._state(lease.profile_id)
            route = self._state(lease.profile_id, lease.route_id, lease.schema_id)
            if category in TRANSIENT:
                targets = [profile] if category == ErrorCategory.RATE_LIMITED else [profile, route]
                for state in targets:
                    state.consecutive_failures += 1
                    backoff = min(self.default_cooldown_s * (2 ** (state.consecutive_failures - 1)), self.cooldown_cap_s)
                    until = self.clock() + backoff
                    if category == ErrorCategory.RATE_LIMITED and retry_after_deadline_mono is not None:
                        until = max(until, retry_after_deadline_mono)
                    state.cooldown_until = until
                    state.blocked_reason = None
                    state.half_open_token = None
                    state.generation += 1
            elif category == ErrorCategory.AUTHENTICATION:
                profile.blocked_reason = ReasonCode.AUTHENTICATION
                profile.cooldown_until = None
                profile.generation += 1
                profile.half_open_token = None
            elif category == ErrorCategory.PERMISSION_DENIED:
                route.blocked_reason = ReasonCode.PERMISSION_DENIED
                route.cooldown_until = None
                route.generation += 1
                route.half_open_token = None
            elif category == ErrorCategory.INVALID_OUTPUT:
                route.consecutive_failures += 1
                backoff = min(self.default_cooldown_s * (2 ** (route.consecutive_failures - 1)), self.cooldown_cap_s)
                route.cooldown_until = self.clock() + backoff
                route.blocked_reason = None
                route.half_open_token = None
                route.generation += 1
            elif category == ErrorCategory.INCOMPATIBLE_ROUTE:
                route.blocked_reason = ReasonCode.INCOMPATIBLE_ROUTE
                route.cooldown_until = None
                route.generation += 1
                route.half_open_token = None
            self._release(lease)

    def release(self, lease: HealthReservation) -> None:
        """Release a pre-dispatch or cancelled lease without marking success."""
        with self._lock:
            self._release(lease)

    def snapshot(self, profile_id: str, route_id: str | None = None,
                 schema_id: str | None = None) -> HealthSnapshot:
        with self._lock:
            state = self._state(profile_id, route_id, schema_id)
            remaining = max(0.0, (state.cooldown_until or self.clock()) - self.clock())
            if state.blocked_reason is not None:
                status = "blocked"
            elif state.cooldown_until is not None and (remaining > 0 or state.half_open_token is not None):
                status = "cooldown"
            else:
                status = "active"
            return HealthSnapshot(status, remaining, state.consecutive_failures, state.blocked_reason)
