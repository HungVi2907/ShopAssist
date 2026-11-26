"""Offline-only tests for the isolated T17 Free Tier validation harness."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from shopassist.llm_gateway.adapters.base import AdapterResult, PreparedRequest
from shopassist.llm_gateway.config import GatewaySettings, ROOT
from shopassist.llm_gateway.experiment_factory import experiment_schema_bindings
from shopassist.llm_gateway.registry import ProviderRegistry
from shopassist.llm_gateway.schemas import GatewayUsage
from shopassist.llm_gateway.validation_harness import (
    MAX_TOTAL_REQUESTS,
    MAX_TOTAL_TOKENS,
    FreeTierEvidence,
    RecommendationFixture,
    T17ValidationHarness,
    ValidationBudget,
    ValidationError,
    load_free_tier_evidence,
    write_result_artifact,
)
from scripts.validate_phase18_providers import parse_args


ROUTES = {
    "query_gemini": ("gemini", "gemini-3.5-flash-lite"),
    "recommendation_gemini": ("gemini", "gemini-3.5-flash-lite"),
    "recommendation_groq": ("groq", "openai/gpt-oss-20b"),
}
ACTIVE_ROUTES = ("query_gemini", "recommendation_gemini", "recommendation_groq")


def _evidence(provider, model, *, paid_disabled=True, expires=timedelta(hours=1)):
    now = datetime.now(timezone.utc)
    artifact = f"synthetic entitlement fixture for {provider}/{model}".encode()
    return FreeTierEvidence(
        provider=provider, model=model, account_ref_sha256=hashlib.sha256(provider.encode()).hexdigest(),
        tier="free", entitlement_verified=True, paid_billing_disabled=paid_disabled,
        source_ref=f"synthetic://test/{provider}", verified_at=now-timedelta(minutes=1), expires_at=now+expires,
        artifact_ref=f"{provider}-proof.txt", artifact_sha256=hashlib.sha256(artifact).hexdigest(),
    )


def _registry(path: Path | None = None):
    settings = GatewaySettings(_env_file=None, enabled=True, allow_paid_models=False,
                               config_path=path or ROOT / "config/llm_gateway.yaml")
    return settings, ProviderRegistry(settings, experiment_schema_bindings())


def _recommendation_json(product_id="T17-PRODUCT-001", evidence_id="T17-PRODUCT-001-E1"):
    return json.dumps({
        "overview": "A recommendation based on the supplied catalog evidence.",
        "products": [{
            "product_id": product_id,
            "summary_reason": "The supplied evidence reports a mesh upper.",
            "strengths": [{"claim": "Mesh upper", "evidence_ids": [evidence_id]}],
            "limitations": [],
            "comparison_note": None,
        }],
    })


class FakeAdapter:
    def __init__(self, route_id, result=None, error=None, callback_twice=False):
        self.route_id = route_id
        self.result = result
        self.error = error
        self.callback_twice = callback_twice
        self.dispatches = 0
        self.closed = 0

    def prepare(self, request, route):
        assert route.route_id == self.route_id
        return PreparedRequest(route, request, b"mock")

    async def complete_once(self, prepared, *, timeout_s, on_dispatch):
        on_dispatch()
        self.dispatches += 1
        if self.callback_twice:
            on_dispatch()
        if self.error:
            raise self.error
        return self.result

    async def aclose(self):
        self.closed += 1


def _harness(tmp_path, *, route_ids=None, live=True, credential=True, evidence_overrides=None,
             adapter_overrides=None, budget=None, paid_allowed=False):
    _settings, registry = _registry()
    route_ids = route_ids or list(ACTIVE_ROUTES)
    evidence = {(provider, model): _evidence(provider, model)
                for provider, model in ROUTES.values()}
    evidence.update(evidence_overrides or {})
    adapters = {}
    for route_id in route_ids:
        provider, model = ROUTES[route_id]
        route = registry.resolve(route_id)
        text = ('{"semantic_query":"running shoes"}' if route_id == "query_gemini"
                else _recommendation_json())
        adapters[route.provider_profile] = FakeAdapter(route_id, AdapterResult(
            raw_text=text, usage=GatewayUsage(input_tokens=80, output_tokens=30, total_tokens=110),
            http_status=200, reported_model=model,
        ))
    adapters.update(adapter_overrides or {})
    synthetic_fixture = RecommendationFixture(
        product_id="T17-PRODUCT-001", product_name="ACME Pace 1", category="running shoes",
        evidence_id="T17-PRODUCT-001-E1", evidence_text="Mesh upper; 250 g per shoe.",
        catalog_sha256=hashlib.sha256(b"synthetic test fixture only").hexdigest(),
    )
    return T17ValidationHarness(
        registry, adapters, budget or ValidationBudget(tmp_path / "budget.json"), evidence,
        credential_available=lambda _route: credential, live_authorized=live,
        paid_models_allowed=paid_allowed, recommendation_fixture=synthetic_fixture,
    ), adapters


def test_candidate_identity_schema_mode_and_output_cap_match_yaml_without_enabling_routes(tmp_path):
    harness, _adapters = _harness(tmp_path)
    for route_id in ACTIVE_ROUTES:
        route, _proof = harness.preflight(route_id)
        assert route.options["max_output_tokens"] == 2048
        assert route.enabled is False
        assert route.approval == "pending"
    assert harness.registry.profile_schema_id(
        __import__("shopassist.llm_gateway.schemas", fromlist=["TaskType"]).TaskType.QUERY_UNDERSTANDING,
        "default",
    ) == "phase8.query.v1"


def test_changed_candidate_model_or_endpoint_fails_exact_identity_preflight(tmp_path):
    data = yaml.safe_load((ROOT / "config/llm_gateway.yaml").read_text(encoding="utf-8"))
    data["routes"]["query_gemini"]["model"] = "different-model"
    path = tmp_path / "changed.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    _settings, registry = _registry(path)
    evidence = {("gemini", ROUTES["query_gemini"][1]): _evidence(*ROUTES["query_gemini"])}
    harness = T17ValidationHarness(registry, {"gemini": FakeAdapter("query_gemini")},
                                  ValidationBudget(tmp_path / "changed-budget.json"), evidence,
                                  lambda _route: True, live_authorized=True)
    with pytest.raises(ValidationError, match="identity"):
        harness.preflight("query_gemini")


def test_gemini_recommendation_candidate_requires_its_separate_credential_profile(tmp_path):
    data = yaml.safe_load((ROOT / "config/llm_gateway.yaml").read_text(encoding="utf-8"))
    data["routes"]["recommendation_gemini"]["provider"] = "gemini"
    path = tmp_path / "wrong-gemini-credential-profile.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    _settings, registry = _registry(path)
    harness, _adapters = _harness(tmp_path, route_ids=["recommendation_gemini"])
    harness.registry = registry
    with pytest.raises(ValidationError, match="identity"):
        harness.preflight("recommendation_gemini")


@pytest.mark.parametrize("live,credential,proof", [
    (False, True, True),
    (True, False, True),
    (True, True, False),
])
def test_preflight_failures_block_before_dispatch(tmp_path, live, credential, proof):
    overrides = {} if proof else {("gemini", ROUTES["query_gemini"][1]): None}
    harness, adapters = _harness(tmp_path, route_ids=["query_gemini"], live=live,
                                 credential=credential, evidence_overrides=overrides,
                                 paid_allowed=False)
    with pytest.raises(ValidationError):
        asyncio.run(harness.validate_one("query_gemini"))
    assert adapters["gemini"].dispatches == 0


def test_harness_rejects_nonzero_paid_policy(tmp_path):
    _settings, registry = _registry()
    with pytest.raises(ValidationError, match="Free Tier only"):
        T17ValidationHarness(registry, {}, ValidationBudget(tmp_path / "ledger.json"), {},
                             lambda _route: True, live_authorized=True, paid_models_allowed=True)


def test_all_preflight_occurs_before_any_dispatch(tmp_path):
    evidence = {("groq", ROUTES["recommendation_groq"][1]): None}
    harness, adapters = _harness(tmp_path, evidence_overrides=evidence)
    with pytest.raises(ValidationError):
        for route_id in ACTIVE_ROUTES:
            harness.preflight(route_id)
    assert all(adapter.dispatches == 0 for adapter in adapters.values())


def test_successful_query_and_recommendation_validate_exact_model_schema_ids_and_usage(tmp_path):
    async def run():
        harness, adapters = _harness(tmp_path, route_ids=["query_gemini", "recommendation_gemini"])
        query = await harness.validate_one("query_gemini")
        rec = await harness.validate_one("recommendation_gemini")
        assert query.status == "passed" and query.output_schema_valid
        assert query.reported_model == query.expected_model
        assert rec.status == "passed" and rec.output_schema_valid
        assert rec.recommendation_ids_valid and rec.evidence_citations_valid
        assert rec.groundedness_review_required is True
        assert adapters["gemini"].dispatches == adapters["gemini_recommendation"].dispatches == 1
        assert harness.budget.total_requests == 2
        assert harness.budget.total_tokens == 220

    asyncio.run(run())


@pytest.mark.parametrize("bad_result", [
    AdapterResult(raw_text="not json", usage=GatewayUsage(total_tokens=9), reported_model="gemini-3.5-flash-lite"),
    AdapterResult(raw_text='{"semantic_query":"x"}', usage=GatewayUsage(total_tokens=9), reported_model="wrong-model"),
])
def test_invalid_json_or_model_mismatch_fails_after_exactly_one_dispatch(tmp_path, bad_result):
    async def run():
        fake = FakeAdapter("query_gemini", bad_result)
        harness, adapters = _harness(tmp_path, route_ids=["query_gemini"],
                                     adapter_overrides={"gemini": fake})
        result = await harness.validate_one("query_gemini")
        assert result.status == "failed"
        assert result.attempt_count == fake.dispatches == 1

    asyncio.run(run())


@pytest.mark.parametrize("product_id,evidence_id,expected", [
    ("UNRELATED-ID", "T17-PRODUCT-001-E1", False),
    ("T17-PRODUCT-001", "MADE-UP-EVIDENCE", False),
    ("T17-PRODUCT-001", "T17-PRODUCT-001-E1", True),
    ("T17-PRODUCT-001", "", False),
])
def test_recommendation_fixture_product_and_evidence_ids_are_checked(tmp_path, product_id, evidence_id, expected):
    async def run():
        route = "recommendation_groq"
        fake = FakeAdapter(route, AdapterResult(raw_text=_recommendation_json(product_id, evidence_id),
                                                usage=GatewayUsage(total_tokens=25),
                                                reported_model=ROUTES[route][1]))
        harness, _adapters = _harness(tmp_path, route_ids=[route], adapter_overrides={"groq": fake})
        result = await harness.validate_one(route)
        assert (result.status == "passed") is expected

    asyncio.run(run())


def test_gemini_recommendation_candidate_uses_profile_credential_adapter_and_validates_grounding_ids(tmp_path):
    async def run():
        route = "recommendation_gemini"
        fake = FakeAdapter(route, AdapterResult(
            raw_text=_recommendation_json(),
            usage=GatewayUsage(input_tokens=75, output_tokens=35, total_tokens=110),
            reported_model=ROUTES[route][1],
        ))
        harness, adapters = _harness(
            tmp_path, route_ids=[route], adapter_overrides={"gemini_recommendation": fake},
        )
        result = await harness.validate_one(route)
        assert result.status == "passed"
        assert result.output_schema_valid
        assert result.recommendation_ids_valid and result.evidence_citations_valid
        assert adapters["gemini_recommendation"].dispatches == 1
        validation = tmp_path / "validation.json"
        write_result_artifact(validation, [result], harness.budget)
        assert result.groundedness_review_ref == "validation_recommendation_gemini_groundedness_review.json"
        review_text = (tmp_path / result.groundedness_review_ref).read_text(encoding="utf-8")
        review = json.loads(review_text)
        assert review["catalog_fixture"]["evidence_text"] == "Mesh upper; 250 g per shoe."
        assert review["recommendation"]["products"][0]["product_id"] == "T17-PRODUCT-001"
        assert "GEMINI_API_KEY" not in review_text
        assert "Return only JSON matching the schema" not in review_text
        assert "review_payload" not in validation.read_text(encoding="utf-8")

    asyncio.run(run())


def test_paid_cost_report_is_rejected_and_no_retry_occurs(tmp_path):
    async def run():
        route_id = "query_gemini"
        fake = FakeAdapter(route_id, AdapterResult(
            raw_text='{"semantic_query":"x"}',
            usage=GatewayUsage(total_tokens=10, estimated_cost_usd=Decimal("0.001")),
            reported_model=ROUTES[route_id][1],
        ))
        harness, adapters = _harness(tmp_path, route_ids=[route_id], adapter_overrides={"gemini": fake})
        result = await harness.validate_one(route_id)
        assert result.status == "failed"
        assert result.attempt_count == adapters["gemini"].dispatches == 1
        assert "nonzero cost" in result.safe_error

    asyncio.run(run())


def test_unknown_usage_is_charged_conservatively_and_does_not_retry(tmp_path):
    async def run():
        route_id = "query_gemini"
        fake = FakeAdapter(route_id, AdapterResult(
            raw_text='{"semantic_query":"x"}', usage=GatewayUsage(),
            reported_model=ROUTES[route_id][1],
        ))
        harness, adapters = _harness(tmp_path, route_ids=[route_id], adapter_overrides={"gemini": fake})
        result = await harness.validate_one(route_id)
        assert result.status == "passed"
        assert harness.budget.tokens["gemini"] > 0
        assert result.attempt_count == adapters["gemini"].dispatches == 1

    asyncio.run(run())


def test_nested_dispatch_callback_is_rejected_without_second_request(tmp_path):
    async def run():
        route_id = "query_gemini"
        fake = FakeAdapter(route_id, AdapterResult(raw_text='{"semantic_query":"x"}',
                                                   usage=GatewayUsage(total_tokens=10),
                                                   reported_model=ROUTES[route_id][1]), callback_twice=True)
        harness, adapters = _harness(tmp_path, route_ids=[route_id], adapter_overrides={"gemini": fake})
        result = await harness.validate_one(route_id)
        assert result.status == "failed"
        assert result.attempt_count == adapters["gemini"].dispatches == 1

    asyncio.run(run())


def test_budget_enforces_provider_and_global_request_and_token_ceilings(tmp_path):
    budget = ValidationBudget(tmp_path / "budget.json", max_total_requests=2, max_total_tokens=100)
    first = budget.reserve("gemini", "query_gemini", 50)
    budget.mark_dispatched(first)
    budget.settle(first, GatewayUsage(input_tokens=30, output_tokens=20, total_tokens=50))
    second = budget.reserve("gemini", "recommendation_gemini", 50)
    budget.mark_dispatched(second)
    budget.settle(second, None)  # Unknown usage conservatively charges reservation.
    assert budget.total_requests == 2
    assert budget.total_tokens == 100
    with pytest.raises(ValidationError, match="request ceiling"):
        budget.reserve("groq", "recommendation_groq", 1)
    with pytest.raises(ValidationError, match="token ceiling"):
        ValidationBudget(tmp_path / "tiny.json", max_total_tokens=20).reserve("gemini", "query_gemini", 21)


def test_operator_amended_two_request_budget_allows_gemini_and_groq_once(tmp_path):
    path = tmp_path / "approved-amendment.json"
    path.write_text(json.dumps({
        "version": 1,
        "requests": {"gemini": 3, "openrouter": 3, "groq": 2},
        "tokens": {"gemini": 819, "openrouter": 11_462, "groq": 1_192},
        "reservations": {},
    }), encoding="utf-8")
    budget = ValidationBudget(path, max_total_requests=10, max_total_tokens=50_000)
    for provider, route_id, tokens in (
        ("gemini", "recommendation_gemini", 664),
        ("groq", "recommendation_groq", 900),
    ):
        reservation = budget.reserve(provider, route_id, 2_048)
        budget.mark_dispatched(reservation)
        budget.settle(reservation, GatewayUsage(total_tokens=tokens))
    assert budget.requests["gemini"] == 4
    assert budget.requests["groq"] == 3
    assert budget.total_requests == 10
    with pytest.raises(ValidationError, match="request ceiling"):
        budget.reserve("groq", "recommendation_groq", 1)
    budget.close()


def test_budget_restart_retains_dispatched_unknown_usage_and_releases_undispatched(tmp_path):
    path = tmp_path / "restart.json"
    budget = ValidationBudget(path)
    dispatched = budget.reserve("gemini", "query_gemini", 100)
    budget.mark_dispatched(dispatched)
    budget.reserve("gemini", "recommendation_gemini", 100)  # No dispatch.
    budget.close()
    restarted = ValidationBudget(path)
    assert restarted.requests["gemini"] == 1
    assert restarted.tokens["gemini"] == 100
    assert restarted.requests["gemini"] == 1
    assert restarted.tokens["gemini"] == 100
    assert restarted.snapshot()["pending_reservations"] == 0
    restarted.close()


def test_budget_ledger_exclusive_process_lock_blocks_concurrent_run(tmp_path):
    path = tmp_path / "exclusive.json"
    first = ValidationBudget(path)
    try:
        with pytest.raises(ValidationError, match="already in use"):
            ValidationBudget(path)
    finally:
        first.close()
    subsequent = ValidationBudget(path)
    subsequent.close()


def test_entitlement_evidence_is_exact_current_free_and_never_synthesized(tmp_path):
    evidence = _evidence("gemini", "gemini-3.5-flash-lite")
    (tmp_path / evidence.artifact_ref).write_text(
        "synthetic entitlement fixture for gemini/gemini-3.5-flash-lite", encoding="utf-8",
    )
    path = tmp_path / "proof.json"
    path.write_text(json.dumps([evidence.model_dump(mode="json")]), encoding="utf-8")
    loaded = load_free_tier_evidence(path)
    assert loaded[("gemini", "gemini-3.5-flash-lite")].paid_billing_disabled
    expired = _evidence("groq", "openai/gpt-oss-20b", expires=timedelta(seconds=-1))
    (tmp_path / expired.artifact_ref).write_text(
        "synthetic entitlement fixture for groq/openai/gpt-oss-20b", encoding="utf-8",
    )
    path.write_text(json.dumps([expired.model_dump(mode="json")]), encoding="utf-8")
    with pytest.raises(ValidationError, match="expired"):
        load_free_tier_evidence(path)


def test_entitlement_artifact_digest_mismatch_fails_closed(tmp_path):
    proof = _evidence("gemini", "gemini-3.5-flash-lite")
    (tmp_path / proof.artifact_ref).write_text("changed evidence", encoding="utf-8")
    path = tmp_path / "proof.json"
    path.write_text(json.dumps([proof.model_dump(mode="json")]), encoding="utf-8")
    with pytest.raises(ValidationError, match="artifact"):
        load_free_tier_evidence(path)


def test_artifact_is_allowlisted_and_does_not_contain_prompts_or_credentials(tmp_path):
    async def run():
        harness, _adapters = _harness(tmp_path, route_ids=["query_gemini"])
        result = await harness.validate_one("query_gemini")
        artifact = tmp_path / "artifact.json"
        write_result_artifact(artifact, [result], harness.budget)
        raw = artifact.read_text(encoding="utf-8")
        assert "Return only valid JSON" not in raw
        assert "GEMINI_API_KEY" not in raw
        assert "actual_cost_usd" in raw

    asyncio.run(run())


def test_budget_hard_caps_cannot_be_increased(tmp_path):
    with pytest.raises(ValidationError, match="hard maximum"):
        ValidationBudget(tmp_path / "too-many.json", max_total_requests=MAX_TOTAL_REQUESTS + 1)
    with pytest.raises(ValidationError, match="hard maximum"):
        ValidationBudget(tmp_path / "too-many-tokens.json", max_total_tokens=MAX_TOTAL_TOKENS + 1)
    with pytest.raises(ValidationError, match="zero-cost"):
        ValidationBudget(tmp_path / "paid.json", max_cost_usd=Decimal("0.01"))


def test_malformed_or_inflated_ledger_fails_closed(tmp_path):
    path = tmp_path / "bad-ledger.json"
    path.write_text(json.dumps({
        "version": 1,
        "requests": {"gemini": 0, "openrouter": 0, "groq": 0},
        "tokens": {"gemini": 10001, "openrouter": 0, "groq": 0},
        "reservations": {},
    }), encoding="utf-8")
    with pytest.raises(ValidationError, match="ledger"):
        ValidationBudget(path)


def test_cli_requires_explicit_live_scope_and_all_zero_cost_budgets():
    args = parse_args([
        "--live", "--routes", "query_gemini", "--operator-approved",
        "--zero-paid-spend-approved", "--entitlement-evidence", "proof.json",
        "--max-requests", "2", "--max-tokens", "10000", "--max-cost-usd", "0",
        "--attempt-timeout", "25", "--deadline", "120",
    ])
    assert args.live is True
    assert args.route_ids == ["query_gemini"]
    with pytest.raises(SystemExit):
        parse_args([
            "--live", "--routes", "query_gemini", "--operator-approved",
            "--zero-paid-spend-approved", "--entitlement-evidence", "proof.json",
            "--max-requests", "2", "--max-tokens", "10000", "--max-cost-usd", "0",
        ])
    with pytest.raises(SystemExit):
        parse_args([
            "--live", "--routes", "query_gemini", "--operator-approved",
            "--zero-paid-spend-approved", "--entitlement-evidence", "proof.json",
            "--max-requests", "2", "--max-tokens", "10000", "--max-cost-usd", "0.01",
            "--attempt-timeout", "25", "--deadline", "120",
        ])
