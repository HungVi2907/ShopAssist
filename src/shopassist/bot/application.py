"""Application factory and handler registration for ShopAssist Telegram Bot (Phase 16)."""

from __future__ import annotations

import logging
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters

from shopassist.bot.clients.recommendation import FastAPIRecommendationClient
from shopassist.bot.config import BotSettings, get_bot_settings
from shopassist.bot.handlers.commands import help_command, reset_command, start_command
from shopassist.bot.handlers.messages import handle_non_text_message, handle_text_message
from shopassist.bot.session import BotSessionManager

logger = logging.getLogger(__name__)


async def _on_shutdown(app: Application) -> None:
    """Cleanly dispose shared resources on application shutdown."""
    logger.info("Closing ShopAssist Telegram Bot application resources...")
    client: FastAPIRecommendationClient | None = app.bot_data.get("api_client")
    if client:
        await client.aclose()
    logger.info("Bot application shutdown completed.")


def create_bot_application(
    settings: BotSettings | None = None,
    api_client: FastAPIRecommendationClient | None = None,
    session_manager: BotSessionManager | None = None,
) -> Application:
    """Build and configure the Telegram Application with all handlers and dependencies.

    Args:
        settings: Bot settings or loaded from environment if None.
        api_client: Custom HTTP client (e.g. for testing) or instantiated from settings.
        session_manager: Custom session manager or new instance.

    Returns:
        Configured telegram Application ready for polling or testing.
    """
    bot_settings = settings or get_bot_settings()

    if not api_client:
        api_client = FastAPIRecommendationClient(
            base_url=bot_settings.shopassist_api_url,
            timeout_seconds=bot_settings.bot_request_timeout_seconds,
        )

    if not session_manager:
        session_manager = BotSessionManager()

    builder = (
        ApplicationBuilder()
        .token(bot_settings.telegram_bot_token)
        .post_shutdown(_on_shutdown)
    )

    app = builder.build()

    # Store shared services in bot_data
    app.bot_data["settings"] = bot_settings
    app.bot_data["api_client"] = api_client
    app.bot_data["session_manager"] = session_manager

    # Register Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset_command))

    # Register Message Handlers
    # Text messages (excluding commands)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )
    # Non-text messages (photos, stickers, audio, documents, voice)
    app.add_handler(
        MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_non_text_message)
    )

    logger.info(
        "ShopAssist Telegram Bot configured (API Base: %s, Default Top-K: %d)",
        bot_settings.shopassist_api_url,
        bot_settings.bot_default_top_k,
    )

    return app
