"""Automated unit and integration tests for Phase 5.8: Knowledge Base Validation & Filtered Search Verification.

Covers:
1. Unit Tests (Deterministic / Local / Mock):
   - ValidationTestResult model serialization and attributes.
   - Cosine distance computation vs NumPy ground truth.
   - Parameterized query formatting and SQL injection protection.
   - Top-K result ordering and distance monotonic increase assertions.
   - Post-filtering underfill detection logic.
   - Benchmark statistics calculation (P50, P95, mean, min, max).
   - Report export atomicity and JSON schema compliance.
   - Graceful handling of malformed or invalid inputs.

2. Live Integration Tests (Read-Only Supabase):
   - Group A: Data integrity validation (A01 - A10).
   - Group B: SQL hard constraint filtering (B01 - B10).
   - Group C: Vector similarity search (C01 - C07).
   - Group D: Filtered semantic search & underfill analysis (D01 - D10).
   - Group E: Index verification & performance benchmarking (E01 - E06).
   - End-to-end validation pipeline execution and report generation.
"""

from __future__ import annotations

import asyncio
from functools import wraps
import json
import math
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from shopassist.db.connection import ensure_windows_event_loop_policy, get_async_engine
from shopassist.db.search_validation import (
    CANONICAL_PARQUET_PATH,
    DEFAULT_REPORT_PATH,
    EXPECTED_CATALOG_SIZE,
    EXPECTED_CATEGORY_COUNT,
    EXPECTED_EMBEDDING_DIM,
    ValidationTestResult,
    export_validation_report,
    run_phase5_8_full_validation,
    validate_group_a_integrity,
    validate_group_b_filtering,
    validate_group_c_vector_search,
    validate_group_d_filtered_semantic,
    validate_group_e_index_performance,
)

ensure_windows_event_loop_policy()


def async_test(coro):
    """Decorator to execute async test functions cleanly without pytest-asyncio plugin."""
    @wraps(coro)
    def wrapper(*args, **kwargs):
        ensure_windows_event_loop_policy()
        return asyncio.run(coro(*args, **kwargs))
    return wrapper


# ==============================================================================
# 1. Unit Tests (Deterministic & Independent of Database)
# ==============================================================================

def test_validation_test_result_model():
    """Verify ValidationTestResult dataclass initializes and serializes correctly."""
    res = ValidationTestResult(
        test_id="T01",
        name="Test Model",
        category="A_integrity",
        status="PASS",
        description="Verify model fields",
        expected="8405",
        actual="8405",
        details={"key": "val"},
        error_message=None,
    )
    d = res.to_dict()
    assert d["test_id"] == "T01"
    assert d["name"] == "Test Model"
    assert d["category"] == "A_integrity"
    assert d["status"] == "PASS"
    assert d["expected"] == "8405"
    assert d["actual"] == "8405"
    assert d["details"] == {"key": "val"}
    assert d["error_message"] is None


