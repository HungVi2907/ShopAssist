"""Telegram Bot message handlers for natural language shopping queries (Phase 16)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from shopassist.bot.clients.recommendation import FastAPIRecommendationClient
from shopassist.bot.config import BotSettings
from shopassist.bot.formatters.products import (
    MAX_TELEGRAM_CAPTION_LENGTH,
    format_error_message,
    format_recommendation_response,
    format_status_message,
    split_telegram_message,
)
from shopassist.bot.session import BotSessionManager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def typing_indicator(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    interval_seconds: float = 4.0,
) -> AsyncGenerator[None, None]:
    """Background task displaying Telegram typing action while waiting for backend response."""
    stop_event = asyncio.Event()

    # Send initial typing action immediately
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception as exc:
        logger.debug("Initial typing action failed for chat %d: %s", chat_id, exc)

    async def _send_typing_loop() -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass
            if not stop_event.is_set():
                try:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                except Exception as exc:
                    logger.debug("Periodic typing action failed for chat %d: %s", chat_id, exc)

    typing_task = asyncio.create_task(_send_typing_loop())
    try:
        yield
    finally:
        stop_event.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


async def _safe_reply_html(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    """Send HTML message with automatic fallback to plain text if HTML parsing fails."""
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    chunks = split_telegram_message(text)
    for chunk in chunks:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except BadRequest as exc:
            logger.warning("HTML parsing failed, falling back to plain text: %s", exc)
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=None,
                disable_web_page_preview=True,
            )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process incoming text query, call FastAPI backend, and return formatted recommendations."""
    if not update.effective_message or not update.effective_chat:
        return

    # Phase 16 MVP: Restrict to private chats to avoid accidental multi-user context leakage
    if update.effective_chat.type != "private":
        return

    raw_query = update.effective_message.text or ""
    query_text = raw_query.strip()
    chat_id = update.effective_chat.id

    # 1. Input Validation
    if not query_text:
        await _safe_reply_html(
            update,
            context,
            "⚠️ <i>Please enter a product name, brand, or category to search.</i>",
        )
        return

    if len(query_text) > 500:
        await _safe_reply_html(
            update,
            context,
            (
                "⚠️ <b>Query Too Long</b>\n\n"
                f"Your query is {len(query_text)} characters. "
                "Please shorten your shopping request to under 500 characters."
            ),
        )
        return

    # 2. Concurrency Control (Per-Chat Lock)
    session_manager: BotSessionManager = context.bot_data.get("session_manager")
    if not session_manager:
        session_manager = BotSessionManager()
        context.bot_data["session_manager"] = session_manager

    chat_lock = session_manager.get_lock(chat_id)
    if chat_lock.locked():
        await update.effective_message.reply_text(
            "⏳ I am already searching for your previous query. Please give me a moment to finish!"
        )
        return

    async with chat_lock:
        session_id = session_manager.get_session_id(chat_id)
        api_client: FastAPIRecommendationClient = context.bot_data.get("api_client")
        settings: BotSettings = context.bot_data.get("settings")

        if not api_client or not settings:
            logger.error("api_client or settings missing in bot_data.")
            await _safe_reply_html(
                update,
                context,
                "⚠️ <b>Internal Configuration Error</b>\n\nBot services are not properly initialized.",
            )
            return

        logger.info(
            "Processing query for chat %d (session=%s): %s",
            chat_id,
            session_id,
            query_text[:60],
        )

        # 3. Call FastAPI with Typing Indicator
        try:
            async with typing_indicator(chat_id=chat_id, context=context):
                response = await api_client.recommend(
                    query=query_text,
                    top_k=settings.bot_default_top_k,
                    language=settings.bot_default_language,
                    session_id=session_id,
                )
        except Exception as exc:
            error_msg = format_error_message(exc)
            await _safe_reply_html(update, context, error_msg)
            return

        # 4. Handle Recommendations vs Status Stop-States
        if response.status in ("SUCCESS", "DETERMINISTIC_FALLBACK") and response.products:
            overview_text, products = format_recommendation_response(response)

            # Send Overview Message
            await _safe_reply_html(update, context, overview_text)

            # Send Individual Product Cards
            for prod_item in products:
                card_text = prod_item["text"]
                image_url = prod_item["image_url"]

                if image_url:
                    try:
                        # Attempt sending photo with card caption
                        if len(card_text) <= MAX_TELEGRAM_CAPTION_LENGTH:
                            await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=image_url,
                                caption=card_text,
                                parse_mode=ParseMode.HTML,
                            )
                        else:
                            # Caption exceeds limit: send photo, then send full text card
                            await context.bot.send_photo(chat_id=chat_id, photo=image_url)
                            await _safe_reply_html(update, context, card_text)
                    except Exception as img_exc:
                        logger.warning(
                            "Failed to deliver product image %s for %s, falling back to text: %s",
                            image_url,
                            prod_item.get("product_name"),
                            img_exc,
                        )
                        await _safe_reply_html(update, context, card_text)
                else:
                    await _safe_reply_html(update, context, card_text)
        else:
            # Business stop-state (CLARIFICATION_REQUIRED, NO_RESULTS, UNSUPPORTED_INTENT, etc.)
            status_text = format_status_message(response)
            await _safe_reply_html(update, context, status_text)


async def handle_non_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Politely reject non-text updates (photos, stickers, audio, documents, voice)."""
    if not update.effective_message or not update.effective_chat:
        return

    if update.effective_chat.type != "private":
        return

    msg = (
        "📸 <b>ShopAssist accepts text shopping queries.</b>\n\n"
        "Please type what you are looking for in text, for example:\n"
        "• <i>Tìm giày Puma dưới 3000 INR</i>\n"
        "• <i>Bluetooth earphones under 1500 INR</i>\n"
        "• <i>Đồng hồ nam dây da dưới 2000 INR</i>"
    )
    await _safe_reply_html(update, context, msg)
