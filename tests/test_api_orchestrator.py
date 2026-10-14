"""Unit tests for RecommendationOrchestrator short-circuits and status mapping (Phase 15)."""

from __future__ import annotations

import asyncio
import functools
from unittest.mock import AsyncMock, MagicMock
import pytest

from shopassist.api.config import APISettings
from shopassist.api.schemas import RecommendationRequest
from shopassist.api.services.orchestrator import RecommendationOrchestrator
from shopassist.api.session import InMemorySessionStore
from shopassist.llm.schemas import (
    HardConstraints,
    QueryUnderstandingOutput,
    QueryUnderstandingResult,
    TokenUsageMetadata,
)
from shopassist.preferences.schemas import (
    PreferenceRepresentationResult,
    RepresentationStatus,
)
from shopassist.recommendation.schemas import (
    ProductClaim,
    ProductEvidence,
    RecommendationResult,
    RecommendationStatus,
    RecommendedProduct,
    TokenUsage,
)
from shopassist.reranking.core import (
    RerankedProduct,
    RerankingResult,
    RerankingStatus,
)
from shopassist.retrieval.hybrid import (
    HybridCandidate,
    HybridRetrievalResult,
    HybridRetrievalStatus,
)


def async_test(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapped


@pytest.fixture
def mock_orchestrator_components():
    query_engine = MagicMock()
    preference_service = MagicMock()
    hybrid_service = MagicMock()
    reranking_service = MagicMock()
    recommendation_service = MagicMock()
    session_store = InMemorySessionStore(ttl_seconds=3600, max_messages=5)
    settings = APISettings()

    orchestrator = RecommendationOrchestrator(
        query_engine=query_engine,
        preference_service=preference_service,
        hybrid_service=hybrid_service,
        reranking_service=reranking_service,
        recommendation_service=recommendation_service,
        session_store=session_store,
        settings=settings,
    )

    return {
        "orchestrator": orchestrator,
        "query_engine": query_engine,
        "preference_service": preference_service,
        "hybrid_service": hybrid_service,
        "reranking_service": reranking_service,
        "recommendation_service": recommendation_service,
        "session_store": session_store,
    }


@async_test
async def test_short_circuit_on_unsafe_negative_intent(mock_orchestrator_components):
    orchestrator = mock_orchestrator_components["orchestrator"]
    query_engine = mock_orchestrator_components["query_engine"]

    req = RecommendationRequest(query="running shoes no leather", top_k=5)
    res = await orchestrator.orchestrate(req, request_id="test-req-1")

    assert res.status == "UNSUPPORTED_INTENT"
    assert "negative or exclusion semantics" in res.overview.lower()
    # Upstream/downstream services must NOT be called
    query_engine.parse_query_async.assert_not_called()


@async_test
async def test_short_circuit_on_phase8_invalid_query(mock_orchestrator_components):
    orchestrator = mock_orchestrator_components["orchestrator"]
    query_engine = mock_orchestrator_components["query_engine"]
    preference_service = mock_orchestrator_components["preference_service"]

    query_engine.parse_query_async = AsyncMock(
        return_value=QueryUnderstandingResult(
            query="invalid???",
            output=QueryUnderstandingOutput(
                semantic_query="invalid",
                needs_clarification=True,
                clarification_reason="Could not extract intent",
            ),
            is_valid=False,
            validation_errors=["Could not extract intent"],
        )
    )

    req = RecommendationRequest(query="invalid???", top_k=5)
    res = await orchestrator.orchestrate(req, request_id="test-req-2")

    assert res.status == "INVALID_INPUT"
    assert "could not extract intent" in res.overview.lower()
    preference_service.represent.assert_not_called()


@async_test
async def test_short_circuit_on_phase8_clarification(mock_orchestrator_components):
    orchestrator = mock_orchestrator_components["orchestrator"]
    query_engine = mock_orchestrator_components["query_engine"]
    preference_service = mock_orchestrator_components["preference_service"]

    query_engine.parse_query_async = AsyncMock(
        return_value=QueryUnderstandingResult(
            query="something good",
            output=QueryUnderstandingOutput(
                semantic_query="something good",
                needs_clarification=True,
                clarification_reason="Please specify product category.",
            ),
            is_valid=True,
        )
    )

    req = RecommendationRequest(query="something good", top_k=5)
    res = await orchestrator.orchestrate(req, request_id="test-req-3")

    assert res.status == "CLARIFICATION_REQUIRED"
    assert "please specify product category" in res.overview.lower()
    preference_service.represent.assert_not_called()


@async_test
async def test_short_circuit_on_foreign_currency(mock_orchestrator_components):
    orchestrator = mock_orchestrator_components["orchestrator"]
    query_engine = mock_orchestrator_components["query_engine"]
    preference_service = mock_orchestrator_components["preference_service"]

    query_engine.parse_query_async = AsyncMock(
        return_value=QueryUnderstandingResult(
            query="laptop under 500 USD",
            output=QueryUnderstandingOutput(
                semantic_query="laptop",
                hard_constraints=HardConstraints(category="Computers", max_price=500.0, currency="USD"),
            ),
            is_valid=True,
        )
    )

    req = RecommendationRequest(query="laptop under 500 USD", top_k=5)
    res = await orchestrator.orchestrate(req, request_id="test-req-4")

    assert res.status == "UNSUPPORTED_INTENT"
    assert "currency 'USD' is not supported" in res.overview
    preference_service.represent.assert_not_called()


@async_test
async def test_short_circuit_on_ambiguous_price_semantics(mock_orchestrator_components):
    orchestrator = mock_orchestrator_components["orchestrator"]
    query_engine = mock_orchestrator_components["query_engine"]
    preference_service = mock_orchestrator_components["preference_service"]

    query_engine.parse_query_async = AsyncMock(
        return_value=QueryUnderstandingResult(
            query="shoes around 2000 INR",
            output=QueryUnderstandingOutput(
                semantic_query="shoes",
                hard_constraints=HardConstraints(category="Footwear", max_price=2000.0, currency="INR"),
            ),
            is_valid=True,
        )
    )

    req = RecommendationRequest(query="shoes around 2000 INR", top_k=5)
    res = await orchestrator.orchestrate(req, request_id="test-req-5")

    assert res.status == "CLARIFICATION_REQUIRED"
    assert "ambiguous" in res.overview.lower() or "budget" in res.overview.lower()
    preference_service.represent.assert_not_called()


@async_test
async def test_short_circuit_on_phase9_embedding_failure(mock_orchestrator_components):
    orchestrator = mock_orchestrator_components["orchestrator"]
    query_engine = mock_orchestrator_components["query_engine"]
    preference_service = mock_orchestrator_components["preference_service"]
    hybrid_service = mock_orchestrator_components["hybrid_service"]

    query_engine.parse_query_async = AsyncMock(
        return_value=QueryUnderstandingResult(
            query="comfortable shoes",
            output=QueryUnderstandingOutput(
                semantic_query="shoes",
                soft_preferences=["comfortable"],
            ),
            is_valid=True,
        )
    )
    preference_service.represent.return_value = PreferenceRepresentationResult(
        semantic_query="shoes",
        has_preferences=True,
        status=RepresentationStatus.EMBEDDING_FAILURE,
        diagnostic_reason="PyTorch OOM",
    )

    req = RecommendationRequest(query="comfortable shoes", top_k=5)
    res = await orchestrator.orchestrate(req, request_id="test-req-6")

    assert res.status == "EMBEDDING_FAILURE"
    hybrid_service.retrieve.assert_not_called()


@async_test
async def test_short_circuit_on_phase10_no_results(mock_orchestrator_components):
    orchestrator = mock_orchestrator_components["orchestrator"]
    query_engine = mock_orchestrator_components["query_engine"]
    preference_service = mock_orchestrator_components["preference_service"]
    hybrid_service = mock_orchestrator_components["hybrid_service"]
    reranking_service = mock_orchestrator_components["reranking_service"]

    query_engine.parse_query_async = AsyncMock(
        return_value=QueryUnderstandingResult(
            query="luxury titanium running shoes",
            output=QueryUnderstandingOutput(
                semantic_query="luxury titanium running shoes",
                hard_constraints=HardConstraints(category="Footwear"),
            ),
            is_valid=True,
        )
    )
    preference_service.represent.return_value = PreferenceRepresentationResult(
        semantic_query="luxury titanium running shoes",
        has_preferences=False,
        status=RepresentationStatus.NO_PREFERENCES,
    )
    hybrid_service.retrieve = AsyncMock(
        return_value=HybridRetrievalResult(
            status=HybridRetrievalStatus.NO_RESULTS,
            candidates=[],
            applied_constraints={"category": "Footwear"},
        )
    )

    req = RecommendationRequest(query="luxury titanium running shoes", top_k=5)
    res = await orchestrator.orchestrate(req, request_id="test-req-7")

    assert res.status == "NO_RESULTS"
    assert "no products in our catalog match" in res.overview.lower()
    reranking_service.rerank.assert_not_called()


@async_test
async def test_deterministic_fallback_flow(mock_orchestrator_components):
    orchestrator = mock_orchestrator_components["orchestrator"]
    query_engine = mock_orchestrator_components["query_engine"]
    preference_service = mock_orchestrator_components["preference_service"]
    hybrid_service = mock_orchestrator_components["hybrid_service"]
    reranking_service = mock_orchestrator_components["reranking_service"]
    recommendation_service = mock_orchestrator_components["recommendation_service"]

    # 1. P8 success
    query_engine.parse_query_async = AsyncMock(
        return_value=QueryUnderstandingResult(
            query="Puma shoes under 3000",
            output=QueryUnderstandingOutput(
                semantic_query="shoes",
                hard_constraints=HardConstraints(category="Footwear", brand="Puma", max_price=3000.0),
            ),
            is_valid=True,
            token_usage=TokenUsageMetadata(prompt_tokens=50, candidates_tokens=30, total_tokens=80),
        )
    )
    # 2. P9 success
    preference_service.represent.return_value = PreferenceRepresentationResult(
        semantic_query="shoes",
        has_preferences=False,
        status=RepresentationStatus.NO_PREFERENCES,
    )
    # 3. P10 success
    candidate = HybridCandidate(
        rank=1,
        product_id="PUMA001",
        product_name="Puma Runner",
        category="Footwear",
        brand="Puma",
        discounted_price=1999.0,
        rating=4.5,
        rrf_score=0.033,
    )
    hybrid_service.retrieve = AsyncMock(
        return_value=HybridRetrievalResult(
            status=HybridRetrievalStatus.SUCCESS,
            candidates=[candidate],
            applied_constraints={"category": "Footwear", "brand": "Puma"},
        )
    )
    # 4. P11 success
    reranked = RerankedProduct(
        product_id="PUMA001",
        original_rank=1,
        reranked_rank=1,
        product_name="Puma Runner",
        retrieval_text="Puma Runner high performance",
        category="Footwear",
        brand="Puma",
        discounted_price=1999.0,
        rating=4.5,
        rrf_score=0.033,
        sources={},
        metadata={},
        final_score=0.033,
    )
    reranking_service.rerank.return_value = RerankingResult(
        status=RerankingStatus.SUCCESS,
        method="RRF",
        products=[reranked],
        total_candidates=1,
        returned_count=1,
    )
    # 5. P12 fallback
    rec_product = RecommendedProduct(
        product_id="PUMA001",
        product_name="Puma Runner",
        brand="Puma",
        category="Footwear",
        discounted_price=1999.0,
        rating=4.5,
        currency="INR",
        original_rank=1,
        reranked_rank=1,
        rrf_score=0.033,
        summary_reason="Puma Runner from Footwear priced at 1999.0 INR.",
        strengths=[ProductClaim(claim="Priced within budget", evidence_ids=["PUMA001-E1"])],
        limitations=[],
        available_evidence=[ProductEvidence(evidence_id="PUMA001-E1", product_id="PUMA001", source_field="discounted_price", text="1999.0")],
    )
    recommendation_service.generate = AsyncMock(
        return_value=RecommendationResult(
            status=RecommendationStatus.DETERMINISTIC_FALLBACK,
            overview="Catalog recommendations generated via fallback.",
            products=[rec_product],
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )
    )

    req = RecommendationRequest(query="Puma shoes under 3000", top_k=5, session_id="sess-fall")
    res = await orchestrator.orchestrate(req, request_id="test-req-8")

    assert res.status == "DETERMINISTIC_FALLBACK"
    assert res.metadata.fallback_used is True
    assert len(res.products) == 1
    assert res.products[0].product_id == "PUMA001"
    assert res.metadata.session_id == "sess-fall"
    assert res.usage.total_tokens == 80  # P8 tokens preserved even with P12 fallback
