"""Mocked end-to-end integration tests for Telegram Bot to FastAPI backend (Phase 16)."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest

from shopassist.bot.application import create_bot_application
from shopassist.bot.clients.recommendation import FastAPIRecommendationClient
from shopassist.bot.config import BotSettings
from shopassist.bot.formatters.products import escape_html
from shopassist.bot.handlers.messages import handle_text_message
from shopassist.bot.session import BotSessionManager


@pytest.fixture
def bot_test_fixtures():
    settings = BotSettings(
        TELEGRAM_BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        SHOPASSIST_API_URL="http://127.0.0.1:8000",
        BOT_DEFAULT_TOP_K=5,
        BOT_DEFAULT_LANGUAGE="auto",
    )
    session_manager = BotSessionManager()
    return settings, session_manager


def _create_mock_context(settings, api_client, session_manager):
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
    return context


def _create_mock_update(chat_id: int, text: str):
    update = MagicMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_chat.type = "private"
    update.effective_message = MagicMock()
    update.effective_message.text = text
    update.effective_message.reply_text = AsyncMock()
    return update


# ------------------------------------------------------------------------------
# 1. Successful Recommendation (English)
# ------------------------------------------------------------------------------
def test_mocked_recommendation_english(bot_test_fixtures):
    settings, session_manager = bot_test_fixtures

    mock_resp = {
        "request_id": "req-en-1",
        "status": "SUCCESS",
        "overview": "Here are 2 Puma shoes under 3000 INR.",
        "products": [
            {
                "product_id": "P1",
                "product_name": "Puma Descendant v3",
                "brand": "Puma",
                "category": "Footwear",
                "discounted_price": 2499.0,
                "currency": "INR",
                "rating": 4.2,
                "summary_reason": "Breathable mesh.",
                "strengths": [{"claim": "Lightweight", "evidence_ids": ["E1"]}],
                "limitations": [],
                "comparison_note": "Great runner.",
                "available_evidence": [],
                "product_url": "https://www.flipkart.com/puma-1",
                "image": "https://img.flixcart.com/puma-1.jpg",
            }
        ],
        "metadata": {"recommended_count": 1, "session_id": "tg_101_abc"},
        "usage": {"total_tokens": 120},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_resp)

    client = FastAPIRecommendationClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    )
    context = _create_mock_context(settings, client, session_manager)
    update = _create_mock_update(chat_id=101, text="Puma running shoes under 3000 INR")

    asyncio.run(handle_text_message(update, context))

    # Overview sent
    assert context.bot.send_message.await_count >= 1
    overview_text = context.bot.send_message.await_args_list[0].kwargs["text"]
    assert "Here are 2 Puma shoes under 3000 INR." in overview_text

    # Photo sent with caption
    context.bot.send_photo.assert_awaited_once()
    photo_kwargs = context.bot.send_photo.await_args.kwargs
    assert photo_kwargs["photo"] == "https://img.flixcart.com/puma-1.jpg"
    assert "Puma Descendant v3" in photo_kwargs["caption"]
    assert "₹2,499 INR" in photo_kwargs["caption"]
    assert '<a href="https://www.flipkart.com/puma-1">View Product on Flipkart</a>' in photo_kwargs["caption"]


# ------------------------------------------------------------------------------
# 2. Successful Recommendation (Vietnamese Query)
# ------------------------------------------------------------------------------
def test_mocked_recommendation_vietnamese(bot_test_fixtures):
    settings, session_manager = bot_test_fixtures

    mock_resp = {
        "request_id": "req-vi-1",
        "status": "SUCCESS",
        "overview": "Dưới đây là giày chạy bộ Puma phù hợp với bạn.",
        "products": [
            {
                "product_id": "P2",
                "product_name": "Puma Carson Runner",
                "brand": "Puma",
                "category": "Footwear",
                "discounted_price": 2199.0,
                "currency": "INR",
                "rating": 4.5,
                "summary_reason": "Đệm êm ái, thoáng khí.",
                "strengths": [{"claim": "Đế êm", "evidence_ids": []}],
                "limitations": [],
                "comparison_note": None,
                "available_evidence": [],
                "product_url": "https://www.flipkart.com/puma-2",
                "image": "https://img.flixcart.com/puma-2.jpg",
            }
        ],
        "metadata": {"recommended_count": 1},
        "usage": {"total_tokens": 150},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["query"] == "giày chạy bộ Puma dưới 3000 INR"
        return httpx.Response(200, json=mock_resp)

    client = FastAPIRecommendationClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    )
    context = _create_mock_context(settings, client, session_manager)
    update = _create_mock_update(chat_id=102, text="giày chạy bộ Puma dưới 3000 INR")

    asyncio.run(handle_text_message(update, context))

    overview_text = context.bot.send_message.await_args_list[0].kwargs["text"]
    assert "Dưới đây là giày chạy bộ Puma phù hợp với bạn." in overview_text
    context.bot.send_photo.assert_awaited_once()
    assert "Đệm êm ái, thoáng khí." in context.bot.send_photo.await_args.kwargs["caption"]


# ------------------------------------------------------------------------------
# 3. Multiple Products
# ------------------------------------------------------------------------------
def test_mocked_recommendation_multiple_products(bot_test_fixtures):
    settings, session_manager = bot_test_fixtures

    products = [
        {
            "product_id": f"P{i}",
            "product_name": f"Product {i}",
            "category": "Footwear",
            "discounted_price": 1000.0 * i,
            "currency": "INR",
            "rating": 4.0,
            "summary_reason": f"Product summary {i}",
            "strengths": [],
            "limitations": [],
            "comparison_note": None,
            "available_evidence": [],
            "image": None,
        }
        for i in range(1, 4)
    ]
    mock_resp = {
        "request_id": "req-multi",
        "status": "SUCCESS",
        "overview": "Top 3 products found.",
        "products": products,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_resp)

    client = FastAPIRecommendationClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    )
    context = _create_mock_context(settings, client, session_manager)
    update = _create_mock_update(chat_id=103, text="running shoes")

    asyncio.run(handle_text_message(update, context))

    # Overview + 3 products as text cards (since image is None) = 4 send_message calls
    assert context.bot.send_message.await_count == 4


# ------------------------------------------------------------------------------
# 4. Stop-States: NO_RESULTS, CLARIFICATION_REQUIRED, UNSUPPORTED_INTENT, FALLBACK
# ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "status,overview,expected_in_reply",
    [
        (
            "NO_RESULTS",
            "No products match your budget below 100 INR.",
            "No Matching Products Found",
        ),
        (
            "CLARIFICATION_REQUIRED",
            "Your query is too ambiguous. What type of shoes?",
            "Clarification Needed",
        ),
        (
            "UNSUPPORTED_INTENT",
            "Negative exclusion 'no leather' is not supported.",
            "Unsupported Request",
        ),
        (
            "INVALID_INPUT",
            "Could not parse query structure.",
            "Invalid Query",
        ),
        (
            "EMBEDDING_FAILURE",
            "Neural embedding encoder failed.",
            "Temporary Catalog Issue",
        ),
    ],
)
def test_mocked_business_stop_states(bot_test_fixtures, status, overview, expected_in_reply):
    settings, session_manager = bot_test_fixtures

    mock_resp = {
        "request_id": f"req-{status}",
        "status": status,
        "overview": overview,
        "products": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_resp)

    client = FastAPIRecommendationClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    )
    context = _create_mock_context(settings, client, session_manager)
    update = _create_mock_update(chat_id=104, text="some query")

    asyncio.run(handle_text_message(update, context))

    reply_text = context.bot.send_message.await_args.kwargs["text"]
    assert expected_in_reply in reply_text
    assert escape_html(overview) in reply_text


def test_mocked_deterministic_fallback_notice(bot_test_fixtures):
    settings, session_manager = bot_test_fixtures

    mock_resp = {
        "request_id": "req-fb",
        "status": "DETERMINISTIC_FALLBACK",
        "overview": "Fallback recommendations generated.",
        "products": [
            {
                "product_id": "FB1",
                "product_name": "Fallback Shoe",
                "category": "Footwear",
                "discounted_price": 1500.0,
                "currency": "INR",
                "rating": 4.1,
                "summary_reason": "Rule-based grounded explanation.",
                "strengths": [],
                "limitations": [],
                "available_evidence": [],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_resp)

    client = FastAPIRecommendationClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    )
    context = _create_mock_context(settings, client, session_manager)
    update = _create_mock_update(chat_id=105, text="fallback shoes")

    asyncio.run(handle_text_message(update, context))

    overview_text = context.bot.send_message.await_args_list[0].kwargs["text"]
    assert "Showing grounded catalog recommendations" in overview_text


# ------------------------------------------------------------------------------
# 5. Network & Server Errors (503, 504, Timeout)
# ------------------------------------------------------------------------------
def test_mocked_http_503_service_unavailable(bot_test_fixtures):
    settings, session_manager = bot_test_fixtures

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "Database is unhealthy"})

    client = FastAPIRecommendationClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    )
    context = _create_mock_context(settings, client, session_manager)
    update = _create_mock_update(chat_id=106, text="laptop Asus")

    asyncio.run(handle_text_message(update, context))

    reply_text = context.bot.send_message.await_args.kwargs["text"]
    assert "Backend Error (503)" in reply_text


def test_mocked_http_504_gateway_timeout(bot_test_fixtures):
    settings, session_manager = bot_test_fixtures

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(504, json={"detail": "Pipeline orchestration timed out after 90s"})

    client = FastAPIRecommendationClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8000")
    )
    context = _create_mock_context(settings, client, session_manager)
    update = _create_mock_update(chat_id=107, text="headphones")

    asyncio.run(handle_text_message(update, context))

    reply_text = context.bot.send_message.await_args.kwargs["text"]
    assert "Backend Processing Timeout (504)" in reply_text


# ------------------------------------------------------------------------------
# 6. Secret Redaction Verification
# ------------------------------------------------------------------------------
def test_secret_redaction_in_bot_environment(bot_test_fixtures, caplog):
    settings, session_manager = bot_test_fixtures
    caplog.set_level(logging.DEBUG)

    # Ensure raw token value NEVER appears in BotSettings repr or masked property
    raw_token = settings.telegram_bot_token
    token_secret = raw_token.split(":", 1)[1]

    assert token_secret not in repr(settings)
    assert token_secret not in settings.masked_token
