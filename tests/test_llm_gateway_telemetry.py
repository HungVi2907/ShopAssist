"""Telemetry tests use synthetic records and temporary local files only."""
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from shopassist.llm_gateway.config import GatewaySettings
from shopassist.llm_gateway.errors import ErrorCategory, ReasonCode
from shopassist.llm_gateway.schemas import AttemptHistory, AttemptRecord, GatewayUsage, TaskType
from shopassist.llm_gateway.telemetry import (
    MAX_DEDUP_KEYS,
    RouteSkip,
    TelemetrySink,
    build_task_summary,
)


def attempt(number=1, *, outcome="success", route="query_gemini", provider="gemini", model="gemini-3.5-flash-lite", usage=None):
    failed = outcome != "success"
    return AttemptRecord(
        request_id="request-1", task_id="task-1", task=TaskType.QUERY_UNDERSTANDING,
        profile="default", schema_id="phase8.query.v1", attempt_number=number,
        route_index=number - 1, route_id=route, provider=provider, model=model,
        started_at_utc=datetime(2026, 11, 25, tzinfo=timezone.utc), latency_ms=12.5,
        http_status=503 if failed else 200, outcome=outcome,
        error_category=ErrorCategory.PROVIDER_UNAVAILABLE if failed else None,
        reason_code=ReasonCode.PROVIDER_UNAVAILABLE if failed else None,
        usage=usage or GatewayUsage(), system_chars=10, user_chars=20, context_chars=30,
        is_failover_route=number > 1,
    )


def settings(tmp_path, **kwargs):
    return GatewaySettings(_env_file=None, telemetry_dir=tmp_path, **kwargs)


def test_summary_uses_winning_provider_and_aggregates_attempt_usage_once():
    first = attempt(1, outcome="error", usage=GatewayUsage(input_tokens=10, output_tokens=5, total_tokens=15, reasoning_tokens=2, estimated_cost_usd=Decimal("0.01")))
    second = attempt(2, route="query_openrouter", provider="openrouter", model="baidu/ernie-5.5-flash-preview:free",
                     usage=GatewayUsage(input_tokens=20, output_tokens=7, total_tokens=27, reasoning_tokens=3, estimated_cost_usd=Decimal("0")))
    history = AttemptHistory(request_id="request-1", task_id="task-1", attempts=(first, second))
    summary = build_task_summary(history, task=TaskType.QUERY_UNDERSTANDING, profile="default",
                                 schema_id="phase8.query.v1", outcome="success", elapsed_ms=100)
    assert (summary.actual_route_id, summary.actual_provider, summary.actual_model) == (
        "query_openrouter", "openrouter", "baidu/ernie-5.5-flash-preview:free")
    assert summary.attempt_count == 2 and summary.failover_used
    assert (summary.input_tokens, summary.output_tokens, summary.total_tokens) == (30, 12, 42)
    assert summary.reasoning_tokens == 5
    assert summary.estimated_cost_usd == Decimal("0.01")
    assert summary.missing_usage_attempts == 0


def test_summary_preserves_unknown_usage_instead_of_inventing_totals():
    history = AttemptHistory(request_id="request-1", task_id="task-1", attempts=(
        attempt(1, usage=GatewayUsage(input_tokens=10, output_tokens=None, total_tokens=None)),
    ))
    summary = build_task_summary(history, task=TaskType.QUERY_UNDERSTANDING, profile="default",
                                 schema_id="phase8.query.v1", outcome="success", elapsed_ms=5)
    assert summary.input_tokens == 10
    assert summary.output_tokens is None
    assert summary.total_tokens is None
    assert summary.missing_usage_attempts == 1


def test_task_failover_flag_tracks_attempt_even_when_backup_fails():
    history = AttemptHistory(request_id="request-1", task_id="task-1", attempts=(
        attempt(1, outcome="error"),
        attempt(2, outcome="error", route="query_openrouter", provider="openrouter",
                model="baidu/ernie-5.5-flash-preview:free"),
    ))
    summary = build_task_summary(history, task=TaskType.QUERY_UNDERSTANDING, profile="default",
                                 schema_id="phase8.query.v1", outcome="failure", elapsed_ms=30)
    assert summary.failover_used
    assert summary.actual_route_id is None and summary.actual_provider is None


