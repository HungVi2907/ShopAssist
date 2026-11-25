"""Pure contract tests with no provider or database dependencies."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from shopassist.llm_gateway.errors import ErrorCategory, GatewayError, ProviderAttemptError, ReasonCode
from shopassist.llm_gateway.schemas import AttemptRecord, GatewayRequest, GatewayResponse, GatewayUsage


class Output(BaseModel):
    value: int


def attempt(**changes):
    values = dict(
        request_id="request-1", task_id="task-1", task="query_understanding",
        schema_id="phase8.query.v1", attempt_number=1, route_index=0,
        route_id="primary", provider="gemini", model="gemini-test",
        started_at_utc=datetime.now(timezone.utc), latency_ms=1,
        outcome="success", system_chars=2, user_chars=3, context_chars=5,
        is_failover_route=False,
    )
    values.update(changes)
    return AttemptRecord(**values)


def response(**changes):
    winner = attempt()
    values = dict(
        request_id="request-1", task_id="task-1", task=winner.task,
        schema_id=winner.schema_id, payload={"value": 1}, raw_text="sensitive-output",
        route_id=winner.route_id, provider=winner.provider, model=winner.model,
        usage=winner.usage, attempts=(winner,), latency_ms=2, failover_used=False,
    )
    values.update(changes)
    return GatewayResponse[Output](**values)


def test_usage_unknown_and_real_zero():
    assert GatewayUsage().input_tokens is None
    assert GatewayUsage(input_tokens=0).input_tokens == 0
    assert GatewayUsage(input_tokens=2, output_tokens=3).total_tokens is None
    assert GatewayUsage(estimated_cost_usd=Decimal("0.001")).estimated_cost_usd == Decimal("0.001")


@pytest.mark.parametrize("fields", [
    {"input_tokens": -1}, {"total_tokens": True}, {"output_tokens": "3"},
    {"estimated_cost_usd": "NaN"}, {"estimated_cost_usd": -1},
])
def test_usage_rejects_invalid_values(fields):
    with pytest.raises(ValidationError):
        GatewayUsage(**fields)


def test_request_preserves_prompt_and_hides_content():
    request = GatewayRequest[Output](
        task="query_understanding", request_id="req", task_id="task",
        schema_id="phase8.query.v1", response_schema=Output,
        system_prompt="  sensitive-system  ", user_prompt="sensitive-user",
    )
    assert request.system_prompt == "  sensitive-system  "
    assert "sensitive" not in repr(request)
    assert "sensitive" not in request.model_dump_json()
    with pytest.raises(ValidationError):
        request.task_id = "changed"


@pytest.mark.parametrize("changes", [
    {"system_prompt": "  "}, {"schema_id": "phase14.judge.v1"},
    {"parent_deadline_mono": float("inf")}, {"request_id": "bad\nID"},
    {"model": "caller-override"},
])
def test_invalid_request(changes):
    fields = dict(task="query_understanding", request_id="req", task_id="task",
                  schema_id="phase8.query.v1", response_schema=Output,
                  system_prompt="system", user_prompt="user")
    fields.update(changes)
    with pytest.raises(ValidationError):
        GatewayRequest[Output](**fields)


@pytest.mark.parametrize("changes", [
    {"started_at_utc": datetime(2026, 1, 1)}, {"context_chars": 7},
    {"attempt_number": 3}, {"latency_ms": float("nan")},
    {"is_failover_route": True}, {"outcome": "error"},
    {"error_category": ErrorCategory.INVALID_OUTPUT},
])
def test_invalid_attempt(changes):
    with pytest.raises(ValidationError):
        attempt(**changes)


def test_response_is_typed_and_sensitive_output_excluded():
    result = response()
    assert isinstance(result.payload, Output)
    assert result.payload.value == 1
    assert "sensitive-output" not in result.model_dump_json()
    assert "payload" not in repr(result)
    with pytest.raises(ValidationError):
        response(payload={"value": "not-an-integer"})


@pytest.mark.parametrize("changes", [
    {"attempts": ()}, {"provider": "groq"}, {"failover_used": True},
    {"task_id": "different"}, {"usage": GatewayUsage(input_tokens=99)},
])
def test_response_requires_matching_winner(changes):
    with pytest.raises(ValidationError):
        response(**changes)


def test_failover_history_and_provider_usage():
    failed = attempt(outcome="error", error_category=ErrorCategory.INVALID_OUTPUT,
                     reason_code=ReasonCode.INVALID_OUTPUT, usage=GatewayUsage(input_tokens=7))
    winner = attempt(attempt_number=2, route_index=1, route_id="backup", is_failover_route=True)
    result = response(attempts=(failed, winner), route_id="backup", failover_used=True)
    assert result.attempts[0].usage.input_tokens == 7
    error = ProviderAttemptError(category=ErrorCategory.INVALID_OUTPUT,
                                 reason_code=ReasonCode.INVALID_OUTPUT, usage=failed.usage)
    assert error.usage.input_tokens == 7
    assert str(error) == "LLM provider attempt failed (INVALID_OUTPUT)."


def test_safe_gateway_error_and_deadline():
    error = GatewayError(request_id="req", task_id="task",
                         category=ErrorCategory.DEADLINE_EXCEEDED,
                         reason_code=ReasonCode.DEADLINE_EXCEEDED,
                         source="deadline", deadline_scope="parent", elapsed_ms=30)
    assert error.deadline_scope == "parent"
    assert error.attempts == ()
    assert error.to_safe_dict()["error"]["category"] == "DEADLINE_EXCEEDED"
    with pytest.raises(ValidationError):
        GatewayError(request_id="req", task_id="task", category=ErrorCategory.INTERNAL_ERROR,
                     reason_code="raw-secret", source="gateway")


def test_duplicate_route_is_rejected():
    failed = attempt(outcome="error", error_category=ErrorCategory.ATTEMPT_TIMEOUT,
                     reason_code=ReasonCode.ATTEMPT_TIMEOUT)
    with pytest.raises(ValidationError):
        response(attempts=(failed, attempt(attempt_number=2)))


def test_deadline_scope_is_required():
    with pytest.raises(ValidationError):
        GatewayError(request_id="req", task_id="task", category=ErrorCategory.DEADLINE_EXCEEDED,
                     reason_code=ReasonCode.DEADLINE_EXCEEDED, source="deadline")


def test_failure_rejects_successful_history():
    with pytest.raises(ValidationError):
        GatewayError(request_id="request-1", task_id="task-1",
                     attempts=(attempt(),), category=ErrorCategory.INTERNAL_ERROR,
                     reason_code=ReasonCode.INTERNAL_ERROR, source="gateway")
