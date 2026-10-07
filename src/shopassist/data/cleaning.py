"""Data cleaning, normalization, specification parsing, and conservative deduplication for ShopAssist."""

from __future__ import annotations

import html
import json
import logging
import re
import unicodedata
from collections import Counter
from typing import Any, Iterable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Regex for stripping HTML tags
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Regex for control characters (exclude regular tab and newline for preliminary checks)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F-\x9F]")

# Regex to safely parse Ruby hash product_specifications:
# {"key"=>"...", "value"=>"..."} or {"key"=>"...", "value"=>nil} or numbers/booleans
_SPEC_KV_RE = re.compile(
    r'\{"key"=>"(?P<key>(?:\\.|[^"\\])*)",\s*"value"=>(?P<val>(?:"(?:\\.|[^"\\])*"|nil|\d+(?:\.\d+)?|true|false))\}'
)


def clean_text(text: Any) -> str | None:
    """Clean freeform text by decoding HTML, stripping tags, and normalizing whitespace.

    Preserves numbers, punctuation, casing, dimensions, and technical terms.
    """
    if text is None or pd.isna(text):
        return None

    s = str(text)
    if not s.strip():
        return None

    # Decode HTML entities (&amp;, &quot;, &#39;, etc.)
    s = html.unescape(s)

    # Remove residual HTML tags (<br>, <p>, etc.)
    s = _HTML_TAG_RE.sub(" ", s)

    # Normalize unicode to NFKC
    s = unicodedata.normalize("NFKC", s)

    # Remove invisible control characters
    s = _CONTROL_CHAR_RE.sub("", s)

    # Collapse multiple consecutive whitespace characters to a single space
    s = re.sub(r"\s+", " ", s).strip()

    # Treat string placeholders as None
    if s.lower() in {"none", "nan", "null", ""}:
        return None

    return s


def clean_price(price: Any) -> float | None:
    """Validate and convert price to float.

    Requires price to be numeric and strictly positive (> 0).
    """
    if price is None or pd.isna(price):
        return None

    try:
        val = float(price)
        if np.isnan(val) or np.isinf(val):
            return None
        if val <= 0:
            return None
        return round(val, 2)
    except (ValueError, TypeError):
        return None


def normalize_rating(product_rating: Any, overall_rating: Any = None) -> float | None:
    """Normalize rating from product_rating with fallback to overall_rating.

    Converts valid rating strings to float in range [1.0, 5.0].
    Maps 'No rating available', 'None', '', and invalid values to None.
    """
    for candidate in (product_rating, overall_rating):
        if candidate is None or pd.isna(candidate):
            continue

        s = str(candidate).strip()
        if not s or s.lower() in {"no rating available", "none", "nan", "null"}:
            continue

        try:
            val = float(s)
            if 1.0 <= val <= 5.0:
                return round(val, 2)
        except (ValueError, TypeError):
            continue

    return None


def build_brand_canonical_map(brands: Iterable[Any]) -> dict[str, str]:
    """Build a deterministic lowercase-to-canonical brand mapping from dataset frequency.

    Resolves casing inconsistencies (e.g., 'd-link' vs 'D-Link' vs 'D-LINK')
    by picking the most frequent valid casing, breaking ties by preferring
    mixed-case representation over all-caps or all-lower.
    """
    brand_counts: Counter[str] = Counter()
    for b in brands:
        if b is None or pd.isna(b):
            continue
        cleaned = " ".join(str(b).strip().split())
        if cleaned and cleaned.lower() not in {"none", "nan", "null"}:
            brand_counts[cleaned] += 1

    grouped_casings: dict[str, list[tuple[str, int]]] = {}
    for b, count in brand_counts.items():
        key = b.lower()
        if key not in grouped_casings:
            grouped_casings[key] = []
        grouped_casings[key].append((b, count))

    canonical_map: dict[str, str] = {}
    for key, items in grouped_casings.items():
        if len(items) == 1:
            canonical_map[key] = items[0][0]
        else:
            # Sort by frequency descending; prefer mixed-case if counts are tied
            def _score(item: tuple[str, int]) -> tuple[int, int]:
                name, cnt = item
                is_mixed = any(c.isupper() for c in name) and any(c.islower() for c in name)
                return (cnt, 1 if is_mixed else 0)

            sorted_items = sorted(items, key=_score, reverse=True)
            canonical_map[key] = sorted_items[0][0]

    return canonical_map


