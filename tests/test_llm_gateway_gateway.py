"""Gateway engine tests use synthetic evidence and mocked one-shot adapters."""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import yaml
from pydantic import BaseModel

from shopassist.llm_gateway.adapters.base import AdapterResult, PreparedRequest
from shopassist.llm_gateway.config import GatewaySettings, ROOT
from shopassist.llm_gateway.errors import ErrorCategory, GatewayError, ProviderAttemptError, ReasonCode
from shopassist.llm_gateway.gateway import Gateway
from shopassist.llm_gateway.health import ProviderHealthManager
from shopassist.llm_gateway.registry import ProviderRegistry
from shopassist.llm_gateway.schemas import GatewayRequest, GatewayUsage, SCHEMA_IDS, TaskType
from shopassist.llm_gateway.telemetry import TelemetrySink


class Output(BaseModel):
    value: int


def build_gateway(tmp_path, monkeypatch, *, disabled=(), failover=True, timeout=0.03,
                  deadline=1.0, telemetry=False, limits=None, adapter_results=None,
                  credential_available=None, budget_estimator=None, health=None):
    data = yaml.safe_load((ROOT / "config/llm_gateway.yaml").read_text(encoding="utf-8"))
    selected = ("recommendation_openrouter", "recommendation_groq")
    # These generic failover tests construct an isolated synthetic OpenRouter
    # candidate; production YAML and composition roots no longer include it.
    data["providers"]["openrouter"] = {
        "kind": "openrouter", "credential_env": "OPENROUTER_API_KEY",
        "endpoint": "https://openrouter.ai/api/v1",
    }
    data["routes"]["recommendation_openrouter"] = {
        "provider": "openrouter", "model": "baidu/ernie-5.5-flash-preview:free",
        "structured_mode": "json_schema", "schema_ids": ["phase12.recommendation.v1"],
        "enabled": False, "approval": {"status": "pending"}, "cost": {"class": "unknown"},
        "options": {"max_output_tokens": 2048},
    }
    data["tasks"]["recommendation_generation"]["profiles"]["default"]["route_ids"] = list(selected)
    for provider_name, values in (limits or {}).items():
        data["providers"][provider_name]["limits"] = values
    for route_id in selected:
        route = data["routes"][route_id]
        provider_name = route["provider"]
        is_disabled = route_id in disabled
        route["enabled"] = not is_disabled
        if is_disabled:
            # Disabled routes need no evidence and remain in ordered routing.
            continue
        route["approval"] = {"status": "approved", "evidence_ref": f"{route_id}.yaml"}
        route["cost"] = {"class": "free", "evidence_ref": f"{route_id}.yaml",
                         "input_per_million_usd": 0.0, "output_per_million_usd": 0.0}
        artifact = f"synthetic artifact for {route_id}".encode()
        artifact_ref = f"{route_id}.artifact"
        (tmp_path / artifact_ref).write_bytes(artifact)
        evidence = {
            "route_id": route_id, "task": "recommendation_generation", "provider": provider_name,
            "endpoint": data["providers"][provider_name]["endpoint"], "model": route["model"],
            "schema_id": SCHEMA_IDS[TaskType.RECOMMENDATION_GENERATION],
            "structured_mode": route["structured_mode"], "status": "valid", "approval": "approved",
            "cost_class": "free", "input_per_million_usd": 0.0, "output_per_million_usd": 0.0,
            "artifact_ref": artifact_ref, "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        }
        (tmp_path / f"{route_id}.yaml").write_text(yaml.safe_dump(evidence), encoding="utf-8")
    config_path = tmp_path / "gateway.yaml"
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    settings = GatewaySettings(_env_file=None, enabled=True, config_path=config_path,
                               auto_failover=failover, attempt_timeout_seconds=timeout,
                               recommendation_deadline_seconds=deadline,
                               telemetry_enabled=telemetry, telemetry_dir=tmp_path / "telemetry")
    bindings = {schema_id: Output for schema_id in SCHEMA_IDS.values()}
    registry = ProviderRegistry(settings, bindings)
    primary = MockAdapter((adapter_results or {}).get("openrouter", [AdapterResult(raw_text='{"value": 7}')]))
    backup = MockAdapter((adapter_results or {}).get("groq", [AdapterResult(raw_text='{"value": 8}')]))
    sink = TelemetrySink(settings) if telemetry else None
    gateway = Gateway(settings, registry, {"openrouter": primary, "groq": backup}, telemetry=sink,
                      credential_available=credential_available or (lambda _route: True),
                      budget_estimator=budget_estimator, health=health)
    request = GatewayRequest[Output](
        task=TaskType.RECOMMENDATION_GENERATION, profile="default", request_id="request-1",
        task_id="task-1", system_prompt="system prompt", user_prompt="user prompt",
        schema_id=SCHEMA_IDS[TaskType.RECOMMENDATION_GENERATION], response_schema=Output,
    )
    return gateway, request, primary, backup, sink


class MockAdapter:
    def __init__(self, results):
        self.results = list(results)
        self.prepare_count = 0
        self.call_count = 0
        self.dispatch_count = 0
        self.closed = 0

    def prepare(self, request, route):
        self.prepare_count += 1
        return PreparedRequest(route=route, request=request, body=b"synthetic request")

    async def complete_once(self, prepared, *, timeout_s, on_dispatch):
        self.call_count += 1
        result = self.results.pop(0)
        if isinstance(result, BeforeDispatchFailure):
            raise result.error
        on_dispatch()
        self.dispatch_count += 1
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            return await result()
        return result

    async def aclose(self):
        self.closed += 1


def test_profile_specific_adapter_overrides_kind_adapter(tmp_path, monkeypatch):
    gateway, _request, _primary, _backup, _sink = build_gateway(tmp_path, monkeypatch)
    kind_adapter = MockAdapter([AdapterResult(raw_text='{"value": 1}')])
    profile_adapter = MockAdapter([AdapterResult(raw_text='{"value": 2}')])
    gateway.adapters["gemini"] = kind_adapter
    gateway.adapters["gemini_recommendation"] = profile_adapter
    route = gateway.registry.resolve("recommendation_gemini")
    assert gateway._adapter_for_route(route) is profile_adapter
    route = gateway.registry.resolve("query_gemini")
    assert gateway._adapter_for_route(route) is kind_adapter


class BeforeDispatchFailure:
    def __init__(self, error):
        self.error = error


@pytest.mark.asyncio
async def test_primary_success_returns_validated_payload_without_backup(tmp_path, monkeypatch):
    gateway, request, primary, backup, _ = build_gateway(tmp_path, monkeypatch)
    response = await gateway.complete(request)
    assert response.payload.value == 7
    assert response.provider == "openrouter" and response.route_id == "recommendation_openrouter"
    assert response.failover_used is False
    assert len(response.attempts) == 1 and response.attempts[0].attempt_number == 1
    assert primary.dispatch_count == 1 and backup.dispatch_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ErrorCategory.RATE_LIMITED, ErrorCategory.PROVIDER_UNAVAILABLE])
