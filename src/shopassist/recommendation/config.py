"""Configuration management for LLM Recommendation Generation (Phase 12).

Supports OpenRouter (default: google/gemma-4-26b-a4b-it:free) and Groq (openai/gpt-oss-20b).
Loads parameters from environment variables or .env file with validation,
safe masking, and default fallbacks.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shopassist.core.config import ENV_FILE_PATH

logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_MODEL: str = "google/gemma-4-26b-a4b-it:free"
DEFAULT_GROQ_MODEL: str = "openai/gpt-oss-20b"
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

DEFAULT_MAX_COMPLETION_TOKENS: int = 4096
DEFAULT_TIMEOUT_SECONDS: float = 30.0
DEFAULT_REASONING_EFFORT: str = "low"
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_TOP_K: int = 5
DEFAULT_OUTPUT_LANGUAGE: str = "auto"

# Pricing as of 2026-10:
# OpenRouter google/gemma-4-26b-a4b-it:free -> $0.00 / 1M prompt, $0.00 / 1M completion
# Groq openai/gpt-oss-20b -> $0.075 / 1M prompt, $0.30 / 1M completion
DEFAULT_OPENROUTER_FREE_COST_INPUT: float = 0.0
DEFAULT_OPENROUTER_FREE_COST_OUTPUT: float = 0.0
DEFAULT_GROQ_COST_INPUT: float = 0.075
DEFAULT_GROQ_COST_OUTPUT: float = 0.30


def mask_api_key(key: str | None) -> str:
    """Mask an API key for safe logging and reporting.

    Example: 'sk-or-v1-1234...5678' -> 'sk-or-...5678'

    Args:
        key: Raw API key or None.

    Returns:
        Masked API key string or '[NOT CONFIGURED]'.
    """
    if not key or not str(key).strip():
        return "[NOT CONFIGURED]"
    clean = str(key).strip()
    if len(clean) <= 8:
        return "****"
    return f"{clean[:6]}...{clean[-4:]}"


class RecommendationSettings(BaseSettings):
    """LLM provider configuration settings for Phase 12 recommendation generation."""

    openrouter_api_key: str | None = Field(
        default=None,
        alias="OPENROUTER_API_KEY",
        repr=False,
        exclude=True,
    )
    groq_api_key: str | None = Field(
        default=None,
        alias="GROQ_API_KEY",
        repr=False,
        exclude=True,
    )
    phase12_llm_provider: str = Field(
        default="openrouter",
        alias="PHASE12_LLM_PROVIDER",
    )
    phase12_llm_model: str = Field(
        default=DEFAULT_OPENROUTER_MODEL,
        alias="PHASE12_LLM_MODEL",
    )
    openrouter_base_url: str = Field(
        default=OPENROUTER_BASE_URL,
        alias="OPENROUTER_BASE_URL",
    )
    openrouter_http_referer: str | None = Field(
        default="https://github.com/HungVi2907/ShopAssist",
        alias="OPENROUTER_HTTP_REFERER",
    )
    openrouter_app_title: str | None = Field(
        default="ShopAssist",
        alias="OPENROUTER_APP_TITLE",
    )
    phase12_llm_timeout_seconds: float = Field(
        default=DEFAULT_TIMEOUT_SECONDS,
        alias="PHASE12_LLM_TIMEOUT_SECONDS",
    )
    phase12_llm_max_completion_tokens: int = Field(
        default=DEFAULT_MAX_COMPLETION_TOKENS,
        alias="PHASE12_LLM_MAX_COMPLETION_TOKENS",
    )
    phase12_llm_reasoning_effort: str = Field(
        default=DEFAULT_REASONING_EFFORT,
        alias="PHASE12_LLM_REASONING_EFFORT",
    )
    phase12_llm_max_retries: int = Field(
        default=DEFAULT_MAX_RETRIES,
        alias="PHASE12_LLM_MAX_RETRIES",
    )
    phase12_top_k: int = Field(
        default=DEFAULT_TOP_K,
        alias="PHASE12_TOP_K",
    )
    phase12_output_language: str = Field(
        default=DEFAULT_OUTPUT_LANGUAGE,
        alias="PHASE12_OUTPUT_LANGUAGE",
    )
    phase12_cost_input_per_m: float | None = Field(
        default=None,
        alias="PHASE12_COST_INPUT_PER_M",
    )
    phase12_cost_output_per_m: float | None = Field(
        default=None,
        alias="PHASE12_COST_OUTPUT_PER_M",
    )

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH) if ENV_FILE_PATH.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("phase12_llm_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ("openrouter", "groq"):
            raise ValueError(f"PHASE12_LLM_PROVIDER must be 'openrouter' or 'groq', got '{v}'")
        return clean

    @field_validator("phase12_llm_max_completion_tokens")
    @classmethod
    def validate_max_tokens(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"phase12_llm_max_completion_tokens must be positive, got {v}")
        return v

    @field_validator("phase12_llm_timeout_seconds")
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"phase12_llm_timeout_seconds must be positive, got {v}")
        return v

    @field_validator("phase12_llm_max_retries")
    @classmethod
    def validate_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"phase12_llm_max_retries must be non-negative, got {v}")
        return v

    @field_validator("phase12_top_k")
    @classmethod
    def validate_top_k(cls, v: int) -> int:
        if not (1 <= v <= 20):
            raise ValueError(f"phase12_top_k must be between 1 and 20, got {v}")
        return v

    @field_validator("phase12_llm_reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ("none", "low", "medium", "high"):
            raise ValueError(f"reasoning_effort must be one of ('none', 'low', 'medium', 'high'), got {v}")
        return clean

    @model_validator(mode="after")
    def resolve_costs_and_model(self) -> RecommendationSettings:
        # Default pricing based on provider and model if not explicitly specified
        if self.phase12_cost_input_per_m is None:
            if self.phase12_llm_provider == "openrouter":
                self.phase12_cost_input_per_m = (
                    DEFAULT_OPENROUTER_FREE_COST_INPUT if ":free" in self.phase12_llm_model else 0.07
                )
            else:
                self.phase12_cost_input_per_m = DEFAULT_GROQ_COST_INPUT

        if self.phase12_cost_output_per_m is None:
            if self.phase12_llm_provider == "openrouter":
                self.phase12_cost_output_per_m = (
                    DEFAULT_OPENROUTER_FREE_COST_OUTPUT if ":free" in self.phase12_llm_model else 0.25
                )
            else:
                self.phase12_cost_output_per_m = DEFAULT_GROQ_COST_OUTPUT

        return self

    def get_api_key(self) -> str:
        """Retrieve and validate the active provider's API key.

        Returns:
            Non-empty API key string.

        Raises:
            ValueError: If the required API key for the selected provider is missing.
        """
        provider = self.phase12_llm_provider.lower()
        if provider == "openrouter":
            if not self.openrouter_api_key or not self.openrouter_api_key.strip():
                raise ValueError(
                    "OPENROUTER_API_KEY is not configured in the environment or .env file. "
                    "Please configure OPENROUTER_API_KEY in your .env file."
                )
            return self.openrouter_api_key.strip()
        elif provider == "groq":
            if not self.groq_api_key or not self.groq_api_key.strip():
                raise ValueError(
                    "GROQ_API_KEY is not configured in the environment or .env file. "
                    "Please configure GROQ_API_KEY in your .env file."
                )
            return self.groq_api_key.strip()
        else:
            raise ValueError(f"Unsupported provider: '{self.phase12_llm_provider}'")

    def get_masked_api_key(self) -> str:
        """Return masked version of the active provider's API key."""
        try:
            return mask_api_key(self.get_api_key())
        except ValueError:
            return "[NOT CONFIGURED]"

    def to_safe_dict(self) -> dict[str, Any]:
        """Convert settings to dictionary without exposing sensitive secrets."""
        return {
            "phase12_llm_provider": self.phase12_llm_provider,
            "phase12_llm_model": self.phase12_llm_model,
            "openrouter_api_key": mask_api_key(self.openrouter_api_key),
            "groq_api_key": mask_api_key(self.groq_api_key),
            "active_api_key": self.get_masked_api_key(),
            "phase12_llm_timeout_seconds": self.phase12_llm_timeout_seconds,
            "phase12_llm_max_completion_tokens": self.phase12_llm_max_completion_tokens,
            "phase12_llm_reasoning_effort": self.phase12_llm_reasoning_effort,
            "phase12_llm_max_retries": self.phase12_llm_max_retries,
            "phase12_top_k": self.phase12_top_k,
            "phase12_output_language": self.phase12_output_language,
            "phase12_cost_input_per_m": self.phase12_cost_input_per_m,
            "phase12_cost_output_per_m": self.phase12_cost_output_per_m,
        }


# Global singleton
recommendation_settings = RecommendationSettings()


def get_recommendation_settings() -> RecommendationSettings:
    """Retrieve global RecommendationSettings singleton."""
    global recommendation_settings
    return recommendation_settings
