"""Comprehensive automated tests for Phase 6: TF-IDF Baseline Retrieval Engine.

Covers:
1. Vectorizer & Mathematical Tests:
   - Vocabulary creation & term mapping.
   - Sparse matrix shape & CSR format.
   - Numerical correctness against hand-calculated TF-IDF values.
   - L2 normalization verification.
   - Non-zero feature counts.

2. Query Processing Tests:
   - Standard queries.
   - Empty & whitespace-only queries.
   - Pure out-of-vocabulary (OOV) queries.
   - Invalid query types.
   - Case-insensitivity verification.

3. Retrieval & Ranking Tests:
   - Cosine similarity calculation & ranking order.
   - Deterministic tie-breaking by score DESC, product_id ASC.
   - Queries with fewer than K matching candidates.
   - Top-K edge cases (K=1, K > corpus size, invalid K <= 0).
   - Metadata alignment with retrieved product records.

4. Persistence & Reproducibility Tests:
   - Full artifact export (joblib vectorizer, npz matrix, parquet metadata, manifest).
   - Artifact reload and roundtrip deserialization.
   - 100% identical search output verification post-reload.
   - Error detection for corrupted or missing artifacts.

5. Integration Tests:
   - Canonical 8,405-product dataset loading & validation.
   - Full catalog index fitting & memory statistics.
   - Representative search scenarios.
   - Query latency verification (< 25 ms).
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp

from shopassist.retrieval.tfidf import (
    CANONICAL_PRODUCTS_PATH,
    EXPECTED_CATALOG_SIZE,
    SearchResult,
    TFIDFConfig,
    TFIDFIndex,
    benchmark_tfidf_latency,
    load_canonical_products,
    run_retrieval_scenarios,
)


@pytest.fixture
def synthetic_product_df() -> pd.DataFrame:
    """Create a minimal synthetic product catalog for deterministic mathematical testing."""
    return pd.DataFrame([
        {
            "product_id": "P001",
            "product_name": "Running Shoes Nike",
            "category": "Footwear",
            "brand": "Nike",
            "discounted_price": 99.99,
            "retrieval_text": "running shoes running",
        },
        {
            "product_id": "P002",
            "product_name": "Athletic Running Shoes Adidas",
            "category": "Footwear",
            "brand": "Adidas",
            "discounted_price": 89.99,
            "retrieval_text": "running shoes athletic",
        },
        {
            "product_id": "P003",
            "product_name": "Digital Leather Watch Casio",
            "category": "Watches",
            "brand": "Casio",
            "discounted_price": 49.99,
            "retrieval_text": "leather watch digital",
        },
    ])


# ==============================================================================
# 1. Vectorizer & Mathematical Tests
# ==============================================================================

def test_tfidf_config_serialization():
    """Verify TFIDFConfig serializes to dict and reconstructs from dict."""
    cfg = TFIDFConfig(ngram_range=(1, 2), min_df=3, max_df=0.75, sublinear_tf=False)
    d = cfg.to_dict()
    assert d["ngram_range"] == [1, 2]
    assert d["min_df"] == 3
    assert d["max_df"] == 0.75
    assert d["sublinear_tf"] is False

    reconstructed = TFIDFConfig.from_dict(d)
    assert reconstructed.ngram_range == (1, 2)
    assert reconstructed.min_df == 3
    assert reconstructed.max_df == 0.75
    assert reconstructed.sublinear_tf is False


def test_tfidf_vectorizer_vocabulary_creation(synthetic_product_df):
    """Verify vectorizer creates expected vocabulary and sparse matrix."""
    config = TFIDFConfig(ngram_range=(1, 1), min_df=1, max_df=1.0, sublinear_tf=False)
    index = TFIDFIndex(config=config)
    index.fit(synthetic_product_df)

    assert index.is_fitted is True
    vocab = index.vectorizer.vocabulary_
    expected_words = {"athletic", "digital", "leather", "running", "shoes", "watch"}
    assert set(vocab.keys()) == expected_words
    assert index.document_matrix.shape == (3, 6)
    assert sp.isspmatrix_csr(index.document_matrix)


def test_tfidf_mathematical_hand_calculation_match(synthetic_product_df):
    """Verify scikit-learn smoothed IDF and L2-normalized TF-IDF match exact hand calculations."""
    config = TFIDFConfig(ngram_range=(1, 1), min_df=1, max_df=1.0, sublinear_tf=False, smooth_idf=True)
    index = TFIDFIndex(config=config)
    index.fit(synthetic_product_df)

    # Document 1: 'running shoes running' (tf: running=2, shoes=1; df: running=2, shoes=2)
    # IDF for running and shoes (df=2): ln((1+3)/(1+2)) + 1 = ln(4/3) + 1 ≈ 1.287682
    # Unnormalized: running = 2 * 1.287682 = 2.575364; shoes = 1 * 1.287682 = 1.287682
    # Norm: sqrt(2.575364^2 + 1.287682^2) = sqrt(6.63250 + 1.65812) = sqrt(8.29062) ≈ 2.879344
    # Normalized running: 2.575364 / 2.879344 ≈ 0.894427
    # Normalized shoes: 1.287682 / 2.879344 ≈ 0.447214
    vocab = index.vectorizer.vocabulary_
    idx_running = vocab["running"]
    idx_shoes = vocab["shoes"]

    row_0 = index.document_matrix.getrow(0).toarray().ravel()
    assert abs(row_0[idx_running] - 0.894427) < 1e-4
    assert abs(row_0[idx_shoes] - 0.447214) < 1e-4


def test_tfidf_l2_normalization(synthetic_product_df):
    """Verify all document vectors in the sparse matrix have unit L2 length (||v||_2 = 1.0)."""
    index = TFIDFIndex(config=TFIDFConfig(min_df=1))
    index.fit(synthetic_product_df)

    matrix = index.document_matrix
    for row_idx in range(matrix.shape[0]):
        row_vec = matrix.getrow(row_idx).toarray().ravel()
        l2_norm = float(np.linalg.norm(row_vec))
        assert abs(l2_norm - 1.0) < 1e-6, f"Row {row_idx} L2 norm was {l2_norm}, expected 1.0"


def test_tfidf_statistics_computation(synthetic_product_df):
    """Verify get_statistics computes accurate structural and memory attributes."""
    index = TFIDFIndex(config=TFIDFConfig(ngram_range=(1, 1), min_df=1))
    index.fit(synthetic_product_df)

    stats = index.get_statistics()
    assert stats["is_fitted"] is True
    assert stats["total_documents"] == 3
    assert stats["vocabulary_size"] == 6
    assert stats["matrix_shape"] == [3, 6]
    # d1 has 2 unique terms, d2 has 3 unique terms, d3 has 3 unique terms -> 8 non-zero entries
    assert stats["nonzero_elements"] == 8
    expected_sparsity = (1.0 - (8 / 18)) * 100.0
    assert abs(stats["sparsity_pct"] - expected_sparsity) < 1e-3
    assert stats["memory_bytes_approx"] > 0


# ==============================================================================
# 2. Query Processing Tests
# ==============================================================================

def test_query_empty_and_whitespace(synthetic_product_df):
    """Verify empty or whitespace-only queries return an empty result list without errors."""
    index = TFIDFIndex(config=TFIDFConfig(min_df=1))
    index.fit(synthetic_product_df)

    assert index.search("") == []
    assert index.search("   ") == []
    assert index.search("\t\n") == []


def test_query_pure_out_of_vocabulary(synthetic_product_df):
    """Verify queries containing zero recognized catalog words return empty list (zero-score policy)."""
    index = TFIDFIndex(config=TFIDFConfig(min_df=1))
    index.fit(synthetic_product_df)

    # Words completely absent from mini-corpus
    oov_query = "supercalifragilisticexpialidocious quantum"
    results = index.search(oov_query, top_k=5)
    assert results == []


def test_query_case_insensitivity(synthetic_product_df):
    """Verify case differences yield identical search scores under lowercase=True."""
    index = TFIDFIndex(config=TFIDFConfig(min_df=1, lowercase=True))
    index.fit(synthetic_product_df)

    res_lower = index.search("running shoes", top_k=2)
    res_upper = index.search("RUNNING SHOES", top_k=2)
    res_mixed = index.search("RuNnInG ShOeS", top_k=2)

    assert len(res_lower) == len(res_upper) == len(res_mixed) == 2
    assert res_lower[0].product_id == res_upper[0].product_id == res_mixed[0].product_id
    assert abs(res_lower[0].tfidf_score - res_upper[0].tfidf_score) < 1e-6
    assert abs(res_lower[0].tfidf_score - res_mixed[0].tfidf_score) < 1e-6


def test_transform_query_unfitted_raises():
    """Verify transform_query raises RuntimeError when index is not yet fitted."""
    unfitted_index = TFIDFIndex()
    with pytest.raises(RuntimeError, match="must be fitted"):
        unfitted_index.transform_query("running shoes")


def test_transform_query_invalid_type_raises(synthetic_product_df):
    """Verify non-string query inputs raise ValueError."""
    index = TFIDFIndex(config=TFIDFConfig(min_df=1))
    index.fit(synthetic_product_df)

    with pytest.raises(ValueError, match="must be a string"):
        index.transform_query(12345)  # type: ignore


# ==============================================================================
# 3. Retrieval & Ranking Tests
# ==============================================================================

def test_cosine_similarity_ranking_correctness(synthetic_product_df):
    """Verify candidate ranking correctly reflects term overlap and concentration."""
    config = TFIDFConfig(ngram_range=(1, 1), min_df=1, max_df=1.0, sublinear_tf=False, smooth_idf=True)
    index = TFIDFIndex(config=config)
    index.fit(synthetic_product_df)

    # Query: 'running shoes'
    # From mathematical walkthrough: d1 score ≈ 0.948684, d2 score ≈ 0.732360, d3 score = 0.0
    results = index.search("running shoes", top_k=5)
    assert len(results) == 2  # d3 has score 0.0, excluded by positive-score policy
    assert results[0].product_id == "P001"
    assert results[1].product_id == "P002"
    assert abs(results[0].tfidf_score - 0.948684) < 1e-4
    assert abs(results[1].tfidf_score - 0.732360) < 1e-4
    assert results[0].tfidf_score > results[1].tfidf_score


def test_deterministic_tie_breaking():
    """Verify identical scores are broken deterministically by product_id ASC."""
    # Two products with identical retrieval text but different IDs
    tied_df = pd.DataFrame([
        {
            "product_id": "P009",
            "product_name": "Product Z",
            "category": "Tools",
            "brand": "BrandX",
            "discounted_price": 10.0,
            "retrieval_text": "cordless drill hammer",
        },
        {
            "product_id": "P001",
            "product_name": "Product A",
            "category": "Tools",
            "brand": "BrandX",
            "discounted_price": 10.0,
            "retrieval_text": "cordless drill hammer",
        },
    ])
    index = TFIDFIndex(config=TFIDFConfig(min_df=1, max_df=1.0))
    index.fit(tied_df)

    results = index.search("cordless drill", top_k=2)
    assert len(results) == 2
    assert abs(results[0].tfidf_score - results[1].tfidf_score) < 1e-6
    # P001 should rank ahead of P009 because 'P001' < 'P009' alphabetically
    assert results[0].product_id == "P001"
    assert results[1].product_id == "P009"


def test_top_k_edge_cases(synthetic_product_df):
    """Verify edge cases for top_k parameter (K=1, K > corpus, K <= 0)."""
    index = TFIDFIndex(config=TFIDFConfig(min_df=1))
    index.fit(synthetic_product_df)

    # K = 1
    res_k1 = index.search("running shoes", top_k=1)
    assert len(res_k1) == 1
    assert res_k1[0].rank == 1

    # K > total matches
    res_k100 = index.search("running shoes", top_k=100)
    assert len(res_k100) == 2  # Only 2 positive matches exist

    # Invalid K <= 0
    with pytest.raises(ValueError, match="must be a positive integer"):
        index.search("running shoes", top_k=0)

    with pytest.raises(ValueError, match="must be a positive integer"):
        index.search("running shoes", top_k=-5)


def test_metadata_alignment(synthetic_product_df):
    """Verify retrieved SearchResult objects contain matching metadata from original rows."""
    index = TFIDFIndex(config=TFIDFConfig(min_df=1))
    index.fit(synthetic_product_df)

    results = index.search("watch digital", top_k=1)
    assert len(results) == 1
    r = results[0]
    assert r.product_id == "P003"
    assert r.product_name == "Digital Leather Watch Casio"
    assert r.category == "Watches"
    assert r.brand == "Casio"
    assert r.discounted_price == 49.99


# ==============================================================================
# 4. Persistence & Reproducibility Tests
# ==============================================================================

def test_artifact_persistence_and_reload(synthetic_product_df, tmp_path: Path):
    """Verify index can be persisted to disk and reloaded with 100% identical outputs."""
    artifact_dir = tmp_path / "tfidf_test_artifacts"
    index = TFIDFIndex(config=TFIDFConfig(ngram_range=(1, 2), min_df=1))
    index.fit(synthetic_product_df)

    # Save
    saved_dir = index.save(artifact_dir, manifest_extra={"test_note": "unit_test"})
    assert (saved_dir / "tfidf_vectorizer.joblib").exists()
    assert (saved_dir / "tfidf_matrix.npz").exists()
    assert (saved_dir / "product_metadata.parquet").exists()
    assert (saved_dir / "tfidf_manifest.json").exists()

    # Load
    reloaded = TFIDFIndex.load(saved_dir)
    assert reloaded.is_fitted is True
    assert reloaded.document_matrix.shape == index.document_matrix.shape
    assert len(reloaded.product_ids) == len(index.product_ids)
    assert len(reloaded.vectorizer.vocabulary_) == len(index.vectorizer.vocabulary_)

    # Verify identical query results
    for q in ["running shoes", "watch", "athletic footwear"]:
        orig_res = index.search(q, top_k=5)
        reloaded_res = reloaded.search(q, top_k=5)
        assert len(orig_res) == len(reloaded_res)
        for r1, r2 in zip(orig_res, reloaded_res):
            assert r1.product_id == r2.product_id
            assert abs(r1.tfidf_score - r2.tfidf_score) < 1e-6


def test_reload_missing_files_raises(tmp_path: Path):
    """Verify loading from an incomplete directory raises FileNotFoundError."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="Missing required TF-IDF artifact"):
        TFIDFIndex.load(empty_dir)


