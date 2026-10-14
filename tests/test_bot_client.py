"""Unit tests for FastAPIRecommendationClient (Phase 16)."""

from __future__ import annotations

import asyncio
import json
import httpx
import pytest

from shopassist.api.schemas import HealthResponse, RecommendationResponse
from shopassist.bot.clients.recommendation import (
    BackendConnectionError,
    BackendResponseError,
    BackendSchemaError,
    BackendTimeoutError,
    FastAPIRecommendationClient,
)


@pytest.fixture
def mock_recommendation_payload() -> dict:
    return {
        "request_id": "req-12345",
        "status": "SUCCESS",
        "overview": "Here are 2 Puma shoes.",
        "products": [
            {
                "product_id": "P001",
                "product_name": "Puma Carson Runner",
                "brand": "Puma",
                "category": "Footwear",
                "discounted_price": 2299.0,
                "currency": "INR",
                "rating": 4.3,
                "summary_reason": "Breathable running shoes.",
                "strengths": [{"claim": "Lightweight", "evidence_ids": ["E1"]}],
                "limitations": [],
                "comparison_note": None,
                "available_evidence": [],
                "product_url": "https://www.flipkart.com/item/1",
                "image": "https://img.flixcart.com/item/1.jpg",
            }
        ],
        "metadata": {
            "recommended_count": 1,
            "retrieval_method": "HYBRID_RRF",
            "reranking_method": "RRF",
            "fallback_used": False,
            "session_id": "tg-sess-1",
            "applied_constraints": {"brand": "Puma"},
        },
        "usage": {
            "total_tokens": 500,
            "prompt_tokens": 400,
            "completion_tokens": 100,
            "estimated_cost_usd": 0.0,
            "total_latency_ms": 1200.0,
            "stage_latencies_ms": {},
        },
    }


def test_client_recommend_success(mock_recommendation_payload):
    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["query"] == "Puma shoes under 3000 INR"
        assert data["top_k"] == 5
        assert data["language"] == "en"
        assert data["session_id"] == "tg-sess-1"
        return httpx.Response(200, json=mock_recommendation_payload)

    transport = httpx.MockTransport(handler)
    raw_client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
    client = FastAPIRecommendationClient(client=raw_client)

    response = asyncio.run(
        client.recommend(
            query="Puma shoes under 3000 INR",
            top_k=5,
            language="en",
            session_id="tg-sess-1",
        )
    )

    assert isinstance(response, RecommendationResponse)
    assert response.status == "SUCCESS"
    assert response.request_id == "req-12345"
    assert len(response.products) == 1
    assert response.products[0].product_name == "Puma Carson Runner"
    assert response.products[0].discounted_price == 2299.0
    assert response.products[0].product_url == "https://www.flipkart.com/item/1"
    assert response.products[0].image == "https://img.flixcart.com/item/1.jpg"


def test_client_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by peer")

    transport = httpx.MockTransport(handler)
    raw_client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
    client = FastAPIRecommendationClient(client=raw_client)

    with pytest.raises(BackendConnectionError) as exc_info:
        asyncio.run(client.recommend(query="Puma shoes"))
    assert "Cannot connect to ShopAssist backend" in str(exc_info.value)


def test_client_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out after 95s")

    transport = httpx.MockTransport(handler)
    raw_client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
    client = FastAPIRecommendationClient(client=raw_client)

    with pytest.raises(BackendTimeoutError) as exc_info:
        asyncio.run(client.recommend(query="Puma shoes"))
    assert "timed out" in str(exc_info.value)


def test_client_http_422_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "Query cannot be empty or whitespace-only."})

    transport = httpx.MockTransport(handler)
    raw_client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
    client = FastAPIRecommendationClient(client=raw_client)

    with pytest.raises(BackendResponseError) as exc_info:
        asyncio.run(client.recommend(query="valid query text"))
    assert exc_info.value.status_code == 422
    assert "Query cannot be empty" in exc_info.value.detail


def test_client_http_500_response_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"detail": "Internal server error occurred."},
            headers={"x-request-id": "req-err-500"},
        )

    transport = httpx.MockTransport(handler)
    raw_client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
    client = FastAPIRecommendationClient(client=raw_client)

    with pytest.raises(BackendResponseError) as exc_info:
        asyncio.run(client.recommend(query="shoes"))
    assert exc_info.value.status_code == 500
    assert exc_info.value.request_id == "req-err-500"


def test_client_invalid_json_raises_schema_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html5>Not JSON</html>")

    transport = httpx.MockTransport(handler)
    raw_client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
    client = FastAPIRecommendationClient(client=raw_client)

    with pytest.raises(BackendSchemaError) as exc_info:
        asyncio.run(client.recommend(query="shoes"))
    assert "invalid non-JSON" in str(exc_info.value)


def test_client_schema_mismatch_raises_schema_error():
    def handler(request: httpx.Request) -> httpx.Response:
        # Missing required 'request_id' and 'status'
        return httpx.Response(200, json={"arbitrary_key": "arbitrary_val"})

    transport = httpx.MockTransport(handler)
    raw_client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
    client = FastAPIRecommendationClient(client=raw_client)

    with pytest.raises(BackendSchemaError) as exc_info:
        asyncio.run(client.recommend(query="shoes"))
    assert "Response schema mismatch" in str(exc_info.value)


def test_client_health_check_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/health"
        return httpx.Response(
            200,
            json={
                "status": "healthy",
                "components": {"database": "healthy", "tfidf": "ready"},
                "timestamp": "2026-10-14T15:35:00Z",
            },
        )

    transport = httpx.MockTransport(handler)
    raw_client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
    client = FastAPIRecommendationClient(client=raw_client)

    health = asyncio.run(client.check_health())
    assert isinstance(health, HealthResponse)
    assert health.status == "healthy"
    assert health.components["database"] == "healthy"


def test_client_aclose():
    client = FastAPIRecommendationClient()
    assert not client._client.is_closed
    asyncio.run(client.aclose())
    assert client._client.is_closed
