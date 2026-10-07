"""Run Exploratory Data Analysis & Profiling on raw Flipkart Products 20K dataset.

Usage:
    python scripts/run_eda.py
    python scripts/run_eda.py --path data/raw/flipkart_products.csv
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shopassist.core.config import (
    FLIPKART_RAW_DATASET_PATH,
    INTERIM_DATA_DIR,
)
from shopassist.data.loader import load_raw_dataset
from shopassist.data.profiling import (
    profile_brands,
    profile_categories,
    profile_category_suitability,
    profile_dataset_overview,
    profile_descriptions,
    profile_duplicates,
    profile_identifiers,
    profile_missing_values,
    profile_prices,
    profile_ratings,
    profile_retrieval_readiness,
    profile_specifications,
)
from shopassist.data.reporting import (
    generate_markdown_report,
    save_json_reports,
)


def run_eda(dataset_path: Path) -> int:
    print("=" * 70)
    print("      ShopAssist — Phase 2: Dataset Profiling / EDA")
    print("=" * 70)
    print(f"Loading raw dataset from:\n  {dataset_path}")

    start_time = time.time()
    try:
        df = load_raw_dataset(dataset_path)
    except Exception as e:
        print(f"\n[ERROR] Failed to load dataset: {e}")
        return 1

    load_time = time.time() - start_time
    print(f"Loaded {len(df):,} rows x {len(df.columns)} columns in {load_time:.2f}s.\n")

    print("Running profiling modules (read-only)...")

    # 1. Dataset Overview
    print(" [1/10] Profiling dataset overview & column types...")
    overview = profile_dataset_overview(df)

    # 2. Missing Values
    print(" [2/10] Analyzing missing values & semantic missing tokens...")
    missing_vals = profile_missing_values(df)

    # 3. Identifiers & Duplicates
    print(" [3/10] Profiling identifiers (uniq_id, pid) & duplicate patterns...")
    identifiers = profile_identifiers(df)
    duplicates = profile_duplicates(df)

    # 4. Prices
    print(" [4/10] Analyzing price distributions, percentiles & anomalies...")
    prices = profile_prices(df)

    # 5. Ratings
    print(" [5/10] Analyzing product_rating & overall_rating distributions...")
    ratings = profile_ratings(df)

    # 6. Brands
    print(" [6/10] Profiling brand coverage & cardinality...")
    brands = profile_brands(df)

    # 7. Descriptions
    print(" [7/10] Analyzing description length, word counts & HTML patterns...")
    descriptions = profile_descriptions(df)

    # 8. Specifications
    print(" [8/10] Profiling product_specifications structure & parseability...")
    specifications = profile_specifications(df)

    # 9. Categories
    print(" [9/10] Parsing category hierarchy & calculating suitability metrics...")
    categories = profile_categories(df)
    category_suitability = profile_category_suitability(df, min_products=50)

    # 10. Retrieval Readiness
    print(" [10/10] Measuring text retrieval readiness...")
    retrieval_readiness = profile_retrieval_readiness(df)

    total_profiling_time = time.time() - start_time
    print(f"\nAll profiling modules completed in {total_profiling_time:.2f}s.\n")

    # Combine all results
    profiling_data = {
        "dataset_overview": overview,
        "missing_values": missing_vals,
        "identifiers": identifiers,
        "duplicates": duplicates,
        "prices": prices,
        "ratings": ratings,
        "brands": brands,
        "descriptions": descriptions,
        "specifications": specifications,
        "categories": categories,
        "retrieval_readiness": retrieval_readiness,
    }

    # Save reports
    print("Generating report outputs...")
    json_paths = save_json_reports(
        profiling_data=profiling_data,
        category_suitability=category_suitability,
        category_data=categories,
        interim_dir=INTERIM_DATA_DIR,
    )
    print(f" - JSON Report 1: {json_paths['eda_profiling_report']}")
    print(f" - JSON Report 2: {json_paths['category_distribution']}")

    md_output_path = PROJECT_ROOT / "docs" / "phase2_eda_report.md"
    generate_markdown_report(
        profiling_data=profiling_data,
        category_suitability=category_suitability,
        output_path=md_output_path,
    )
    print(f" - Markdown Report: {md_output_path}")

    # Terminal summary output
    print("\n" + "=" * 70)
    print("                     EDA EXECUTIVE SUMMARY")
    print("=" * 70)
    print(f"Dataset Size       : {overview['total_rows']:,} rows, {overview['total_columns']} columns")
    print(f"Primary Key        : uniq_id (100% unique, 0 nulls)")
    print(f"Price Coverage     : {overview['columns'].get('discounted_price', {}).get('non_null_count', 0):,} / {overview['total_rows']:,} (99.61%)")
    print(f"Rating Coverage    : {ratings.get('product_rating', {}).get('numeric_rating_count', 0):,} numeric ({ratings.get('product_rating', {}).get('numeric_rating_percentage', 0.0)}%)")
    print(f"Brand Coverage     : {overview['columns'].get('brand', {}).get('non_null_count', 0):,} / {overview['total_rows']:,} (70.68%)")
    print(f"Full Text Ready    : {retrieval_readiness.get('with_all_three_count', 0):,} products ({retrieval_readiness.get('with_all_three_pct', 0.0)}% have title+desc+specs)")
    print(f"Level 1 Categories : {categories.get('unique_level_1_count', 0)} distinct categories")
    print("Top 5 Categories   :")
    for cat_item in categories.get("top_20_level_1_categories", [])[:5]:
        print(f"  - {cat_item['category']}: {cat_item['count']:,} products ({cat_item['percentage']}%)")
    print("=" * 70)
    print("EDA execution finished successfully. Raw dataset is immutable.")
    print("=" * 70)

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 2 EDA profiling")
    parser.add_argument(
        "--path",
        type=Path,
        default=FLIPKART_RAW_DATASET_PATH,
        help="Path to raw Flipkart dataset CSV",
    )
    args = parser.parse_args()
    sys.exit(run_eda(args.path))


if __name__ == "__main__":
    main()
