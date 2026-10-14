"""Main CLI entry point for ShopAssist Telegram Bot (Phase 16).

Usage:
    python -m shopassist.bot.main
"""

from __future__ import annotations

import logging
import sys
from telegram.error import Conflict, InvalidToken

from shopassist.bot.application import create_bot_application
from shopassist.bot.config import get_bot_settings
from shopassist.db.connection import ensure_windows_event_loop_policy


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured logging for bot execution."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=level,
        stream=sys.stdout,
        force=True,
    )
    # Silence noisy polling logs from external libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


def main() -> None:
    """Entry point initializing configuration and running Telegram Long Polling."""
    ensure_windows_event_loop_policy()

    try:
        settings = get_bot_settings()
    except Exception as exc:
        print(f"❌ Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(settings.bot_log_level)
    logger = logging.getLogger("shopassist.bot")

    logger.info("=" * 60)
    logger.info("ShopAssist Telegram Bot — Phase 16")
    logger.info("Target Backend URL: %s", settings.shopassist_api_url)
    logger.info("Bot Token Configured: %s", settings.masked_token)
    logger.info("=" * 60)

    try:
        app = create_bot_application(settings=settings)
    except InvalidToken:
        logger.error("❌ Invalid TELEGRAM_BOT_TOKEN. Please verify your token with BotFather.")
        sys.exit(1)
    except Exception as exc:
        logger.exception("❌ Failed to initialize bot application: %s", exc)
        sys.exit(1)

    logger.info("Starting Telegram Long Polling... (Press Ctrl+C to stop)")
    try:
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=["message"],
        )
    except Conflict:
        logger.error(
            "❌ Polling conflict: Another instance of this Telegram Bot is already running with the same token! "
            "Please terminate the other bot process before starting this one."
        )
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Stopping bot polling cleanly...")
    except Exception as exc:
        logger.exception("❌ Bot polling encountered an unhandled exception: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
