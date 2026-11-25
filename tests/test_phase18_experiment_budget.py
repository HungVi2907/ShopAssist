"""Persistent experiment budget lifecycle tests; no network or provider evidence."""
import pytest
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

import yaml
from shopassist.llm.schemas import QueryUnderstandingOutput
from shopassist.llm_gateway.adapters.base import AdapterResult, PreparedRequest
from shopassist.llm_gateway.config import GatewaySettings, ROOT
from shopassist.llm_gateway.errors import ErrorCategory, ProviderAttemptError, ReasonCode
from shopassist.llm_gateway.experiment_factory import experiment_schema_bindings
from shopassist.llm_gateway.gateway import Gateway
from shopassist.llm_gateway.registry import ProviderRegistry
from shopassist.llm_gateway.schema_ids import EXPERIMENTAL_SCHEMA_IDS
from shopassist.llm_gateway.schemas import GatewayRequest, GatewayUsage, TaskType

from shopassist.llm.experiments.phase82.persistent_budget import (
    ExperimentBudgetExceeded,
    PersistentExperimentBudget,
)
from shopassist.llm_gateway.schemas import GatewayUsage


def test_no_dispatch_releases_reservation_without_charging(tmp_path):
    budget = PersistentExperimentBudget(tmp_path / "budget.json", 1, 100)
    token = budget.reserve("task-1", "route-1", 80)
    budget.release(token)
    assert budget.snapshot() == {
        "requests": 0, "charged_tokens": 0, "observed_tokens": 0,
        "unknown_usage_attempts": 0, "pending_reservations": 0,
    }


def test_dispatch_settles_actual_usage_once(tmp_path):
    budget = PersistentExperimentBudget(tmp_path / "budget.json", 2, 100)
    token = budget.reserve("task-1", "route-1", 80)
    budget.mark_dispatched(token)
    usage = GatewayUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    budget.settle(token, usage)
    budget.settle(token, usage)
    assert budget.snapshot()["requests"] == 1
    assert budget.snapshot()["charged_tokens"] == 15
    assert budget.snapshot()["observed_tokens"] == 15


def test_unknown_usage_retains_reserved_tokens(tmp_path):
    budget = PersistentExperimentBudget(tmp_path / "budget.json", 1, 100)
    token = budget.reserve("task-1", "route-1", 90)
    budget.mark_dispatched(token)
    budget.settle(token, None)
    snapshot = budget.snapshot()
    assert snapshot["requests"] == 1
    assert snapshot["charged_tokens"] == 90
    assert snapshot["observed_tokens"] == 0
    assert snapshot["unknown_usage_attempts"] == 1


def test_ceiling_denies_before_dispatch(tmp_path):
    budget = PersistentExperimentBudget(tmp_path / "budget.json", 1, 50)
    with pytest.raises(ExperimentBudgetExceeded):
        budget.reserve("task-1", "route-1", 51)
    assert budget.snapshot()["requests"] == 0


def test_restart_preserves_dispatched_charge_and_discards_pre_dispatch_reservation(tmp_path):
    path = tmp_path / "budget.json"
    budget = PersistentExperimentBudget(path, 3, 100)
    pending = budget.reserve("task-pending", "route-pending", 20)
    dispatched = budget.reserve("task-sent", "route-sent", 40)
    budget.mark_dispatched(dispatched)

    restarted = PersistentExperimentBudget(path, 3, 100)
    snapshot = restarted.snapshot()
    assert snapshot["requests"] == 1
    assert snapshot["charged_tokens"] == 40
    assert snapshot["unknown_usage_attempts"] == 1
    assert snapshot["pending_reservations"] == 0
    with pytest.raises(ExperimentBudgetExceeded):
        # The old reservation had never been dispatched and was correctly freed.
        limited = PersistentExperimentBudget(path, 1, 100)
        limited.reserve("task-new", "route-new", 1)


def test_legacy_budget_file_upgrades_without_resetting_counters(tmp_path):
    path = tmp_path / "budget.json"
    path.write_text('{"requests": 4, "charged_tokens": 300, "observed_tokens": 250}', encoding="utf-8")
    budget = PersistentExperimentBudget(path, 5, 500)
    assert budget.snapshot()["requests"] == 4
    assert budget.snapshot()["charged_tokens"] == 300
    assert budget.snapshot()["observed_tokens"] == 250


