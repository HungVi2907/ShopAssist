"""Category Selection and candidate extraction module for ShopAssist (Phase 3).

Applies evidence-based multi-criteria evaluation to select product categories
that meet project requirements:
    1. Product volume & target size (5,000 - 15,000 products)
    2. High price & description coverage
    3. Rich specifications for soft-preference matching
    4. Category balance (no single category dominates >15-20%)
    5. Conversational recommendation suitability
"""

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import pandas as pd

from shopassist.data.category_parser import extract_category_level


# Definition of candidate category evaluation records
CATEGORY_EVALUATION_SPECS: Dict[str, Dict[str, Any]] = {
    "Clothing": {
        "status": "REJECT",
        "reason": "Dominance risk (6,198 items / 31% of total), high duplicate name rate (51.1%), and low brand coverage (50.9%). Would distort benchmark balance.",
        "conversational_suitability": "Medium (many generic clothing variants differ only by size/color without rich functional trade-offs).",
    },
    "Jewellery": {
        "status": "REJECT",
        "reason": "Dominance risk (3,531 items / 17.7%), high duplicate name rate (44.6%), and low conversational functional trade-off complexity (mostly generic imitation jewellery).",
        "conversational_suitability": "Low-to-Medium (limited preference dimensions beyond visual aesthetics).",
    },
    "Beauty and Personal Care": {
        "status": "REJECT",
        "reason": "Very low brand coverage (22.0%), high missing brand rate hinders structured filtering.",
        "conversational_suitability": "Medium.",
    },
    "Toys & School Supplies": {
        "status": "REJECT",
        "reason": "Low brand coverage (31.2%) and relatively low specification detail for conversational trade-offs.",
        "conversational_suitability": "Medium.",
    },
    "Footwear": {
        "status": "SELECT",
        "reason": "Substantial product count (1,227), 99.8% price coverage, 100% specs coverage, high conversational query diversity (running, casual, formal, comfort, material).",
        "conversational_suitability": "High (comfortable, durable, lightweight, formal vs casual wear).",
    },
    "Mobiles & Accessories": {
        "status": "SELECT",
        "reason": "1,099 products, 100% brand coverage, 99.8% price coverage, longest median description (639 chars), outstanding for compatibility and feature-based recommendation.",
        "conversational_suitability": "Very High (battery life, shockproof, slim, fast charging, compatibility).",
    },
    "Automotive": {
        "status": "SELECT",
        "reason": "1,012 products, 100% brand coverage, 99.8% price coverage, 100% specs coverage, exceptionally low duplicate name rate (2.6%).",
        "conversational_suitability": "High (car model compatibility, durability, sun protection, maintenance).",
    },
    "Home Decor & Festive Needs": {
        "status": "SELECT",
        "reason": "929 products, 92.9% brand coverage, 99.8% price coverage, 100% specs coverage, balanced consumer lifestyle category.",
        "conversational_suitability": "High (material, style, room fit, modern vs traditional aesthetics).",
    },
    "Home Furnishing": {
        "status": "SELECT",
        "reason": "700 products, 100% brand coverage, 100% price coverage, 100% specs coverage, rich textile/fabric specifications.",
        "conversational_suitability": "High (cotton, size dimensions, thread count, blackout, modern prints).",
    },
    "Kitchen & Dining": {
        "status": "SELECT",
        "reason": "647 products, 99.7% price coverage, 100% specs coverage, high median description length (482 chars), very low duplicate rate (3.2%).",
        "conversational_suitability": "Very High (capacity, easy to clean, non-stick, cookware, dining).",
    },
    "Computers": {
        "status": "SELECT",
        "reason": "578 products, 99.8% brand coverage, 99.1% price coverage, 100% specs coverage, highest rating coverage (30.4%), lowest duplicate rate (1.6%).",
        "conversational_suitability": "Outstanding (laptops, peripherals, office work, gaming, portability, specs).",
    },
    "Watches": {
        "status": "SELECT",
        "reason": "530 products, 99.6% price coverage, 100% specs coverage, 36.4% rating coverage, zero duplicate product names (100% unique items).",
        "conversational_suitability": "High (water resistance, strap material, analog vs digital, formal vs sports).",
    },
    "Baby Care": {
        "status": "SELECT",
        "reason": "483 products, 94.6% brand coverage, 99.6% price coverage, 100% specs coverage, strong use-case specific preferences.",
        "conversational_suitability": "High (safety, hypoallergenic, age group, lightweight, portable).",
    },
    "Tools & Hardware": {
        "status": "SELECT",
        "reason": "391 products, 100% brand coverage, 99.0% price coverage, 100% specs coverage, rich technical parameters.",
        "conversational_suitability": "High (DIY, cordless, durability, power, portability).",
    },
    "Pens & Stationery": {
        "status": "SELECT",
        "reason": "313 products, 100% price coverage, 100% specs coverage, good variety for students and office workers.",
        "conversational_suitability": "Medium-High (office work, student gifts, fountain pens, notebooks).",
    },
    "Bags, Wallets & Belts": {
        "status": "SELECT",
        "reason": "265 products, 99.6% price coverage, 100% specs coverage, high median description length (361 chars).",
        "conversational_suitability": "High (waterproof, laptop compartment, genuine leather, slim design).",
    },
    "Furniture": {
        "status": "SELECT",
        "reason": "180 products, 100% brand coverage, 100% price coverage, 100% specs coverage, distinct space-saving and ergonomic criteria.",
        "conversational_suitability": "High (compact, foldable, sofa bed, wooden finish, ergonomic).",
    },
    "Sports & Fitness": {
        "status": "SELECT",
        "reason": "166 products, 100% price coverage, 100% specs coverage, 65.1% brand coverage, low duplicate rate (2.4%).",
        "conversational_suitability": "High (home workout, durable, yoga, portable, fitness level).",
    },
    "Cameras & Accessories": {
        "status": "SELECT",
        "reason": "82 products, 100% brand coverage, 100% specs coverage, low duplicate rate (1.2%), technical gear.",
        "conversational_suitability": "High (beginner vs professional, compatibility, tripod, compact).",
    },
    "Home Improvement": {
        "status": "SELECT",
        "reason": "81 products, 100% brand coverage, 97.5% price coverage, 100% specs coverage, low duplicate rate (1.2%).",
        "conversational_suitability": "High (security, fixtures, installation, energy-efficient).",
    },
}


