"""Mocked Phase 8 experiment integrations; adapters never perform network I/O."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from shopassist.llm.experiments.phase82.candidates import CANDIDATES
from shopassist.llm.experiments.phase82.runner import ResearchRunner, fingerprint
from shopassist.llm.experiments.registry import ExperimentRegistry
from shopassist.llm.experiments.runner import ExperimentRunner
from shopassist.llm.schemas import QueryUnderstandingOutput
from shopassist.llm_gateway.schema_ids import EXPERIMENTAL_SCHEMA_IDS
from shopassist.llm_gateway.schemas import GatewayUsage


class MockGateway:
    def __init__(self, output, route):
        self.registry = SimpleNamespace(routes_for=lambda request: (route,))
        self.request = None
        self.complete = AsyncMock(side_effect=self.complete_request)
        self.output = output

    async def complete_request(self, request):
        self.request = request
        return SimpleNamespace(
            payload=self.output,
            raw_text=self.output.model_dump_json(),
            latency_ms=5.0,
            usage=GatewayUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            provider="gemini", model="yaml-model", route_id="yaml-route",
            attempts=(SimpleNamespace(usage=GatewayUsage(input_tokens=10, output_tokens=5, total_tokens=15)),),
        )


def fake_route(temperature=0.0, model="yaml-model"):
    return SimpleNamespace(
        provider="gemini", endpoint="https://generativelanguage.googleapis.com",
        model=model, route_id="yaml-route", enabled=False, approval="pending",
        options={"temperature": temperature, "max_output_tokens": 2048},
    )


def test_phase81_calls_exact_declared_gateway_profile_and_reports_provenance(tmp_path):
    async def run():
        output = QueryUnderstandingOutput(semantic_query="running shoes")
        gateway = MockGateway(output, fake_route())
        runner = ExperimentRunner(
            settings=None, max_requests=2, max_tokens=1000, pacing_delay_sec=0,
            cache_path=tmp_path / "phase81-cache.json", gateway=gateway,
        )
        result = await runner.execute_experiment(
            ExperimentRegistry.get("E1-A"),
            [{"test_id": "case-1", "query": "running shoes", "expected": {}}],
        )
        assert gateway.request.profile == "phase81_e1_a"
        assert gateway.request.schema_id == EXPERIMENTAL_SCHEMA_IDS["query_understanding"]["query_v1"]
        assert gateway.request.response_schema is QueryUnderstandingOutput
        case = result["per_case_results"][0]
        assert case["provider"] == "gemini"
        assert case["model"] == "yaml-model"
        assert case["route_id"] == "yaml-route"
        assert runner._client is None

    asyncio.run(run())


def test_phase82_calls_candidate_profile_with_exact_schema_and_cache_namespace(tmp_path):
    async def run():
        candidate = CANDIDATES["B0"]
        output = candidate.schema(semantic_query="running shoes")
        gateway = MockGateway(output, fake_route(candidate.temperature))
        runner = ResearchRunner(
            settings=None, output_dir=tmp_path, max_requests=2, max_tokens=1000,
            pacing=0, use_cache=True, gateway=gateway,
        )
        row = await runner.run_case(
            candidate,
            {"test_id": "case-1", "query": "running shoes", "expected": {}},
            {"split": "synthetic"}, profile="phase82_b0",
        )
        assert gateway.request.profile == "phase82_b0"
        assert gateway.request.schema_id == EXPERIMENTAL_SCHEMA_IDS["query_understanding"]["query_refined_v1"]
        assert gateway.request.response_schema is candidate.schema
        assert row["provenance"] == {"provider": "gemini", "model": "yaml-model", "route_id": "yaml-route"}
        assert row["token_usage"]["total_tokens"] == 15
        assert runner.client is None
        cache_files = list((tmp_path / "cache").glob("*.json"))
        assert len(cache_files) == 1
        cached = json.loads(cache_files[0].read_text(encoding="utf-8"))
        assert cached["fingerprint"]["profile"] == "phase82_b0"
        assert cached["provenance"]["route_id"] == "yaml-route"

        # Same prompt/model but another declared profile cannot share the cache key.
        profile_c3 = fingerprint(
            candidate, None, "running shoes", profile="phase82_c3",
            route=fake_route(candidate.temperature),
            schema_id=EXPERIMENTAL_SCHEMA_IDS["query_understanding"]["query_refined_v1"],
        )
        assert profile_c3 != cached["fingerprint"]

    asyncio.run(run())
