"""Phase 5.8 executable CLI script: Product Knowledge Base Validation & Filtered Search Verification.

Performs read-only validation of the ShopAssist Product Knowledge Base on Supabase PostgreSQL:
- Test Group A: Data Integrity Validation (A01 - A10)
- Test Group B: SQL Hard Constraint Filtering (B01 - B10)
- Test Group C: Vector Similarity Search (C01 - C07)
- Test Group D: Filtered Semantic Search (D01 - D10)
- Test Group E: Index Verification & Performance Benchmarking (E01 - E06)

Usage:
    python scripts/validate_product_knowledge_base.py
    python scripts/validate_product_knowledge_base.py --report data/interim/phase5_8_knowledge_base_validation_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
import sys
from typing import Any

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shopassist.db.connection import ensure_windows_event_loop_policy
from shopassist.db.search_validation import (
    CANONICAL_PARQUET_PATH,
    DEFAULT_REPORT_PATH,
    ValidationTestResult,
    run_phase5_8_full_validation,
)

ensure_windows_event_loop_policy()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("validate_product_knowledge_base")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Phase 5.8 — Product Knowledge Base Validation & Filtered Search Verification."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"Path to output execution report JSON (default: {DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--parquet",
        type=Path,
        default=CANONICAL_PARQUET_PATH,
        help=f"Path to source Parquet dataset (default: {CANONICAL_PARQUET_PATH})",
    )
    return parser.parse_args()


def print_summary(
    report: dict[str, Any],
    results: list[ValidationTestResult],
    report_path: Path,
) -> None:
    """Pretty print terminal summary report."""
    target_db = report.get("target_database", {})
    conn_info = target_db.get("connection", {})
    ds_stats = report.get("dataset_statistics", {})
    summary = report.get("test_summary", {})
    group_counts = summary.get("group_breakdown", {})
    benchmarks = report.get("latency_benchmarks", {})
    tradeoff = report.get("exact_vs_ann_tradeoff", {})
    perf = report.get("performance", {})
    phase5_eval = report.get("phase5_completion_assessment", {})

    print("\n" + "=" * 80)
    print("PHASE 5.8 — PRODUCT KNOWLEDGE BASE VALIDATION & SEARCH VERIFICATION")
    print("=" * 80)
    print(f"Overall Status:               {report.get('overall_status', 'FAIL')}")
    print(f"Execution Timestamp:          {report.get('execution_timestamp', 'N/A')}")
    print(f"Target Database:              {target_db.get('masked_url', 'N/A')}")
    print(f"PostgreSQL Version:           {conn_info.get('postgresql_version', 'N/A')}")
    print(f"pgvector Version:             {conn_info.get('pgvector_version', 'N/A')}")
    print(f"Target Table:                 {target_db.get('table', 'public.products')}")
    print(f"Total Products:               {ds_stats.get('actual_products', 0):,}")
    print(f"Total Categories:             {ds_stats.get('actual_categories', 0)}")
    print(f"Embedding Dimension:          {ds_stats.get('embedding_dimension', 0)}")
    print(f"Embedding Model:              {ds_stats.get('embedding_model', 'N/A')}")
    print(f"Total Validation Tests:       {summary.get('total_tests', 0)}")
    print(f"Passed Tests:                 {summary.get('passed_tests', 0)}")
    print(f"Failed Tests:                 {summary.get('failed_tests', 0)}")
    print(f"Test Pass Rate:               {summary.get('pass_rate_pct', 0.0)}%")
    print(f"Total Execution Time:         {perf.get('total_elapsed_seconds', 0.0):.2f} s")
    print("-" * 80)
    print("TEST GROUP BREAKDOWN:")
    print(f"  [Group A] Data Integrity Validation:           {group_counts.get('Group_A_Data_Integrity', 'N/A')}")
    print(f"  [Group B] SQL Hard Constraint Filtering:       {group_counts.get('Group_B_SQL_Filtering', 'N/A')}")
    print(f"  [Group C] Vector Similarity Search:            {group_counts.get('Group_C_Vector_Search', 'N/A')}")
    print(f"  [Group D] Filtered Semantic Search:            {group_counts.get('Group_D_Filtered_Semantic', 'N/A')}")
    print(f"  [Group E] Index Verification & Benchmarking:   {group_counts.get('Group_E_Index_Performance', 'N/A')}")
    print("-" * 80)
    print("SEARCH LATENCY BENCHMARKS (measured over warm runs):")
    if isinstance(benchmarks, list):
        for b in benchmarks:
            q_id = b.get("query_id", "unknown")
            mean_lat = b.get("mean_ms", 0.0)
            p50 = b.get("p50_ms", 0.0)
            p95 = b.get("p95_ms", 0.0)
            min_lat = b.get("min_ms", 0.0)
            max_lat = b.get("max_ms", 0.0)
            runs = b.get("num_measured_runs", 0)
            print(f"  - {q_id:<28}: P50={p50:6.2f}ms | P95={p95:6.2f}ms | Mean={mean_lat:6.2f}ms | Min={min_lat:6.2f}ms | Max={max_lat:6.2f}ms ({runs} runs)")
    elif isinstance(benchmarks, dict):
        for q_id, b in benchmarks.items():
            mean_lat = b.get("mean_ms", 0.0)
            p50 = b.get("p50_ms", 0.0)
            p95 = b.get("p95_ms", 0.0)
            min_lat = b.get("min_ms", 0.0)
            max_lat = b.get("max_ms", 0.0)
            runs = b.get("num_measured_runs", 0)
            print(f"  - {q_id:<28}: P50={p50:6.2f}ms | P95={p95:6.2f}ms | Mean={mean_lat:6.2f}ms | Min={min_lat:6.2f}ms | Max={max_lat:6.2f}ms ({runs} runs)")
    print("-" * 80)
    print("HNSW ANN VS. EXACT BRUTE-FORCE TRADE-OFF:")
    ann_client = tradeoff.get("ann_ms", 0.0)
    exact_client = tradeoff.get("exact_ms", 0.0)
    client_speedup = tradeoff.get("client_speedup_factor", tradeoff.get("speedup_factor", 1.0))
    server_ann = tradeoff.get("server_ann_ms", 0.0)
    server_exact = tradeoff.get("server_exact_ms", 0.0)
    server_speedup = tradeoff.get("server_speedup_factor", 1.0)
    c07_test = next((r for r in results if r.test_id == "C07"), None)
    c07_actual = c07_test.actual if c07_test else "N/A"
    print(f"  - Client Latency (P50):      Exact={exact_client:.2f} ms vs HNSW={ann_client:.2f} ms ({client_speedup:.1f}x speedup)")
    print(f"  - Server Execution Time:     Exact={server_exact:.3f} ms vs HNSW={server_ann:.3f} ms ({server_speedup:.1f}x speedup)")
    print(f"  - ANN Search Quality:        {c07_actual}")
    print("-" * 80)
    print("POST-FILTERING UNDERFILL EVALUATION:")
    underfill_test = next((r for r in results if r.test_id == "D09"), None)
    if underfill_test:
        uf_details = underfill_test.details
        print(f"  - Eligible Candidates in Pool: {uf_details.get('eligible_candidates')}")
        print(f"  - Requested Top-K:           {uf_details.get('requested_k')}")
        print(f"  - Standard ANN Returned:     {uf_details.get('standard_ann_returned')}")
        print(f"  - Underfill Detected:        {uf_details.get('underfill_detected')}")
        print(f"  - Iterative Scan Supported:  {uf_details.get('iterative_scan_supported')}")
        print(f"  - Mitigation Verified:       {uf_details.get('mitigation_verified')}")
    print("-" * 80)
    print("FAILED TESTS (IF ANY):")
    failed_items = [r for r in results if r.status == "FAIL"]
    if not failed_items:
        print("  None! All 43 test cases passed successfully.")
    else:
        for f in failed_items:
            print(f"  - [{f.test_id}] {f.name}: Expected={f.expected} | Actual={f.actual}")
            if f.error_message:
                print(f"      Error: {f.error_message}")
    print("-" * 80)
    print(f"Phase 5 Completion Status:    {phase5_eval.get('product_knowledge_base_status', 'N/A')}")
    print(f"Readiness for Phase 6:        {'READY' if phase5_eval.get('ready_for_phase_6') else 'NOT READY'} ({phase5_eval.get('next_phase', 'N/A')})")
    print(f"Report File:                  {report_path}")
    print("=" * 80 + "\n")


def main() -> int:
    """CLI execution entrypoint."""
    args = parse_args()
    logger.info("Executing Phase 5.8 validation CLI...")
    logger.info("Report path: %s", args.report)
    logger.info("Parquet path: %s", args.parquet)

    try:
        report, results = asyncio.run(
            run_phase5_8_full_validation(
                report_path=args.report,
                parquet_path=args.parquet,
            )
        )
    except Exception as exc:
        logger.error("Phase 5.8 validation failed with exception: %s", exc, exc_info=True)
        return 1

    print_summary(report, results, args.report)

    if report.get("overall_status") == "PASS":
        logger.info("Phase 5.8 validation COMPLETED WITH STATUS: PASS")
        return 0
    else:
        logger.error("Phase 5.8 validation FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
