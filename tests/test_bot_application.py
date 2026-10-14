"""Unit tests for bot application factory and handler lifecycle (Phase 16)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from telegram.ext import CommandHandler, MessageHandler

from shopassist.bot.application import _on_shutdown, create_bot_application
from shopassist.bot.clients.recommendation import FastAPIRecommendationClient
from shopassist.bot.config import BotSettings
from shopassist.bot.session import BotSessionManager


def test_create_bot_application():
    settings = BotSettings(
        TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        SHOPASSIST_API_URL="http://127.0.0.1:8000",
    )
    api_client = MagicMock(spec=FastAPIRecommendationClient)
    session_manager = BotSessionManager()

    app = create_bot_application(
        settings=settings,
        api_client=api_client,
        session_manager=session_manager,
    )

    assert app.bot_data["settings"] is settings
    assert app.bot_data["api_client"] is api_client
    assert app.bot_data["session_manager"] is session_manager

    # Check registered handler groups
    handlers = app.handlers.get(0, [])
    command_handlers = [h for h in handlers if isinstance(h, CommandHandler)]
    message_handlers = [h for h in handlers if isinstance(h, MessageHandler)]

    commands = {cmd for h in command_handlers for cmd in h.commands}
    assert "start" in commands
    assert "help" in commands
    assert "reset" in commands
    assert len(message_handlers) >= 2


def test_on_shutdown_closes_api_client():
    mock_app = MagicMock()
    mock_client = MagicMock(spec=FastAPIRecommendationClient)
    mock_client.aclose = AsyncMock()
    mock_app.bot_data = {"api_client": mock_client}

    asyncio.run(_on_shutdown(mock_app))

    mock_client.aclose.assert_awaited_once()