async def test_retryable_primary_error_fails_over_once_and_uses_winner_attribution(tmp_path, monkeypatch, failure):
    first = ProviderAttemptError(category=failure, reason_code=ReasonCode(failure.value), http_status=429 if failure == ErrorCategory.RATE_LIMITED else 503)
    gateway, request, primary, backup, _ = build_gateway(
        tmp_path, monkeypatch, adapter_results={"openrouter": [first], "groq": [AdapterResult(raw_text='{"value": 9}', usage=GatewayUsage(input_tokens=3, output_tokens=2, total_tokens=5))]}
    )
    response = await gateway.complete(request)
    assert response.payload.value == 9
    assert (response.provider, response.model, response.route_id) == ("groq", "openai/gpt-oss-20b", "recommendation_groq")
    assert response.failover_used is True
    assert [(record.attempt_number, record.route_index) for record in response.attempts] == [(1, 0), (2, 1)]
    assert [primary.dispatch_count, backup.dispatch_count] == [1, 1]


@pytest.mark.asyncio
async def test_invalid_json_preserves_usage_and_fails_over_without_repair(tmp_path, monkeypatch):
    bad_output = AdapterResult(raw_text="not json", usage=GatewayUsage(input_tokens=12, output_tokens=4, total_tokens=16))
    gateway, request, primary, backup, _ = build_gateway(tmp_path, monkeypatch, adapter_results={"openrouter": [bad_output]})
    response = await gateway.complete(request)
    assert response.payload.value == 8
    assert response.attempts[0].error_category == ErrorCategory.INVALID_OUTPUT
    assert response.attempts[0].usage.total_tokens == 16
    assert primary.call_count == primary.dispatch_count == 1
    assert backup.call_count == backup.dispatch_count == 1


