"""Telegram Bot command handlers: /start, /help, /reset (Phase 16)."""

from __future__ import annotations

import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from shopassist.bot.session import BotSessionManager

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command — introduce ShopAssist and display example shopping queries."""
    if not update.effective_message:
        return

    user_first_name = update.effective_user.first_name if update.effective_user else "there"

    welcome_text = (
        f"👋 <b>Welcome to ShopAssist, {user_first_name}!</b>\n\n"
        "I am your AI-powered conversational shopping assistant, powered by a multi-stage "
        "hybrid retrieval and grounded recommendation pipeline.\n\n"
        "I can help you find products from our catalog (8,400+ verified items) with "
        "evidence-backed reasons, verified strengths, and price transparency.\n\n"
        "<b>Catalog Currency:</b> Indian Rupee (INR / ₹)\n"
        "<b>Supported Languages:</b> English and Tiếng Việt 🇻🇳\n\n"
        "<b>Try asking me something like:</b>\n"
        "• <i>Tìm giày Puma dưới 3000 INR</i>\n"
        "• <i>Noise cancelling headphones under 2500 INR</i>\n"
        "• <i>Tai nghe Bluetooth pin trâu tầm giá 1500 INR</i>\n"
        "• <i>Casual cotton t-shirt under 800 INR</i>\n\n"
        "Type your shopping query directly, or use /help to see all options."
    )

    await update.effective_message.reply_text(
        text=welcome_text,
        parse_mode=ParseMode.HTML,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command — display usage guidelines, search tips, and available commands."""
    if not update.effective_message:
        return

    help_text = (
        "📖 <b>ShopAssist Guide & Commands</b>\n\n"
        "<b>Available Commands:</b>\n"
        "• /start — Welcome message and quick start examples\n"
        "• /help — Show this help manual\n"
        "• /reset — Reset your conversational context and start fresh\n\n"
        "<b>How to Search:</b>\n"
        "Simply type your natural language shopping request in English or Vietnamese.\n\n"
        "<b>Best Practices:</b>\n"
        "1. <b>Mention a Product Type:</b> e.g. 'shoes', 'tai nghe', 'laptop', 'watch'\n"
        "2. <b>Specify a Price Limit in INR:</b> e.g. 'under 3000 INR', 'dưới 2000 INR'\n"
        "3. <b>Optional Brand Preferences:</b> e.g. 'Puma', 'Sony', 'Samsung', 'Adidas'\n\n"
        "<b>Important Limitations:</b>\n"
        "• Catalog prices are strictly in <b>Indian Rupee (INR)</b>. Foreign currencies (USD, VND) are not converted.\n"
        "• Negative exclusions (e.g. 'no leather', 'không phải màu đen') are unsupported for safety.\n"
        "• Maximum query length is 500 characters."
    )

    await update.effective_message.reply_text(
        text=help_text,
        parse_mode=ParseMode.HTML,
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reset command — rotate conversational session context."""
    if not update.effective_message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    session_manager: BotSessionManager = context.bot_data.get("session_manager")
    if session_manager:
        new_sess = session_manager.reset_session(chat_id)
        logger.info("User reset session for chat %d -> %s", chat_id, new_sess)

    reset_text = (
        "🔄 <b>Conversation Context Reset</b>\n\n"
        "Your conversational shopping context has been reset. "
        "Any subsequent searches will be treated as a brand new shopping session.\n\n"
        "What product would you like to explore now?"
    )

    await update.effective_message.reply_text(
        text=reset_text,
        parse_mode=ParseMode.HTML,
    )
