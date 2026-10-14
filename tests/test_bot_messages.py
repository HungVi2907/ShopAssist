"""Unit and mocked message handler tests for ShopAssist Telegram Bot (Phase 16)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from shopassist.api.schemas import (
    ProductClaimItem,
    ProductResponseItem,
    RecommendationMetadata,
    RecommendationResponse,
    RecommendationUsage,
)
from shopassist.bot.clients.recommendation import (
    BackendConnectionError,
    BackendResponseError,
    BackendTimeoutError,
    FastAPIRecommendationClient,
)
from shopassist.bot.config import BotSettings
from shopassist.bot.handlers.messages import handle_non_text_message, handle_text_message
from shopassist.bot.session import BotSessionManager


@pytest.fixture
def mock_bot_environment():
    settings = BotSettings(
        TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        SHOPASSIST_API_URL="http://127.0.0.1:8000",
        BOT_DEFAULT_TOP_K=5,
        BOT_DEFAULT_LANGUAGE="auto",
    )
    api_client = MagicMock(spec=FastAPIRecommendationClient)
    api_client.recommend = AsyncMock()
    session_manager = BotSessionManager()

    context = MagicMock()
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_photo = AsyncMock()
    context.bot.send_chat_action = AsyncMock()
    context.bot_data = {
        "settings": settings,
        "api_client": api_client,
        "session_manager": session_manager,
    }

    update = MagicMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = 998877
    update.effective_chat.type = "private"
    update.effective_message = MagicMock()
    update.effective_message.text = "Puma shoes under 3000 INR"
    update.effective_message.reply_text = AsyncMock()

    return update, context, api_client, session_manager


def test_handle_text_message_success(mock_bot_environment):
    update, context, api_client, session_manager = mock_bot_environment

    product = ProductResponseItem(
        product_id="P1",
        product_name="Puma Descendant v3",
        brand="Puma",
        category="Footwear",
        discounted_price=2499.0,
        currency="INR",
        rating=4.2,
        summary_reason="Great lightweight runner.",
        strengths=[ProductClaimItem(claim="Breathable", evidence_ids=["E1"])],
        limitations=[],
        product_url="https://www.flipkart.com/item/1",
        image="https://img.flixcart.com/item/1.jpg",
    )
    api_client.recommend.return_value = RecommendationResponse(
        request_id="req-test-1",
        status="SUCCESS",
        overview="Found 1 matching pair of shoes.",
        products=[product],
        metadata=RecommendationMetadata(recommended_count=1),
        usage=RecommendationUsage(total_tokens=100),
    )

    asyncio.run(handle_text_message(update, context))

    # Should send typing action
    context.bot.send_chat_action.assert_awaited()

    # Should send overview message
    assert context.bot.send_message.await_count >= 1
    first_msg_text = context.bot.send_message.await_args_list[0].kwargs["text"]
    assert "Found 1 matching pair of shoes." in first_msg_text

    # Should deliver product photo
    context.bot.send_photo.assert_awaited_once()
    photo_kwargs = context.bot.send_photo.await_args.kwargs
    assert photo_kwargs["photo"] == "https://img.flixcart.com/item/1.jpg"
    assert "Puma Descendant v3" in photo_kwargs["caption"]
    assert "₹2,499 INR" in photo_kwargs["caption"]


def test_handle_text_message_image_delivery_failure_fallback_to_text(mock_bot_environment):
    update, context, api_client, _ = mock_bot_environment

    product = ProductResponseItem(
        product_id="P1",
        product_name="Puma Shoe",
        category="Footwear",
        discounted_price=2000.0,
        summary_reason="Nice shoe.",
        image="https://img.flixcart.com/broken.jpg",
    )
    api_client.recommend.return_value = RecommendationResponse(
        request_id="req-test-2",
        status="SUCCESS",
        overview="Here is your recommendation.",
        products=[product],
    )

    # Simulate Telegram failing to fetch/send image
    context.bot.send_photo.side_effect = Exception("Telegram image fetch failed")

    asyncio.run(handle_text_message(update, context))

    # send_photo attempted
    context.bot.send_photo.assert_awaited_once()

    # After failure, it must fall back to text message so recommendation is NOT lost
    # Message 1 = Overview, Message 2 = Product Card Text
    assert context.bot.send_message.await_count == 2
    card_kwargs = context.bot.send_message.await_args_list[1].kwargs
    assert "Puma Shoe" in card_kwargs["text"]
    assert "₹2,000 INR" in card_kwargs["text"]


def test_handle_text_message_empty_text(mock_bot_environment):
    update, context, api_client, _ = mock_bot_environment
    update.effective_message.text = "   "

    asyncio.run(handle_text_message(update, context))

    api_client.recommend.assert_not_awaited()
    sent_text = context.bot.send_message.await_args.kwargs["text"]
    assert "Please enter a product name" in sent_text


def test_handle_text_message_excessive_length(mock_bot_environment):
    update, context, api_client, _ = mock_bot_environment
    update.effective_message.text = "shoes " * 110  # > 500 characters

    asyncio.run(handle_text_message(update, context))

    api_client.recommend.assert_not_awaited()
    sent_text = context.bot.send_message.await_args.kwargs["text"]
    assert "Query Too Long" in sent_text


def test_handle_text_message_ignores_group_chats(mock_bot_environment):
    update, context, api_client, _ = mock_bot_environment
    update.effective_chat.type = "group"

    asyncio.run(handle_text_message(update, context))

    api_client.recommend.assert_not_awaited()
    context.bot.send_message.assert_not_awaited()


def test_handle_text_message_handles_backend_connection_error(mock_bot_environment):
    update, context, api_client, _ = mock_bot_environment
    api_client.recommend.side_effect = BackendConnectionError("Connection refused")

    asyncio.run(handle_text_message(update, context))

    sent_text = context.bot.send_message.await_args.kwargs["text"]
    assert "Backend Connection Unavailable" in sent_text


def test_handle_text_message_handles_backend_timeout_error(mock_bot_environment):
    update, context, api_client, _ = mock_bot_environment
    api_client.recommend.side_effect = BackendTimeoutError("Timed out after 95s")

    asyncio.run(handle_text_message(update, context))

    sent_text = context.bot.send_message.await_args.kwargs["text"]
    assert "Request Timed Out" in sent_text


def test_handle_non_text_message(mock_bot_environment):
    update, context, api_client, _ = mock_bot_environment

    asyncio.run(handle_non_text_message(update, context))

    sent_text = context.bot.send_message.await_args.kwargs["text"]
    assert "ShopAssist accepts text shopping queries" in sent_text
