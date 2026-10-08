"""Configuration management for LLM and Google Gemini API (Phase 8).

Loads parameters from environment variables or .env file with validation,
safe masking, and default fallbacks.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shopassist.core.config import ENV_FILE_PATH, PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL: str = "gemini-3.1-flash-lite"
DEFAULT_TEMPERATURE: float = 0.0
DEFAULT_MAX_OUTPUT_TOKENS: int = 2048
DEFAULT_TIMEOUT_SECONDS: float = 30.0
DEFAULT_MAX_RETRIES: int = 3


def mask_api_key(key: str | None) -> str:
    """Mask an API key for safe logging and reporting.

    Example: 'AIzaSyD...1234' -> 'AIzaSy...1234'

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


class LLMSettings(BaseSettings):
    """Google Gemini and LLM provider configuration settings."""

    llm_provider: str = Field(default="gemini", alias="LLM_PROVIDER")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default=DEFAULT_GEMINI_MODEL, alias="GEMINI_MODEL")
    gemini_temperature: float = Field(default=DEFAULT_TEMPERATURE, alias="GEMINI_TEMPERATURE")
    gemini_max_output_tokens: int = Field(default=DEFAULT_MAX_OUTPUT_TOKENS, alias="GEMINI_MAX_OUTPUT_TOKENS")
    gemini_timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, alias="GEMINI_TIMEOUT_SECONDS")
    gemini_max_retries: int = Field(default=DEFAULT_MAX_RETRIES, alias="GEMINI_MAX_RETRIES")

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH) if ENV_FILE_PATH.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("gemini_temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """Validate temperature is between 0.0 and 2.0."""
        if not (0.0 <= v <= 2.0):
            raise ValueError(f"gemini_temperature must be between 0.0 and 2.0, got {v}")
        return v

    @field_validator("gemini_max_output_tokens")
    @classmethod
    def validate_max_tokens(cls, v: int) -> int:
        """Validate max_output_tokens is positive."""
        if v <= 0:
            raise ValueError(f"gemini_max_output_tokens must be positive, got {v}")
        return v

    @field_validator("gemini_timeout_seconds")
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        """Validate timeout_seconds is positive."""
        if v <= 0.0:
            raise ValueError(f"gemini_timeout_seconds must be positive, got {v}")
        return v

    @field_validator("gemini_max_retries")
    @classmethod
    def validate_retries(cls, v: int) -> int:
        """Validate max_retries is non-negative."""
        if v < 0:
            raise ValueError(f"gemini_max_retries must be non-negative, got {v}")
        return v

    def get_api_key(self) -> str:
        """Retrieve and validate the Gemini API key.

        Returns:
            Non-empty API key string.

        Raises:
            ValueError: If GEMINI_API_KEY is not configured or empty.
        """
        if not self.gemini_api_key or not self.gemini_api_key.strip():
            raise ValueError(
                "GEMINI_API_KEY is not configured in the environment or .env file. "
                "Please configure GEMINI_API_KEY in your .env file."
            )
        return self.gemini_api_key.strip()

    def get_masked_api_key(self) -> str:
        """Return masked version of the API key."""
        return mask_api_key(self.gemini_api_key)

    @property
    def provider(self) -> str:
        return self.llm_provider

    @property
    def model(self) -> str:
        return self.gemini_model

    @property
    def temperature(self) -> float:
        return self.gemini_temperature

    @property
    def max_output_tokens(self) -> int:
        return self.gemini_max_output_tokens

    @property
    def timeout_seconds(self) -> float:
        return self.gemini_timeout_seconds

    @property
    def max_retries(self) -> int:
        return self.gemini_max_retries

    @property
    def masked_api_key(self) -> str:
        return self.get_masked_api_key()

    def to_safe_dict(self) -> dict[str, Any]:
        """Convert settings to dictionary without exposing sensitive secrets."""
        return {
            "llm_provider": self.llm_provider,
            "gemini_api_key": self.get_masked_api_key(),
            "gemini_model": self.gemini_model,
            "gemini_temperature": self.gemini_temperature,
            "gemini_max_output_tokens": self.gemini_max_output_tokens,
            "gemini_timeout_seconds": self.gemini_timeout_seconds,
            "gemini_max_retries": self.gemini_max_retries,
        }


# Global LLM settings singleton
llm_settings = LLMSettings()


def get_llm_settings() -> LLMSettings:
    """Retrieve the global LLMSettings singleton."""
    global llm_settings
    return llm_settings