@pytest.mark.asyncio
async def test_all_routes_fail_raise_safe_error_with_both_attempts(tmp_path, monkeypatch):
    gateway, request, primary, backup, _ = build_gateway(tmp_path, monkeypatch, adapter_results={
        "openrouter": [ProviderAttemptError(category=ErrorCategory.RATE_LIMITED, reason_code=ReasonCode.RATE_LIMITED)],
        "groq": [ProviderAttemptError(category=ErrorCategory.PROVIDER_UNAVAILABLE, reason_code=ReasonCode.PROVIDER_UNAVAILABLE)],
    })
    with pytest.raises(GatewayError) as caught:
        await gateway.complete(request)
    assert caught.value.category == ErrorCategory.PROVIDER_UNAVAILABLE
    assert len(caught.value.attempts) == 2
    assert [primary.dispatch_count, backup.dispatch_count] == [1, 1]
    assert "synthetic" not in str(caught.value)


@pytest.mark.asyncio
async def test_pending_disabled_routes_fail_closed_without_dispatch(tmp_path, monkeypatch):
    gateway, request, primary, backup, _ = build_gateway(tmp_path, monkeypatch, disabled=("recommendation_openrouter", "recommendation_groq"))
    with pytest.raises(GatewayError) as caught:
        await gateway.complete(request)
    assert caught.value.category == ErrorCategory.NO_ELIGIBLE_ROUTE
    assert not caught.value.attempts
    assert primary.dispatch_count == backup.dispatch_count == 0


@pytest.mark.asyncio
async def test_primary_skip_uses_backup_as_attempt_one_and_records_failover_route(tmp_path, monkeypatch):
    gateway, request, primary, backup, _ = build_gateway(tmp_path, monkeypatch, disabled=("recommendation_openrouter",))
    response = await gateway.complete(request)
    assert response.failover_used
    assert len(response.attempts) == 1
    assert (response.attempts[0].attempt_number, response.attempts[0].route_index) == (1, 1)
    assert primary.dispatch_count == 0 and backup.dispatch_count == 1


@pytest.mark.asyncio
async def test_failover_off_does_not_consider_backup_after_primary_skip(tmp_path, monkeypatch):
    gateway, request, primary, backup, _ = build_gateway(
        tmp_path, monkeypatch, disabled=("recommendation_openrouter",), failover=False
    )
    with pytest.raises(GatewayError):
        await gateway.complete(request)
    assert primary.dispatch_count == backup.dispatch_count == 0


@pytest.mark.asyncio
async def test_missing_credentials_skip_without_provider_attempt(tmp_path, monkeypatch):
    gateway, request, primary, backup, _ = build_gateway(tmp_path, monkeypatch, credential_available=lambda _route: False)
    with pytest.raises(GatewayError) as caught:
        await gateway.complete(request)
    assert caught.value.category == ErrorCategory.NO_ELIGIBLE_ROUTE
    assert primary.dispatch_count == backup.dispatch_count == 0


