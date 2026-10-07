"""CLI script to inspect the raw Flipkart Products 20K dataset.

Usage:
    python scripts/inspect_dataset.py
    python scripts/inspect_dataset.py --path data/raw/flipkart_products.csv
"""

import argparse
import sys
from pathlib import Path

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shopassist.core.config import FLIPKART_RAW_DATASET_PATH, PROPOSAL_CANDIDATE_FIELDS
from shopassist.data.loader import load_raw_dataset
from shopassist.data.validation import inspect_raw_schema, validate_raw_file


def format_field_status(found: bool) -> str:
    return "FOUND" if found else "NOT FOUND"


def run_inspection(dataset_path: Path) -> int:
    print("=" * 60)
    print("        Flipkart Dataset Inspection (Phase 1)")
    print("=" * 60)
    print(f"Path: {dataset_path}")

    # Step 1: Validate file existence and readability
    try:
        validated_path = validate_raw_file(dataset_path)
        file_size_mb = validated_path.stat().st_size / (1024 * 1024)
        print(f"File Size: {file_size_mb:.2f} MB")
        print("File Status: VALID & READABLE")
    except Exception as e:
        print(f"File Status: ERROR ({e})")
        return 1

    # Step 2: Load raw CSV
    try:
        df = load_raw_dataset(validated_path)
    except Exception as e:
        print(f"Load Error: Failed to parse CSV: {e}")
        return 1

    # Step 3: Inspect raw schema
    schema = inspect_raw_schema(df, PROPOSAL_CANDIDATE_FIELDS)

    print("\n--- Dataset Summary ---")
    print(f"Rows: {schema['row_count']}")
    print(f"Columns: {schema['column_count']}")

    dup_cols = schema["duplicate_columns"]
    if dup_cols:
        print(f"WARNING: Duplicate columns detected: {dup_cols}")
    else:
        print("Duplicate Columns: None")

    print("\n--- Actual Columns & Inferred Data Types ---")
    col_width = max(len(c) for c in schema["columns"]) + 2
    for col in schema["columns"]:
        dtype = schema["dtypes"][col]
        print(f"  {col.ljust(col_width)}: {dtype}")

    print("\n--- Candidate Field Availability (from proposal.md) ---")
    field_width = max(len(f) for f in PROPOSAL_CANDIDATE_FIELDS) + 2
    for field in PROPOSAL_CANDIDATE_FIELDS:
        status = format_field_status(schema["candidate_status"].get(field, False))
        print(f"  {field.ljust(field_width)}: {status}")

    print("\n--- Sample Values (Row 1) ---")
    first_row = df.iloc[0]
    for col in schema["columns"]:
        val = str(first_row[col])
        if len(val) > 80:
            val = val[:77] + "..."
        print(f"  {col.ljust(col_width)}: {val}")

    print("\n" + "=" * 60)
    print("Inspection completed successfully. Raw dataset is immutable.")
    print("=" * 60)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect raw Flipkart dataset")
    parser.add_argument(
        "--path",
        type=Path,
        default=FLIPKART_RAW_DATASET_PATH,
        help="Path to flipkart_products.csv",
    )
    args = parser.parse_args()
    sys.exit(run_inspection(args.path))


if __name__ == "__main__":
    main()
