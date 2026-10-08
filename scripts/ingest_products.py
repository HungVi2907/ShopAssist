"""Phase 5.6 executable CLI script: Database Loading / Ingestion.

Loads all 8,405 processed products from data/processed/products.parquet
into the Supabase PostgreSQL table public.products.

Usage:
    python scripts/ingest_products.py
    python scripts/ingest_products.py --batch-size 250
    python scripts/ingest_products.py --input data/processed/products.parquet
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
from shopassist.db.ingestion import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_REPORT_PATH,
    DEFAULT_SOURCE_PARQUET_PATH,
    run_phase5_6_pipeline,
)

ensure_windows_event_loop_policy()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_products")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Phase 5.6 — Database Loading / Ingestion into Supabase PostgreSQL public.products."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_SOURCE_PARQUET_PATH,
        help=f"Path to input Parquet artifact (default: {DEFAULT_SOURCE_PARQUET_PATH})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"Path to output execution report JSON (default: {DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Batch size for parameterized insert (default: {DEFAULT_BATCH_SIZE})",
    )
    return parser.parse_args()


def print_summary(report: dict, post_metrics: Any, report_path: Path) -> None:
    """Pretty print terminal summary report."""
    pre_audit = report.get("pre_ingestion_audit", {})
    ingest_exec = report.get("ingestion_execution", {})
    target_db = report.get("target_database", {})
    perf = report.get("pipeline_performance", {})

    print("\n" + "=" * 78)
    print("PHASE 5.6 — DATABASE LOADING / INGESTION EXECUTION SUMMARY")
    print("=" * 78)
    print(f"Overall Status:               {report.get('overall_status', 'FAIL')}")
    print(f"Target Database:              {target_db.get('masked_url', 'N/A')}")
    print(f"Target Table:                 {target_db.get('table', 'public.products')}")
    print(f"Source Parquet Artifact:      {report['source_parquet']['path']}")
    print(f"Source Product Count:         {report['source_parquet']['rows']:,}")
    print(f"Pre-Ingestion DB State:       {pre_audit.get('state', 'N/A')}")
    print(f"Pre-Ingestion Row Count:      {pre_audit.get('current_row_count', 0):,}")
    print(f"Ingestion Status:             {ingest_exec.get('status', 'N/A')}")
    print(f"Products Inserted:            {ingest_exec.get('inserted_records', 0):,}")
    print(f"Post-Ingestion Row Count:     {post_metrics.total_rows:,}")
    print(f"Distinct Product IDs:         {post_metrics.distinct_product_ids:,}")
    print(f"Batch Size:                   {ingest_exec.get('batch_size', 'N/A')}")
    print(f"Total Batches:                {ingest_exec.get('num_batches', 'N/A')}")
    print(f"Ingestion Elapsed Time:       {ingest_exec.get('elapsed_seconds', 0.0)} s")
    print(f"Ingestion Throughput:         {ingest_exec.get('throughput_rows_per_sec', 0.0)} rows/sec")
    print(f"Transaction Status:           {ingest_exec.get('transaction_status', 'N/A')}")
    print(f"Null Mandatory Fields:        {post_metrics.null_mandatory_fields_count}")
    print(f"Invalid Vector Dims:          {post_metrics.invalid_vector_dims_count}")
    print(f"Invalid Specs JSON Arrays:    {post_metrics.invalid_specs_json_count}")
    print(f"Null Timestamp Records:       {post_metrics.null_timestamps_count}")
    print(f"Content Spot Check Matches:   {post_metrics.sample_spot_check_matched}/{post_metrics.sample_spot_check_count}")
    print(f"Vector Smoke Test Passed:     {post_metrics.vector_smoke_test_passed}")
    print(f"Vector Self-Cosine Distance:  {post_metrics.vector_smoke_test_distance:.8f}")
    print(f"Total Pipeline Runtime:       {perf.get('total_pipeline_elapsed_seconds', 0.0)} s")
    print(f"Phase 5.7 Index Readiness:    Ready (5 deferred indexes pending)")
    print(f"Report File:                  {report_path}")
    print("=" * 78 + "\n")


def main() -> int:
    """CLI execution entrypoint."""
    args = parse_args()

    try:
        report, post_metrics = asyncio.run(
            run_phase5_6_pipeline(
                source_parquet_path=args.input,
                report_path=args.report,
                batch_size=args.batch_size,
            )
        )
        print_summary(report, post_metrics, args.report)
        return 0 if report.get("overall_status") == "PASS" else 1

    except Exception as exc:
        logger.exception("Phase 5.6 pipeline execution failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
