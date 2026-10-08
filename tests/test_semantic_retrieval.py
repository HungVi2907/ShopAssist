"""Automated Unit and Integration Tests for Phase 7 Dense Semantic Retrieval Engine.

Covers:
1. DenseQueryEncoder unit tests:
   - Output dimension (384)
   - Finite values, nonzero vectors, unit L2 norm
   - Query validation: rejection of None, int, dict, list
   - Empty and whitespace queries
   - BGE instruction prefix behavior and no-instruction override
   - Model caching / singleton behavior
2. SemanticSearchEngine unit tests:
   - top_k validation: rejection of float, negative, zero, > max_top_k
   - Result mapping and score calculation (semantic_score = 1.0 - cosine_distance)
   - Deterministic in-memory tie-breaking on (cosine_distance ASC, product_id ASC)
   - Mocked SQL retrieval execution
3. Helper and data model tests:
   - SemanticSearchConfig serialization and deserialization
   - SemanticSearchResult to_dict()
   - compute_result_overlap() metric correctness
4. Live Supabase integration tests (conditional on database connectivity):
   - Live semantic search on 8,405 catalog items
   - Monotonic distance ordering
   - EXPLAIN ANALYZE HNSW index scan verification
   - Exact linear scan retrieval
   - Catalog integrity verification (8,405 rows preserved)
"""

from __future__ import annotations

import asyncio
from functools import wraps
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from shopassist.core.config import settings
from shopassist.db.connection import ensure_windows_event_loop_policy, get_async_engine
from shopassist.retrieval.semantic import (
    DenseQueryEncoder,
    SemanticSearchConfig,
    SemanticSearchEngine,
    SemanticSearchResult,
    compute_result_overlap,
)

ensure_windows_event_loop_policy()


def async_test(coro):
    """Decorator to execute async test functions cleanly without pytest-asyncio plugin."""
    @wraps(coro)
    def wrapper(*args, **kwargs):
        ensure_windows_event_loop_policy()
        return asyncio.run(coro(*args, **kwargs))
    return wrapper


@pytest.fixture(scope="module")
def shared_encoder() -> DenseQueryEncoder:
    """Create a shared module-level DenseQueryEncoder instance."""
    return DenseQueryEncoder()


# ==============================================================================
# 1. DenseQueryEncoder Unit Tests
# ==============================================================================

class TestDenseQueryEncoder:
    """Unit tests for query encoding, normalization, and validation."""

    def test_query_validation_valid_string(self, shared_encoder: DenseQueryEncoder) -> None:
        """Verify normal query is stripped and returned."""
        assert shared_encoder.validate_query("  running shoes  ") == "running shoes"

    def test_query_validation_invalid_types(self, shared_encoder: DenseQueryEncoder) -> None:
        """Verify non-string inputs raise TypeError."""
        for invalid_val in [None, 123, 45.6, ["shoes"], {"query": "shoes"}, True]:
            with pytest.raises(TypeError, match="Query must be a string"):
                shared_encoder.validate_query(invalid_val)

    def test_query_validation_empty_whitespace(self, shared_encoder: DenseQueryEncoder) -> None:
        """Verify empty and whitespace queries return empty string."""
        assert shared_encoder.validate_query("") == ""
        assert shared_encoder.validate_query("    \t\n  ") == ""

    def test_encode_query_dimension_and_norm(self, shared_encoder: DenseQueryEncoder) -> None:
        """Verify encoded query has exact 384 dimensions and unit L2 norm."""
        vec = shared_encoder.encode_query("wireless bluetooth keyboard")
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (384,)
        assert vec.dtype == np.float32
        assert np.all(np.isfinite(vec))
        norm = float(np.linalg.norm(vec))
        assert abs(norm - 1.0) < 1e-4

    def test_encode_query_instruction_difference(self, shared_encoder: DenseQueryEncoder) -> None:
        """Verify BGE instruction yields different vector than no-instruction."""
        vec_with = shared_encoder.encode_query("running shoes", instruction="Represent this sentence for searching relevant passages: ")
        vec_without = shared_encoder.encode_query("running shoes", instruction=None)

        assert not np.allclose(vec_with, vec_without, atol=1e-3)
        # Both must still be unit normalized
        assert abs(float(np.linalg.norm(vec_with)) - 1.0) < 1e-4
        assert abs(float(np.linalg.norm(vec_without)) - 1.0) < 1e-4

    def test_encode_empty_query_raises_value_error(self, shared_encoder: DenseQueryEncoder) -> None:
        """Verify encoding an empty or whitespace string raises ValueError."""
        with pytest.raises(ValueError, match="empty or whitespace-only"):
            shared_encoder.encode_query("")
        with pytest.raises(ValueError, match="empty or whitespace-only"):
            shared_encoder.encode_query("    ")

    @async_test
    async def test_encode_query_async(self, shared_encoder: DenseQueryEncoder) -> None:
        """Verify asynchronous encoding runs non-blockingly."""
        vec = await shared_encoder.encode_query_async("ergonomic office chair")
        assert vec.shape == (384,)
        assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-4

    def test_model_caching_singleton(self) -> None:
        """Verify subsequent encoder instantiations reuse the cached model."""
        enc1 = DenseQueryEncoder()
        enc2 = DenseQueryEncoder()
        assert enc1.model is enc2.model