class MockAdapter:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.dispatched = 0

    def prepare(self, request, route):
        return PreparedRequest(route, request, b"mock")

    async def complete_once(self, prepared, *, timeout_s, on_dispatch):
        on_dispatch()
        self.dispatched += 1
        if self.error:
            raise self.error
        return self.result

    async def aclose(self):
        return None


def _approved_gateway_config(tmp_path):
    data = yaml.safe_load((ROOT / "config/llm_gateway.yaml").read_text(encoding="utf-8"))
    profile = data["tasks"]["query_understanding"]["profiles"]["phase81_e1_a"]
    profile["route_ids"] = ["query_phase81_e1_a", "query_phase81_e1_a_backup"]
    data["providers"]["openrouter"] = {
        "kind": "openrouter", "credential_env": "OPENROUTER_API_KEY",
        "endpoint": "https://openrouter.ai/api/v1",
    }
    data["routes"]["query_phase81_e1_a"]["enabled"] = True
    data["routes"]["query_phase81_e1_a"]["approval"] = {"status": "approved", "evidence_ref": "evidence.yaml"}
    data["routes"]["query_phase81_e1_a"]["cost"] = {
        "class": "free", "evidence_ref": "evidence.yaml",
        "input_per_million_usd": 0.0, "output_per_million_usd": 0.0,
    }
    backup = dict(data["routes"]["query_phase81_e1_a"])
    backup.update(provider="openrouter", model="fixture/free-model", structured_mode="json_schema")
    backup["approval"] = {"status": "approved", "evidence_ref": "backup_evidence.yaml"}
    backup["cost"] = {"class": "free", "evidence_ref": "backup_evidence.yaml",
                       "input_per_million_usd": 0.0, "output_per_million_usd": 0.0}
    data["routes"]["query_phase81_e1_a_backup"] = backup
    artifacts = {}
    for route_id, file_name, provider_key, model in (
        ("query_phase81_e1_a", "primary.txt", "gemini", "gemini-3.1-flash-lite"),
        ("query_phase81_e1_a_backup", "backup.txt", "openrouter", "fixture/free-model"),
    ):
        content = ("synthetic artifact " + route_id).encode()
        (tmp_path / file_name).write_bytes(content)
        provider = data["providers"][provider_key]
        artifacts[route_id] = {
            "route_id": route_id, "task": "query_understanding", "provider": provider_key,
            "endpoint": provider["endpoint"], "model": model,
            "schema_id": EXPERIMENTAL_SCHEMA_IDS["query_understanding"]["query_v1"],
            "structured_mode": "gemini_schema" if provider_key == "gemini" else "json_schema",
            "status": "valid", "approval": "approved", "cost_class": "free",
            "input_per_million_usd": 0.0, "output_per_million_usd": 0.0,
            "artifact_ref": file_name, "artifact_sha256": hashlib.sha256(content).hexdigest(),
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        }
    (tmp_path / "evidence.yaml").write_text(yaml.safe_dump(artifacts["query_phase81_e1_a"]), encoding="utf-8")
    (tmp_path / "backup_evidence.yaml").write_text(yaml.safe_dump(artifacts["query_phase81_e1_a_backup"]), encoding="utf-8")
    config_path = tmp_path / "gateway.yaml"
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return GatewaySettings(_env_file=None, enabled=True, config_path=config_path)


def test_gateway_failover_accounts_each_dispatch_and_settles_each_attempt(tmp_path):
    async def run():
        settings = _approved_gateway_config(tmp_path)
        registry = ProviderRegistry(settings, experiment_schema_bindings())
        primary = MockAdapter(error=ProviderAttemptError(
            category=ErrorCategory.NETWORK_ERROR, reason_code=ReasonCode.NETWORK_ERROR,
            usage=GatewayUsage(input_tokens=8, output_tokens=3, total_tokens=11),
        ))
        backup = MockAdapter(result=AdapterResult(
            raw_text=QueryUnderstandingOutput(semantic_query="shoes").model_dump_json(),
            usage=GatewayUsage(input_tokens=9, output_tokens=4, total_tokens=13),
            http_status=200, reported_model="fixture/free-model",
        ))
        budget = PersistentExperimentBudget(tmp_path / "persistent-budget.json", 2, 5000)
        gateway = Gateway(
            settings, registry, {"gemini": primary, "openrouter": backup},
            credential_available=lambda _route: True,
            budget_estimator=lambda _route, _request: (1000, None),
            attempt_accounting=budget,
        )
        request = GatewayRequest[QueryUnderstandingOutput](
            task=TaskType.QUERY_UNDERSTANDING, profile="phase81_e1_a",
            request_id="request-1", task_id="task-1",
            system_prompt="system prompt", user_prompt="query prompt",
            schema_id=EXPERIMENTAL_SCHEMA_IDS["query_understanding"]["query_v1"],
            response_schema=QueryUnderstandingOutput,
        )
        response = await gateway.complete(request)
        await gateway.aclose()
        snapshot = budget.snapshot()
        assert len(response.attempts) == 2
        assert snapshot["requests"] == 2
        assert snapshot["charged_tokens"] == 24
        assert snapshot["observed_tokens"] == 24
        assert primary.dispatched == backup.dispatched == 1

    asyncio.run(run())


