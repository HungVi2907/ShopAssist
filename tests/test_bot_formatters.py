"""Unit tests for Telegram HTML formatters and message splitting (Phase 16)."""

from __future__ import annotations

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
    BackendSchemaError,
    BackendTimeoutError,
)
from shopassist.bot.formatters.products import (
    escape_html,
    format_error_message,
    format_product_card,
    format_recommendation_response,
    format_status_message,
    is_valid_http_url,
    split_telegram_message,
)


def test_escape_html():
    assert escape_html("AT&T <Phone> & \"Watch\"") == "AT&amp;T &lt;Phone&gt; &amp; &quot;Watch&quot;"
    assert escape_html(None) == ""
    assert escape_html("") == ""
    assert escape_html("   Plain text   ") == "Plain text"


def test_is_valid_http_url():
    assert is_valid_http_url("http://example.com/item") is True
    assert is_valid_http_url("https://www.flipkart.com/p/123") is True
    assert is_valid_http_url("javascript:alert(1)") is False
    assert is_valid_http_url("file:///etc/passwd") is False
    assert is_valid_http_url("ftp://ftp.example.com") is False
    assert is_valid_http_url("") is False
    assert is_valid_http_url(None) is False
    assert is_valid_http_url("not a url") is False


def test_format_product_card_complete():
    product = ProductResponseItem(
        product_id="P001",
        product_name="Puma Descendant v3 Running Shoes",
        brand="Puma",
        category="Footwear",
        discounted_price=2499.0,
        currency="INR",
        rating=4.2,
        summary_reason="Puma running shoes with breathable air mesh.",
        strengths=[ProductClaimItem(claim="Air mesh upper", evidence_ids=["E1"])],
        limitations=[ProductClaimItem(claim="Not waterproof", evidence_ids=[])],
        comparison_note="Lighter than typical sneakers.",
        product_url="https://www.flipkart.com/item/123",
        image="https://img.flixcart.com/item/123.jpg",
    )

    card = format_product_card(product, index=1)

    assert "<b>1. </b><b>Puma Descendant v3 Running Shoes</b>" in card
    assert "<i>Brand:</i> Puma" in card
    assert "<i>Category:</i> Footwear" in card
    assert "₹2,499 INR" in card
    assert "⭐ 4.2/5.0" in card
    assert "Air mesh upper <i>[E1]</i>" in card
    assert "Not waterproof" in card
    assert "Lighter than typical sneakers." in card
    assert '<a href="https://www.flipkart.com/item/123">View Product on Flipkart</a>' in card


def test_format_product_card_missing_rating_shows_not_rated():
    product = ProductResponseItem(
        product_id="P002",
        product_name="Generic Canvas Shoes",
        category="Footwear",
        discounted_price=599.0,
        rating=None,  # Not rated in catalog
        summary_reason="Affordable canvas shoes.",
        product_url=None,
    )

    card = format_product_card(product, index=2)

    assert "⭐ <i>Not rated</i>" in card
    assert "0/5.0" not in card  # Must NOT display missing ratings as 0
    assert "View Product on Flipkart" not in card


def test_format_product_card_unsafe_url_ignored():
    product = ProductResponseItem(
        product_id="P003",
        product_name="Test Product",
        category="Electronics",
        discounted_price=1000.0,
        summary_reason="Test summary",
        product_url="javascript:alert(document.cookie)",
    )

    card = format_product_card(product)
    assert "javascript:" not in card
    assert "View Product on Flipkart" not in card


def test_format_status_messages():
    resp_clarification = RecommendationResponse(
        request_id="r1",
        status="CLARIFICATION_REQUIRED",
        overview="Query is too broad. Please specify product type.",
        products=[],
    )
    msg1 = format_status_message(resp_clarification)
    assert "Clarification Needed" in msg1
    assert "Query is too broad" in msg1

    resp_no_results = RecommendationResponse(
        request_id="r2",
        status="NO_RESULTS",
        overview="No products match your criteria.",
        products=[],
    )
    msg2 = format_status_message(resp_no_results)
    assert "No Matching Products Found" in msg2

    resp_unsupported = RecommendationResponse(
        request_id="r3",
        status="UNSUPPORTED_INTENT",
        overview="Prices are in INR; USD is unsupported.",
        products=[],
    )
    msg3 = format_status_message(resp_unsupported)
    assert "Unsupported Request" in msg3


def test_format_error_messages():
    err_conn = BackendConnectionError("Cannot connect")
    assert "Backend Connection Unavailable" in format_error_message(err_conn)

    err_timeout = BackendTimeoutError("Timed out")
    assert "Request Timed Out" in format_error_message(err_timeout)

    err_422 = BackendResponseError(status_code=422, detail="Query empty")
    assert "Request Validation Error" in format_error_message(err_422)

    err_504 = BackendResponseError(status_code=504, detail="Pipeline timeout")
    assert "Backend Processing Timeout (504)" in format_error_message(err_504)

    err_500 = BackendResponseError(status_code=500, detail="Server crash", request_id="req-999")
    msg_500 = format_error_message(err_500)
    assert "Backend Error (500)" in msg_500
    assert "req-999" in msg_500

    err_schema = BackendSchemaError("Bad schema")
    assert "Response Format Error" in format_error_message(err_schema)


def test_split_telegram_message():
    short_text = "Hello ShopAssist!"
    assert split_telegram_message(short_text) == [short_text]

    # Create long text exceeding max length
    paragraphs = [f"Line {i}: " + ("x" * 100) for i in range(50)]
    long_text = "\n".join(paragraphs)
    chunks = split_telegram_message(long_text, max_length=1000)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1000


def test_format_recommendation_response():
    resp = RecommendationResponse(
        request_id="req-test",
        status="DETERMINISTIC_FALLBACK",
        overview="Here are 2 fallback shoes.",
        products=[
            ProductResponseItem(
                product_id="P1",
                product_name="Shoe 1",
                category="Shoes",
                discounted_price=1000.0,
                summary_reason="Good shoe",
                image="https://img.com/shoe1.jpg",
            ),
            ProductResponseItem(
                product_id="P2",
                product_name="Shoe 2",
                category="Shoes",
                discounted_price=1500.0,
                summary_reason="Another shoe",
                image="invalid_image_string",
            ),
        ],
    )

    overview, items = format_recommendation_response(resp)
    assert "Showing grounded catalog recommendations" in overview
    assert "Here are 2 fallback shoes." in overview
    assert len(items) == 2
    assert items[0]["image_url"] == "https://img.com/shoe1.jpg"
    assert items[1]["image_url"] is None  # Invalid image URL rejected
