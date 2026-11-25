"""Safe, structured errors shared by gateway callers and adapters."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ErrorCategory(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    NO_ELIGIBLE_ROUTE = "NO_ELIGIBLE_ROUTE"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    NETWORK_ERROR = "NETWORK_ERROR"
    ATTEMPT_TIMEOUT = "ATTEMPT_TIMEOUT"
    INCOMPATIBLE_ROUTE = "INCOMPATIBLE_ROUTE"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    CANCELLED = "CANCELLED"


class ReasonCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    DISABLED = "DISABLED"
    UNAPPROVED = "UNAPPROVED"
    UNCONFIGURED = "UNCONFIGURED"
    COST_DENIED = "COST_DENIED"
    COOLDOWN = "COOLDOWN"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
    NO_ELIGIBLE_ROUTE = "NO_ELIGIBLE_ROUTE"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    NETWORK_ERROR = "NETWORK_ERROR"
    ATTEMPT_TIMEOUT = "ATTEMPT_TIMEOUT"
    INCOMPATIBLE_ROUTE = "INCOMPATIBLE_ROUTE"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    CANCELLED = "CANCELLED"


class ErrorDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    category: ErrorCategory
    reason_code: ReasonCode
    source: Literal["request", "admission", "provider", "gateway", "deadline"]
    deadline_scope: Literal["task", "parent"] | None = None
    elapsed_ms: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_deadline(self):
        if (self.category == ErrorCategory.DEADLINE_EXCEEDED) != (self.deadline_scope is not None):
            raise ValueError("Deadline category requires a deadline scope")
        if self.deadline_scope is not None and self.source != "deadline":
            raise ValueError("Deadline error requires deadline source")
        return self


class GatewayError(Exception):
    """Caller-visible error whose message never includes provider content."""

    def __init__(self, *, request_id: str, task_id: str, attempts=(), **details):
        from shopassist.llm_gateway.schemas import FailureRecord

        self.record = FailureRecord(
            request_id=request_id, task_id=task_id, attempts=attempts,
            error=ErrorDetails(**details),
        )
        self.category = self.record.error.category
        self.reason_code = self.record.error.reason_code
        self.source = self.record.error.source
        self.deadline_scope = self.record.error.deadline_scope
        self.attempts = self.record.attempts
        self.request_id = self.record.request_id
        self.task_id = self.record.task_id
        self.elapsed_ms = self.record.error.elapsed_ms
        super().__init__(f"LLM gateway failed ({self.category.value}).")

    def to_safe_dict(self):
        return self.record.model_dump(mode="json")


class ProviderAttemptError(Exception):
    """Normalized adapter failure carrying usage even when output is invalid."""

    def __init__(self, *, category: ErrorCategory, reason_code: ReasonCode,
                 http_status: int | None = None, retry_after_s: float | None = None,
                 usage=None):
        from shopassist.llm_gateway.schemas import ProviderFailure

        self.record = ProviderFailure(
            category=category, reason_code=reason_code, http_status=http_status,
            retry_after_s=retry_after_s, usage=usage,
        )
        self.category = self.record.category
        self.reason_code = self.record.reason_code
        self.http_status = self.record.http_status
        self.retry_after_s = self.record.retry_after_s
        self.usage = self.record.usage
        super().__init__(f"LLM provider attempt failed ({self.category.value}).")


class DispatchBudgetDenied(Exception):
    """Trusted local experiment budget denied a pre-dispatch reservation."""