def get_selected_category_names() -> List[str]:
    """Return list of category names officially marked for selection."""
    return [
        cat
        for cat, spec in CATEGORY_EVALUATION_SPECS.items()
        if spec["status"] == "SELECT"
    ]


def evaluate_categories(df: pd.DataFrame) -> Dict[str, Any]:
    """Evaluate candidate Level 1 categories against quantitative metrics and qualitative suitability.

    Args:
        df: Raw DataFrame containing 'product_category_tree' and other metadata.

    Returns:
        Structured evaluation dictionary containing selected categories, rejected categories,
        comparison table, and summary statistics.
    """
    total_raw_rows = len(df)
    level1_series = df["product_category_tree"].apply(lambda s: extract_category_level(s, 1))

    selected_list = []
    rejected_list = []
    comparison_table = []
    total_selected_products = 0

    for cat_name, spec in CATEGORY_EVALUATION_SPECS.items():
        sub = df[level1_series == cat_name]
        count = len(sub)
        pct = float(round((count / total_raw_rows) * 100, 2)) if total_raw_rows > 0 else 0.0

        price_cov = float(round(sub["discounted_price"].notnull().mean() * 100, 1)) if count > 0 else 0.0
        brand_cov = float(round(sub["brand"].notnull().mean() * 100, 1)) if count > 0 else 0.0
        desc_cov = float(round(sub["description"].notnull().mean() * 100, 1)) if count > 0 else 0.0
        desc_med = float(sub["description"].dropna().astype(str).str.len().median()) if count > 0 else 0.0
        specs_cov = float(round((sub["product_specifications"].dropna().astype(str).str.strip() != "").mean() * 100, 1)) if count > 0 else 0.0
        rating_cov = float(round(pd.to_numeric(sub["product_rating"], errors="coerce").notnull().mean() * 100, 1)) if count > 0 else 0.0
        name_dup_rate = float(round((1 - sub["product_name"].nunique() / count) * 100, 1)) if count > 0 else 0.0

        record = {
            "category": cat_name,
            "product_count": count,
            "dataset_percentage": pct,
            "price_coverage_pct": price_cov,
            "brand_coverage_pct": brand_cov,
            "description_coverage_pct": desc_cov,
            "description_median_length": desc_med,
            "specification_coverage_pct": specs_cov,
            "rating_numeric_coverage_pct": rating_cov,
            "duplicate_name_rate_pct": name_dup_rate,
            "conversational_suitability": spec["conversational_suitability"],
            "selection_status": spec["status"],
            "selection_reason": spec["reason"],
        }
        comparison_table.append(record)

        if spec["status"] == "SELECT":
            selected_list.append(record)
            total_selected_products += count
        else:
            rejected_list.append(record)

    summary = {
        "total_raw_rows": total_raw_rows,
        "selected_category_count": len(selected_list),
        "rejected_category_count": len(rejected_list),
        "total_selected_products": total_selected_products,
        "selected_percentage_of_raw": float(round((total_selected_products / total_raw_rows) * 100, 2)),
        "target_range": "5,000 - 15,000",
        "target_range_met": bool(5000 <= total_selected_products <= 15000),
    }

    return {
        "selected_categories": selected_list,
        "rejected_categories": rejected_list,
        "comparison_table": comparison_table,
        "summary": summary,
    }


def extract_selected_candidates(
    df: pd.DataFrame, selected_categories: Set[str]
) -> pd.DataFrame:
    """Extract candidate product subset belonging to the selected Level 1 categories.

    Does NOT clean, drop rows, or alter raw column values.
    Appends a helper metadata column '_level1_category' for category tracking.

    Args:
        df: Raw DataFrame.
        selected_categories: Set of selected Level 1 category names.

    Returns:
        Filtered DataFrame containing only rows in selected categories, preserving raw values.
    """
    level1_series = df["product_category_tree"].apply(lambda s: extract_category_level(s, 1))
    mask = level1_series.isin(selected_categories)

    subset_df = df[mask].copy()
    subset_df["_level1_category"] = level1_series[mask]

    return subset_df
