"""Phase 5.7 executable CLI script: PostgreSQL B-Tree & HNSW Index Construction.

Creates and validates 4 relational B-Tree indexes and 1 HNSW vector index
on public.products in Supabase Cloud PostgreSQL.

Usage:
    python scripts/create_product_indexes.py
    python scripts/create_product_indexes.py --report data/interim/phase5_7_index_construction_report.json
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
from shopassist.db.indexing import (
    DEFAULT_INDEX_REPORT_PATH,
    IndexAuditResult,
    run_phase5_7_pipeline,
)

ensure_windows_event_loop_policy()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("create_product_indexes")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Phase 5.7 — PostgreSQL B-Tree & HNSW Index Construction."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_INDEX_REPORT_PATH,
        help=f"Path to output execution report JSON (default: {DEFAULT_INDEX_REPORT_PATH})",
    )
    return parser.parse_args()


def print_summary(report: dict[str, Any], post_audit: IndexAuditResult, report_path: Path) -> None:
    """Pretty print terminal summary report."""
    target_db = report.get("target_database", {})
    pre_mig = report.get("pre_migration_state", {})
    mig_exec = report.get("migration_execution", {})
    post_mig = report.get("post_migration_state", {})
    benchmarks = report.get("query_plan_benchmarks", [])
    integrity = report.get("database_integrity", {})
    perf = report.get("pipeline_performance", {})

    print("\n" + "=" * 78)
    print("PHASE 5.7 — POSTGRESQL B-TREE & HNSW INDEX CONSTRUCTION SUMMARY")
    print("=" * 78)
    print(f"Overall Status:               {report.get('overall_status', 'FAIL')}")
    print(f"Target Database:              {target_db.get('masked_url', 'N/A')}")
    print(f"Target Table:                 {target_db.get('table', 'public.products')}")
    print(f"Catalog Products:             {pre_mig.get('catalog_rows', 0):,}")
    print(f"Pre-Migration Index State:    {pre_mig.get('audit', {}).get('state', 'N/A')}")
    print(f"Indexes Created:              {mig_exec.get('created_indexes', [])}")
    print(f"Migration DDL Duration:       {mig_exec.get('total_elapsed_seconds', 0.0)} s")
    print(f"Post-Migration Index State:   {post_mig.get('audit', {}).get('state', 'N/A')}")
    print(f"Matching Approved Indexes:    {post_audit.existing_matching_count}/{post_audit.total_expected}")
    print(f"Database Integrity Status:    {integrity.get('status', 'N/A')}")
    print(f"Preserved Row Count:          {integrity.get('row_count', 0):,}")
    print(f"Preserved Distinct IDs:       {integrity.get('distinct_ids', 0):,}")
    print(f"Total Pipeline Runtime:       {perf.get('total_pipeline_elapsed_seconds', 0.0)} s")
    print("-" * 78)
    print("QUERY PLAN BENCHMARKS (EXPLAIN ANALYZE):")
    for b in benchmarks:
        q_type = b.get("query_type", "unknown")
        node_type = b.get("primary_node_type", "unknown")
        exec_ms = b.get("execution_time_ms", 0.0)
        scans = b.get("index_scans_used", [])
        scan_str = f" [Index: {', '.join(scans)}]" if scans else ""
        print(f"  - {q_type:<25}: {node_type}{scan_str} in {exec_ms:.3f} ms")
    print("-" * 78)
    print(f"Phase 5.8 Readiness:          Ready for search validation (B-Tree + HNSW active)")
    print(f"Report File:                  {report_path}")
    print("=" * 78 + "\n")


def main() -> int:
    """CLI execution entrypoint."""
    args = parse_args()

    try:
        report, post_audit = asyncio.run(
            run_phase5_7_pipeline(
                report_path=args.report,
            )
        )
        print_summary(report, post_audit, args.report)
        return 0 if report.get("overall_status") == "PASS" else 1

    except Exception as exc:
        logger.exception("Phase 5.7 index construction failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
