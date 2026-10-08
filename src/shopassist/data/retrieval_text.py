"""Retrieval text construction and validation module for ShopAssist (Phase 5.2).

Constructs the canonical `retrieval_text` field for each product to support:
- TF-IDF baseline keyword indexing
- Dense embedding generation (BAAI/bge-small-en-v1.5)
- Semantic vector search (pgvector)
- Cross-Encoder reranking
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_MAX_DESCRIPTION_CHARS: int = 1200

NA_PLACEHOLDERS: frozenset[str] = frozenset(
    {"na", "n/a", "none", "null", "nan", "nil", "undefined", ""}
)

# Regex pattern to catch faulty placeholder emissions such as 'Brand: None', 'Description: null'
FORBIDDEN_PLACEHOLDER_REGEX: re.Pattern = re.compile(
    r"\b(Product|Category|Brand|Specifications|Description):\s*(none|nan|null|na|n/a)\b",
    re.IGNORECASE,
)


def clean_whitespace(text: str | None) -> str:
    """Normalize whitespace by collapsing multiple spaces, tabs, and newlines into a single space.

    Args:
        text: Input string or None.

    Returns:
        Stripped string with normalized single whitespace, or empty string if None.
    """
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def is_placeholder(val: str | None) -> bool:
    """Check if a string represents an empty or meaningless placeholder value.

    Matches (case-insensitive): 'na', 'n/a', 'none', 'null', 'nan', 'nil', 'undefined', ''.

    Args:
        val: Input string or None.

    Returns:
        True if the value is empty or a placeholder, False otherwise.
    """
    if val is None:
        return True
    cleaned = clean_whitespace(str(val)).lower()
    return cleaned in NA_PLACEHOLDERS


def format_specifications(specifications: Any) -> str:
    """Flatten structured product specifications into a clean key-value text string.

    Specifications are represented as:
    ``Key1: Value1; Key2: Value2; Key3: Value3``

    Requirements:
    - Preserves semantic content.
    - Trims whitespace from keys and values.
    - Excludes items with empty or placeholder keys/values (NA, N/A, None, null, etc.).
    - Never uses eval(); safely parses JSON strings.
    - Robust against malformed inputs (non-dict items, non-list containers).
    - Returns empty string if no valid specifications remain.

    Args:
        specifications: JSON string, list of dicts, list of objects with key/value, or None.

    Returns:
        Flattened specifications string, or empty string if absent or empty.
    """
    if specifications is None or (isinstance(specifications, float) and pd.isna(specifications)):
        return ""

    items: Any = specifications
    if isinstance(specifications, str):
        raw_str = specifications.strip()
        if not raw_str or raw_str in ("[]", "null", "None", "{}"):
            return ""
        try:
            items = json.loads(raw_str)
        except Exception:
            logger.debug("Failed to parse specifications as JSON: %s", raw_str[:50])
            return ""

    if not isinstance(items, list):
        return ""

    valid_pairs: list[str] = []
    for item in items:
        k: Any = None
        v: Any = None

        if isinstance(item, dict):
            k = item.get("key")
            v = item.get("value")
        elif hasattr(item, "key") and hasattr(item, "value"):
            k = getattr(item, "key")
            v = getattr(item, "value")
        else:
            continue

        if k is None or v is None:
            continue

        k_clean = clean_whitespace(str(k))
        v_clean = clean_whitespace(str(v))

        if not k_clean or not v_clean:
            continue

        if is_placeholder(k_clean) or is_placeholder(v_clean):
            continue

        valid_pairs.append(f"{k_clean}: {v_clean}")

    return "; ".join(valid_pairs)


def truncate_description(
    text: str | None,
    max_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS,
) -> str:
    """Clean whitespace and truncate description safely at a word boundary.

    Requirements:
    - Normalizes internal whitespace.
    - Returns empty string if null, empty, or placeholder.
    - Truncates to at most max_chars.
    - Does not cut mid-word: seeks the nearest preceding space within the character limit.
    - If no space exists within max_chars (single unbroken token), cleanly cuts at max_chars.

    Args:
        text: Raw product description string or None.
        max_chars: Maximum allowed character length (default: 1200).

    Returns:
        Cleaned and safely truncated description string, or empty string.
    """
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""

    cleaned = clean_whitespace(str(text))
    if not cleaned or is_placeholder(cleaned):
        return ""

    if len(cleaned) <= max_chars:
        return cleaned

    # If the character immediately after max_chars is whitespace, max_chars is a clean cut
    if cleaned[max_chars] == " ":
        return cleaned[:max_chars].rstrip()

    # Look for the last space within the candidate slice
    candidate = cleaned[:max_chars]
    last_space = candidate.rfind(" ")
    if last_space > 0:
        return candidate[:last_space].rstrip()

    # Fallback for an unbroken token
    return candidate.rstrip()


def _extract_field(product: Any, field_name: str) -> Any:
    """Extract a field from a dict, pandas Series, or object."""
    if isinstance(product, dict):
        return product.get(field_name)
    if hasattr(product, field_name):
        return getattr(product, field_name)
    if hasattr(product, "__getitem__"):
        try:
            return product[field_name]
        except (KeyError, IndexError, TypeError):
            pass
    return None


def build_retrieval_text(
    product: Any,
    max_desc_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS,
) -> str:
    """Build standardized composite retrieval_text for a single product.

    Standard Structure & Mandatory Ordering:
    1. Product: <product_name>
    2. Category: <category>
    3. Brand: <brand>                  (omitted if missing/null/placeholder)
    4. Specifications: <specs>          (omitted if empty/placeholder)
    5. Description: <description>      (omitted if missing/null/placeholder, truncated to ~1200 chars)

    Elements are delimited by " | ".
    Hard numerical constraints (discounted_price, retail_price, rating) are NEVER included.

    Args:
        product: Dict, pandas Series, or object containing product attributes.
        max_desc_chars: Maximum character length for description truncation (default: 1200).

    Returns:
        Deterministic composite retrieval text string.

    Raises:
        ValueError: If required fields (product_name, category) are missing, empty, or placeholders.
    """
    raw_name = _extract_field(product, "product_name")
    raw_cat = _extract_field(product, "category")
    raw_brand = _extract_field(product, "brand")
    raw_specs = _extract_field(product, "product_specifications")
    raw_desc = _extract_field(product, "description")

    name = clean_whitespace(str(raw_name)) if raw_name is not None and not pd.isna(raw_name) else ""
    cat = clean_whitespace(str(raw_cat)) if raw_cat is not None and not pd.isna(raw_cat) else ""

    if not name or is_placeholder(name):
        raise ValueError("Field 'product_name' is required and cannot be empty or a placeholder.")
    if not cat or is_placeholder(cat):
        raise ValueError("Field 'category' is required and cannot be empty or a placeholder.")

    parts: list[str] = [
        f"Product: {name}",
        f"Category: {cat}",
    ]

    # Optional Brand
    if raw_brand is not None and not pd.isna(raw_brand):
        brand_clean = clean_whitespace(str(raw_brand))
        if brand_clean and not is_placeholder(brand_clean):
            parts.append(f"Brand: {brand_clean}")

    # Optional Specifications
    formatted_specs = format_specifications(raw_specs)
    if formatted_specs:
        parts.append(f"Specifications: {formatted_specs}")

    # Optional Description
    truncated_desc = truncate_description(raw_desc, max_chars=max_desc_chars)
    if truncated_desc:
        parts.append(f"Description: {truncated_desc}")

    return " | ".join(parts)


def validate_retrieval_text(text: str) -> tuple[bool, str | None]:
    """Validate a constructed retrieval_text against Phase 5.2 quality requirements.

    Requirements:
    - Non-null and non-empty.
    - Not whitespace-only.
    - Must start with 'Product: '.
    - Must contain ' | Category: '.
    - Must not contain obvious faulty placeholders (e.g., 'Brand: None', 'Description: null').

    Args:
        text: Constructed retrieval_text string.

    Returns:
        Tuple of (is_valid, error_reason). error_reason is None if valid.
    """
    if text is None:
        return False, "retrieval_text is None"

    if not isinstance(text, str):
        return False, f"retrieval_text must be str, got {type(text).__name__}"

    stripped = text.strip()
    if not stripped:
        return False, "retrieval_text is empty or whitespace-only"

    if not stripped.startswith("Product: "):
        return False, "retrieval_text does not start with 'Product: '"

    if " | Category: " not in stripped:
        return False, "retrieval_text missing ' | Category: '"

    match = FORBIDDEN_PLACEHOLDER_REGEX.search(stripped)
    if match:
        return False, f"Contains forbidden placeholder: '{match.group(0)}'"

    return True, None


def build_dataset_retrieval_texts(
    df: pd.DataFrame,
    max_desc_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS,
) -> pd.DataFrame:
    """Build retrieval_text column for an entire candidate DataFrame.

    Args:
        df: Input DataFrame containing cleaned candidate records.
        max_desc_chars: Maximum character limit for description truncation.

    Returns:
        Copy of DataFrame with new 'retrieval_text' column.

    Raises:
        ValueError: If required columns are missing from the input DataFrame.
    """
    required_cols = {"product_id", "product_name", "category"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Input DataFrame is missing required columns: {sorted(missing)}")

    result_df = df.copy()
    texts: list[str] = []
    for _, row in result_df.iterrows():
        texts.append(build_retrieval_text(row, max_desc_chars=max_desc_chars))

    result_df["retrieval_text"] = texts
    return result_df


def audit_retrieval_text_dataset(
    df: pd.DataFrame,
    max_desc_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS,
) -> dict[str, Any]:
    """Perform a comprehensive quality audit of retrieval_text across a dataset.

    Args:
        df: DataFrame containing 'retrieval_text' and source fields.
        max_desc_chars: Maximum character limit used for description truncation.

    Returns:
        Dictionary of audit metrics.
    """
    total_rows = len(df)
    if "retrieval_text" not in df.columns:
        raise ValueError("DataFrame must contain 'retrieval_text' column for auditing.")

    valid_rows = 0
    invalid_rows = 0
    invalid_reasons: list[str] = []

    lengths: list[int] = []
    for idx, text in enumerate(df["retrieval_text"]):
        is_val, reason = validate_retrieval_text(text)
        if is_val:
            valid_rows += 1
            lengths.append(len(text))
        else:
            invalid_rows += 1
            if len(invalid_reasons) < 10:
                invalid_reasons.append(f"Row {idx}: {reason}")

    lengths_series = pd.Series(lengths) if lengths else pd.Series([0])

    # Metadata & component stats
    missing_brand_count = (
        int((df["brand"].isna() | df["brand"].astype(str).str.strip().str.lower().isin(NA_PLACEHOLDERS)).sum())
        if "brand" in df.columns
        else 0
    )

    missing_desc_count = (
        int((df["description"].isna() | df["description"].astype(str).str.strip().str.lower().isin(NA_PLACEHOLDERS)).sum())
        if "description" in df.columns
        else 0
    )

    # Count how many descriptions were truncated
    truncated_count = 0
    if "description" in df.columns:
        for d in df["description"]:
            cleaned_d = clean_whitespace(str(d)) if pd.notna(d) else ""
            if len(cleaned_d) > max_desc_chars:
                truncated_count += 1

    # Empty specs count
    empty_specs_count = 0
    if "product_specifications" in df.columns:
        for s in df["product_specifications"]:
            formatted = format_specifications(s)
            if not formatted:
                empty_specs_count += 1

    report: dict[str, Any] = {
        "input_rows": total_rows,
        "output_rows": total_rows,
        "valid_retrieval_text_rows": valid_rows,
        "invalid_retrieval_text_rows": invalid_rows,
        "min_length": int(lengths_series.min()),
        "max_length": int(lengths_series.max()),
        "mean_length": round(float(lengths_series.mean()), 2),
        "median_length": float(lengths_series.median()),
        "percentile_90": float(lengths_series.quantile(0.90)),
        "percentile_95": float(lengths_series.quantile(0.95)),
        "percentile_99": float(lengths_series.quantile(0.99)),
        "description_truncated_count": truncated_count,
        "missing_brand_count": missing_brand_count,
        "missing_description_count": missing_desc_count,
        "empty_specs_count": empty_specs_count,
        "status": "PASS" if invalid_rows == 0 and valid_rows == total_rows else "FAIL",
    }

    if invalid_reasons:
        report["sample_invalid_reasons"] = invalid_reasons

    return report
