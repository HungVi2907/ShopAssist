"""Unit tests for Telegram Bot configuration and secret masking (Phase 16)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shopassist.bot.config import BotSettings


def test_bot_settings_valid():
    settings = BotSettings(
        TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        SHOPASSIST_API_URL="http://127.0.0.1:8000/",
        BOT_REQUEST_TIMEOUT_SECONDS=90.0,
        BOT_DEFAULT_TOP_K=5,
        BOT_DEFAULT_LANGUAGE="auto",
    )
    assert settings.telegram_bot_token == "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
    assert settings.shopassist_api_url == "http://127.0.0.1:8000"
    assert settings.bot_request_timeout_seconds == 90.0
    assert settings.bot_default_top_k == 5
    assert settings.bot_default_language == "auto"


def test_bot_settings_strips_trailing_slash_and_api_path():
    settings = BotSettings(
        TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        SHOPASSIST_API_URL="http://127.0.0.1:8000/api/v1/",
    )
    assert settings.shopassist_api_url == "http://127.0.0.1:8000"


def test_bot_settings_requires_token():
    with pytest.raises(ValidationError):
        BotSettings(
            TELEGRAM_BOT_TOKEN="",
        )


def test_bot_settings_validates_token_format():
    with pytest.raises(ValidationError):
        BotSettings(
            TELEGRAM_BOT_TOKEN="invalidtokenwithoutcolon",
        )


def test_bot_settings_validates_api_url_scheme():
    with pytest.raises(ValidationError):
        BotSettings(
            TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            SHOPASSIST_API_URL="ftp://localhost:8000",
        )


def test_bot_settings_bounds_top_k():
    with pytest.raises(ValidationError):
        BotSettings(
            TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            BOT_DEFAULT_TOP_K=0,
        )

    with pytest.raises(ValidationError):
        BotSettings(
            TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            BOT_DEFAULT_TOP_K=25,
        )


def test_bot_settings_validates_timeout_positive():
    with pytest.raises(ValidationError):
        BotSettings(
            TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            BOT_REQUEST_TIMEOUT_SECONDS=-5.0,
        )


def test_bot_settings_validates_language():
    with pytest.raises(ValidationError):
        BotSettings(
            TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            BOT_DEFAULT_LANGUAGE="fr",
        )

    for lang in ("auto", "en", "vi"):
        s = BotSettings(
            TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            BOT_DEFAULT_LANGUAGE=lang,
        )
        assert s.bot_default_language == lang


def test_bot_settings_token_masking_and_repr():
    settings = BotSettings(
        TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
    )
    # Masked token property must hide the token secret
    assert "1234567890:***" == settings.masked_token
    assert "ABCdefGHIjklMNOpqrsTUVwxyz" not in settings.masked_token

    # __repr__ must NOT leak raw token secret
    repr_str = repr(settings)
    assert "ABCdefGHIjklMNOpqrsTUVwxyz" not in repr_str
    assert "1234567890:***" in repr_str