# ==============================================================================
# 2. SemanticSearchEngine Unit Tests
# ==============================================================================

class TestSemanticSearchEngineUnit:
    """Unit tests for SemanticSearchEngine validation, tie-breaking, and score calculation."""

    @pytest.fixture
    def mock_engine(self, shared_encoder: DenseQueryEncoder) -> SemanticSearchEngine:
        """Create a SemanticSearchEngine with mocked database engine."""
        mock_db_engine = MagicMock(spec=AsyncEngine)
        return SemanticSearchEngine(engine=mock_db_engine, encoder=shared_encoder)

    def test_validate_top_k_valid(self, mock_engine: SemanticSearchEngine) -> None:
        """Verify valid integer top_k is accepted."""
        assert mock_engine.validate_top_k(1) == 1
        assert mock_engine.validate_top_k(5) == 5
        assert mock_engine.validate_top_k(100) == 100

    def test_validate_top_k_invalid_types(self, mock_engine: SemanticSearchEngine) -> None:
        """Verify non-integer top_k values raise TypeError."""
        for val in [None, "5", 5.5, [5], True, False]:
            with pytest.raises(TypeError, match="top_k must be an integer"):
                mock_engine.validate_top_k(val)

    def test_validate_top_k_out_of_bounds(self, mock_engine: SemanticSearchEngine) -> None:
        """Verify zero, negative, or > max_top_k raise ValueError."""
        with pytest.raises(ValueError, match="positive integer"):
            mock_engine.validate_top_k(0)
        with pytest.raises(ValueError, match="positive integer"):
            mock_engine.validate_top_k(-5)
        with pytest.raises(ValueError, match="maximum allowed limit"):
            mock_engine.validate_top_k(101)

    @async_test
    async def test_search_empty_query_safe_zero_policy(self, mock_engine: SemanticSearchEngine) -> None:
        """Verify empty and whitespace queries return empty list without querying DB."""
        res_empty = await mock_engine.search("")
        assert res_empty == []

        res_space = await mock_engine.search("   \t  ")
        assert res_space == []

    @async_test
    async def test_search_deterministic_tie_breaking(self, shared_encoder: DenseQueryEncoder) -> None:
        """Verify tied cosine distances are deterministically sorted by product_id ASC."""
        # Simulated database rows: same distance 0.300000, different product IDs
        raw_rows = [
            ("PID_B", "Product B", "Footwear", "BrandX", 100.0, 150.0, 4.0, "[]", "desc", 0.300000),
            ("PID_A", "Product A", "Footwear", "BrandX", 100.0, 150.0, 4.0, "[]", "desc", 0.300000),
            ("PID_C", "Product C", "Footwear", "BrandX", 100.0, 150.0, 4.0, "[]", "desc", 0.300000),
        ]

        mock_db = MagicMock(spec=AsyncEngine)
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = raw_rows
        mock_conn.execute.return_value = mock_result
        mock_db.connect.return_value.__aenter__.return_value = mock_conn

        search_engine = SemanticSearchEngine(engine=mock_db, encoder=shared_encoder)

        results = await search_engine.search("shoes", top_k=3)
        assert len(results) == 3
        # Should be ordered by product_id ASC due to identical distances
        assert results[0].product_id == "PID_A"
        assert results[0].rank == 1
        assert results[1].product_id == "PID_B"
        assert results[1].rank == 2
        assert results[2].product_id == "PID_C"
        assert results[2].rank == 3

    def test_semantic_score_mapping(self) -> None:
        """Verify semantic_score = 1.0 - cosine_distance."""
        res = SemanticSearchResult(
            rank=1,
            product_id="TEST_01",
            product_name="Test Product",
            category="Electronics",
            brand="Sony",
            discounted_price=1999.0,
            cosine_distance=0.250000,
            semantic_score=round(1.0 - 0.250000, 6),
        )
        assert res.semantic_score == 0.750000
        d = res.to_dict()
        assert d["cosine_distance"] == 0.250000
        assert d["semantic_score"] == 0.750000


# ==============================================================================
# 3. Helper and Metric Tests
# ==============================================================================

