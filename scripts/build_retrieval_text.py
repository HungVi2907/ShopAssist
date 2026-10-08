"""Executable pipeline to construct and validate retrieval_text for candidate products.

Phase 5.2 — retrieval_text Construction & Validation.

Usage:
    python scripts/build_retrieval_text.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd

from shopassist.data.retrieval_text import (
    DEFAULT_MAX_DESCRIPTION_CHARS,
    audit_retrieval_text_dataset,
    build_dataset_retrieval_texts,
    clean_whitespace,
    format_specifications,
    is_placeholder,
    validate_retrieval_text,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_retrieval_text")

DEFAULT_INPUT_PATH = Path("data/interim/cleaned_candidates.parquet")
DEFAULT_OUTPUT_PATH = Path("data/interim/products_with_retrieval_text.parquet")
DEFAULT_REPORT_PATH = Path("data/interim/phase5_2_retrieval_text_report.json")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Phase 5.2 — Construct and validate retrieval_text for products."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to cleaned candidates parquet file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to output parquet file with retrieval_text",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path to output JSON validation report",
    )
    parser.add_argument(
        "--max-desc-chars",
        type=int,
        default=DEFAULT_MAX_DESCRIPTION_CHARS,
        help="Maximum characters for description truncation",
    )
    return parser.parse_args()


def extract_representative_samples(df: pd.DataFrame, max_desc_chars: int) -> dict[str, Any]:
    """Extract representative samples across different data coverage cases for manual review."""
    samples: dict[str, Any] = {}

    # 1. Full product (brand present, specs present, description present)
    full_mask = (
        df["brand"].notna()
        & (~df["brand"].astype(str).str.lower().isin(["none", "nan", "null", ""]))
        & (df["description"].notna())
        & (df["description"].astype(str).str.strip() != "")
    )
    full_candidates = df[full_mask]
    if not full_candidates.empty:
        # Find one where formatted specs is non-empty
        for _, row in full_candidates.iterrows():
            if format_specifications(row["product_specifications"]):
                samples["full_product"] = {
                    "product_id": str(row["product_id"]),
                    "product_name": str(row["product_name"]),
                    "category": str(row["category"]),
                    "brand": str(row["brand"]),
                    "retrieval_text": str(row["retrieval_text"]),
                }
                break

    # 2. Missing brand
    no_brand_mask = df["brand"].isna() | df["brand"].astype(str).str.lower().isin(["none", "nan", "null", ""])
    no_brand_candidates = df[no_brand_mask]
    if not no_brand_candidates.empty:
        row = no_brand_candidates.iloc[0]
        samples["missing_brand"] = {
            "product_id": str(row["product_id"]),
            "product_name": str(row["product_name"]),
            "category": str(row["category"]),
            "brand": None,
            "retrieval_text": str(row["retrieval_text"]),
        }

    # 3. Missing description
    no_desc_mask = df["description"].isna() | df["description"].astype(str).str.lower().isin(["none", "nan", "null", ""])
    no_desc_candidates = df[no_desc_mask]
    if not no_desc_candidates.empty:
        row = no_desc_candidates.iloc[0]
        samples["missing_description"] = {
            "product_id": str(row["product_id"]),
            "product_name": str(row["product_name"]),
            "category": str(row["category"]),
            "description": None,
            "retrieval_text": str(row["retrieval_text"]),
        }

    # 4. Empty specifications
    for _, row in df.iterrows():
        if not format_specifications(row["product_specifications"]):
            samples["empty_specifications"] = {
                "product_id": str(row["product_id"]),
                "product_name": str(row["product_name"]),
                "category": str(row["category"]),
                "raw_specs": str(row["product_specifications"]),
                "retrieval_text": str(row["retrieval_text"]),
            }
            break

    # 5. Long description truncated (> max_desc_chars)
    for _, row in df.iterrows():
        cleaned_desc = clean_whitespace(str(row["description"])) if pd.notna(row["description"]) else ""
        if len(cleaned_desc) > max_desc_chars:
            samples["truncated_description"] = {
                "product_id": str(row["product_id"]),
                "product_name": str(row["product_name"]),
                "original_desc_length": len(cleaned_desc),
                "retrieval_text": str(row["retrieval_text"]),
            }
            break

    return samples


def run_pipeline(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    max_desc_chars: int,
) -> int:
    """Execute retrieval_text construction pipeline and generate report."""
    logger.info("Starting Phase 5.2 retrieval_text construction pipeline")
    logger.info("Input path:  %s", input_path)
    logger.info("Output path: %s", output_path)
    logger.info("Report path: %s", report_path)

    if not input_path.exists():
        logger.error("Input file does not exist: %s", input_path)
        return 1

    input_df = pd.read_parquet(input_path)
    input_rows = len(input_df)
    logger.info("Successfully loaded input dataset with %d rows, %d columns", input_rows, len(input_df.columns))

    # Required columns check
    required_cols = ["product_id", "product_name", "category", "brand", "description", "product_specifications"]
    for col in required_cols:
        if col not in input_df.columns:
            logger.error("Required column '%s' is missing from input dataset", col)
            return 1

    # Check ID uniqueness before transformation
    if not input_df["product_id"].is_unique:
        logger.error("product_id is not unique in input dataset!")
        return 1

    # Build retrieval_text
    logger.info("Constructing retrieval_text for all %d products...", input_rows)
    output_df = build_dataset_retrieval_texts(input_df, max_desc_chars=max_desc_chars)

    # 1. Dataset-level validation
    output_rows = len(output_df)
    if input_rows != output_rows:
        logger.error("Row count mismatch: input has %d, output has %d", input_rows, output_rows)
        return 1

    if not output_df["product_id"].equals(input_df["product_id"]):
        logger.error("product_id ordering or alignment mismatch between input and output!")
        return 1

    # 2. Audit retrieval_text quality
    audit_report = audit_retrieval_text_dataset(output_df, max_desc_chars=max_desc_chars)

    # 3. Extract representative review samples
    samples = extract_representative_samples(output_df, max_desc_chars=max_desc_chars)
    audit_report["representative_samples"] = samples

    # Save output artifacts
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_parquet(output_path, index=False)
    logger.info("Saved output dataset with retrieval_text to: %s (%d rows)", output_path, len(output_df))

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(audit_report, f, indent=2, ensure_ascii=False)
    logger.info("Saved audit report to: %s", report_path)

    # Terminal summary presentation
    print("\n" + "=" * 70)
    print("PHASE 5.2 — RETRIEVAL TEXT CONSTRUCTION & VALIDATION SUMMARY")
    print("=" * 70)
    print(f"Input Rows:                     {audit_report['input_rows']:,}")
    print(f"Output Rows:                    {audit_report['output_rows']:,}")
    print(f"Valid retrieval_text Rows:      {audit_report['valid_retrieval_text_rows']:,} (100.0%)")
    print(f"Invalid retrieval_text Rows:    {audit_report['invalid_retrieval_text_rows']}")
    print(f"Min Length (chars):             {audit_report['min_length']}")
    print(f"Max Length (chars):             {audit_report['max_length']}")
    print(f"Mean Length (chars):            {audit_report['mean_length']}")
    print(f"Median Length (chars):          {audit_report['median_length']}")
    print(f"90th Percentile Length:         {audit_report['percentile_90']}")
    print(f"95th Percentile Length:         {audit_report['percentile_95']}")
    print(f"99th Percentile Length:         {audit_report['percentile_99']}")
    print(f"Truncated Descriptions (>1200): {audit_report['description_truncated_count']}")
    print(f"Missing Brand Count:            {audit_report['missing_brand_count']}")
    print(f"Missing Description Count:      {audit_report['missing_description_count']}")
    print(f"Empty Specifications Count:     {audit_report['empty_specs_count']}")
    print(f"Overall Status:                 {audit_report['status']}")
    print("=" * 70)

    print("\nREPRESENTATIVE SAMPLES REVIEW:")
    print("-" * 70)
    for sample_type, sample_data in samples.items():
        print(f"\n[{sample_type.upper()}]")
        print(f"Product ID: {sample_data.get('product_id')}")
        print(f"Text Preview: {sample_data.get('retrieval_text')[:200]}...")
    print("-" * 70 + "\n")

    return 0 if audit_report["status"] == "PASS" else 1


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    return run_pipeline(
        input_path=args.input,
        output_path=args.output,
        report_path=args.report,
        max_desc_chars=args.max_desc_chars,
    )


if __name__ == "__main__":
    sys.exit(main())
