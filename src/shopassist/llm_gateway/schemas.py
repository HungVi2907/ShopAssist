"""Internal gateway contracts. Business schemas remain owned by callers."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shopassist.llm_gateway.errors import ErrorCategory, ErrorDetails, ReasonCode

T = TypeVar("T", bound=BaseModel)
Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$")]
Prompt = Annotated[str, Field(strict=True, min_length=1, max_length=1_000_000)]
Count = Annotated[int, Field(strict=True, ge=0)]
Duration = Annotated[float, Field(ge=0, allow_inf_nan=False)]
HttpStatus = Annotated[int, Field(strict=True, ge=100, le=599)]


class TaskType(str, Enum):
    QUERY_UNDERSTANDING = "query_understanding"
    RECOMMENDATION_GENERATION = "recommendation_generation"
    LLM_JUDGE = "llm_judge"


SCHEMA_IDS = {
    TaskType.QUERY_UNDERSTANDING: "phase8.query.v1",
    TaskType.RECOMMENDATION_GENERATION: "phase12.recommendation.v1",
    TaskType.LLM_JUDGE: "phase14.judge.v1",
}


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class GatewayUsage(ContractModel):
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    total_tokens: Count | None = None
    reasoning_tokens: Count | None = None
    estimated_cost_usd: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)] | None = None
    pricing_ref: Identifier | None = None


class GatewayRequest(ContractModel, Generic[T]):
    task: TaskType
    profile: Identifier = "default"
    request_id: Identifier
    task_id: Identifier
    system_prompt: Prompt = Field(repr=False, exclude=True)
    user_prompt: Prompt = Field(repr=False, exclude=True)
    schema_id: Identifier
    response_schema: type[T] = Field(repr=False, exclude=True)
    parent_deadline_mono: Duration | None = None

    @model_validator(mode="after")
    def check_input(self):
        if not self.system_prompt.strip() or not self.user_prompt.strip():
            raise ValueError("Prompts must contain text")
        if self.schema_id != SCHEMA_IDS[self.task]:
            raise ValueError("Task and schema ID do not match")
        return self


class AttemptRecord(ContractModel):
    request_id: Identifier
    task_id: Identifier
    task: TaskType
    profile: Identifier = "default"
    schema_id: Identifier
    attempt_number: Annotated[int, Field(strict=True, ge=1, le=2)]
    route_index: Count
    route_id: Identifier
    provider: Literal["gemini", "openrouter", "groq"]
    model: Identifier
    reported_model: Identifier | None = None
    started_at_utc: datetime
    latency_ms: Duration
    http_status: HttpStatus | None = None
    outcome: Literal["success", "error", "cancelled"]
    error_category: ErrorCategory | None = None
    reason_code: ReasonCode | None = None
    usage: GatewayUsage = Field(default_factory=GatewayUsage)
    system_chars: Count
    user_chars: Count
    context_chars: Count
    is_failover_route: bool

    @model_validator(mode="after")
    def check_attempt(self):
        if self.started_at_utc.utcoffset() is None or self.started_at_utc.utcoffset().total_seconds() != 0:
            raise ValueError("Attempt timestamp must use UTC")
        if self.context_chars != self.system_chars + self.user_chars:
            raise ValueError("Context character count does not match prompts")
        if self.is_failover_route != (self.route_index > 0):
            raise ValueError("Failover flag does not match route index")
        if self.schema_id != SCHEMA_IDS[self.task]:
            raise ValueError("Task and schema ID do not match")
        if self.outcome == "success":
            if self.error_category is not None or self.reason_code is not None:
                raise ValueError("Successful attempt cannot contain an error")
        elif self.error_category is None or self.reason_code is None:
            raise ValueError("Failed attempt requires normalized error")
        if self.outcome == "cancelled" and self.error_category != ErrorCategory.CANCELLED:
            raise ValueError("Cancelled attempt requires cancellation category")
        return self


class AttemptHistory(ContractModel):
    request_id: Identifier
    task_id: Identifier
    attempts: tuple[AttemptRecord, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def check_history(self):
        routes = set()
        for number, attempt in enumerate(self.attempts, 1):
            if attempt.request_id != self.request_id or attempt.task_id != self.task_id or attempt.attempt_number != number:
                raise ValueError("Attempt correlation or ordering mismatch")
            if attempt.route_id in routes:
                raise ValueError("A route can only be attempted once")
            if (attempt.task, attempt.profile, attempt.schema_id) != (self.attempts[0].task, self.attempts[0].profile, self.attempts[0].schema_id):
                raise ValueError("Attempts must belong to the same task profile")
            routes.add(attempt.route_id)
        return self


class GatewayResponse(AttemptHistory, Generic[T]):
    task: TaskType
    schema_id: Identifier
    payload: T = Field(repr=False, exclude=True)
    raw_text: Annotated[str, Field(max_length=1_000_000)] | None = Field(default=None, repr=False, exclude=True)
    route_id: Identifier
    provider: Literal["gemini", "openrouter", "groq"]
    model: Identifier
    reported_model: Identifier | None = None
    usage: GatewayUsage
    latency_ms: Duration
    failover_used: bool

    @model_validator(mode="after")
    def check_winner(self):
        if not self.attempts:
            raise ValueError("Response requires a successful attempt")
        winner = self.attempts[-1]
        if (
            winner.outcome != "success"
            or any(attempt.outcome == "success" for attempt in self.attempts[:-1])
            or (self.task, self.schema_id, self.route_id, self.provider, self.model, self.reported_model, self.usage, self.failover_used)
            != (winner.task, winner.schema_id, winner.route_id, winner.provider, winner.model, winner.reported_model, winner.usage, winner.is_failover_route)
        ):
            raise ValueError("Response does not match successful attempt")
        return self


class FailureRecord(AttemptHistory):
    error: ErrorDetails

    @model_validator(mode="after")
    def check_failure(self):
        if any(attempt.outcome == "success" for attempt in self.attempts):
            raise ValueError("Failure cannot include a successful attempt")
        return self


class ProviderFailure(ContractModel):
    category: ErrorCategory
    reason_code: ReasonCode
    http_status: HttpStatus | None = None
    retry_after_s: Duration | None = None
    usage: GatewayUsage | None = None
