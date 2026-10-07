"""Validate Phase 4 cleaned dataset against Phase 5 production schema specifications.

Generates data/interim/phase5_schema_readiness.json.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
from shopassist.data.schema import (
    save_schema_readiness_report,
    validate_cleaned_dataset_readiness,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("validate_schema_readiness")

CLEANED_CANDIDATES_PATH = Path("data/interim/cleaned_candidates.parquet")
SELECTED_CATEGORIES_PATH = Path("data/interim/selected_categories.json")
OUTPUT_REPORT_PATH = Path("data/interim/phase5_schema_readiness.json")


def main() -> int:
    """Run schema readiness check on cleaned dataset."""
    logger.info("Starting Phase 5.1 Schema Readiness Validation")

    if not CLEANED_CANDIDATES_PATH.exists():
        logger.error("Cleaned candidates parquet not found at %s", CLEANED_CANDIDATES_PATH)
        return 1

    df = pd.read_parquet(CLEANED_CANDIDATES_PATH)
    logger.info("Loaded cleaned dataset: %d rows, %d columns", len(df), len(df.columns))

    selected_cats = []
    if SELECTED_CATEGORIES_PATH.exists():
        with open(SELECTED_CATEGORIES_PATH, encoding="utf-8") as f:
            cat_data = json.load(f)
            if "selected_categories" in cat_data:
                selected_cats = [c["category"] if isinstance(c, dict) else str(c) for c in cat_data["selected_categories"]]
        logger.info("Loaded %d official selected categories", len(selected_cats))

    report = validate_cleaned_dataset_readiness(df, selected_categories=selected_cats)
    save_schema_readiness_report(report, OUTPUT_REPORT_PATH)

    logger.info("Schema Readiness Validation finished with status: %s", report["overall_status"])

    print("\n" + "=" * 60)
    print("PHASE 5.1 SCHEMA READINESS VALIDATION SUMMARY")
    print("=" * 60)
    print(f"Total Rows Checked:            {report['rows_checked']:,}")
    print(f"Product ID Unique:             {report['product_id_validation']['is_unique']}")
    print(f"Product ID Mismatches:         {report['product_id_validation']['id_mismatches']}")
    print(f"Valid Specifications Arrays:   {report['specification_validation']['valid_specs_arrays']:,}")
    print(f"Empty Specifications Arrays:   {report['specification_validation']['empty_specs_arrays']:,}")
    print(f"Invalid Specifications:        {report['specification_validation']['invalid_specs']}")
    print(f"Price Violations (<= 0 or NaN):{report['numeric_validation']['price_violations']}")
    print(f"Rating Violations (Out-of-range): {report['numeric_validation']['rating_violations']}")
    print(f"Overall Status:                {report['overall_status']}")
    print(f"Saved Report:                  {OUTPUT_REPORT_PATH}")
    print("=" * 60 + "\n")

    return 0 if report["overall_status"] == "READY_FOR_PHASE_5_2" else 1


if __name__ == "__main__":
    sys.exit(main())