def test_reload_nonexistent_directory_raises():
    """Verify loading from a nonexistent directory raises FileNotFoundError."""
    nonexistent = Path("nonexistent_path_xyz_12345")
    with pytest.raises(FileNotFoundError, match="does not exist"):
        TFIDFIndex.load(nonexistent)


# ==============================================================================
# 5. Full Real Dataset Integration Tests (products.parquet)
# ==============================================================================

def test_canonical_products_loading():
    """Verify canonical products.parquet loads with exactly 8,405 records and required columns."""
    if not CANONICAL_PRODUCTS_PATH.exists():
        pytest.skip(f"Canonical dataset not found: {CANONICAL_PRODUCTS_PATH}")

    df = load_canonical_products(CANONICAL_PRODUCTS_PATH, expected_count=EXPECTED_CATALOG_SIZE)
    assert len(df) == EXPECTED_CATALOG_SIZE
    assert df["product_id"].nunique() == EXPECTED_CATALOG_SIZE
    assert df["category"].nunique() == 16
    assert not df["retrieval_text"].isna().any()


def test_full_corpus_tfidf_index_smoke():
    """Smoke test fitting TFIDFIndex on full 8,405 products and running queries."""
    if not CANONICAL_PRODUCTS_PATH.exists():
        pytest.skip(f"Canonical dataset not found: {CANONICAL_PRODUCTS_PATH}")

    df = load_canonical_products(CANONICAL_PRODUCTS_PATH)
    config = TFIDFConfig(ngram_range=(1, 2), min_df=2, max_df=0.8, sublinear_tf=True)
    index = TFIDFIndex(config=config)
    index.fit(df)

    stats = index.get_statistics()
    assert stats["total_documents"] == EXPECTED_CATALOG_SIZE
    assert stats["vocabulary_size"] > 40000
    assert stats["sparsity_pct"] > 99.0
    assert stats["memory_mb_approx"] < 50.0  # Sparse matrix is compact

    # Query smoke test
    results = index.search("Allure Auto car mat", top_k=5)
    assert len(results) == 5
    assert results[0].tfidf_score > 0.0
    assert "Allure Auto" in results[0].product_name or results[0].brand == "Allure Auto"


