"""Unit tests for API configuration and public schemas (Phase 15)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shopassist.api.config import APISettings
from shopassist.api.schemas import (
    ProductClaimItem,
    ProductEvidenceItem,
    ProductResponseItem,
    RecommendationMetadata,
    RecommendationRequest,
    RecommendationResponse,
    RecommendationUsage,
)


def test_api_settings_defaults():
    settings = APISettings()
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.api_default_top_k == 5
    assert settings.api_max_top_k == 20
    assert settings.api_retrieval_top_n == 20
    assert settings.api_reranking_method == "RRF"
    assert settings.api_request_timeout_seconds == 90.0
    assert len(settings.api_cors_origins) > 0


def test_api_settings_validation_invalid_method():
    with pytest.raises(ValidationError):
        APISettings(api_reranking_method="UNKNOWN_METHOD")


def test_api_settings_validation_non_positive_values():
    with pytest.raises(ValidationError):
        APISettings(api_default_top_k=0)

    with pytest.raises(ValidationError):
        APISettings(api_request_timeout_seconds=-10.0)


def test_recommendation_request_valid():
    req = RecommendationRequest(
        query="Puma running shoes under 3000 INR",
        top_k=5,
        language="en",
        session_id="sess-123",
    )
    assert req.query == "Puma running shoes under 3000 INR"
    assert req.top_k == 5
    assert req.language == "en"
    assert req.session_id == "sess-123"


def test_recommendation_request_rejects_empty_query():
    with pytest.raises(ValidationError):
        RecommendationRequest(query="   ")


def test_recommendation_request_rejects_excessive_length():
    long_query = "a" * 501
    with pytest.raises(ValidationError):
        RecommendationRequest(query=long_query)


def test_recommendation_request_bounds_top_k():
    with pytest.raises(ValidationError):
        RecommendationRequest(query="shoes", top_k=0)

    with pytest.raises(ValidationError):
        RecommendationRequest(query="shoes", top_k=25)


def test_recommendation_request_validates_language():
    with pytest.raises(ValidationError):
        RecommendationRequest(query="shoes", language="fr")

    # Valid languages
    for lang in ("auto", "en", "vi"):
        req = RecommendationRequest(query="shoes", language=lang)
        assert req.language == lang


def test_recommendation_request_forbids_extra_fields():
    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate({"query": "shoes", "unsupported_field": 123})


def test_recommendation_response_serialization():
    product = ProductResponseItem(
        product_id="P001",
        product_name="Puma Speed Running Shoes",
        brand="Puma",
        category="Footwear",
        discounted_price=2499.0,
        currency="INR",
        rating=4.2,
        summary_reason="Excellent lightweight running shoe within budget.",
        strengths=[ProductClaimItem(claim="Breathable mesh", evidence_ids=["P001-E1"])],
        limitations=[ProductClaimItem(claim="Not waterproof", evidence_ids=[])],
        comparison_note=None,
        available_evidence=[
            ProductEvidenceItem(evidence_id="P001-E1", source_field="specifications", text="Mesh upper")
        ],
    )

    metadata = RecommendationMetadata(
        recommended_count=1,
        retrieval_method="HYBRID_RRF",
        reranking_method="RRF",
        fallback_used=False,
        session_id="test-session",
        applied_constraints={"category": "Footwear", "brand": "Puma"},
    )

    usage = RecommendationUsage(
        total_tokens=450,
        prompt_tokens=350,
        completion_tokens=100,
        estimated_cost_usd=0.0001,
        total_latency_ms=1250.5,
        stage_latencies_ms={"phase8_query_understanding": 400.0, "phase10_hybrid_retrieval": 150.0},
    )

    response = RecommendationResponse(
        request_id="req-uuid-12345",
        status="SUCCESS",
        overview="Here are the best Puma running shoes for your criteria.",
        products=[product],
        metadata=metadata,
        usage=usage,
    )

    d = response.model_dump()
    assert d["request_id"] == "req-uuid-12345"
    assert d["status"] == "SUCCESS"
    assert len(d["products"]) == 1
    assert d["products"][0]["product_id"] == "P001"
    assert d["metadata"]["recommended_count"] == 1
    assert d["usage"]["total_tokens"] == 450