def test_budget_exhaustion_blocks_backup_before_its_dispatch(tmp_path):
    async def run():
        from shopassist.llm_gateway.errors import DispatchBudgetDenied
        settings = _approved_gateway_config(tmp_path)
        registry = ProviderRegistry(settings, experiment_schema_bindings())
        primary = MockAdapter(error=ProviderAttemptError(
            category=ErrorCategory.NETWORK_ERROR, reason_code=ReasonCode.NETWORK_ERROR,
            usage=GatewayUsage(input_tokens=5, output_tokens=3, total_tokens=8),
        ))
        backup = MockAdapter(result=AdapterResult(raw_text="{}", usage=GatewayUsage()))
        budget = PersistentExperimentBudget(tmp_path / "cap.json", 1, 5000)
        gateway = Gateway(settings, registry, {"gemini": primary, "openrouter": backup},
                          credential_available=lambda _route: True,
                          budget_estimator=lambda _route, _request: (500, None),
                          attempt_accounting=budget)
        request = GatewayRequest[QueryUnderstandingOutput](
            task=TaskType.QUERY_UNDERSTANDING, profile="phase81_e1_a",
            request_id="request-cap", task_id="task-cap", system_prompt="system",
            user_prompt="query", schema_id=EXPERIMENTAL_SCHEMA_IDS["query_understanding"]["query_v1"],
            response_schema=QueryUnderstandingOutput,
        )
        with pytest.raises(DispatchBudgetDenied):
            await gateway.complete(request)
        await gateway.aclose()
        assert primary.dispatched == 1
        assert backup.dispatched == 0
        assert budget.snapshot()["requests"] == 1
        assert budget.snapshot()["charged_tokens"] == 8

    asyncio.run(run())


def test_cancelled_dispatch_keeps_request_and_unknown_token_reservation(tmp_path):
    async def run():
        settings = _approved_gateway_config(tmp_path)
        registry = ProviderRegistry(settings, experiment_schema_bindings())
        entered = asyncio.Event()

        class BlockingAdapter(MockAdapter):
            async def complete_once(self, prepared, *, timeout_s, on_dispatch):
                on_dispatch()
                self.dispatched += 1
                entered.set()
                await asyncio.Event().wait()

        primary = BlockingAdapter()
        backup = MockAdapter(result=AdapterResult(raw_text="{}"))
        budget = PersistentExperimentBudget(tmp_path / "cancel.json", 2, 5000)
        gateway = Gateway(settings, registry, {"gemini": primary, "openrouter": backup},
                          credential_available=lambda _route: True,
                          budget_estimator=lambda _route, _request: (700, None),
                          attempt_accounting=budget)
        request = GatewayRequest[QueryUnderstandingOutput](
            task=TaskType.QUERY_UNDERSTANDING, profile="phase81_e1_a",
            request_id="request-cancel", task_id="task-cancel", system_prompt="system",
            user_prompt="query", schema_id=EXPERIMENTAL_SCHEMA_IDS["query_understanding"]["query_v1"],
            response_schema=QueryUnderstandingOutput,
        )
        task = asyncio.create_task(gateway.complete(request))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await gateway.aclose()
        snapshot = budget.snapshot()
        assert snapshot["requests"] == 1
        assert snapshot["charged_tokens"] == 700
        assert snapshot["unknown_usage_attempts"] == 1
        assert backup.dispatched == 0

    asyncio.run(run())
