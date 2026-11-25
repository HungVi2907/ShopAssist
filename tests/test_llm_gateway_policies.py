"""Policy tests are local-only and use fake monotonic clocks."""
import asyncio

import pytest

from shopassist.llm_gateway.config import GatewaySettings
from shopassist.llm_gateway.errors import ErrorCategory, GatewayError, ProviderAttemptError
from shopassist.llm_gateway.policies import begin_task
from shopassist.llm_gateway.schemas import TaskType


def policy(*, task=TaskType.QUERY_UNDERSTANDING, now=100.0, parent=None, **settings):
    config = GatewaySettings(_env_file=None, **settings)
    clock_value = [now]
    result = begin_task(config, task=task, task_id="task-1", request_id="request-1",
                        parent_deadline_mono=parent, clock=lambda: clock_value[0])
    return result, clock_value


def test_effective_deadline_is_minimum_of_task_and_parent():
    current, _ = policy(parent=129.0)
    assert (current.deadline.at, current.deadline.scope) == (129.0, "parent")
    task_limited, _ = policy(parent=150.0)
    assert (task_limited.deadline.at, task_limited.deadline.scope) == (130.0, "task")
    no_parent, _ = policy()
    assert (no_parent.deadline.at, no_parent.deadline.scope) == (130.0, "task")


def test_attempt_timeout_is_bounded_by_remaining_deadline():
    current, clock = policy(attempt_timeout_seconds=25, query_deadline_seconds=30)
    assert current.timeout_for_attempt() == 25
    clock[0] = 108
    assert current.timeout_for_attempt() == 22


def test_expired_parent_deadline_prevents_dispatch():
    current, clock = policy(parent=105)
    clock[0] = 105
    with pytest.raises(GatewayError) as caught:
        current.before_dispatch("route-a")
    assert caught.value.category == ErrorCategory.DEADLINE_EXCEEDED
    assert caught.value.deadline_scope == "parent"
    assert current.attempt_count == 0


def test_outbound_dispatch_budget_is_two_and_route_is_unique():
    current, _ = policy(max_attempts_per_task=2)
    current.record_dispatch("route-a")
    with pytest.raises(GatewayError):
        current.record_dispatch("route-a")
    current.record_dispatch("route-b")
    with pytest.raises(GatewayError):
        current.record_dispatch("route-c")
    assert current.attempt_count == 2


def test_one_attempt_configuration_never_allows_a_second_dispatch():
    current, _ = policy(max_attempts_per_task=1)
    current.record_dispatch("route-a")
    assert not current.can_failover(enabled=True, category=ErrorCategory.RATE_LIMITED)


@pytest.mark.parametrize("category,expected", [
    (None, True),
    (ErrorCategory.RATE_LIMITED, True),
    (ErrorCategory.PROVIDER_UNAVAILABLE, True),
    (ErrorCategory.ATTEMPT_TIMEOUT, True),
    (ErrorCategory.INVALID_OUTPUT, True),
    (ErrorCategory.AUTHENTICATION, True),
    (ErrorCategory.INVALID_REQUEST, False),
    (ErrorCategory.PROVIDER_REJECTED, False),
    (ErrorCategory.INTERNAL_ERROR, False),
    (ErrorCategory.DEADLINE_EXCEEDED, False),
    (ErrorCategory.CANCELLED, False),
])
def test_failover_categories_and_switch(category, expected):
    current, _ = policy()
    assert current.can_failover(enabled=True, category=category) is expected
    assert not current.can_failover(enabled=False, category=category)


def test_no_failover_after_deadline_or_attempt_budget():
    current, clock = policy(max_attempts_per_task=2)
    current.record_dispatch("route-a")
    clock[0] = 130
    assert not current.can_failover(enabled=True, category=ErrorCategory.RATE_LIMITED)
    current, _ = policy(max_attempts_per_task=2)
    current.record_dispatch("route-a")
    current.record_dispatch("route-b")
    assert not current.can_failover(enabled=True, category=ErrorCategory.RATE_LIMITED)


@pytest.mark.asyncio
async def test_attempt_timeout_is_normalized_for_later_failover():
    current, _ = policy(attempt_timeout_seconds=0.01)

    async def hangs():
        await asyncio.Event().wait()

    with pytest.raises(ProviderAttemptError) as caught:
        await current.run_attempt("route-a", hangs())
    assert caught.value.category == ErrorCategory.ATTEMPT_TIMEOUT
    assert current.can_failover(enabled=True, category=caught.value.category)


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_without_becoming_provider_timeout():
    current, _ = policy(attempt_timeout_seconds=10)
    started = asyncio.Event()

    async def wait_for_cancel():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(current.run_attempt("route-a", wait_for_cancel()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert current.attempt_count == 0


@pytest.mark.asyncio
async def test_task_deadline_during_attempt_stops_before_failover():
    current, clock = policy(parent=101.0, attempt_timeout_seconds=25)

    async def expire_then_wait():
        clock[0] = 101.0
        await asyncio.Event().wait()

    with pytest.raises(GatewayError) as caught:
        await current.run_attempt("route-a", expire_then_wait())
    assert caught.value.category == ErrorCategory.DEADLINE_EXCEEDED
    assert caught.value.deadline_scope == "parent"
    assert not current.can_failover(enabled=True)
