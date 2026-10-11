"""Opt-in real Groq API integration tests for Phase 12.

Requires GROQ_API_KEY and SHOPASSIST_PHASE12_LIVE_GROQ=1.
Executes real inference on Groq openai/gpt-oss-20b using real catalog products.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import pytest
import pandas as pd

from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput, QueryUnderstandingResult
from shopassist.preferences.schemas import PreferenceRepresentationResult, RepresentationStatus
from shopassist.reranking.core import (
    CandidateSource,
    RerankedProduct,
    RerankingResult,
    RerankingStatus,
)
from shopassist.recommendation import (
    GroqProvider,
    RecommendationResult,
    RecommendationService,
    RecommendationSettings,
    RecommendationStatus,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data/processed/products.parquet"

pytestmark = pytest.mark.skipif(
    os.getenv("SHOPASSIST_PHASE12_LIVE_GROQ") != "1",
    reason="set SHOPASSIST_PHASE12_LIVE_GROQ=1 to run live Groq API tests",
)


def load_real_candidates(pids: list[str]) -> list[RerankedProduct]:
    """Load actual catalog rows from products.parquet as RerankedProducts."""
    df = pd.read_parquet(CATALOG_PATH)
    indexed = df.set_index(df.product_id.astype(str), drop=False)
    products = []
    for rank, pid in enumerate(pids, 1):
        if pid in indexed.index:
            row = indexed.loc[pid]
            rating = float(row.rating) if pd.notna(row.rating) else None
            price = float(row.discounted_price) if pd.notna(row.discounted_price) else float(row.retail_price or 1000.0)
            category_val = str(row.category) if pd.notna(row.category) else "Footwear"
            specs = row.product_specifications if isinstance(row.product_specifications, dict) else {}
            products.append(
                RerankedProduct(
                    product_id=str(row.product_id),
                    original_rank=rank,
                    reranked_rank=rank,
                    product_name=str(row.product_name),
                    retrieval_text=str(row.retrieval_text),
                    category=category_val,
                    brand=str(row.brand) if pd.notna(row.brand) else None,
                    discounted_price=price,
                    rating=rating,
                    rrf_score=1.0 / (60 + rank),
                    sources={"dense": {"rank": rank, "score": 0.8}, "lexical": {"rank": rank, "score": 10.0}},
                    metadata={"product_specifications": specs},
                    final_score=1.0 / (60 + rank),
                    score_components={},
                )
            )
    return products


def test_real_groq_smoke_test():
    """Verify live Groq API connectivity and schema enforcement."""
    async def run():
        provider = GroqProvider()
        system_prompt = "You are a product recommendation assistant. Recommend the product P001."
        user_prompt = "User wants running shoes. Candidate: Product ID P001, Name: Nike Air Zoom, Price: 3000 INR. Evidence: [P001-E1] (product_name): Nike Air Zoom"

        payload, usage = await provider.generate_recommendation_payload(system_prompt, user_prompt)
        assert payload.overview.strip()
        assert len(payload.products) >= 1
        assert payload.products[0].product_id == "P001"
        assert usage.prompt_tokens > 0
        assert usage.completion_tokens > 0
        assert usage.latency_ms > 0
        assert usage.estimated_cost_usd > 0
        print(f"\n[Smoke Test] Latency: {usage.latency_ms:.1f}ms | Tokens: {usage.total_tokens} (prompt={usage.prompt_tokens}, completion={usage.completion_tokens}, reasoning={usage.reasoning_tokens}) | Cost: ${usage.estimated_cost_usd:.6f}")

    asyncio.run(run())


def test_real_groq_catalog_recommendation_english():
    """Execute grounded recommendation over real catalog products for an English shopping query."""
    async def run():
        # Using 3 real candidate shoes from Q03
        candidate_ids = [
            "7ae33aaf60fc1ffa5d2601c92ec11304",
            "855c191a7973278a777e8374c67b2c8a",
            "09779c98e54c30f905b21bd9744ae685",
        ]
        candidates = load_real_candidates(candidate_ids)
        assert len(candidates) == 3

        q8 = QueryUnderstandingResult(
            query="lightweight running shoes for jogging",
            output=QueryUnderstandingOutput(
                semantic_query="running shoes for jogging",
                hard_constraints=HardConstraints(category="Footwear"),
                soft_preferences=["lightweight", "cushioned"],
            ),
        )
        q9 = PreferenceRepresentationResult(
            semantic_query="running shoes for jogging",
            normalized_preferences=["lightweight", "cushioned"],
            preference_query="lightweight cushioned — running shoes for jogging",
            has_preferences=True,
            status=RepresentationStatus.SUCCESS,
        )
        reranking = RerankingResult(
            status=RerankingStatus.SUCCESS,
            method="RRF",
            products=candidates,
            total_candidates=3,
            returned_count=3,
            applied_constraints={"category": "Footwear"},
        )

        service = RecommendationService()
        result = await service.generate(q8, q9, reranking, top_k=3, language="en")

        assert result.status == RecommendationStatus.SUCCESS
        assert len(result.products) == 3
        assert result.overview.strip()
        # Verify sequence and product IDs
        assert [p.product_id for p in result.products] == candidate_ids

        # Verify authoritative attributes preserved
        for i, rec in enumerate(result.products):
            orig = candidates[i]
            assert rec.product_name == orig.product_name
            assert rec.discounted_price == orig.discounted_price
            assert rec.rating == orig.rating
            assert rec.brand == orig.brand
            assert rec.summary_reason.strip()
            # Assert evidence IDs exist in available evidence
            valid_eids = {e.evidence_id for e in rec.available_evidence}
            for claim in rec.strengths:
                assert set(claim.evidence_ids).issubset(valid_eids)
            for lim in rec.limitations:
                assert set(lim.evidence_ids).issubset(valid_eids)

        assert result.usage.total_tokens > 0
        assert result.usage.latency_ms > 0
        assert result.usage.estimated_cost_usd > 0
        safe_overview = result.overview[:80].encode("ascii", "replace").decode("ascii")
        safe_reason = result.products[0].summary_reason[:80].encode("ascii", "replace").decode("ascii")
        print(f"\n[English Test] Latency: {result.usage.latency_ms:.1f}ms | Tokens: {result.usage.total_tokens} | Cost: ${result.usage.estimated_cost_usd:.6f}")
        print("Overview:", safe_overview, "...")
        print("Product 1 Summary:", safe_reason, "...")

    asyncio.run(run())


def test_real_groq_catalog_recommendation_vietnamese():
    """Execute grounded recommendation over real catalog products for a Vietnamese query."""
    async def run():
        candidate_ids = [
            "7ae33aaf60fc1ffa5d2601c92ec11304",
            "855c191a7973278a777e8374c67b2c8a",
        ]
        candidates = load_real_candidates(candidate_ids)
        assert len(candidates) == 2

        q8 = QueryUnderstandingResult(
            query="giày chạy bộ nam êm chân nhẹ",
            output=QueryUnderstandingOutput(
                semantic_query="giày chạy bộ nam",
                hard_constraints=HardConstraints(category="Footwear"),
                soft_preferences=["êm chân", "nhẹ"],
            ),
        )
        q9 = PreferenceRepresentationResult(
            semantic_query="giày chạy bộ nam",
            normalized_preferences=["êm chân", "nhẹ"],
            preference_query="êm chân nhẹ — giày chạy bộ nam",
            has_preferences=True,
            status=RepresentationStatus.SUCCESS,
        )
        reranking = RerankingResult(
            status=RerankingStatus.SUCCESS,
            method="RRF",
            products=candidates,
            total_candidates=2,
            returned_count=2,
            applied_constraints={"category": "Footwear"},
        )

        service = RecommendationService()
        result = await service.generate(q8, q9, reranking, top_k=2, language="vi")

        assert result.status == RecommendationStatus.SUCCESS
        assert len(result.products) == 2
        assert [p.product_id for p in result.products] == candidate_ids

        # Verify Vietnamese output
        assert result.overview.strip()
        assert result.products[0].summary_reason.strip()
        safe_vn_overview = result.overview[:80].encode("ascii", "replace").decode("ascii")
        safe_vn_reason = result.products[0].summary_reason[:80].encode("ascii", "replace").decode("ascii")
        print(f"\n[Vietnamese Test] Latency: {result.usage.latency_ms:.1f}ms | Tokens: {result.usage.total_tokens}")
        print("Vietnamese Overview:", safe_vn_overview, "...")
        print("Vietnamese Product 1 Reason:", safe_vn_reason, "...")

    asyncio.run(run())