def normalize_brand(brand: Any, canonical_map: dict[str, str] | None = None) -> str | None:
    """Normalize brand string using whitespace collapsing, canonical casing, and null mapping."""
    if brand is None or pd.isna(brand):
        return None

    cleaned = " ".join(str(brand).strip().split())
    if not cleaned or cleaned.lower() in {"none", "nan", "null"}:
        return None

    if canonical_map:
        return canonical_map.get(cleaned.lower(), cleaned)

    return cleaned


def parse_specifications(specs_str: Any) -> list[dict[str, str | None]]:
    """Safely parse Flipkart Ruby hash product_specifications into a structured list of dicts.

    DOES NOT use eval() or execute arbitrary code. Uses regex tokenization.
    Returns: list of {"key": "...", "value": "..."}, or empty list if missing/nil.
    """
    if specs_str is None or pd.isna(specs_str):
        return []

    s = str(specs_str).strip()
    if not s or s in {'{"product_specification"=>nil}', '{"product_specification"=>""}'}:
        return []

    matches = _SPEC_KV_RE.findall(s)
    if not matches:
        return []

    parsed: list[dict[str, str | None]] = []
    for k, v in matches:
        # Unescape quotes
        k_clean = k.replace(r'\"', '"').replace(r"\'", "'").strip()

        if v.startswith('"') and v.endswith('"'):
            v_clean: str | None = v[1:-1].replace(r'\"', '"').replace(r"\'", "'").strip()
            # Normalize empty string
            if not v_clean:
                v_clean = None
        elif v == "nil":
            v_clean = None
        else:
            v_clean = v.strip()

        parsed.append({"key": k_clean, "value": v_clean})

    return parsed


def extract_specs_dict(specs_list: list[dict[str, Any]]) -> dict[str, str]:
    """Convert parsed specification list to a lowercase key-value dictionary for comparison."""
    res: dict[str, str] = {}
    for item in specs_list:
        k = str(item.get("key", "")).strip().lower()
        v = str(item.get("value", "")).strip().lower()
        if k and v and v not in {"none", "nan", "null", "nil"}:
            res[k] = v
    return res


def specs_conflict(s1: dict[str, str], s2: dict[str, str]) -> bool:
    """Check if two specification dictionaries conflict on any shared attribute.

    Returns True if there is at least one attribute present in both with different values
    (e.g., color: 'black' vs 'beige', size: '7' vs '8').
    Returns False if they are mutually consistent.
    """
    common_keys = set(s1.keys()).intersection(set(s2.keys()))
    for k in common_keys:
        if s1[k] != s2[k]:
            return True
    return False


