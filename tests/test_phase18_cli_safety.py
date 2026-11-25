"""Offline checks for explicit live CLI gates and Phase 14 Gateway mapping."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shopassist.evaluation.phase14_judge import (
    LLMJudgeResponseSchema,
    run_llm_judge,
    run_llm_judge_with_gateway,
)
from shopassist.llm_gateway.schemas import SCHEMA_IDS, TaskType


def test_phase12_evaluation_requires_explicit_live_flag():
    from scripts.evaluate_phase12 import parse_args

    assert parse_args([]).live is False
    assert parse_args(["--live"]).live is True


def test_phase12_runner_skips_before_loading_or_constructing_provider(monkeypatch):
    from scripts import evaluate_phase12

    monkeypatch.setattr(evaluate_phase12, "load_evaluation_cases", lambda *_: pytest.fail("dataset should not load"))
    result = asyncio.run(evaluate_phase12.run_evaluation(live=False))
    assert result == {"status": "LIVE_SKIPPED", "reason": "EXPLICIT_LIVE_FLAG_REQUIRED"}


def test_gemini_diagnostics_requires_explicit_live_flag():
    from scripts.test_gemini_connection import parse_args

    assert parse_args([]).live is False
    assert parse_args(["--live"]).live is True


def test_phase14_gateway_bridge_preserves_task_schema_and_actual_route():
    output = LLMJudgeResponseSchema(
        groundedness_score=5, factual_correctness_score=4, query_relevance_score=5,
        citation_support_score=5, missing_info_handling_score=4,
        overall_decision="PASS", evidence_supported=True,
        unsupported_claims=[], critique="Evidence supports claims.",
    )
    gateway = SimpleNamespace(complete=AsyncMock(return_value=SimpleNamespace(
        payload=output, provider="gemini", model="approved-model", latency_ms=12.3,
    )))

    result = asyncio.run(run_llm_judge_with_gateway(
        gateway, "query", "evidence", "recommendation"
    ))

    request = gateway.complete.await_args.args[0]
    assert request.task == TaskType.LLM_JUDGE
    assert request.schema_id == SCHEMA_IDS[TaskType.LLM_JUDGE]
    assert request.response_schema is LLMJudgeResponseSchema
    assert result.judge_provider == "gemini"
    assert result.judge_model == "approved-model"
    assert result.execution_mode == "LIVE_API"
    assert result.groundedness_score == 5


def test_phase14_live_generation_failure_is_not_replaced_by_demo():
    client = SimpleNamespace(
        settings=SimpleNamespace(gemini_model="test-model"),
        generate_structured=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
    )

    with pytest.raises(RuntimeError, match="synthetic failure"):
        run_llm_judge("query", "evidence", "recommendation", client=client)


def test_phase14_gateway_pending_route_is_skipped_before_dispatch(monkeypatch):
    from scripts.run_phase14_evaluation import _run_gateway_judge_if_eligible

    monkeypatch.setenv("LLM_GATEWAY_ENABLED", "true")
    result, diagnostics = asyncio.run(_run_gateway_judge_if_eligible(
        "query", "evidence", "recommendation"
    ))

    assert result is None
    assert diagnostics["status"] == "LIVE_SKIPPED"
    assert diagnostics["reason"] in {"DISABLED", "UNAPPROVED"}