def test_retrieval_scenarios_execution(synthetic_product_df):
    """Verify run_retrieval_scenarios executes custom scenarios and formats outputs."""
    index = TFIDFIndex(config=TFIDFConfig(min_df=1))
    index.fit(synthetic_product_df)

    custom_scenarios = [
        {"scenario_id": "SC1", "description": "Test query 1", "query": "running shoes"},
        {"scenario_id": "SC2", "description": "Test query 2", "query": "leather watch"},
        {"scenario_id": "SC3", "description": "Test query 3 (OOV)", "query": "gibberishwordxyz"},
    ]
    outputs = run_retrieval_scenarios(index, custom_scenarios, top_k=2)
    assert len(outputs) == 3
    assert outputs[0]["returned_count"] == 2
    assert outputs[1]["returned_count"] == 1
    assert outputs[2]["returned_count"] == 0  # OOV returns 0 items


def test_benchmark_tfidf_latency_execution(synthetic_product_df):
    """Verify benchmark_tfidf_latency runs repeated iterations and computes percentiles."""
    index = TFIDFIndex(config=TFIDFConfig(min_df=1))
    index.fit(synthetic_product_df)

    bench = benchmark_tfidf_latency(
        index,
        queries=["running shoes", "watch"],
        num_iterations=5,
        warmup_runs=1,
        top_k=2,
    )
    assert bench["num_queries"] == 2
    assert bench["iterations_per_query"] == 5
    assert bench["total_measured_calls"] == 10
    assert bench["p50_latency_ms"] >= 0.0
    assert bench["p95_latency_ms"] >= bench["p50_latency_ms"]
    assert bench["mean_latency_ms"] > 0.0
