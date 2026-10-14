"""Configuration settings for ShopAssist Telegram Bot (Phase 16)."""

from __future__ import annotations

import logging
from typing import Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class BotSettings(BaseSettings):
    """Environment configuration for the ShopAssist Telegram Bot application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(
        ...,
        alias="TELEGRAM_BOT_TOKEN",
        description="Telegram Bot API token provided by BotFather.",
    )
    shopassist_api_url: str = Field(
        default="http://127.0.0.1:8000",
        alias="SHOPASSIST_API_URL",
        description="Base URL of the local FastAPI backend.",
    )
    bot_request_timeout_seconds: float = Field(
        default=95.0,
        alias="BOT_REQUEST_TIMEOUT_SECONDS",
        description="HTTP client timeout in seconds (includes transport margin over backend 90s timeout).",
    )
    bot_default_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        alias="BOT_DEFAULT_TOP_K",
        description="Default number of recommendations to request.",
    )
    bot_default_language: str = Field(
        default="auto",
        alias="BOT_DEFAULT_LANGUAGE",
        description="Default language preference ('auto', 'en', 'vi').",
    )
    bot_log_level: str = Field(
        default="INFO",
        alias="BOT_LOG_LEVEL",
        description="Logging level for bot handlers.",
    )

    @field_validator("telegram_bot_token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("TELEGRAM_BOT_TOKEN must not be empty.")
        if ":" not in clean or len(clean) < 15:
            raise ValueError("TELEGRAM_BOT_TOKEN format is invalid (expected 'bot_id:token_hash').")
        return clean

    @field_validator("shopassist_api_url")
    @classmethod
    def normalize_api_url(cls, v: str) -> str:
        clean = v.strip().rstrip("/")
        if not clean:
            raise ValueError("SHOPASSIST_API_URL must not be empty.")
        # If user passed full path ending in /api/v1, strip it so base URL remains root
        if clean.endswith("/api/v1"):
            clean = clean[:-7].rstrip("/")
        if not (clean.startswith("http://") or clean.startswith("https://")):
            raise ValueError("SHOPASSIST_API_URL must start with http:// or https://")
        return clean

    @field_validator("bot_request_timeout_seconds")
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("BOT_REQUEST_TIMEOUT_SECONDS must be positive.")
        return v

    @field_validator("bot_default_language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in {"auto", "en", "vi"}:
            raise ValueError("BOT_DEFAULT_LANGUAGE must be one of 'auto', 'en', 'vi'.")
        return clean

    @property
    def masked_token(self) -> str:
        """Return sanitized token string for safe logging."""
        if not self.telegram_bot_token:
            return "<EMPTY>"
        parts = self.telegram_bot_token.split(":", 1)
        if len(parts) == 2:
            return f"{parts[0]}:***"
        return "***"

    def __repr__(self) -> str:
        """Prevent accidental token disclosure in debug logs or tracebacks."""
        return (
            f"BotSettings("
            f"telegram_bot_token='{self.masked_token}', "
            f"shopassist_api_url='{self.shopassist_api_url}', "
            f"bot_request_timeout_seconds={self.bot_request_timeout_seconds}, "
            f"bot_default_top_k={self.bot_default_top_k}, "
            f"bot_default_language='{self.bot_default_language}')"
        )


def get_bot_settings() -> BotSettings:
    """Load and validate bot settings singleton."""
    return BotSettings()
