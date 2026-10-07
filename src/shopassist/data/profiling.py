"""Comprehensive Dataset Profiling and EDA module for ShopAssist.

This module is strictly read-only and analytical:
    OBSERVE, MEASURE, ANALYZE, REPORT.
No cleaning, row dropping, or raw data transformations are performed.
"""

import math
import re
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from shopassist.data.category_parser import (
    get_category_depth,
    parse_category_tree,
)
from shopassist.data.validation import check_duplicate_columns

# Semantic missing value tokens
SEMANTIC_MISSING_TOKENS = {
    "no rating available",
    "none",
    "null",
    "n/a",
    "na",
    "-",
    "--",
    "nan",
}


def _safe_float(val: Any) -> Optional[float]:
    """Convert value to float safely or return None."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def profile_dataset_overview(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute overall dataset statistics and per-column summaries."""
    total_rows = len(df)
    total_cols = len(df.columns)
    mem_usage_mb = float(df.memory_usage(deep=True).sum() / (1024 * 1024))
    duplicate_cols = check_duplicate_columns(df)

    columns_summary = {}
    for col in df.columns:
        series = df[col]
        non_null = int(series.notnull().sum())
        null_count = int(series.isnull().sum())
        null_pct = float(round((null_count / total_rows) * 100, 2)) if total_rows > 0 else 0.0

        # Unique count (excluding NaNs)
        n_unique = int(series.nunique(dropna=True))
        unique_pct = float(round((n_unique / total_rows) * 100, 2)) if total_rows > 0 else 0.0

        # Sample values (up to 3 non-null unique string representations)
        samples = []
        for val in series.dropna().unique()[:3]:
            s_val = str(val)
            if len(s_val) > 60:
                s_val = s_val[:57] + "..."
            samples.append(s_val)

        columns_summary[col] = {
            "dtype": str(series.dtype),
            "non_null_count": non_null,
            "null_count": null_count,
            "null_percentage": null_pct,
            "unique_count": n_unique,
            "unique_percentage": unique_pct,
            "sample_values": samples,
        }

    return {
        "total_rows": total_rows,
        "total_columns": total_cols,
        "memory_usage_mb": round(mem_usage_mb, 2),
        "duplicate_column_names": duplicate_cols,
        "columns": columns_summary,
    }


