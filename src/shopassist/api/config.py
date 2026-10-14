"""API runtime configuration and environment settings (Phase 15)."""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shopassist.core.config import ENV_FILE_PATH, PROJECT_ROOT


class APISettings(BaseSettings):
    """Runtime configuration for ShopAssist FastAPI backend."""

    # Server binding
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_log_level: str = Field(default="INFO", alias="API_LOG_LEVEL")

    # Orchestrator limits and defaults
    api_default_top_k: int = Field(default=5, alias="API_DEFAULT_TOP_K")
    api_max_top_k: int = Field(default=20, alias="API_MAX_TOP_K")
    api_retrieval_top_n: int = Field(default=20, alias="API_RETRIEVAL_TOP_N")
    api_reranking_method: str = Field(default="RRF", alias="API_RERANKING_METHOD")
    api_request_timeout_seconds: float = Field(default=90.0, alias="API_REQUEST_TIMEOUT_SECONDS")

    # CORS configuration
    api_cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000", "http://127.0.0.1:8000"],
        alias="API_CORS_ORIGINS",
    )

    # Session configuration for Phase 16 preparation
    api_session_ttl_seconds: int = Field(default=3600, alias="API_SESSION_TTL_SECONDS")
    api_session_max_messages: int = Field(default=10, alias="API_SESSION_MAX_MESSAGES")

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH) if ENV_FILE_PATH.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("api_default_top_k", "api_max_top_k", "api_retrieval_top_n")
    @classmethod
    def validate_positive_integers(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Top-K and Top-N settings must be positive integers.")
        return v

    @field_validator("api_request_timeout_seconds")
    @classmethod
    def validate_positive_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Timeout must be a positive number.")
        return v

    @field_validator("api_reranking_method")
    @classmethod
    def validate_reranking_method(cls, v: str) -> str:
        clean = v.strip().upper()
        allowed = {"RRF", "MULTI_SIGNAL", "CROSS_ENCODER", "COMBINED"}
        if clean not in allowed:
            raise ValueError(f"Unsupported reranking method: '{v}'. Must be one of {allowed}")
        return clean

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            if not v.strip():
                return []
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        if isinstance(v, list):
            return [str(origin).strip() for origin in v if str(origin).strip()]
        return []


_cached_api_settings: APISettings | None = None


def get_api_settings() -> APISettings:
    """Return singleton APISettings instance."""
    global _cached_api_settings
    if _cached_api_settings is None:
        _cached_api_settings = APISettings()
    return _cached_api_settings
