"""Typed Phase 9 contract."""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class RepresentationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_PREFERENCES = "NO_PREFERENCES"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_INTENT = "UNSUPPORTED_INTENT"
    EMBEDDING_FAILURE = "EMBEDDING_FAILURE"


class PreferenceRepresentationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = "1.0.0"
    semantic_query: str
    normalized_preferences: list[str] = Field(default_factory=list)
    preference_query: str | None = None
    preference_embedding: list[float] | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    has_preferences: bool
    status: RepresentationStatus
    warnings: list[str] = Field(default_factory=list)
    diagnostic_reason: str | None = None