def profile_missing_values(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze missing values: NaN, empty strings, whitespace, semantic missing."""
    total_rows = len(df)
    report = {}

    for col in df.columns:
        series = df[col]
        actual_null = int(series.isnull().sum())

        empty_str = 0
        whitespace_only = 0
        semantic_missing = 0

        # Check string representations for non-null items
        for val in series.dropna():
            if isinstance(val, str):
                trimmed = val.strip()
                if len(val) == 0:
                    empty_str += 1
                elif len(trimmed) == 0:
                    whitespace_only += 1
                elif trimmed.lower() in SEMANTIC_MISSING_TOKENS:
                    semantic_missing += 1

        effective_missing = actual_null + empty_str + whitespace_only + semantic_missing
        effective_pct = float(round((effective_missing / total_rows) * 100, 2)) if total_rows > 0 else 0.0

        report[col] = {
            "actual_null_count": actual_null,
            "actual_null_percentage": float(round((actual_null / total_rows) * 100, 2)),
            "empty_string_count": empty_str,
            "whitespace_only_count": whitespace_only,
            "semantic_missing_count": semantic_missing,
            "effective_missing_count": effective_missing,
            "effective_missing_percentage": effective_pct,
        }

    return report


def profile_identifiers(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze quality and mapping consistency of uniq_id and pid."""
    total_rows = len(df)

    uniq_id_series = df["uniq_id"] if "uniq_id" in df.columns else pd.Series([], dtype=object)
    pid_series = df["pid"] if "pid" in df.columns else pd.Series([], dtype=object)

    uniq_total = len(uniq_id_series)
    uniq_unique = int(uniq_id_series.nunique(dropna=True))
    uniq_nulls = int(uniq_id_series.isnull().sum())
    uniq_dup_count = total_rows - uniq_unique

    pid_total = len(pid_series)
    pid_unique = int(pid_series.nunique(dropna=True))
    pid_nulls = int(pid_series.isnull().sum())
    pid_dup_count = total_rows - pid_unique

    # Cross mapping analysis
    one_uniq_multiple_pid = 0
    one_pid_multiple_uniq = 0
    conflicting_pid_samples = []

    if "uniq_id" in df.columns and "pid" in df.columns:
        mapping_df = df[["uniq_id", "pid"]].dropna()

        # Check if one uniq_id maps to multiple pids
        uniq_to_pids = mapping_df.groupby("uniq_id")["pid"].nunique()
        one_uniq_multiple_pid = int((uniq_to_pids > 1).sum())

        # Check if one pid maps to multiple uniq_ids
        pid_to_uniqs = mapping_df.groupby("pid")["uniq_id"].nunique()
        one_pid_multiple_uniq = int((pid_to_uniqs > 1).sum())

        if one_pid_multiple_uniq > 0:
            dup_pids = pid_to_uniqs[pid_to_uniqs > 1].index.tolist()[:3]
            for p in dup_pids:
                mapped_u = mapping_df[mapping_df["pid"] == p]["uniq_id"].tolist()
                conflicting_pid_samples.append({"pid": p, "mapped_uniq_ids": mapped_u})

    return {
        "uniq_id": {
            "total_count": uniq_total,
            "unique_count": uniq_unique,
            "null_count": uniq_nulls,
            "duplicate_count": uniq_dup_count,
            "duplicate_percentage": float(round((uniq_dup_count / total_rows) * 100, 2)) if total_rows > 0 else 0.0,
            "is_unique_primary_key_candidate": bool(uniq_unique == total_rows and uniq_nulls == 0),
        },
        "pid": {
            "total_count": pid_total,
            "unique_count": pid_unique,
            "null_count": pid_nulls,
            "duplicate_count": pid_dup_count,
            "duplicate_percentage": float(round((pid_dup_count / total_rows) * 100, 2)) if total_rows > 0 else 0.0,
            "is_unique_primary_key_candidate": bool(pid_unique == total_rows and pid_nulls == 0),
        },
        "mapping_consistency": {
            "one_uniq_to_multiple_pid_count": one_uniq_multiple_pid,
            "one_pid_to_multiple_uniq_count": one_pid_multiple_uniq,
            "conflicting_pid_samples": conflicting_pid_samples,
        },
    }


def profile_duplicates(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze exact duplicate rows, duplicate keys, and potential duplicate product items."""
    total_rows = len(df)
    exact_duplicates = int(df.duplicated().sum())

    uniq_duplicates = total_rows - int(df["uniq_id"].nunique()) if "uniq_id" in df.columns else 0
    pid_duplicates = total_rows - int(df["pid"].nunique()) if "pid" in df.columns else 0
    name_duplicates = total_rows - int(df["product_name"].nunique()) if "product_name" in df.columns else 0

    # Potential duplicates: same normalized product_name + brand + discounted_price
    potential_duplicate_count = 0
    if {"product_name", "brand", "discounted_price"}.issubset(df.columns):
        norm_name = df["product_name"].fillna("").astype(str).str.strip().str.lower()
        norm_brand = df["brand"].fillna("").astype(str).str.strip().str.lower()
        price_str = df["discounted_price"].fillna(-1).astype(str)

        combined_hash = norm_name + "||" + norm_brand + "||" + price_str
        potential_duplicate_count = int(combined_hash.duplicated().sum())

    return {
        "exact_duplicate_rows": exact_duplicates,
        "duplicate_uniq_id": uniq_duplicates,
        "duplicate_pid": pid_duplicates,
        "duplicate_product_name": name_duplicates,
        "potential_duplicate_products": potential_duplicate_count,
    }


def profile_prices(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze retail_price and discounted_price distributions and anomalies."""
    report = {}

    for col in ["retail_price", "discounted_price"]:
        if col not in df.columns:
            continue

        series = pd.to_numeric(df[col], errors="coerce")
        valid_series = series.dropna()

        count = len(valid_series)
        missing = len(series) - count
        missing_pct = float(round((missing / len(df)) * 100, 2)) if len(df) > 0 else 0.0

        if count > 0:
            stats = {
                "count": count,
                "missing_count": missing,
                "missing_percentage": missing_pct,
                "min": float(valid_series.min()),
                "max": float(valid_series.max()),
                "mean": float(round(valid_series.mean(), 2)),
                "median": float(round(valid_series.median(), 2)),
                "std": float(round(valid_series.std(), 2)) if count > 1 else 0.0,
                "P1": float(round(np.percentile(valid_series, 1), 2)),
                "P5": float(round(np.percentile(valid_series, 5), 2)),
                "P25": float(round(np.percentile(valid_series, 25), 2)),
                "P50": float(round(np.percentile(valid_series, 50), 2)),
                "P75": float(round(np.percentile(valid_series, 75), 2)),
                "P95": float(round(np.percentile(valid_series, 95), 2)),
                "P99": float(round(np.percentile(valid_series, 99), 2)),
            }
        else:
            stats = {"count": 0, "missing_count": missing, "missing_percentage": missing_pct}

        report[col] = stats

    # Anomaly checks between retail and discounted
    if "retail_price" in df.columns and "discounted_price" in df.columns:
        rp = pd.to_numeric(df["retail_price"], errors="coerce")
        dp = pd.to_numeric(df["discounted_price"], errors="coerce")

        discount_exceeds_retail = int(((dp > rp) & dp.notnull() & rp.notnull()).sum())
        zero_or_negative_rp = int((rp <= 0).sum())
        zero_or_negative_dp = int((dp <= 0).sum())
        both_missing = int((rp.isnull() & dp.isnull()).sum())
        rp_missing_dp_present = int((rp.isnull() & dp.notnull()).sum())
        dp_missing_rp_present = int((dp.isnull() & rp.notnull()).sum())

        # Discount amounts and percentages on valid pairs
        valid_pairs = (rp.notnull()) & (dp.notnull()) & (rp > 0)
        discount_amount = rp[valid_pairs] - dp[valid_pairs]
        discount_pct = (discount_amount / rp[valid_pairs]) * 100

        report["anomalies_and_comparisons"] = {
            "discount_exceeds_retail_count": discount_exceeds_retail,
            "zero_or_negative_retail_price": zero_or_negative_rp,
            "zero_or_negative_discounted_price": zero_or_negative_dp,
            "both_prices_missing_count": both_missing,
            "retail_missing_discount_present_count": rp_missing_dp_present,
            "discount_missing_retail_present_count": dp_missing_rp_present,
            "discount_amount_stats": {
                "mean": float(round(discount_amount.mean(), 2)) if len(discount_amount) > 0 else 0.0,
                "median": float(round(discount_amount.median(), 2)) if len(discount_amount) > 0 else 0.0,
                "max": float(round(discount_amount.max(), 2)) if len(discount_amount) > 0 else 0.0,
                "min": float(round(discount_amount.min(), 2)) if len(discount_amount) > 0 else 0.0,
            },
            "discount_percentage_stats": {
                "mean": float(round(discount_pct.mean(), 2)) if len(discount_pct) > 0 else 0.0,
                "median": float(round(discount_pct.median(), 2)) if len(discount_pct) > 0 else 0.0,
                "max": float(round(discount_pct.max(), 2)) if len(discount_pct) > 0 else 0.0,
                "min": float(round(discount_pct.min(), 2)) if len(discount_pct) > 0 else 0.0,
            },
        }

    return report


def profile_ratings(df: pd.DataFrame) -> Dict[str, Any]:
    """Profile product_rating and overall_rating format, numeric values, and relation."""
    report = {}
    total_rows = len(df)

    for col in ["product_rating", "overall_rating"]:
        if col not in df.columns:
            continue

        raw_series = df[col].astype(str)
        actual_nulls = int(df[col].isnull().sum())

        no_rating_avail = int((raw_series.str.strip().str.lower() == "no rating available").sum())

        # Attempt parsing to float
        numeric_series = pd.to_numeric(df[col], errors="coerce")
        numeric_valid = numeric_series.dropna()
        numeric_count = len(numeric_valid)
        invalid_format_count = total_rows - actual_nulls - no_rating_avail - numeric_count

        numeric_stats = {}
        if numeric_count > 0:
            numeric_stats = {
                "min": float(numeric_valid.min()),
                "max": float(numeric_valid.max()),
                "mean": float(round(numeric_valid.mean(), 2)),
                "median": float(round(numeric_valid.median(), 2)),
                "out_of_range_low": int((numeric_valid < 0).sum()),
                "out_of_range_high": int((numeric_valid > 5).sum()),
                "rating_distribution_rounded": {
                    f"{star}_star": int((numeric_valid.round() == star).sum())
                    for star in range(1, 6)
                },
            }

        report[col] = {
            "total_count": total_rows,
            "actual_null_count": actual_nulls,
            "no_rating_available_count": no_rating_avail,
            "numeric_rating_count": numeric_count,
            "numeric_rating_percentage": float(round((numeric_count / total_rows) * 100, 2)) if total_rows > 0 else 0.0,
            "invalid_format_count": invalid_format_count,
            "numeric_stats": numeric_stats,
        }

    # Relationship analysis between product_rating and overall_rating
    if "product_rating" in df.columns and "overall_rating" in df.columns:
        pr_str = df["product_rating"].fillna("NULL").astype(str).str.strip()
        or_str = df["overall_rating"].fillna("NULL").astype(str).str.strip()

        exact_match = int((pr_str == or_str).sum())
        mismatch = total_rows - exact_match

        pr_num = pd.to_numeric(df["product_rating"], errors="coerce")
        or_num = pd.to_numeric(df["overall_rating"], errors="coerce")

        both_numeric = int((pr_num.notnull() & or_num.notnull()).sum())
        only_pr_numeric = int((pr_num.notnull() & or_num.isnull()).sum())
        only_or_numeric = int((pr_num.isnull() & or_num.notnull()).sum())
        both_missing_numeric = int((pr_num.isnull() & or_num.isnull()).sum())

        report["relationship"] = {
            "exact_raw_string_match_count": exact_match,
            "raw_string_mismatch_count": mismatch,
            "both_have_numeric_rating": both_numeric,
            "only_product_rating_numeric": only_pr_numeric,
            "only_overall_rating_numeric": only_or_numeric,
            "both_lack_numeric_rating": both_missing_numeric,
        }

    return report


def profile_brands(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze brand coverage, cardinality, whitespace, and case variations."""
    total_rows = len(df)
    if "brand" not in df.columns:
        return {}

    series = df["brand"]
    null_count = int(series.isnull().sum())
    valid_series = series.dropna()
    valid_count = len(valid_series)

    # Whitespace issues
    leading_trailing_ws = int((valid_series != valid_series.str.strip()).sum())

    # Case variations
    unique_raw = valid_series.unique()
    unique_lower = set(s.strip().lower() for s in unique_raw if s.strip())
    case_variation_count = len(unique_raw) - len(unique_lower)

    # Top brands
    top_brands = []
    brand_counts = valid_series.value_counts().head(20)
    for b_name, count in brand_counts.items():
        pct = float(round((count / total_rows) * 100, 2))
        top_brands.append({"brand": str(b_name), "count": int(count), "percentage": pct})

    return {
        "total_rows": total_rows,
        "missing_count": null_count,
        "missing_percentage": float(round((null_count / total_rows) * 100, 2)) if total_rows > 0 else 0.0,
        "unique_brand_count_raw": len(unique_raw),
        "unique_brand_count_normalized": len(unique_lower),
        "case_variation_redundancy": case_variation_count,
        "leading_trailing_whitespace_count": leading_trailing_ws,
        "top_20_brands": top_brands,
    }


def profile_descriptions(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze description length, word counts, HTML tag presence, and URLs."""
    total_rows = len(df)
    if "description" not in df.columns:
        return {}

    series = df["description"]
    null_count = int(series.isnull().sum())

    valid_descriptions = series.dropna().astype(str)
    empty_count = int((valid_descriptions.str.strip() == "").sum())

    char_lengths = valid_descriptions.str.len()
    word_counts = valid_descriptions.apply(lambda s: len(s.split()))

    # Short description thresholds
    short_under_20 = int((char_lengths < 20).sum())
    short_under_50 = int((char_lengths < 50).sum())
    short_under_100 = int((char_lengths < 100).sum())

    # HTML and URL patterns
    html_pattern = re.compile(r"<[a-zA-Z\/][^>]*>")
    url_pattern = re.compile(r"https?://")

    html_presence = int(valid_descriptions.apply(lambda s: bool(html_pattern.search(s))).sum())
    url_presence = int(valid_descriptions.apply(lambda s: bool(url_pattern.search(s))).sum())

    length_stats = {}
    word_stats = {}
    if len(char_lengths) > 0:
        length_stats = {
            "min": int(char_lengths.min()),
            "max": int(char_lengths.max()),
            "mean": float(round(char_lengths.mean(), 2)),
            "median": float(round(char_lengths.median(), 2)),
            "P25": float(round(np.percentile(char_lengths, 25), 2)),
            "P50": float(round(np.percentile(char_lengths, 50), 2)),
            "P75": float(round(np.percentile(char_lengths, 75), 2)),
            "P95": float(round(np.percentile(char_lengths, 95), 2)),
        }
        word_stats = {
            "min": int(word_counts.min()),
            "max": int(word_counts.max()),
            "mean": float(round(word_counts.mean(), 2)),
            "median": float(round(word_counts.median(), 2)),
            "P25": float(round(np.percentile(word_counts, 25), 2)),
            "P50": float(round(np.percentile(word_counts, 50), 2)),
            "P75": float(round(np.percentile(word_counts, 75), 2)),
            "P95": float(round(np.percentile(word_counts, 95), 2)),
        }

    return {
        "total_rows": total_rows,
        "missing_count": null_count,
        "missing_percentage": float(round((null_count / total_rows) * 100, 2)) if total_rows > 0 else 0.0,
        "empty_string_count": empty_count,
        "valid_text_count": len(valid_descriptions) - empty_count,
        "character_length_stats": length_stats,
        "word_count_stats": word_stats,
        "short_descriptions": {
            "under_20_chars": short_under_20,
            "under_50_chars": short_under_50,
            "under_100_chars": short_under_100,
        },
        "content_patterns": {
            "html_tags_present_count": html_presence,
            "url_present_count": url_presence,
        },
    }


def profile_specifications(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze product_specifications coverage, string length, and format structure."""
    total_rows = len(df)
    if "product_specifications" not in df.columns:
        return {}

    series = df["product_specifications"]
    null_count = int(series.isnull().sum())
    valid_series = series.dropna().astype(str)
    empty_count = int((valid_series.str.strip() == "").sum())

    char_lengths = valid_series.str.len()

    # Pattern check: Ruby-style hash arrows `=>` vs standard JSON `:`
    ruby_style_count = int(valid_series.str.contains(r"=>", regex=True).sum())
    json_style_count = int((valid_series.str.contains(r'":', regex=True) & ~valid_series.str.contains(r"=>", regex=True)).sum())

    # Sample extraction test to estimate parseable key-value pairs
    sample_size = min(500, len(valid_series))
    sample = valid_series.sample(n=sample_size, random_state=42) if len(valid_series) > 0 else []

    key_regex = re.compile(r'["\']key["\']\s*=>\s*["\']([^"\']+)["\']')
    parseable_records = 0
    extracted_keys_count = 0
    key_frequencies: Dict[str, int] = {}

    for text in sample:
        found_keys = key_regex.findall(text)
        if found_keys:
            parseable_records += 1
            extracted_keys_count += len(found_keys)
            for k in found_keys:
                clean_k = k.strip()
                key_frequencies[clean_k] = key_frequencies.get(clean_k, 0) + 1

    sample_parseable_rate = float(round((parseable_records / sample_size) * 100, 2)) if sample_size > 0 else 0.0

    top_keys = [
        {"key": k, "frequency_in_sample": v}
        for k, v in sorted(key_frequencies.items(), key=lambda x: x[1], reverse=True)[:15]
    ]

    length_stats = {}
    if len(char_lengths) > 0:
        length_stats = {
            "min": int(char_lengths.min()),
            "max": int(char_lengths.max()),
            "mean": float(round(char_lengths.mean(), 2)),
            "median": float(round(char_lengths.median(), 2)),
            "P25": float(round(np.percentile(char_lengths, 25), 2)),
            "P50": float(round(np.percentile(char_lengths, 50), 2)),
            "P75": float(round(np.percentile(char_lengths, 75), 2)),
            "P95": float(round(np.percentile(char_lengths, 95), 2)),
        }

    return {
        "total_rows": total_rows,
        "missing_count": null_count,
        "missing_percentage": float(round((null_count / total_rows) * 100, 2)) if total_rows > 0 else 0.0,
        "empty_string_count": empty_count,
        "character_length_stats": length_stats,
        "format_structure": {
            "ruby_arrow_syntax_count": ruby_style_count,
            "json_colon_syntax_count": json_style_count,
        },
        "sample_parsing_audit": {
            "sample_size": sample_size,
            "parseable_records_in_sample": parseable_records,
            "sample_parseable_rate_pct": sample_parseable_rate,
            "total_keys_extracted_in_sample": extracted_keys_count,
            "top_15_keys_in_sample": top_keys,
        },
    }


def profile_categories(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze category tree depths, distributions, and top Level 1 & 2 categories."""
    total_rows = len(df)
    if "product_category_tree" not in df.columns:
        return {}

    series = df["product_category_tree"]
    null_count = int(series.isnull().sum())

    depths = []
    level1_list = []
    level2_list = []
    full_paths = []
    malformed_count = 0

    for val in series:
        levels = parse_category_tree(val)
        depth = len(levels)
        depths.append(depth)

        if depth == 0:
            if pd.notnull(val) and str(val).strip():
                malformed_count += 1
            level1_list.append("UNKNOWN")
            level2_list.append("UNKNOWN")
            full_paths.append("UNKNOWN")
        else:
            level1_list.append(levels[0])
            level2_list.append(levels[1] if depth > 1 else "(single-level)")
            full_paths.append(" >> ".join(levels))

    s_depths = pd.Series(depths)
    s_l1 = pd.Series(level1_list)
    s_l2 = pd.Series(level2_list)
    s_paths = pd.Series(full_paths)

    depth_dist = {str(d): int((s_depths == d).sum()) for d in range(0, int(s_depths.max()) + 1)}

    top_l1 = []
    for cat, count in s_l1[s_l1 != "UNKNOWN"].value_counts().head(20).items():
        pct = float(round((count / total_rows) * 100, 2))
        top_l1.append({"category": cat, "count": int(count), "percentage": pct})

    top_l2 = []
    for cat, count in s_l2[s_l2 != "UNKNOWN"].value_counts().head(20).items():
        pct = float(round((count / total_rows) * 100, 2))
        top_l2.append({"category": cat, "count": int(count), "percentage": pct})

    top_paths = []
    for path, count in s_paths[s_paths != "UNKNOWN"].value_counts().head(15).items():
        pct = float(round((count / total_rows) * 100, 2))
        top_paths.append({"path": path, "count": int(count), "percentage": pct})

    return {
        "total_rows": total_rows,
        "missing_category_tree_count": null_count,
        "malformed_category_tree_count": malformed_count,
        "valid_category_tree_count": total_rows - null_count - malformed_count,
        "depth_statistics": {
            "min_depth": int(s_depths.min()),
            "max_depth": int(s_depths.max()),
            "mean_depth": float(round(s_depths.mean(), 2)),
            "median_depth": float(round(s_depths.median(), 2)),
            "depth_distribution": depth_dist,
        },
        "unique_level_1_count": int(s_l1[s_l1 != "UNKNOWN"].nunique()),
        "unique_level_2_count": int(s_l2[s_l2 != "UNKNOWN"].nunique()),
        "unique_full_paths_count": int(s_paths[s_paths != "UNKNOWN"].nunique()),
        "top_20_level_1_categories": top_l1,
        "top_20_level_2_categories": top_l2,
        "top_15_full_category_paths": top_paths,
    }


def profile_category_suitability(df: pd.DataFrame, min_products: int = 50) -> List[Dict[str, Any]]:
    """Build category quality and suitability metrics table for top-level categories.

    Used directly as quantitative evidence for Phase 3 Category Selection.
    """
    if "product_category_tree" not in df.columns:
        return []

    # Parse level 1 for each row
    level1_series = df["product_category_tree"].apply(lambda s: parse_category_tree(s)[0] if parse_category_tree(s) else "UNKNOWN")

    suitability_table = []
    total_dataset_rows = len(df)

    cat_counts = level1_series[level1_series != "UNKNOWN"].value_counts()
    eligible_categories = cat_counts[cat_counts >= min_products].index.tolist()

    for cat in eligible_categories:
        sub_df = df[level1_series == cat]
        cat_count = len(sub_df)
        cat_pct = float(round((cat_count / total_dataset_rows) * 100, 2))

        # Description coverage & median length
        desc_valid = sub_df["description"].dropna().astype(str).str.strip() if "description" in sub_df.columns else pd.Series([], dtype=str)
        desc_coverage = float(round((len(desc_valid[desc_valid != ""]) / cat_count) * 100, 2)) if cat_count > 0 else 0.0
        desc_med_len = float(desc_valid.str.len().median()) if len(desc_valid) > 0 else 0.0

        # Price coverage
        rp = pd.to_numeric(sub_df["retail_price"], errors="coerce") if "retail_price" in sub_df.columns else pd.Series([], dtype=float)
        dp = pd.to_numeric(sub_df["discounted_price"], errors="coerce") if "discounted_price" in sub_df.columns else pd.Series([], dtype=float)
        rp_cov = float(round((rp.notnull().sum() / cat_count) * 100, 2)) if cat_count > 0 else 0.0
        dp_cov = float(round((dp.notnull().sum() / cat_count) * 100, 2)) if cat_count > 0 else 0.0

        # Rating numeric coverage
        rating_num = pd.to_numeric(sub_df["product_rating"], errors="coerce") if "product_rating" in sub_df.columns else pd.Series([], dtype=float)
        rating_cov = float(round((rating_num.notnull().sum() / cat_count) * 100, 2)) if cat_count > 0 else 0.0

        # Brand coverage & unique brand count
        brand_valid = sub_df["brand"].dropna().astype(str).str.strip() if "brand" in sub_df.columns else pd.Series([], dtype=str)
        brand_cov = float(round((len(brand_valid[brand_valid != ""]) / cat_count) * 100, 2)) if cat_count > 0 else 0.0
        unique_brands = int(brand_valid.nunique())

        # Specifications coverage & median length
        spec_valid = sub_df["product_specifications"].dropna().astype(str).str.strip() if "product_specifications" in sub_df.columns else pd.Series([], dtype=str)
        spec_cov = float(round((len(spec_valid[spec_valid != ""]) / cat_count) * 100, 2)) if cat_count > 0 else 0.0
        spec_med_len = float(spec_valid.str.len().median()) if len(spec_valid) > 0 else 0.0

        suitability_table.append({
            "category": cat,
            "product_count": cat_count,
            "percentage_of_dataset": cat_pct,
            "description_coverage_pct": desc_coverage,
            "description_median_length": desc_med_len,
            "retail_price_coverage_pct": rp_cov,
            "discounted_price_coverage_pct": dp_cov,
            "rating_numeric_coverage_pct": rating_cov,
            "brand_coverage_pct": brand_cov,
            "unique_brand_count": unique_brands,
            "specification_coverage_pct": spec_cov,
            "specification_median_length": spec_med_len,
        })

    return suitability_table


def profile_retrieval_readiness(df: pd.DataFrame) -> Dict[str, Any]:
    """Measure the readiness of unstructured text fields for semantic search.

    Evaluates availability of product_name, description, and specifications without
    constructing the final retrieval_text.
    """
    total_rows = len(df)

    has_title = df["product_name"].notnull() & (df["product_name"].astype(str).str.strip() != "") if "product_name" in df.columns else pd.Series([False] * total_rows)
    has_desc = df["description"].notnull() & (df["description"].astype(str).str.strip() != "") if "description" in df.columns else pd.Series([False] * total_rows)
    has_specs = df["product_specifications"].notnull() & (df["product_specifications"].astype(str).str.strip() != "") if "product_specifications" in df.columns else pd.Series([False] * total_rows)

    title_count = int(has_title.sum())
    desc_count = int(has_desc.sum())
    specs_count = int(has_specs.sum())

    title_desc_count = int((has_title & has_desc).sum())
    all_three_count = int((has_title & has_desc & has_specs).sum())

    # Combined text length distribution (simulated length without modifying dataset)
    combined_lens = []
    for _, row in df.iterrows():
        t = str(row.get("product_name", "") or "").strip()
        d = str(row.get("description", "") or "").strip()
        s = str(row.get("product_specifications", "") or "").strip()
        combined_lens.append(len(t) + len(d) + len(s))

    s_comb = pd.Series(combined_lens)

    length_stats = {
        "min": int(s_comb.min()),
        "max": int(s_comb.max()),
        "mean": float(round(s_comb.mean(), 2)),
        "median": float(round(s_comb.median(), 2)),
        "P25": float(round(np.percentile(s_comb, 25), 2)),
        "P50": float(round(np.percentile(s_comb, 50), 2)),
        "P75": float(round(np.percentile(s_comb, 75), 2)),
        "P95": float(round(np.percentile(s_comb, 95), 2)),
    }

    return {
        "total_products": total_rows,
        "with_product_name_count": title_count,
        "with_product_name_pct": float(round((title_count / total_rows) * 100, 2)),
        "with_description_count": desc_count,
        "with_description_pct": float(round((desc_count / total_rows) * 100, 2)),
        "with_specifications_count": specs_count,
        "with_specifications_pct": float(round((specs_count / total_rows) * 100, 2)),
        "with_title_and_description_count": title_desc_count,
        "with_title_and_description_pct": float(round((title_desc_count / total_rows) * 100, 2)),
        "with_all_three_count": all_three_count,
        "with_all_three_pct": float(round((all_three_count / total_rows) * 100, 2)),
        "simulated_combined_text_length_stats": length_stats,
    }
