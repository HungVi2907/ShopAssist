"""Opt-in live integration tests with real OpenRouter API using google/gemma-4-26b-a4b-it:free.

These tests execute real HTTP calls against OpenRouter Cloud API.
They are skipped unless SHOPASSIST_PHASE12_LIVE_OPENROUTER=1 is explicitly set
and OPENROUTER_API_KEY is configured in the environment or .env file.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import pytest
import pandas as pd

from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput, QueryUnderstandingResult
from shopassist.preferences.schemas import PreferenceRepresentationResult, RepresentationStatus
from shopassist.reranking.core import RerankedProduct, RerankingResult, RerankingStatus
from shopassist.recommendation import (
    OpenRouterProvider,
    RecommendationService,
    RecommendationSettings,
    RecommendationStatus,
)


from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data/processed/products.parquet"

LIVE_FLAG = os.getenv("SHOPASSIST_PHASE12_LIVE_OPENROUTER", "0").strip().lower() in ("1", "true", "yes")


def _is_live_configured() -> bool:
    if not LIVE_FLAG:
        return False
    key = os.getenv("OPENROUTER_API_KEY")
    return bool(key and key.strip())


pytestmark = pytest.mark.skipif(
    not _is_live_configured(),
    reason="Live OpenRouter tests skipped: set SHOPASSIST_PHASE12_LIVE_OPENROUTER=1 and configure OPENROUTER_API_KEY",
)


def _load_sample_products(n: int = 3) -> list[RerankedProduct]:
    df = pd.read_parquet(
        CATALOG_PATH,
        columns=["product_id", "product_name", "category", "brand", "discounted_price", "rating", "retrieval_text", "product_specifications"],
    )
    # Pick products from footwear
    footwear = df[df["category"].str.contains("Footwear", na=False)].head(n)
    products = []
    for rank, (_, row) in enumerate(footwear.iterrows(), 1):
        spec_dict = {}
        if isinstance(row["product_specifications"], dict):
            spec_dict = row["product_specifications"]

        rating_val = None
        if pd.notna(row["rating"]):
            try:
                rating_val = float(row["rating"])
            except Exception:
                pass

        products.append(
            RerankedProduct(
                product_id=str(row["product_id"]),
                original_rank=rank,
                reranked_rank=rank,
                product_name=str(row["product_name"]),
                retrieval_text=str(row["retrieval_text"]),
                category=str(row["category"]),
                brand=str(row["brand"]) if pd.notna(row["brand"]) else None,
                discounted_price=float(row["discounted_price"]),
                rating=rating_val,
                rrf_score=1.0 / (60 + rank),
                sources={"dense": {"rank": rank, "score": 0.8}, "lexical": {"rank": rank, "score": 0.8}},
                metadata={"product_specifications": spec_dict},
                final_score=1.0 / (60 + rank),
            )
        )
    return products


MODEL_NAME = os.getenv("PHASE12_LLM_MODEL", "google/gemma-4-26b-a4b-it:free")


def test_real_openrouter_smoke_test():
    """Verify OpenRouter authentication and basic JSON completion with Gemma 4."""
    async def run():
        settings = RecommendationSettings(
            phase12_llm_provider="openrouter",
            phase12_llm_model=MODEL_NAME,
        )
        provider = OpenRouterProvider(settings=settings)

        system_prompt = "You are a product recommendation assistant. Output valid JSON matching the schema."
        user_prompt = "Recommend 1 running shoe in JSON format matching the schema."

        try:
            payload, usage = await provider.generate_recommendation_payload(system_prompt, user_prompt)
        except RuntimeError as err:
            if "429" in str(err) or "rate limit" in str(err).lower():
                pytest.skip(f"OpenRouter upstream rate limit (429) encountered for model '{MODEL_NAME}': {err}")
            raise

        assert payload.overview is not None
        assert isinstance(payload.products, list)
        assert usage.prompt_tokens > 0
        assert usage.completion_tokens > 0
        assert usage.latency_ms > 0
        if ":free" in MODEL_NAME:
            assert usage.estimated_cost_usd == 0.0

        # Safe logging without exposing keys
        print(f"\n[Smoke Test] Latency: {usage.latency_ms:.1f}ms | Tokens: {usage.total_tokens} (prompt={usage.prompt_tokens}, completion={usage.completion_tokens}) | Cost: ${usage.estimated_cost_usd:.6f}")

    asyncio.run(run())


def test_real_openrouter_catalog_recommendation_english():
    """Verify recommendation generation on authentic catalog products in English."""
    async def run():
        settings = RecommendationSettings(
            phase12_llm_provider="openrouter",
            phase12_llm_model=MODEL_NAME,
        )
        service = RecommendationService(settings=settings)

        candidates = _load_sample_products(3)
        q8 = QueryUnderstandingResult(
            query="lightweight cushioned running shoes for daily training",
            status="SUCCESS",
            output=QueryUnderstandingOutput(
                semantic_query="lightweight cushioned running shoes",
                hard_constraints=HardConstraints(category="Footwear", currency="INR"),
                soft_preferences=["lightweight", "cushioned", "running"],
            ),
        )
        q9 = PreferenceRepresentationResult(
            semantic_query="lightweight cushioned running shoes",
            has_preferences=True,
            status=RepresentationStatus.SUCCESS,
            preference_query="lightweight cushioned running shoes",
            normalized_preferences=["lightweight", "cushioned", "running"],
        )
        rr = RerankingResult(
            status=RerankingStatus.SUCCESS,
            method="RRF",
            products=candidates,
            total_candidates=len(candidates),
            returned_count=len(candidates),
        )

        res = await service.generate(q8, q9, rr)

        if res.status == RecommendationStatus.DETERMINISTIC_FALLBACK:
            assert "429" in (res.diagnostic_reason or "") or "rate limit" in (res.diagnostic_reason or "").lower()
            print("\n[English Test] Upstream 429 encountered -> Deterministic Fallback engaged cleanly.")
        else:
            assert res.status == RecommendationStatus.SUCCESS

        assert len(res.products) == 3
        # Candidate IDs must match
        cand_pids = [c.product_id for c in candidates]
        rec_pids = [p.product_id for p in res.products]
        assert rec_pids == cand_pids

        # Authoritative prices preserved
        for p, c in zip(res.products, candidates):
            assert p.discounted_price == c.discounted_price
            assert p.product_name == c.product_name

        print(f"\n[English Test] Latency: {res.usage.latency_ms:.1f}ms | Tokens: {res.usage.total_tokens} | Cost: ${res.usage.estimated_cost_usd:.6f}")
        ascii_overview = res.overview[:80].encode("ascii", "replace").decode("ascii")
        print(f"Overview: {ascii_overview} ...")

    asyncio.run(run())


def test_real_openrouter_catalog_recommendation_vietnamese():
    """Verify recommendation generation on authentic catalog products in Vietnamese."""
    async def run():
        settings = RecommendationSettings(
            phase12_llm_provider="openrouter",
            phase12_llm_model=MODEL_NAME,
        )
        service = RecommendationService(settings=settings)

        candidates = _load_sample_products(3)
        q8 = QueryUnderstandingResult(
            query="Tìm cho tôi giày chạy bộ nam êm ái thoáng khí giá tốt",
            status="SUCCESS",
            output=QueryUnderstandingOutput(
                semantic_query="giày chạy bộ nam êm ái thoáng khí",
                hard_constraints=HardConstraints(category="Footwear", currency="INR"),
                soft_preferences=["êm ái", "thoáng khí", "giá tốt"],
            ),
        )
        q9 = PreferenceRepresentationResult(
            semantic_query="giày chạy bộ nam êm ái thoáng khí",
            has_preferences=True,
            status=RepresentationStatus.SUCCESS,
            preference_query="giày chạy bộ nam êm ái thoáng khí",
            normalized_preferences=["êm ái", "thoáng khí", "giá tốt"],
        )
        rr = RerankingResult(
            status=RerankingStatus.SUCCESS,
            method="RRF",
            products=candidates,
            total_candidates=len(candidates),
            returned_count=len(candidates),
        )

        res = await service.generate(q8, q9, rr, language="vi")

        if res.status == RecommendationStatus.DETERMINISTIC_FALLBACK:
            assert "429" in (res.diagnostic_reason or "") or "rate limit" in (res.diagnostic_reason or "").lower()
            print("\n[Vietnamese Test] Upstream 429 encountered -> Deterministic Fallback engaged cleanly.")
        else:
            assert res.status == RecommendationStatus.SUCCESS

        assert len(res.products) == 3
        assert [p.product_id for p in res.products] == [c.product_id for c in candidates]
        for p, c in zip(res.products, candidates):
            assert p.discounted_price == c.discounted_price
            assert p.product_name == c.product_name

        print(f"\n[Vietnamese Test] Latency: {res.usage.latency_ms:.1f}ms | Tokens: {res.usage.total_tokens}")
        ascii_overview = res.overview[:80].encode("ascii", "replace").decode("ascii")
        print(f"Vietnamese Overview: {ascii_overview} ...")

    asyncio.run(run())