@pytest.mark.asyncio
async def test_attempt_timeout_can_fail_over_but_still_respects_two_dispatch_cap(tmp_path, monkeypatch):
    async def hangs():
        await asyncio.Event().wait()

    gateway, request, primary, backup, _ = build_gateway(
        tmp_path, monkeypatch, timeout=0.01, adapter_results={"openrouter": [hangs]}
    )
    response = await gateway.complete(request)
    assert response.provider == "groq"
    assert response.attempts[0].error_category == ErrorCategory.ATTEMPT_TIMEOUT
    assert primary.dispatch_count + backup.dispatch_count == 2


@pytest.mark.asyncio
async def test_parent_deadline_stops_backup_after_primary_timeout(tmp_path, monkeypatch):
    async def hangs():
        await asyncio.Event().wait()

    gateway, request, primary, backup, _ = build_gateway(
        tmp_path, monkeypatch, timeout=1.0, adapter_results={"openrouter": [hangs]}
    )
    request = request.model_copy(update={"parent_deadline_mono": gateway.monotonic() + 0.5})
    with pytest.raises(GatewayError) as caught:
        await gateway.complete(request)
    assert caught.value.category == ErrorCategory.DEADLINE_EXCEEDED
    assert caught.value.deadline_scope == "parent"
    assert len(caught.value.attempts) == 1
    assert primary.dispatch_count == 1 and backup.dispatch_count == 0


@pytest.mark.asyncio
async def test_caller_cancellation_finalizes_dispatched_attempt_and_propagates(tmp_path, monkeypatch):
    started = asyncio.Event()

    async def hangs():
        started.set()
        await asyncio.Event().wait()

    gateway, request, primary, backup, sink = build_gateway(
        tmp_path, monkeypatch, timeout=1, adapter_results={"openrouter": [hangs]}, telemetry=True
    )
    task = asyncio.create_task(gateway.complete(request))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await sink.flush()
    assert primary.dispatch_count == 1 and backup.dispatch_count == 0
    events = [json.loads(line) for line in (tmp_path / "telemetry" / "gateway.jsonl").read_text().splitlines()]
    assert events[0]["outcome"] == "cancelled"
    await gateway.aclose()
    await gateway.aclose()
    assert primary.closed == backup.closed == 1


@pytest.mark.asyncio
async def test_reported_model_mismatch_is_route_incompatibility_and_uses_backup(tmp_path, monkeypatch):
    gateway, request, primary, backup, _ = build_gateway(tmp_path, monkeypatch, adapter_results={
        "openrouter": [AdapterResult(raw_text='{"value": 1}', reported_model="unexpected/model")]
    })
    response = await gateway.complete(request)
    assert response.provider == "groq"
    assert response.attempts[0].error_category == ErrorCategory.INCOMPATIBLE_ROUTE
    assert primary.dispatch_count == backup.dispatch_count == 1


@pytest.mark.asyncio
async def test_nonretryable_provider_rejection_does_not_call_backup(tmp_path, monkeypatch):
    rejected = ProviderAttemptError(category=ErrorCategory.PROVIDER_REJECTED,
                                    reason_code=ReasonCode.PROVIDER_REJECTED, http_status=400)
    gateway, request, primary, backup, _ = build_gateway(
        tmp_path, monkeypatch, adapter_results={"openrouter": [rejected]}
    )
    with pytest.raises(GatewayError) as caught:
        await gateway.complete(request)
    assert caught.value.category == ErrorCategory.PROVIDER_REJECTED
    assert len(caught.value.attempts) == 1
    assert primary.dispatch_count == 1 and backup.dispatch_count == 0


