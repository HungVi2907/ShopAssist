"""Bounded, local-only telemetry for Gateway task and attempt records.

Only validated allowlisted contract fields are persisted. Prompt, response,
credential, header, exception, and arbitrary provider payloads are never input
to this sink.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field

from shopassist.llm_gateway.config import GatewaySettings, ROOT
from shopassist.llm_gateway.errors import ReasonCode
from shopassist.llm_gateway.schemas import (
    AttemptHistory,
    AttemptRecord,
    ContractModel,
    GatewayUsage,
    Identifier,
    TaskType,
)

QUEUE_CAPACITY = 1000
MAX_FILE_BYTES = 1_048_576
MAX_FILES = 3
MAX_DEDUP_KEYS = 10_000
_USAGE_FIELDS = (
    "input_tokens", "output_tokens", "total_tokens", "reasoning_tokens", "estimated_cost_usd"
)


class RouteSkip(ContractModel):
    route_id: Identifier
    reason: ReasonCode


class TaskTelemetrySummary(ContractModel):
    request_id: Identifier
    task_id: Identifier
    task: TaskType
    profile: Identifier
    schema_id: Identifier
    outcome: Literal["success", "failure", "fallback", "skipped", "cancelled"]
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False)
    actual_route_id: Identifier | None = None
    actual_provider: Literal["gemini", "openrouter", "groq"] | None = None
    actual_model: Identifier | None = None
    skip_reasons: tuple[RouteSkip, ...] = Field(default=(), max_length=32)
    attempt_count: int = Field(ge=0, le=2)
    failover_used: bool
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    missing_usage_attempts: int = Field(ge=0, le=2)


def _aggregate(attempts: tuple[AttemptRecord, ...], field_name: str):
    if not attempts:
        return Decimal(0) if field_name == "estimated_cost_usd" else 0
    values = [getattr(attempt.usage, field_name) for attempt in attempts]
    if any(value is None for value in values):
        return None
    return sum(values, Decimal(0) if field_name == "estimated_cost_usd" else 0)


def build_task_summary(
    history: AttemptHistory,
    *,
    task: TaskType,
    profile: str,
    schema_id: str,
    outcome: Literal["success", "failure", "fallback", "skipped", "cancelled"],
    elapsed_ms: float,
    skip_reasons: tuple[RouteSkip, ...] = (),
) -> TaskTelemetrySummary:
    """Build one summary, aggregating attempt usage exactly once."""
    attempts = history.attempts
    if any((attempt.task, attempt.profile, attempt.schema_id) != (task, profile, schema_id) for attempt in attempts):
        raise ValueError("Task summary identity does not match attempt history")
    winner = next((attempt for attempt in reversed(attempts) if attempt.outcome == "success"), None)
    missing = sum(
        1 for attempt in attempts
        if any(getattr(attempt.usage, name) is None for name in _USAGE_FIELDS)
    )
    return TaskTelemetrySummary(
        request_id=history.request_id,
        task_id=history.task_id,
        task=task,
        profile=profile,
        schema_id=schema_id,
        outcome=outcome,
        elapsed_ms=elapsed_ms,
        actual_route_id=winner.route_id if winner else None,
        actual_provider=winner.provider if winner else None,
        actual_model=winner.model if winner else None,
        skip_reasons=skip_reasons,
        attempt_count=len(attempts),
        failover_used=any(attempt.is_failover_route for attempt in attempts),
        **{name: _aggregate(attempts, name) for name in _USAGE_FIELDS},
        missing_usage_attempts=missing,
    )


class TelemetrySink:
    """Nonblocking bounded queue and rotating local JSONL writer."""

    def __init__(self, settings: GatewaySettings, *, queue_capacity: int = QUEUE_CAPACITY,
                 max_file_bytes: int = MAX_FILE_BYTES, max_files: int = MAX_FILES):
        if queue_capacity < 1 or max_file_bytes < 128 or max_files < 1:
            raise ValueError("Invalid telemetry bounds")
        self.enabled = bool(settings.telemetry_enabled)
        directory = Path(settings.telemetry_dir)
        self.directory = directory if directory.is_absolute() else ROOT / directory
        self.path = self.directory / "gateway.jsonl"
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=queue_capacity)
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.dropped_records = 0
        self._seen_attempts: OrderedDict[tuple[str, int], None] = OrderedDict()
        self._writer: asyncio.Task | None = None
        self._closed = False

    def start(self) -> None:
        if self.enabled and not self._closed and self._writer is None:
            self._writer = asyncio.create_task(self._write_loop(), name="llm-gateway-telemetry")

    def emit_attempt(self, record: AttemptRecord) -> bool:
        """Queue one finalized attempt; duplicate task/attempt keys are ignored."""
        key = (record.task_id, record.attempt_number)
        if not self.enabled or self._closed or key in self._seen_attempts:
            return False
        self._seen_attempts[key] = None
        if len(self._seen_attempts) > MAX_DEDUP_KEYS:
            self._seen_attempts.popitem(last=False)
        return self._enqueue("attempt", record.model_dump(mode="json"))

    def emit_task(self, summary: TaskTelemetrySummary) -> bool:
        if not self.enabled or self._closed:
            return False
        return self._enqueue("task_summary", summary.model_dump(mode="json"))

    def _enqueue(self, event: str, payload: dict) -> bool:
        try:
            line = json.dumps({"event": event, **payload}, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
            if len(line) > self.max_file_bytes:
                self.dropped_records += 1
                return False
            self.queue.put_nowait(line)
            return True
        except (asyncio.QueueFull, TypeError, ValueError):
            self.dropped_records += 1
            return False

    async def _write_loop(self) -> None:
        while True:
            line = await self.queue.get()
            try:
                if line is None:
                    return
                self._write_line(line)
            except Exception:
                # Telemetry failure never changes the provider/business result.
                self.dropped_records += 1
            finally:
                self.queue.task_done()

    def _rotate(self) -> None:
        if self.max_files == 1:
            self.path.unlink(missing_ok=True)
            return
        oldest = self.directory / f"gateway.jsonl.{self.max_files - 1}"
        oldest.unlink(missing_ok=True)
        for index in range(self.max_files - 2, 0, -1):
            source = self.directory / f"gateway.jsonl.{index}"
            if source.exists():
                os.replace(source, self.directory / f"gateway.jsonl.{index + 1}")
        if self.path.exists():
            os.replace(self.path, self.directory / "gateway.jsonl.1")

    def _write_line(self, line: bytes) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        current_size = self.path.stat().st_size if self.path.exists() else 0
        if current_size + len(line) > self.max_file_bytes:
            self._rotate()
        with self.path.open("ab") as stream:
            stream.write(line)

    async def flush(self) -> None:
        if self._writer is not None:
            await self.queue.join()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        writer, self._writer = self._writer, None
        if writer is not None:
            await self.queue.join()
            await self.queue.put(None)
            await writer
