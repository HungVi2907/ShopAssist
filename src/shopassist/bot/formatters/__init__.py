"""Response formatting and HTML rendering for ShopAssist Telegram Bot."""

from shopassist.bot.formatters.products import (
    escape_html,
    format_error_message,
    format_product_card,
    format_recommendation_response,
    format_status_message,
    split_telegram_message,
)

__all__ = [
    "escape_html",
    "format_error_message",
    "format_product_card",
    "format_recommendation_response",
    "format_status_message",
    "split_telegram_message",
]
