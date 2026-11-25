"""Registry tests use synthetic evidence solely to test validation logic."""
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from pydantic import BaseModel

from shopassist.llm_gateway.adapters.base import AdapterResult, PreparedRequest
from shopassist.llm_gateway.config import GatewayConfigurationError, GatewaySettings, ROOT
from shopassist.llm_gateway.errors import ReasonCode
from shopassist.llm_gateway.registry import ProviderRegistry
from shopassist.llm_gateway.schemas import GatewayRequest, SCHEMA_IDS, TaskType


class Output(BaseModel):
    value: int


class OtherOutput(BaseModel):
    value: int


def request(task=TaskType.QUERY_UNDERSTANDING, **changes):
    values = dict(task=task, request_id="req", task_id="task", schema_id=SCHEMA_IDS[task],
                  response_schema=Output, system_prompt="sensitive-system", user_prompt="sensitive-user")
    values.update(changes)
    return GatewayRequest[BaseModel](**values)


@pytest.fixture
def registry_factory(tmp_path):
    def build(*, approved=False, enabled=True, paid=False, allow_paid=False, task_paid=False):
        data = yaml.safe_load((ROOT / "config/llm_gateway.yaml").read_text(encoding="utf-8"))
        if approved:
            route = data["routes"]["query_gemini"]
            route["enabled"] = enabled
            route["approval"] = {"status": "approved", "evidence_ref": "evidence.yaml"}
            route["cost"] = {"class": "paid" if paid else "free", "evidence_ref": "evidence.yaml",
                             "input_per_million_usd": 1.0 if paid else 0.0, "output_per_million_usd": 1.0 if paid else 0.0}
            data["providers"]["gemini"]["limits"] = {"cost_per_day_usd": 1.0}
            data["tasks"]["query_understanding"]["profiles"]["default"]["allow_paid"] = task_paid
            artifact = b"SYNTHETIC fixture only"
            (tmp_path / "artifact.txt").write_bytes(artifact)
            evidence = dict(
                route_id="query_gemini", task="query_understanding", provider="gemini",
                endpoint=data["providers"]["gemini"]["endpoint"], model=route["model"],
                schema_id="phase8.query.v1", structured_mode="gemini_schema",
                status="valid", approval="approved", cost_class=route["cost"]["class"],
                input_per_million_usd=route["cost"]["input_per_million_usd"],
                output_per_million_usd=route["cost"]["output_per_million_usd"],
                artifact_ref="artifact.txt", artifact_sha256=hashlib.sha256(artifact).hexdigest(),
                valid_until=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            )
            (tmp_path / "evidence.yaml").write_text(yaml.safe_dump(evidence), encoding="utf-8")
        path = tmp_path / "gateway.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        settings = GatewaySettings(_env_file=None, enabled=True, config_path=path, allow_paid_models=allow_paid)
        registry = ProviderRegistry(settings, {schema_id: Output for schema_id in SCHEMA_IDS.values()})
        return registry, settings, data
    return build


def test_order_and_pending_backup(registry_factory, monkeypatch):
    registry, _, _ = registry_factory()
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-secret")
    monkeypatch.setenv("PHASE12_LLM_MODEL", "override")
    routes = registry.routes_for(request(TaskType.RECOMMENDATION_GENERATION))
    assert [route.route_id for route in routes] == ["recommendation_openrouter", "recommendation_groq"]
    assert routes[1].model == "openai/gpt-oss-20b"
    assert registry.ineligibility(routes[1].route_id, TaskType.RECOMMENDATION_GENERATION) == ReasonCode.DISABLED


def test_schema_binding_and_profile_rejected(registry_factory):
    registry, _, _ = registry_factory()
    for invalid in (request(response_schema=OtherOutput), request(profile="missing")):
        with pytest.raises(GatewayConfigurationError):
            registry.routes_for(invalid)


@pytest.mark.parametrize("allow_paid,task_paid,expected", [
    (False, False, ReasonCode.COST_DENIED), (True, False, ReasonCode.COST_DENIED),
    (False, True, ReasonCode.COST_DENIED), (True, True, None),
])
def test_paid_requires_both_permissions(registry_factory, allow_paid, task_paid, expected):
    registry, _, _ = registry_factory(approved=True, paid=True, allow_paid=allow_paid, task_paid=task_paid)
    assert registry.ineligibility("query_gemini", TaskType.QUERY_UNDERSTANDING) == expected


def test_approved_free_and_disabled_approved(registry_factory):
    registry, _, _ = registry_factory(approved=True)
    assert registry.ineligibility("query_gemini", TaskType.QUERY_UNDERSTANDING) is None
    registry, _, _ = registry_factory(approved=True, enabled=False)
    assert registry.ineligibility("query_gemini", TaskType.QUERY_UNDERSTANDING) == ReasonCode.DISABLED


def test_registry_snapshot_is_immutable(registry_factory):
    registry, settings, _ = registry_factory(approved=True)
    settings.allow_paid_models = True
    route = registry.resolve("query_gemini")
    with pytest.raises((AttributeError, TypeError)):
        route.model = "changed"
    with pytest.raises(TypeError):
        route.options["max_output_tokens"] = 99
    assert isinstance(route.options["reported_model_aliases"], tuple)


def test_missing_and_incompatible_routes(registry_factory):
    registry, _, _ = registry_factory()
    with pytest.raises(GatewayConfigurationError):
        registry.resolve("unknown")
    with pytest.raises(GatewayConfigurationError):
        registry.ineligibility("judge_gemini", TaskType.QUERY_UNDERSTANDING)


def test_revalidates_changed_model_and_unsupported_mode(registry_factory):
    _, settings, data = registry_factory(approved=True)
    data["routes"]["query_gemini"]["model"] = "changed"
    settings.config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(GatewayConfigurationError):
        ProviderRegistry(settings, {schema_id: Output for schema_id in SCHEMA_IDS.values()})


def test_pending_cannot_be_enabled(registry_factory):
    _, settings, data = registry_factory()
    data["routes"]["recommendation_groq"]["enabled"] = True
    settings.config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(GatewayConfigurationError):
        ProviderRegistry(settings, {schema_id: Output for schema_id in SCHEMA_IDS.values()})


def test_unsupported_structured_mode(registry_factory):
    _, settings, data = registry_factory()
    data["routes"]["query_gemini"]["structured_mode"] = "json_schema"
    settings.config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(GatewayConfigurationError):
        ProviderRegistry(settings, {schema_id: Output for schema_id in SCHEMA_IDS.values()})


def test_expired_evidence_becomes_ineligible(registry_factory, monkeypatch):
    registry, _, _ = registry_factory(approved=True)
    future = datetime.now(timezone.utc) + timedelta(days=2)

    class FutureClock:
        @staticmethod
        def now(tz):
            return future

    monkeypatch.setattr("shopassist.llm_gateway.registry.datetime", FutureClock)
    assert registry.ineligibility("query_gemini", TaskType.QUERY_UNDERSTANDING) == ReasonCode.UNAPPROVED


def test_adapter_contract_content_is_private(registry_factory):
    registry, _, _ = registry_factory()
    prepared = PreparedRequest(registry.resolve("query_gemini"), request(), b"synthetic-secret")
    assert "synthetic-secret" not in repr(prepared)
    result = AdapterResult(raw_text="synthetic-secret")
    assert "synthetic-secret" not in repr(result)
    assert "synthetic-secret" not in result.model_dump_json()