def deduplicate_candidates(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Perform conservative deduplication on candidate products.

    Preserves meaningful variants (different colors, sizes, models, compatibility).
    Removes redundant duplicates within (name, brand, category, discounted_price) clusters
    when specifications do not conflict, retaining the most complete record.
    """
    n_input = len(df)

    # Prepare normalized comparison keys
    norm_name = df["product_name"].astype(str).str.lower().str.strip().str.replace(r"\s+", " ", regex=True)
    norm_brand = df["brand"].fillna("").astype(str).str.lower().str.strip().str.replace(r"\s+", " ", regex=True)
    norm_cat = df["category"].astype(str).str.strip()
    norm_price = df["discounted_price"].round(2)

    # Extracted specification dictionaries
    specs_dicts = [extract_specs_dict(s) for s in df["product_specifications_parsed"]]

    # Completeness scoring for tie-breaking: description length, specs attribute count
    desc_lens = df["description"].fillna("").astype(str).str.len().tolist()
    specs_lens = [len(d) for d in specs_dicts]

    temp_df = pd.DataFrame(
        {
            "orig_idx": df.index,
            "_n_name": norm_name,
            "_n_brand": norm_brand,
            "_n_cat": norm_cat,
            "_n_price": norm_price,
            "_desc_len": desc_lens,
            "_specs_len": specs_lens,
        }
    )

    grouped = temp_df.groupby(["_n_name", "_n_brand", "_n_cat", "_n_price"])

    kept_indices: list[int] = []
    dropped_indices: list[int] = []
    clusters_inspected = 0
    duplicate_clusters_count = 0
    variants_preserved_count = 0

    for _, group in grouped:
        clusters_inspected += 1
        if len(group) == 1:
            kept_indices.append(int(group["orig_idx"].iloc[0]))
        else:
            duplicate_clusters_count += 1
            # Sort by completeness descending: longest description, then longest specs
            sorted_group = group.sort_values(
                by=["_desc_len", "_specs_len"],
                ascending=[False, False],
            )

            retained: list[tuple[int, dict[str, str]]] = []
            for _, row in sorted_group.iterrows():
                row_orig_idx = int(row["orig_idx"])
                row_pos = df.index.get_loc(row_orig_idx)
                # handle slice or int loc
                loc_idx = row_pos if isinstance(row_pos, int) else int(np.where(df.index == row_orig_idx)[0][0])
                s = specs_dicts[loc_idx]

                is_dup = False
                for _, ret_s in retained:
                    if not specs_conflict(s, ret_s):
                        is_dup = True
                        break

                if is_dup:
                    dropped_indices.append(row_orig_idx)
                else:
                    retained.append((row_orig_idx, s))
                    kept_indices.append(row_orig_idx)

            if len(retained) > 1:
                variants_preserved_count += len(retained)

    df_deduped = df.loc[kept_indices].copy()

    metrics = {
        "input_rows": n_input,
        "kept_rows": len(df_deduped),
        "dropped_rows": len(dropped_indices),
        "dropped_percentage": round(len(dropped_indices) / n_input * 100, 2) if n_input > 0 else 0.0,
        "clusters_total": clusters_inspected,
        "duplicate_clusters": duplicate_clusters_count,
        "variants_preserved": variants_preserved_count,
    }

    return df_deduped, metrics


def clean_candidate_dataset(
    df: pd.DataFrame,
    selected_categories: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute end-to-end cleaning, normalization, validation, and deduplication pipeline."""
    initial_rows = len(df)
    initial_cols = len(df.columns)

    # 1. Lineage & Required Field Validation
    missing_id = int(df["uniq_id"].isna().sum()) if "uniq_id" in df.columns else initial_rows
    missing_name = int(df["product_name"].isna().sum()) if "product_name" in df.columns else initial_rows

    cat_col = "_level1_category" if "_level1_category" in df.columns else "category"
    missing_cat = int(df[cat_col].isna().sum()) if cat_col in df.columns else initial_rows

    # 2. Price Validation (operational price discounted_price > 0)
    cleaned_discounted = df["discounted_price"].apply(clean_price)
    cleaned_retail = df["retail_price"].apply(clean_price)
    invalid_price = int(cleaned_discounted.isna().sum())

    # Filter invalid records
    valid_mask = (
        df["uniq_id"].notna()
        & df["product_name"].notna()
        & df[cat_col].notna()
        & cleaned_discounted.notna()
    )

    df_valid = df[valid_mask].copy()
    df_valid["discounted_price"] = cleaned_discounted[valid_mask]
    df_valid["retail_price"] = cleaned_retail[valid_mask]

    # 3. Category Normalization
    df_valid["category"] = df_valid[cat_col].astype(str).str.strip()
    if selected_categories:
        invalid_cat_mask = ~df_valid["category"].isin(selected_categories)
        unexpected_categories = int(invalid_cat_mask.sum())
        if unexpected_categories > 0:
            df_valid = df_valid[~invalid_cat_mask]
    else:
        unexpected_categories = 0

    # 4. Brand Normalization
    raw_brands = df_valid["brand"].copy()
    canonical_map = build_brand_canonical_map(raw_brands)
    brand_casings_fixed = len([
        b
        for b in {" ".join(str(x).strip().split()) for x in raw_brands.dropna() if str(x).strip()}
        if b != canonical_map.get(b.lower(), b)
    ])
    df_valid["brand"] = df_valid["brand"].apply(lambda b: normalize_brand(b, canonical_map))

    # 5. Rating Normalization
    df_valid["rating"] = [
        normalize_rating(pr, ov)
        for pr, ov in zip(df_valid["product_rating"], df_valid["overall_rating"])
    ]

    # 6. Text Cleaning (product_name & description)
    df_valid["product_name"] = df_valid["product_name"].apply(clean_text)
    df_valid["description"] = df_valid["description"].apply(clean_text)

    # 7. Specifications Parsing
    parsed_specs = df_valid["product_specifications"].apply(parse_specifications)
    df_valid["product_specifications_parsed"] = parsed_specs
    # Store deterministic JSON string for downstream interoperability
    df_valid["product_specifications"] = parsed_specs.apply(lambda p: json.dumps(p, ensure_ascii=False))

    spec_success = int((parsed_specs.apply(len) > 0).sum())
    spec_empty = int((parsed_specs.apply(len) == 0).sum())

    # 8. Conservative Deduplication
    df_deduped, dedup_metrics = deduplicate_candidates(df_valid)

    # 9. Cleaned Logical Schema Assembly
    df_deduped["product_id"] = df_deduped["uniq_id"]

    core_columns = [
        "product_id",
        "product_name",
        "category",
        "brand",
        "retail_price",
        "discounted_price",
        "rating",
        "description",
        "product_specifications",
        "product_url",
    ]

    auxiliary_columns = [
        "uniq_id",
        "pid",
        "image",
        "crawl_timestamp",
        "is_FK_Advantage_product",
    ]

    # Preserve core + available auxiliary columns
    final_cols = [c for c in core_columns if c in df_deduped.columns] + [
        c for c in auxiliary_columns if c in df_deduped.columns
    ]

    df_final = df_deduped[final_cols].copy()

    # Compile comprehensive metrics report
    report = {
        "input": {
            "rows": initial_rows,
            "columns": initial_cols,
        },
        "removed": {
            "missing_id": missing_id,
            "missing_title": missing_name,
            "missing_category": missing_cat,
            "invalid_price": invalid_price,
            "unexpected_categories": unexpected_categories,
            "duplicates": dedup_metrics["dropped_rows"],
            "total_removed": initial_rows - len(df_final),
            "removed_percentage": round((initial_rows - len(df_final)) / initial_rows * 100, 2),
        },
        "normalization": {
            "brand_normalized": int(df_final["brand"].notna().sum()),
            "brand_missing": int(df_final["brand"].isna().sum()),
            "brand_canonical_casings_fixed": brand_casings_fixed,
            "rating_numeric": int(df_final["rating"].notna().sum()),
            "rating_missing": int(df_final["rating"].isna().sum()),
            "specification_parse_success": spec_success,
            "specification_empty_or_nil": spec_empty,
        },
        "deduplication": dedup_metrics,
        "output": {
            "rows": len(df_final),
            "columns": len(df_final.columns),
            "unique_product_id": int(df_final["product_id"].nunique()),
            "exact_duplicate_rows": int(df_final.duplicated().sum()),
        },
    }

    return df_final, report
