"""Unit tests for Telegram Bot command handlers (Phase 16)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from telegram.constants import ParseMode

from shopassist.bot.handlers.commands import help_command, reset_command, start_command
from shopassist.bot.session import BotSessionManager


@pytest.fixture
def mock_update():
    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.first_name = "Alex"
    update.effective_chat = MagicMock()
    update.effective_chat.id = 12345
    return update


@pytest.fixture
def mock_context():
    context = MagicMock()
    context.bot_data = {
        "session_manager": BotSessionManager(),
    }
    return context


def test_start_command(mock_update, mock_context):
    asyncio.run(start_command(mock_update, mock_context))

    mock_update.effective_message.reply_text.assert_awaited_once()
    call_kwargs = mock_update.effective_message.reply_text.await_args.kwargs
    assert "Welcome to ShopAssist, Alex!" in call_kwargs["text"]
    assert "Tìm giày Puma dưới 3000 INR" in call_kwargs["text"]
    assert call_kwargs["parse_mode"] == ParseMode.HTML


def test_help_command(mock_update, mock_context):
    asyncio.run(help_command(mock_update, mock_context))

    mock_update.effective_message.reply_text.assert_awaited_once()
    call_kwargs = mock_update.effective_message.reply_text.await_args.kwargs
    assert "ShopAssist Guide & Commands" in call_kwargs["text"]
    assert "/start" in call_kwargs["text"]
    assert "/help" in call_kwargs["text"]
    assert "/reset" in call_kwargs["text"]
    assert "Indian Rupee (INR)" in call_kwargs["text"]


def test_reset_command_rotates_session(mock_update, mock_context):
    sm: BotSessionManager = mock_context.bot_data["session_manager"]
    initial_sess = sm.get_session_id(12345)

    asyncio.run(reset_command(mock_update, mock_context))

    mock_update.effective_message.reply_text.assert_awaited_once()
    call_kwargs = mock_update.effective_message.reply_text.await_args.kwargs
    assert "Conversation Context Reset" in call_kwargs["text"]

    new_sess = sm.get_session_id(12345)
    assert new_sess != initial_sess
