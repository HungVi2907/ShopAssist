"""Phase 5.5 executable pipeline: Batch Embedding Generation & products.parquet Export.

Generates 384-dimensional dense vector embeddings for all 8,405 cleaned products
using BAAI/bge-small-en-v1.5 and exports the canonical Product Knowledge Base artifact:
    data/processed/products.parquet

Usage:
    python scripts/generate_product_embeddings.py
    python scripts/generate_product_embeddings.py --batch-size 64
    python scripts/generate_product_embeddings.py --device cuda
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

from shopassist.embeddings.batch import (
    EXPECTED_CATALOG_SIZE,
    run_phase5_5_pipeline,
)
from shopassist.embeddings.model import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_MODEL_NAME,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("generate_product_embeddings")

DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "interim" / "cleaned_candidates.parquet"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "products.parquet"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "interim" / "phase5_5_embedding_generation_report.json"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Phase 5.5 — Generate batch embeddings and export products.parquet."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Path to input candidate dataset (default: {DEFAULT_INPUT_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to canonical output Parquet artifact (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"Path to output execution report JSON (default: {DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=DEFAULT_MODEL_NAME,
        help=f"HuggingFace embedding model name (default: {DEFAULT_MODEL_NAME})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Inference mini-batch size (default: 32)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Compute device ('cuda', 'cpu', 'mps', or None for auto-detect)",
    )
    parser.add_argument(
        "--include-timestamps",
        action="store_true",
        default=False,
        help="Whether to include created_at/updated_at columns (default: False, allows PostgreSQL DEFAULT NOW())",
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        default=EXPECTED_CATALOG_SIZE,
        help=f"Expected product count (default: {EXPECTED_CATALOG_SIZE}, 0 to disable check)",
    )
    return parser.parse_args()


def main() -> int:
    """CLI execution entrypoint."""
    args = parse_args()
    expected_count = args.expected_count if args.expected_count > 0 else None

    exit_code, report = run_phase5_5_pipeline(
        input_path=args.input,
        output_path=args.output,
        report_path=args.report,
        model_name=args.model_name,
        batch_size=args.batch_size,
        device=args.device,
        include_timestamps=args.include_timestamps,
        expected_count=expected_count,
    )

    # Pretty print summary terminal report
    print("\n" + "=" * 76)
    print("PHASE 5.5 — BATCH EMBEDDING GENERATION & PRODUCTS.PARQUET EXPORT SUMMARY")
    print("=" * 76)
    print(f"Overall Status:            {report.get('overall_status', 'FAIL')}")
    print(f"Input Dataset:             {report['input_dataset']['path']}")
    print(f"Input Product Count:       {report['input_dataset']['rows']:,}")
    print(f"Output Dataset:            {report['output_dataset']['path']}")
    print(f"Output Product Count:      {report['output_dataset']['rows']:,}")
    print(f"Output Column Count:       {report['output_dataset']['column_count']}")
    print(f"Output File Size:          {report['output_dataset']['file_size_mb']} MB ({report['output_dataset']['file_size_bytes']:,} bytes)")
    print(f"Model Identifier:          {report['model_configuration']['model_name']}")
    print(f"Embedding Dimension:       {report['model_configuration']['embedding_dimension']}")
    print(f"Compute Device:            {report['model_configuration']['device']} ({report['model_configuration'].get('cuda_device_name') or 'N/A'})")
    print(f"Inference Batch Size:      {report['generation_performance']['batch_size']}")
    print(f"Total Batches Processed:   {report['generation_performance']['total_batches']}")
    print(f"Embedding Elapsed Time:    {report['generation_performance']['embedding_elapsed_seconds']} s")
    print(f"Processing Throughput:     {report['generation_performance']['throughput_texts_per_second']} texts/sec")
    print(f"Per-Item Latency:          {report['generation_performance']['milliseconds_per_text']} ms/text")
    print(f"Total Pipeline Runtime:    {report['total_pipeline_seconds']} s")
    print(f"Roundtrip Validation:      {report['output_dataset']['roundtrip_validation']}")
    print(f"Semantic Sanity Passed:    {report['semantic_sanity_checks']['passed']}/{report['semantic_sanity_checks']['total_scenarios']}")
    print(f"Timestamps Policy:         {report['timestamps_policy']['rationale']}")
    print(f"Report File:               {args.report}")
    print("=" * 76 + "\n")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