def test_zero_dispatch_summary_has_zero_usage_and_no_actual_provider():
    history = AttemptHistory(request_id="request-1", task_id="task-1")
    summary = build_task_summary(
        history, task=TaskType.RECOMMENDATION_GENERATION, profile="default",
        schema_id="phase12.recommendation.v1", outcome="fallback", elapsed_ms=4,
        skip_reasons=(RouteSkip(route_id="recommendation_openrouter", reason=ReasonCode.DISABLED),),
    )
    assert summary.attempt_count == 0
    assert summary.input_tokens == summary.output_tokens == summary.total_tokens == 0
    assert summary.estimated_cost_usd == 0
    assert summary.actual_provider is None and summary.actual_model is None


@pytest.mark.asyncio
async def test_sink_writes_allowlisted_records_and_deduplicates_attempt(tmp_path):
    sink = TelemetrySink(settings(tmp_path))
    sink.start()
    record = attempt(usage=GatewayUsage(input_tokens=2, output_tokens=3, total_tokens=5))
    assert sink.emit_attempt(record)
    assert not sink.emit_attempt(record)
    summary = build_task_summary(AttemptHistory(request_id="request-1", task_id="task-1", attempts=(record,)),
                                 task=TaskType.QUERY_UNDERSTANDING, profile="default", schema_id="phase8.query.v1",
                                 outcome="success", elapsed_ms=12.5)
    assert sink.emit_task(summary)
    await sink.flush()
    await sink.aclose()
    events = [json.loads(line) for line in (tmp_path / "gateway.jsonl").read_text().splitlines()]
    assert [event["event"] for event in events] == ["attempt", "task_summary"]
    assert events[0]["model"] == "gemini-3.5-flash-lite"
    assert "system_prompt" not in events[0] and "raw_text" not in events[0]
    assert "GEMINI_API_KEY" not in json.dumps(events)


@pytest.mark.asyncio
async def test_queue_is_bounded_and_dropped_records_are_counted(tmp_path):
    sink = TelemetrySink(settings(tmp_path), queue_capacity=1)
    assert sink.emit_attempt(attempt())
    assert not sink.emit_attempt(attempt(2, route="route-b", provider="groq", model="openai/gpt-oss-20b"))
    assert sink.dropped_records == 1
    assert sink.queue.qsize() == 1
    await sink.aclose()


@pytest.mark.asyncio
async def test_rotating_jsonl_stays_within_file_size_and_count(tmp_path):
    sink = TelemetrySink(settings(tmp_path), max_file_bytes=1024, max_files=3)
    sink.start()
    for i in range(1, 9):
        record = attempt(1, route=f"route_{i}")
        record = record.model_copy(update={"task_id": f"task_{i}", "request_id": f"request_{i}"})
        assert sink.emit_attempt(record)
    await sink.flush()
    await sink.aclose()
    files = list(tmp_path.glob("gateway.jsonl*"))
    assert len(files) <= 3
    assert all(path.stat().st_size <= 1024 for path in files)
    assert sum(len(path.read_text().splitlines()) for path in files) < 8


@pytest.mark.asyncio
async def test_disabled_sink_does_not_write(tmp_path):
    sink = TelemetrySink(settings(tmp_path, telemetry_enabled=False))
    sink.start()
    assert not sink.emit_attempt(attempt())
    await sink.aclose()
    assert not list(tmp_path.iterdir())


def test_record_contract_rejects_unallowlisted_secret_fields():
    with pytest.raises(Exception):
        AttemptRecord.model_validate({**attempt().model_dump(), "api_key": "synthetic-secret"})


def test_deduplication_cache_is_bounded():
    assert MAX_DEDUP_KEYS == 10_000