class TestRetrievalHelpers:
    """Tests for config serialization, overlap metric, and formatting."""

    def test_config_roundtrip(self) -> None:
        """Verify SemanticSearchConfig serializes and deserializes accurately."""
        cfg = SemanticSearchConfig(
            model_name="BAAI/bge-small-en-v1.5",
            embedding_dim=384,
            default_top_k=10,
            max_top_k=50,
            candidate_pool_multiplier=2,
        )
        d = cfg.to_dict()
        cfg_loaded = SemanticSearchConfig.from_dict(d)
        assert cfg_loaded.default_top_k == 10
        assert cfg_loaded.max_top_k == 50
        assert cfg_loaded.candidate_pool_multiplier == 2

    def test_compute_result_overlap(self) -> None:
        """Verify compute_result_overlap calculates Jaccard-like overlap fraction."""
        res_a = [
            SemanticSearchResult(1, "ID1", "P1", "C", None, 10, 0.1, 0.9),
            SemanticSearchResult(2, "ID2", "P2", "C", None, 10, 0.2, 0.8),
            SemanticSearchResult(3, "ID3", "P3", "C", None, 10, 0.3, 0.7),
        ]
        res_b = [
            SemanticSearchResult(1, "ID2", "P2", "C", None, 10, 0.1, 0.9),
            SemanticSearchResult(2, "ID3", "P3", "C", None, 10, 0.2, 0.8),
            SemanticSearchResult(3, "ID4", "P4", "C", None, 10, 0.3, 0.7),
        ]
        # Common IDs: ID2, ID3 out of 3 = 2/3 = 0.6667
        overlap = compute_result_overlap(res_a, res_b, top_k=3)
        assert abs(overlap - 0.6667) < 1e-3

        # Completely disjoint
        overlap_disjoint = compute_result_overlap(res_a, [SemanticSearchResult(1, "ID9", "P9", "C", None, 10, 0.1, 0.9)], top_k=1)
        assert overlap_disjoint == 0.0


# ==============================================================================
# 4. Live Supabase PostgreSQL Integration Tests
# ==============================================================================

@pytest.fixture(scope="module")
def has_db_url() -> bool:
    """Check if live database URL is configured."""
    url = settings.get_raw_supabase_db_url()
    return bool(url and "postgres" in url)


@pytest.mark.integration
class TestLiveSemanticSearchIntegration:
    """Live integration tests requiring operational Supabase PostgreSQL instance."""

    @async_test
    async def test_live_catalog_integrity(self, has_db_url: bool) -> None:

        """Verify all 8,405 products exist with intact 384-d vectors."""
        if not has_db_url:
            pytest.skip("Supabase database connection not configured.")

        engine = SemanticSearchEngine()
        try:
            integrity = await engine.verify_catalog_integrity()
            assert integrity["is_intact"] is True
            assert integrity["total_rows"] == 8405
            assert integrity["matching_dim_rows"] == 8405
            assert integrity["null_emb_rows"] == 0
        finally:
            await engine.close()

    @async_test
    async def test_live_search_normal_query(self, has_db_url: bool) -> None:
        """Verify normal query returns valid Top-K items ordered by similarity."""
        if not has_db_url:
            pytest.skip("Supabase database connection not configured.")

        engine = SemanticSearchEngine()
        try:
            hits = await engine.search("wireless bluetooth keyboard", top_k=5)
            assert len(hits) == 5
            for idx, h in enumerate(hits, start=1):
                assert h.rank == idx
                assert len(h.product_id) > 0
                assert len(h.product_name) > 0
                assert len(h.category) > 0
                assert 0.0 <= h.cosine_distance <= 2.0
                assert -1.0 <= h.semantic_score <= 1.0

            # Distances must be monotonically non-decreasing
            for i in range(len(hits) - 1):
                assert hits[i].cosine_distance <= hits[i + 1].cosine_distance
        finally:
            await engine.close()

    @async_test
    async def test_live_hnsw_execution_plan(self, has_db_url: bool) -> None:
        """Verify EXPLAIN output selects idx_products_embedding HNSW index."""
        if not has_db_url:
            pytest.skip("Supabase database connection not configured.")

        engine = SemanticSearchEngine()
        try:
            plan = await engine.explain_search("portable usb drive", top_k=5)
            assert "idx_products_embedding" in plan
            assert "Index Scan" in plan or "Bitmap Index Scan" in plan
        finally:
            await engine.close()

    @async_test
    async def test_live_exact_linear_scan(self, has_db_url: bool) -> None:
        """Verify search_exact returns valid Top-K items using sequential scan."""
        if not has_db_url:
            pytest.skip("Supabase database connection not configured.")

        engine = SemanticSearchEngine()
        try:
            hits = await engine.search_exact("running shoes", top_k=5)
            assert len(hits) == 5
            for i in range(len(hits) - 1):
                assert hits[i].cosine_distance <= hits[i + 1].cosine_distance
        finally:
            await engine.close()
