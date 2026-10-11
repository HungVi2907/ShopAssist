"""Opt-in read-only integration through the configured Phase 10 database service."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from shopassist.db.connection import get_async_engine
from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput, QueryUnderstandingResult
from shopassist.preferences.schemas import PreferenceRepresentationResult, RepresentationStatus
from shopassist.reranking import RerankingConfig, RerankingMethod, RerankingService, load_canonical_product_texts
from shopassist.retrieval.hybrid import HybridRetrievalConfig, HybridRetrievalService, HybridRetrievalStatus
from shopassist.retrieval.semantic import DenseQueryEncoder
from shopassist.retrieval.tfidf import TFIDFIndex


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.getenv("SHOPASSIST_PHASE11_LIVE_DB") != "1", reason="set SHOPASSIST_PHASE11_LIVE_DB=1 to run read-only live Phase 10 integration")


def test_live_phase10_result_hands_off_to_phase11_without_candidate_changes():
    async def run():
        from shopassist.core.config import settings

        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        engine = get_async_engine(settings.get_raw_supabase_db_url(), pool_size=1, max_overflow=0)
        try:
            encoder = DenseQueryEncoder()
            phase10 = HybridRetrievalService(
                engine,
                TFIDFIndex.load(ROOT / "data/processed/tfidf"),
                query_encoder=encoder,
                config=HybridRetrievalConfig(top_n=25, max_top_n=25),
            )
            q8 = QueryUnderstandingResult(
                query="running shoes in Footwear",
                output=QueryUnderstandingOutput(semantic_query="running shoes", hard_constraints=HardConstraints(category="Footwear")),
            )
            q9 = PreferenceRepresentationResult(
                semantic_query="running shoes", has_preferences=False, status=RepresentationStatus.NO_PREFERENCES
            )
            retrieval = await phase10.retrieve(q8, q9, top_n=25)
            assert retrieval.status == HybridRetrievalStatus.SUCCESS, retrieval.diagnostic_reason
            initial_ids = {item.product_id for item in retrieval.candidates}
            assert initial_ids
            reranker = RerankingService(
                load_canonical_product_texts(str(ROOT / "data/processed/products.parquet")),
                config=RerankingConfig(top_k=5, method=RerankingMethod.RRF),
            )
            result = reranker.rerank(q8, q9, retrieval)
            assert result.status.value == "SUCCESS", result.diagnostic_reason
            final_ids = [item.product_id for item in result.products]
            assert len(final_ids) == len(set(final_ids))
            assert len(final_ids) <= 5
            assert set(final_ids) <= initial_ids
            by_id = {item.product_id: item for item in retrieval.candidates}
            for product in result.products:
                original = by_id[product.product_id]
                assert product.original_rank == original.rank
                assert product.sources.keys() == original.sources.keys()
                assert product.retrieval_text.strip()
        finally:
            await engine.dispose()

    asyncio.run(run())
