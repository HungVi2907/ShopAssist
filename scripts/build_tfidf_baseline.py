"""Phase 6 executable CLI script: Build and Validate TF-IDF Baseline Retrieval Engine.

Usage:
    python scripts/build_tfidf_baseline.py
    python scripts/build_tfidf_baseline.py --parquet data/processed/products.parquet --artifacts data/processed/tfidf/
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shopassist.retrieval.tfidf import (
    CANONICAL_PRODUCTS_PATH,
    DEFAULT_TFIDF_ARTIFACT_DIR,
    DEFAULT_TFIDF_REPORT_PATH,
    TFIDFConfig,
    build_tfidf_baseline,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_tfidf_baseline")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Phase 6 — Build and Validate TF-IDF Baseline Product Retrieval Engine."
    )
    parser.add_argument(
        "--parquet",
        type=Path,
        default=CANONICAL_PRODUCTS_PATH,
        help=f"Path to canonical processed Parquet dataset (default: {CANONICAL_PRODUCTS_PATH})",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=DEFAULT_TFIDF_ARTIFACT_DIR,
        help=f"Target directory for saved TF-IDF artifacts (default: {DEFAULT_TFIDF_ARTIFACT_DIR})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_TFIDF_REPORT_PATH,
        help=f"Output path for JSON execution report (default: {DEFAULT_TFIDF_REPORT_PATH})",
    )
    parser.add_argument(
        "--ngram-max",
        type=int,
        default=2,
        help="Maximum n-gram size for vectorizer (default: 2 for unigrams+bigrams)",
    )
    parser.add_argument(
        "--min-df",
        type=int,
        default=2,
        help="Minimum document frequency threshold (default: 2)",
    )
    parser.add_argument(
        "--max-df",
        type=float,
        default=0.8,
        help="Maximum document frequency threshold (default: 0.8)",
    )
    return parser.parse_args()


def print_summary(report: dict, artifact_dir: Path, report_path: Path) -> None:
    """Pretty print terminal summary report."""
    src = report.get("source_dataset", {})
    stats = report.get("corpus_statistics", {})
    bench = report.get("latency_benchmarks", {})
    pers = report.get("artifact_persistence", {})
    perf = report.get("performance", {})
    scenarios = report.get("retrieval_scenarios", [])

    print("\n" + "=" * 80)
    print("PHASE 6 — TF-IDF BASELINE RETRIEVAL ENGINE BUILD SUMMARY")
    print("=" * 80)
    print(f"Overall Status:               {report.get('overall_status', 'FAIL')}")
    print(f"Execution Timestamp:          {report.get('execution_timestamp', 'N/A')}")
    print(f"Source Dataset:               {src.get('path', 'N/A')}")
    print(f"Total Products Loaded:        {src.get('total_products', 0):,}")
    print(f"Dataset Categories:           {src.get('categories_count', 0)}")
    print(f"Dataset Loading Time:         {src.get('load_time_seconds', 0.0):.3f} s")
    print("-" * 80)
    print("TF-IDF CORPUS & SPARSE MATRIX STATISTICS:")
    print(f"  - Vocabulary Features:       {stats.get('vocabulary_size', 0):,} terms")
    print(f"  - Sparse Matrix Shape:       {stats.get('matrix_shape', [])}")
    print(f"  - Non-Zero Elements (nnz):   {stats.get('nonzero_elements', 0):,}")
    print(f"  - Matrix Sparsity:           {stats.get('sparsity_pct', 0.0):.4f}%")
    print(f"  - Sparse Matrix RAM Size:    ~{stats.get('memory_mb_approx', 0.0):.2f} MB")
    print(f"  - Vectorizer Fit Time:       {stats.get('fit_time_seconds', 0.0):.3f} s")
    print("-" * 80)
    print("ARTIFACT PERSISTENCE & REPRODUCIBILITY:")
    print(f"  - Target Directory:          {pers.get('directory', 'N/A')}")
    print(f"  - Reload Verified (100%):    {pers.get('reload_verified', False)}")
    print(f"  - Artifact Reload Time:      {pers.get('reload_time_seconds', 0.0):.4f} s")
    print("-" * 80)
    print("QUERY LATENCY BENCHMARKS (measured across repeated runs):")
    print(f"  - Total Measured Queries:    {bench.get('total_measured_calls', 0)}")
    print(f"  - Median Latency (P50):      {bench.get('p50_latency_ms', 0.0):.3f} ms")
    print(f"  - 95th Percentile (P95):     {bench.get('p95_latency_ms', 0.0):.3f} ms")
    print(f"  - Mean Latency:              {bench.get('mean_latency_ms', 0.0):.3f} ms")
    print(f"  - Min / Max Latency:         {bench.get('min_latency_ms', 0.0):.3f} ms / {bench.get('max_latency_ms', 0.0):.3f} ms")
    print("-" * 80)
    print("SAMPLE RETRIEVAL EXPERIMENTS (Top-1 Match):")
    for sc in scenarios:
        s_id = sc.get("scenario_id", "")
        q = sc.get("query", "")
        cands = sc.get("candidates", [])
        top_name = cands[0]["product_name"][:45] if cands else "[NO MATCH - EMPTY/OOV]"
        top_score = cands[0]["tfidf_score"] if cands else 0.0
        print(f"  - {s_id:<28}: '{q}' -> score={top_score:.4f} | {top_name}")
    print("-" * 80)
    print(f"Total Pipeline Runtime:       {perf.get('total_pipeline_seconds', 0.0):.2f} s")
    print(f"Phase 7 Readiness:            Baseline 1 ready for dense semantic search comparison")
    print(f"Report File:                  {report_path}")
    print("=" * 80 + "\n")


def main() -> int:
    """CLI execution entrypoint."""
    args = parse_args()
    config = TFIDFConfig(
        ngram_range=(1, args.ngram_max),
        min_df=args.min_df,
        max_df=args.max_df,
    )

    try:
        _, report = build_tfidf_baseline(
            parquet_path=args.parquet,
            artifact_dir=args.artifacts,
            report_path=args.report,
            config=config,
        )
    except Exception as exc:
        logger.error("Phase 6 build failed with exception: %s", exc, exc_info=True)
        return 1

    print_summary(report, args.artifacts, args.report)

    if report.get("overall_status") == "PASS":
        logger.info("Phase 6 TF-IDF baseline build COMPLETED WITH STATUS: PASS")
        return 0
    else:
        logger.error("Phase 6 TF-IDF baseline build FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
