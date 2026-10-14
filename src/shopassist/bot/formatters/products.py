"""Telegram HTML presentation formatters for ShopAssist recommendations (Phase 16)."""

from __future__ import annotations

import html
import logging
from typing import Sequence
from urllib.parse import urlparse

from shopassist.api.schemas import ProductResponseItem, RecommendationResponse
from shopassist.bot.clients.recommendation import (
    BackendConnectionError,
    BackendResponseError,
    BackendSchemaError,
    BackendTimeoutError,
)

logger = logging.getLogger(__name__)

MAX_TELEGRAM_MESSAGE_LENGTH = 4000
MAX_TELEGRAM_CAPTION_LENGTH = 1000


def escape_html(text: str | None) -> str:
    """Safely escape text for Telegram HTML parse mode.

    Replaces &, <, >, and " to prevent HTML parsing errors or injection.
    """
    if text is None:
        return ""
    return html.escape(str(text).strip(), quote=True)


def is_valid_http_url(url: str | None) -> bool:
    """Verify that a URL is a valid, absolute HTTP or HTTPS URL."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def format_product_card(
    product: ProductResponseItem,
    index: int | None = None,
    include_header: bool = True,
) -> str:
    """Render a single product recommendation card in Telegram HTML format.

    Args:
        product: Structured product item from API response.
        index: 1-indexed product rank position (optional).
        include_header: Whether to include rank and product name header.

    Returns:
        Formatted HTML string.
    """
    lines: list[str] = []

    # 1. Header with Name and Rank
    idx_prefix = f"<b>{index}. </b>" if index is not None else ""
    if include_header:
        lines.append(f"{idx_prefix}<b>{escape_html(product.product_name)}</b>")

    # 2. Key Metadata: Brand & Category
    meta_parts: list[str] = []
    if product.brand:
        meta_parts.append(f"🏷️ <i>Brand:</i> {escape_html(product.brand)}")
    if product.category:
        meta_parts.append(f"📁 <i>Category:</i> {escape_html(product.category)}")
    if meta_parts:
        lines.append(" | ".join(meta_parts))

    # 3. Price & Rating (INR catalog currency strictly preserved)
    price_str = f"₹{product.discounted_price:,.0f} INR"
    if product.rating is not None and product.rating > 0:
        rating_str = f"⭐ {product.rating:.1f}/5.0"
    else:
        rating_str = "⭐ <i>Not rated</i>"
    lines.append(f"💰 <b>{price_str}</b>  •  {rating_str}")

    # 4. Summary Reason (Grounded Match Rationale)
    if product.summary_reason:
        lines.append(f"\n💡 <i>Why this matches:</i>\n{escape_html(product.summary_reason)}")

    # 5. Strengths (with Evidence Citations if available)
    if product.strengths:
        lines.append("\n✨ <b>Key Strengths:</b>")
        for s in product.strengths:
            ev_tag = f" <i>[{', '.join(s.evidence_ids)}]</i>" if s.evidence_ids else ""
            lines.append(f"• {escape_html(s.claim)}{ev_tag}")

    # 6. Limitations / Caveats
    if product.limitations:
        lines.append("\n⚠️ <b>Limitations & Caveats:</b>")
        for lim in product.limitations:
            lines.append(f"• {escape_html(lim.claim)}")

    # 7. Comparative Note
    if product.comparison_note:
        lines.append(f"\n🔍 <i>Comparison:</i> {escape_html(product.comparison_note)}")

    # 8. External Catalog Link
    if product.product_url and is_valid_http_url(product.product_url):
        lines.append(f"\n🔗 <a href=\"{product.product_url}\">View Product on Flipkart</a>")

    return "\n".join(lines)


def format_status_message(response: RecommendationResponse) -> str:
    """Format non-SUCCESS business stop-states with actionable conversational guidance."""
    status = response.status
    overview = escape_html(response.overview)

    if status == "CLARIFICATION_REQUIRED":
        return (
            f"🤔 <b>Clarification Needed</b>\n\n"
            f"{overview}\n\n"
            f"💡 <i>Tip: Please specify the category, brand, or price limit (e.g. 'giày Puma dưới 3000 INR' or 'laptop Asus under 40000 INR').</i>"
        )
    elif status == "NO_RESULTS":
        return (
            f"🔍 <b>No Matching Products Found</b>\n\n"
            f"{overview}\n\n"
            f"💡 <i>Tip: Try expanding your budget range, removing brand constraints, or using broader product terms.</i>"
        )
    elif status == "UNSUPPORTED_INTENT":
        return (
            f"ℹ️ <b>Unsupported Request</b>\n\n"
            f"{overview}\n\n"
            f"💡 <i>Note: ShopAssist searches an Indian e-commerce catalog in INR. Non-INR currencies and negative exclusions ('no leather') are not supported.</i>"
        )
    elif status == "INVALID_INPUT":
        return (
            f"⚠️ <b>Invalid Query</b>\n\n"
            f"{overview}\n\n"
            f"Please enter a descriptive shopping request."
        )
    elif status in ("EMBEDDING_FAILURE", "RETRIEVAL_FAILURE"):
        return (
            f"⚠️ <b>Temporary Catalog Issue</b>\n\n"
            f"{overview}\n\n"
            f"Our search engine encountered a temporary issue. Please try again in a few moments."
        )
    else:
        return (
            f"⚠️ <b>Search Status: {escape_html(status)}</b>\n\n"
            f"{overview}"
        )


def format_error_message(exc: Exception) -> str:
    """Render friendly, sanitized error message for network and internal exceptions."""
    if isinstance(exc, BackendConnectionError):
        return (
            "🔌 <b>Backend Connection Unavailable</b>\n\n"
            "ShopAssist cannot reach the recommendation service at this moment.\n"
            "Please make sure the backend is running and try again shortly."
        )
    elif isinstance(exc, BackendTimeoutError):
        return (
            "⏳ <b>Request Timed Out</b>\n\n"
            "The recommendation engine took longer than expected to process your request.\n"
            "Please try simplifying your query or repeating it in a moment."
        )
    elif isinstance(exc, BackendResponseError):
        if exc.status_code == 422:
            return (
                "⚠️ <b>Request Validation Error</b>\n\n"
                f"{escape_html(exc.detail)}\n"
                "Please make sure your shopping query is between 1 and 500 characters."
            )
        elif exc.status_code == 504:
            return (
                "⏳ <b>Backend Processing Timeout (504)</b>\n\n"
                "The recommendation pipeline timed out while retrieving catalog items.\n"
                "Please try again with a more specific query."
            )
        else:
            req_id_str = f"\n<i>Reference ID: {escape_html(exc.request_id)}</i>" if exc.request_id else ""
            return (
                f"⚠️ <b>Backend Error ({exc.status_code})</b>\n\n"
                "The server encountered an error processing your recommendation.\n"
                f"Please try again later.{req_id_str}"
            )
    elif isinstance(exc, BackendSchemaError):
        return (
            "⚠️ <b>Response Format Error</b>\n\n"
            "Received an unexpected response format from the recommendation service.\n"
            "The engineering team has logged this issue."
        )
    else:
        logger.exception("Unexpected bot handler exception: %s", exc)
        return (
            "⚠️ <b>Unexpected Error</b>\n\n"
            "An unexpected error occurred while handling your request.\n"
            "Please try again shortly."
        )


def split_telegram_message(text: str, max_length: int = MAX_TELEGRAM_MESSAGE_LENGTH) -> list[str]:
    """Split a long text message into safe chunks within Telegram message length limits."""
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    lines = text.split("\n")
    current_chunk: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # include newline
        if current_len + line_len > max_length:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0
            # If a single line itself exceeds max_length, split by characters
            while len(line) > max_length:
                chunks.append(line[:max_length])
                line = line[max_length:]
            if line:
                current_chunk.append(line)
                current_len = len(line) + 1
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


def format_recommendation_response(
    response: RecommendationResponse,
) -> tuple[str, list[dict[str, str | None]]]:
    """Format full recommendation response into header overview and product items.

    Returns:
        tuple of:
          - overview_text: Introduction and summary text
          - product_items: list of dicts with {"text": formatted_card_html, "image_url": url_or_none}
    """
    prefix = ""
    if response.status == "DETERMINISTIC_FALLBACK":
        prefix = "ℹ️ <i>Showing grounded catalog recommendations (standard generation fallback).</i>\n\n"

    overview_text = f"{prefix}🛍️ <b>ShopAssist Recommendations</b>\n\n{escape_html(response.overview)}"

    products: list[dict[str, str | None]] = []
    for idx, prod in enumerate(response.products, start=1):
        card_text = format_product_card(prod, index=idx)
        img_url = prod.image if is_valid_http_url(prod.image) else None
        products.append({
            "text": card_text,
            "image_url": img_url,
            "product_name": prod.product_name,
        })

    return overview_text, products