@pytest.mark.asyncio
async def test_adapter_authentication_before_dispatch_is_not_an_attempt(tmp_path, monkeypatch):
    missing = ProviderAttemptError(category=ErrorCategory.AUTHENTICATION,
                                   reason_code=ReasonCode.AUTHENTICATION)
    gateway, request, primary, backup, _ = build_gateway(
        tmp_path, monkeypatch, adapter_results={"openrouter": [BeforeDispatchFailure(missing)]}
    )
    response = await gateway.complete(request)
    assert response.provider == "groq"
    assert response.attempts[0].attempt_number == 1
    assert response.attempts[0].route_index == 1
    assert primary.dispatch_count == 0 and backup.dispatch_count == 1


@pytest.mark.asyncio
async def test_health_cooldown_skips_primary_without_consuming_attempt(tmp_path, monkeypatch):
    now = [100.0]
    health = ProviderHealthManager(default_cooldown_s=30, clock=lambda: now[0])
    lease = health.reserve("openrouter", "recommendation_openrouter", "phase12.recommendation.v1")
    health.record_failure(lease, ErrorCategory.RATE_LIMITED)
    gateway, request, primary, backup, _ = build_gateway(
        tmp_path, monkeypatch, health=health
    )
    response = await gateway.complete(request)
    assert response.provider == "groq"
    assert response.attempts[0].attempt_number == 1
    assert response.attempts[0].route_index == 1
    assert primary.dispatch_count == 0 and backup.dispatch_count == 1


@pytest.mark.asyncio
async def test_attempt_setting_of_one_stops_after_primary_failure(tmp_path, monkeypatch):
    gateway, request, primary, backup, _ = build_gateway(
        tmp_path, monkeypatch,
        adapter_results={"openrouter": [ProviderAttemptError(category=ErrorCategory.RATE_LIMITED,
                           reason_code=ReasonCode.RATE_LIMITED)]},
    )
    gateway.settings.max_attempts_per_task = 1
    with pytest.raises(GatewayError) as caught:
        await gateway.complete(request)
    assert len(caught.value.attempts) == 1
    assert primary.dispatch_count == 1 and backup.dispatch_count == 0


@pytest.mark.asyncio
async def test_gateway_telemetry_captures_both_attempts_and_actual_winner(tmp_path, monkeypatch):
    gateway, request, primary, backup, sink = build_gateway(
        tmp_path, monkeypatch, telemetry=True,
        adapter_results={"openrouter": [ProviderAttemptError(category=ErrorCategory.RATE_LIMITED,
                           reason_code=ReasonCode.RATE_LIMITED)]},
    )
    response = await gateway.complete(request)
    await sink.flush()
    events = [json.loads(line) for line in (tmp_path / "telemetry" / "gateway.jsonl").read_text().splitlines()]
    attempts = [event for event in events if event["event"] == "attempt"]
    summaries = [event for event in events if event["event"] == "task_summary"]
    assert len(attempts) == 2 and [event["attempt_number"] for event in attempts] == [1, 2]
    assert len(summaries) == 1
    assert summaries[0]["actual_provider"] == response.provider == "groq"
    assert summaries[0]["actual_model"] == response.model
    await gateway.aclose()


@pytest.mark.asyncio
async def test_provider_quota_denial_skips_to_backup_without_dispatch(tmp_path, monkeypatch):
    gateway, request, primary, backup, _ = build_gateway(
        tmp_path, monkeypatch, limits={"openrouter": {"tokens_per_day": 100}},
        budget_estimator=lambda _route, _request: (None, None),
    )
    # A token ceiling without a verified upper bound fails closed.
    response = await gateway.complete(request)
    assert response.provider == "groq"
    assert primary.dispatch_count == 0 and backup.dispatch_count == 1


@pytest.mark.asyncio
async def test_gateway_aclose_closes_shared_adapter_only_once(tmp_path, monkeypatch):
    gateway, _, primary, backup, _ = build_gateway(tmp_path, monkeypatch)
    gateway.adapters["groq"] = primary
    await gateway.aclose()
    assert primary.closed == 1
    assert backup.closed == 0
