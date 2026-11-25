"""Bounded attempt and deadline policy for one Gateway task.

This module owns request-count limits and timeout calculation. It never retries
an adapter call itself: callers may dispatch a distinct eligible route only
after recording the preceding outbound attempt.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, TypeVar

from shopassist.llm_gateway.config import GatewaySettings
from shopassist.llm_gateway.errors import (
    ErrorCategory,
    GatewayError,
    ProviderAttemptError,
    ReasonCode,
)
from shopassist.llm_gateway.schemas import TaskType

T = TypeVar("T")

_TASK_BUDGET_SETTING = {
    TaskType.QUERY_UNDERSTANDING: "query_deadline_seconds",
    TaskType.RECOMMENDATION_GENERATION: "recommendation_deadline_seconds",
    TaskType.LLM_JUDGE: "judge_deadline_seconds",
}


@dataclass(frozen=True)
class Deadline:
    """Absolute monotonic deadline and the source that limits the task."""

    at: float
    scope: str


@dataclass
class TaskAttemptPolicy:
    """Per-task dispatch budget; one route can consume at most one attempt."""

    task_id: str
    request_id: str
    task: TaskType
    started_mono: float
    deadline: Deadline
    attempt_timeout_s: float
    max_attempts: int
    max_per_route: int = 1
    clock: Callable[[], float] = time.monotonic
    dispatched_routes: set[str] = field(default_factory=set)

    @property
    def attempt_count(self) -> int:
        return len(self.dispatched_routes)

    def remaining_s(self) -> float:
        return self.deadline.at - self.clock()

    def _deadline_error(self) -> GatewayError:
        elapsed_ms = max(0.0, (self.clock() - self.started_mono) * 1000)
        return GatewayError(
            request_id=self.request_id,
            task_id=self.task_id,
            category=ErrorCategory.DEADLINE_EXCEEDED,
            reason_code=ReasonCode.DEADLINE_EXCEEDED,
            source="deadline",
            deadline_scope=self.deadline.scope,
            elapsed_ms=elapsed_ms,
        )

    def timeout_for_attempt(self) -> float:
        """Return a strictly positive timeout bounded by attempt and task."""
        remaining = self.remaining_s()
        if remaining <= 0:
            raise self._deadline_error()
        return min(self.attempt_timeout_s, remaining)

    def before_dispatch(self, route_id: str) -> float:
        """Recheck limits immediately before the adapter's dispatch hook."""
        timeout = self.timeout_for_attempt()
        if self.attempt_count >= self.max_attempts or route_id in self.dispatched_routes:
            raise GatewayError(
                request_id=self.request_id,
                task_id=self.task_id,
                category=ErrorCategory.NO_ELIGIBLE_ROUTE,
                reason_code=ReasonCode.NO_ELIGIBLE_ROUTE,
                source="admission",
                elapsed_ms=max(0.0, (self.clock() - self.started_mono) * 1000),
            )
        return timeout

    def record_dispatch(self, route_id: str) -> None:
        """Commit one outbound attempt at the transport boundary."""
        self.before_dispatch(route_id)
        self.dispatched_routes.add(route_id)

    def rollback_uncommitted_dispatch(self, route_id: str) -> None:
        """Undo a reservation if a later admission guard denies before I/O."""
        self.dispatched_routes.discard(route_id)

    def can_failover(self, *, enabled: bool, category: ErrorCategory | None = None) -> bool:
        """Whether another configured route may be considered (not dispatched)."""
        if not enabled or self.remaining_s() <= 0 or self.attempt_count >= self.max_attempts:
            return False
        if category is None:
            return True
        return category in {
            ErrorCategory.AUTHENTICATION,
            ErrorCategory.PERMISSION_DENIED,
            ErrorCategory.RATE_LIMITED,
            ErrorCategory.PROVIDER_UNAVAILABLE,
            ErrorCategory.NETWORK_ERROR,
            ErrorCategory.ATTEMPT_TIMEOUT,
            ErrorCategory.INCOMPATIBLE_ROUTE,
            ErrorCategory.INVALID_OUTPUT,
        }

    async def run_attempt(self, route_id: str, awaitable: Awaitable[T]) -> T:
        """Apply the effective timeout and preserve caller cancellation."""
        remaining = self.remaining_s()
        timeout = self.before_dispatch(route_id)
        deadline_limited = remaining <= self.attempt_timeout_s
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout)
        except asyncio.TimeoutError as exc:
            # If the task deadline, rather than the per-attempt cap, elapsed,
            # no backup may be dispatched.
            if deadline_limited or self.remaining_s() <= 0:
                raise self._deadline_error() from None
            raise ProviderAttemptError(
                category=ErrorCategory.ATTEMPT_TIMEOUT,
                reason_code=ReasonCode.ATTEMPT_TIMEOUT,
            ) from None


def begin_task(
    settings: GatewaySettings,
    *,
    task: TaskType,
    task_id: str,
    request_id: str,
    parent_deadline_mono: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> TaskAttemptPolicy:
    """Create a policy snapshot using the minimum task/parent deadline."""
    started = clock()
    task_budget = float(getattr(settings, _TASK_BUDGET_SETTING[task]))
    task_deadline = started + task_budget
    if parent_deadline_mono is not None and parent_deadline_mono <= task_deadline:
        deadline = Deadline(at=parent_deadline_mono, scope="parent")
    else:
        deadline = Deadline(at=task_deadline, scope="task")
    return TaskAttemptPolicy(
        task_id=task_id,
        request_id=request_id,
        task=task,
        started_mono=started,
        deadline=deadline,
        attempt_timeout_s=float(settings.attempt_timeout_seconds),
        max_attempts=int(settings.max_attempts_per_task),
        max_per_route=int(settings.max_attempts_per_route),
        clock=clock,
    )