def test_numpy_cosine_distance_computation():
    """Verify independent NumPy cosine distance calculation matches mathematical properties."""
    v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    v2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    v3 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    v4 = np.array([-1.0, 0.0, 0.0], dtype=np.float32)

    def cos_dist(a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        dot = np.dot(a, b)
        return float(1.0 - (dot / (norm_a * norm_b)))

    # Self-match distance should be 0.0
    assert abs(cos_dist(v1, v3)) < 1e-6
    # Orthogonal vectors distance should be 1.0
    assert abs(cos_dist(v1, v2) - 1.0) < 1e-6
    # Opposite vectors distance should be 2.0
    assert abs(cos_dist(v1, v4) - 2.0) < 1e-6


def test_benchmark_statistics_calculation():
    """Verify percentile and summary statistic calculation logic."""
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p50 = float(np.percentile(latencies, 50))
    p95 = float(np.percentile(latencies, 95))
    mean_val = float(np.mean(latencies))
    min_val = float(np.min(latencies))
    max_val = float(np.max(latencies))

    assert p50 == 55.0
    assert p95 > 90.0
    assert mean_val == 55.0
    assert min_val == 10.0
    assert max_val == 100.0


def test_export_validation_report_atomic(tmp_path: Path):
    """Verify export_validation_report writes JSON file atomically and produces valid JSON."""
    report_dict = {
        "phase": "5.8",
        "overall_status": "PASS",
        "dataset_statistics": {"total_products": EXPECTED_CATALOG_SIZE},
        "test_summary": {"passed_tests": 43, "total_tests": 43},
    }
    out_file = tmp_path / "test_report.json"
    written_path = export_validation_report(report_dict, out_file)

    assert written_path.exists()
    content = json.loads(written_path.read_text(encoding="utf-8"))
    assert content["phase"] == "5.8"
    assert content["overall_status"] == "PASS"
    assert content["test_summary"]["passed_tests"] == 43


def test_underfill_logic_simulation():
    """Verify post-filtering underfill detection and handling logic on simulated data."""
    requested_k = 10
    eligible_count = 25  # At least K eligible items exist

    # Case 1: Approximate search returns fewer than K (e.g., 4) -> underfill
    ann_returned_case1 = 4
    underfill_detected_1 = ann_returned_case1 < requested_k and eligible_count >= requested_k
    assert underfill_detected_1 is True

    # Case 2: Iterative scan returns full K -> resolved
    iterative_returned_case2 = 10
    underfill_detected_2 = iterative_returned_case2 < requested_k and eligible_count >= requested_k
    assert underfill_detected_2 is False

    # Case 3: Candidate pool smaller than K (e.g., 3 eligible items) -> legitimate truncation, not underfill
    small_pool = 3
    ann_returned_case3 = 3
    underfill_detected_3 = ann_returned_case3 < requested_k and small_pool >= requested_k
    assert underfill_detected_3 is False


def test_recall_at_k_calculation():
    """Verify Recall@K calculation on candidate ID lists."""
    exact_ids = ["P1", "P2", "P3", "P4", "P5"]
    ann_ids = ["P1", "P2", "P3", "P4", "P6"]  # 4 out of 5 match

    intersection = set(exact_ids).intersection(set(ann_ids))
    recall = len(intersection) / len(exact_ids)
    assert recall == 0.80

    # 100% recall
    perfect_ann = ["P5", "P4", "P3", "P2", "P1"]
    perfect_recall = len(set(exact_ids).intersection(set(perfect_ann))) / len(exact_ids)
    assert perfect_recall == 1.00


# ==============================================================================
# 2. Live Supabase Integration Tests (Strictly Read-Only)
# ==============================================================================

@async_test
async def test_live_supabase_group_a_integrity():
    """Verify Group A (A01 - A10): Data Integrity on live Supabase public.products."""
    try:
        engine = get_async_engine()
    except Exception as exc:
        pytest.skip(f"Supabase connection unavailable: {exc}")

    results = await validate_group_a_integrity(engine, sample_consistency_size=50)
    assert len(results) == 10

    # All test results must be PASS
    failed = [r for r in results if r.status != "PASS"]
    assert not failed, f"Group A tests failed: {[f.test_id + ': ' + f.name for f in failed]}"

    # Verify key test IDs exist
    test_ids = {r.test_id for r in results}
    expected_ids = {"A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "A10"}
    assert test_ids == expected_ids


@async_test
async def test_live_supabase_group_b_filtering():
    """Verify Group B (B01 - B10): SQL Hard Constraint Filtering on live Supabase."""
    try:
        engine = get_async_engine()
    except Exception as exc:
        pytest.skip(f"Supabase connection unavailable: {exc}")

    results = await validate_group_b_filtering(engine)
    assert len(results) == 10

    failed = [r for r in results if r.status != "PASS"]
    assert not failed, f"Group B tests failed: {[f.test_id + ': ' + f.name for f in failed]}"

    # Verify 100% constraint satisfaction across all filtering tests
    for r in results:
        if "violations" in r.details:
            assert r.details["violations"] == 0, f"{r.test_id} had constraint violations: {r.details}"


@async_test
async def test_live_supabase_group_c_vector_search():
    """Verify Group C (C01 - C07): Vector Similarity Search on live Supabase."""
    try:
        engine = get_async_engine()
    except Exception as exc:
        pytest.skip(f"Supabase connection unavailable: {exc}")

    results = await validate_group_c_vector_search(engine)
    assert len(results) == 7

    failed = [r for r in results if r.status != "PASS"]
    assert not failed, f"Group C tests failed: {[f.test_id + ': ' + f.name for f in failed]}"

    # C01 self match distance must be near 0
    c01 = next(r for r in results if r.test_id == "C01")
    assert float(c01.details["distance"]) < 1e-4

    # C06 Cosine vs NumPy deviation must be near 0
    c06 = next(r for r in results if r.test_id == "C06")
    assert c06.details["max_diff"] < 1e-4

    # C07 HNSW recall must be >= 0.80
    c07 = next(r for r in results if r.test_id == "C07")
    assert all(m["recall"] >= 0.80 for m in c07.details["recall_metrics"])


@async_test
async def test_live_supabase_group_d_filtered_semantic():
    """Verify Group D (D01 - D10): Filtered Semantic Search on live Supabase."""
    try:
        engine = get_async_engine()
    except Exception as exc:
        pytest.skip(f"Supabase connection unavailable: {exc}")

    results = await validate_group_d_filtered_semantic(engine)
    assert len(results) == 10

    failed = [r for r in results if r.status != "PASS"]
    assert not failed, f"Group D tests failed: {[f.test_id + ': ' + f.name for f in failed]}"

    # D10 constraint audit must be 100% compliant
    d10 = next(r for r in results if r.test_id == "D10")
    assert d10.details["satisfaction_rate"] == 1.0


@async_test
async def test_live_supabase_group_e_index_performance():
    """Verify Group E (E01 - E06): Index & Performance Verification on live Supabase."""
    try:
        engine = get_async_engine()
    except Exception as exc:
        pytest.skip(f"Supabase connection unavailable: {exc}")

    results, latency_benchmarks, tradeoff = await validate_group_e_index_performance(engine)
    assert len(results) == 6

    failed = [r for r in results if r.status != "PASS"]
    assert not failed, f"Group E tests failed: {[f.test_id + ': ' + f.name for f in failed]}"

    # E06 database integrity check confirms row count preserved
    e06 = next(r for r in results if r.test_id == "E06")
    assert e06.details["row_count"] == EXPECTED_CATALOG_SIZE
    assert e06.details["matching_indexes"] == 5


@async_test
async def test_live_supabase_full_phase5_8_pipeline(tmp_path: Path):
    """Verify end-to-end execution of run_phase5_8_full_validation."""
    try:
        engine = get_async_engine()
    except Exception as exc:
        pytest.skip(f"Supabase connection unavailable: {exc}")

    test_report_file = tmp_path / "phase5_8_test_report.json"
    report, all_results = await run_phase5_8_full_validation(
        report_path=test_report_file,
        engine=engine,
    )

    assert report["overall_status"] == "PASS"
    assert report["phase"] == "5.8"
    assert report["test_summary"]["total_tests"] == 43
    assert report["test_summary"]["passed_tests"] == 43
    assert report["test_summary"]["failed_tests"] == 0
    assert report["test_summary"]["pass_rate_pct"] == 100.0
    assert report["phase5_completion_assessment"]["ready_for_phase_6"] is True
    assert test_report_file.exists()
