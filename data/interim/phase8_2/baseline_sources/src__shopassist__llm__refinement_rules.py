"""Deterministic business rules, price operator semantics, and validation layer (Phase 8.1 - Experiment E4).

Provides pure Python deterministic post-processing rules to:
1. Enforce strict vs. inclusive price boundary operators (<, <=, >, >=).
2. Validate and correct in-query self-corrections.
3. Resolve brand/product ambiguities and suppress brands on unserviceable/out-of-domain queries (fixes P8-07).
4. Resolve negation conflicts and prevent negative phrases in positive soft preferences (fixes P8-03).
5. Clean product type noun phrases out of soft preferences (fixes P8-02).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from shopassist.llm.normalization import (
    CANONICAL_CATEGORIES_SET,
    normalize_brand,
    normalize_category,
    normalize_currency,
)
from shopassist.llm.schema_variants import (
    ExclusionConstraint,
    RefinedHardConstraints,
    RefinedQueryUnderstandingOutput,
)
from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput

logger = logging.getLogger(__name__)

# Out-of-catalog unserviceable terms that indicate non-e-commerce or unsupported queries
UNSUPPORTED_DOMAINS: tuple[str, ...] = (
    "airplane", "aircraft", "boeing", "airbus",
    "real estate", "house for sale", "apartment for rent", "condo",
    "fresh bananas", "banana", "fresh fruits", "vegetables", "supermarket",
    "grocery", "groceries", "milk", "bread",
    "pet food", "live puppy", "kitten",
    "car for sale", "truck for sale", "motorcycle for sale",
)

# Regex patterns for price boundary detection
STRICT_UPPER_REGEX = re.compile(
    r"\b(under|below|less\s+than|cheaper\s+than|strictly\s+under)\s+(?:rs\.?|inr|rupees|\$|usd|eur|€)?\s*(\d+(?:,\d+)*(?:\.\d+)?)",
    re.IGNORECASE,
)
INCLUSIVE_UPPER_REGEX = re.compile(
    r"\b(at\s+most|up\s+to|max|maximum|within|not\s+exceeding)\s+(?:rs\.?|inr|rupees|\$|usd|eur|€)?\s*(\d+(?:,\d+)*(?:\.\d+)?)",
    re.IGNORECASE,
)
STRICT_LOWER_REGEX = re.compile(
    r"\b(above|more\s+than|greater\s+than|higher\s+than|strictly\s+above)\s+(?:rs\.?|inr|rupees|\$|usd|eur|€)?\s*(\d+(?:,\d+)*(?:\.\d+)?)",
    re.IGNORECASE,
)
INCLUSIVE_LOWER_REGEX = re.compile(
    r"\b(at\s+least|min|minimum|starting\s+(?:from|at))\s+(?:rs\.?|inr|rupees|\$|usd|eur|€)?\s*(\d+(?:,\d+)*(?:\.\d+)?)",
    re.IGNORECASE,
)
IN_QUERY_CORRECTION_REGEX = re.compile(
    r"\b(?:actually|no\s+wait|make\s+it|scratch\s+that|i\s+mean)\b",
    re.IGNORECASE,
)


def detect_price_boundary_semantics(raw_query: str) -> dict[str, Any]:
    """Detect whether price boundaries in raw text are strict or inclusive.

    Returns:
        dict with 'min_inclusive': bool, 'max_inclusive': bool, 'detected_corrections': bool
    """
    res = {
        "min_inclusive": True,
        "max_inclusive": True,
        "detected_corrections": bool(IN_QUERY_CORRECTION_REGEX.search(raw_query)),
    }

    # Upper bound check
    if STRICT_UPPER_REGEX.search(raw_query):
        res["max_inclusive"] = False
    elif INCLUSIVE_UPPER_REGEX.search(raw_query):
        res["max_inclusive"] = True

    # Lower bound check
    if STRICT_LOWER_REGEX.search(raw_query):
        res["min_inclusive"] = False
    elif INCLUSIVE_LOWER_REGEX.search(raw_query):
        res["min_inclusive"] = True

    return res


def is_out_of_domain_query(raw_query: str) -> bool:
    """Check if query is for an unserviceable or out-of-catalog domain."""
    q_lower = raw_query.lower()
    return any(domain in q_lower for domain in UNSUPPORTED_DOMAINS)


def refine_hard_constraints_rules(
    hc: HardConstraints | RefinedHardConstraints,
    raw_query: str,
    catalog_brands: set[str] | None = None,
    is_clarification: bool = False,
) -> tuple[HardConstraints | RefinedHardConstraints, list[str]]:
    """Apply deterministic business rules to hard constraints."""
    warnings: list[str] = []

    # 1. Category validation
    raw_cat = hc.category
    norm_cat = normalize_category(raw_cat)
    if raw_cat and not norm_cat:
        warnings.append(f"Rejected non-canonical category '{raw_cat}'.")
    hc.category = norm_cat

    # 2. Out-of-domain check (Fix P8-07)
    # If the query is an out-of-domain query (e.g. commercial Boeing 747), brand should NOT be extracted as a catalog filter
    if is_out_of_domain_query(raw_query) or (is_clarification and hc.category is None):
        if hc.brand is not None:
            warnings.append(f"Suppressed brand '{hc.brand}' because query is out-of-domain or unserviceable.")
            hc.brand = None
    else:
        # Standard brand normalization
        hc.brand = normalize_brand(hc.brand, catalog_brands=catalog_brands)

    # 3. Currency normalization
    hc.currency = normalize_currency(hc.currency)

    # 4. Price range sanity
    if hc.min_price is not None and hc.max_price is not None:
        if hc.min_price > hc.max_price:
            warnings.append(f"min_price ({hc.min_price}) > max_price ({hc.max_price}); resetting min_price to None.")
            hc.min_price = None

    # 5. Price boundary strictness detection
    bounds = detect_price_boundary_semantics(raw_query)
    if hasattr(hc, "min_inclusive"):
        hc.min_inclusive = bounds["min_inclusive"]
    if hasattr(hc, "max_inclusive"):
        hc.max_inclusive = bounds["max_inclusive"]

    return hc, warnings


def extract_exclusions_from_text(raw_query: str) -> list[ExclusionConstraint]:
    """Deterministically extract explicit exclusions/negations from query text."""
    exclusions: list[ExclusionConstraint] = []
    # Pattern: 'not X', 'no X', 'without X', 'except X'
    negation_pattern = re.compile(
        r"\b(?:not|without|no|except)\s+([a-zA-Z0-9\s]{2,30}?)(?=[,.;]|\band\b|\bwith\b|\bunder\b|\bfor\b|$)",
        re.IGNORECASE,
    )
    for match in negation_pattern.finditer(raw_query):
        val = match.group(1).strip().lower()
        # Filter out common stop-words or false positives
        if val in ("only", "just", "a", "an", "the", "have", "need"):
            continue
        # Check target type
        target_type = "attribute"
        if "shoes" in val or "laptop" in val or "watch" in val or "phone" in val:
            target_type = "product_type"
        elif val in ("nike", "puma", "samsung", "apple", "dell", "sony", "casio"):
            target_type = "brand"
        exclusions.append(ExclusionConstraint(target_type=target_type, value=val))
    return exclusions


def resolve_negation_conflicts(
    soft_preferences: list[str],
    exclusions: list[ExclusionConstraint],
) -> tuple[list[str], list[ExclusionConstraint], list[str]]:
    """Detect and resolve conflicts between positive preferences and negative exclusions.

    1. Removes any negative expressions ('not running') from positive preferences.
    2. Removes positive preferences that contradict explicit exclusions.
    """
    clean_prefs: list[str] = []
    excl_values = {e.value.lower() for e in exclusions}
    warnings: list[str] = []

    for pref in soft_preferences:
        p_clean = pref.lower().strip()
        # Check if preference starts with negative prefix
        is_negative = False
        for prefix in ("not ", "no ", "without ", "except "):
            if p_clean.startswith(prefix):
                extracted_val = p_clean[len(prefix):].strip()
                if extracted_val and extracted_val not in excl_values:
                    exclusions.append(ExclusionConstraint(target_type="attribute", value=extracted_val))
                    excl_values.add(extracted_val)
                warnings.append(f"Moved negative preference '{pref}' into explicit exclusions.")
                is_negative = True
                break

        if is_negative:
            continue

        # Check if positive preference conflicts with an exclusion
        if p_clean in excl_values or any(p_clean in ev or ev in p_clean for ev in excl_values):
            warnings.append(f"Removed preference '{pref}' due to contradiction with exclusion.")
            continue

        clean_prefs.append(pref)

    return clean_prefs, exclusions, warnings


def clean_product_type_from_preferences(
    soft_preferences: list[str],
    product_type: str | None,
    semantic_query: str,
) -> tuple[list[str], list[str]]:
    """Remove product type noun phrases from soft preferences (Fix P8-02).

    Example:
    If product_type is 'running shoes', 'running' should not be in soft_preferences.
    """
    clean_prefs: list[str] = []
    warnings: list[str] = []

    # Known core product nouns / types
    disallowed_nouns = {
        "shoes", "running", "running shoes", "sneakers", "boots", "sandals",
        "watch", "smartwatch", "digital watch", "analog watch",
        "laptop", "computer", "pc", "keyboard", "mouse", "monitor",
        "phone", "smartphone", "earbuds", "headphones", "tablet",
        "drill", "camera", "chair", "table", "pen", "pencils",
    }
    if product_type:
        pt_words = set(product_type.lower().split())
    else:
        pt_words = set()

    for p in soft_preferences:
        p_lower = p.lower().strip()
        # If preference exactly matches disallowed product noun or equals product_type
        if p_lower in disallowed_nouns or (product_type and p_lower == product_type.lower()):
            warnings.append(f"Filtered product noun '{p}' out of soft_preferences.")
            continue
        clean_prefs.append(p)

    return clean_prefs, warnings


def apply_rule_based_refinement_v1(
    output: QueryUnderstandingOutput,
    raw_query: str,
    catalog_brands: set[str] | None = None,
) -> tuple[QueryUnderstandingOutput, list[str]]:
    """Apply full rule-based post-processing on Schema v1.0.0 output."""
    all_warnings: list[str] = []

    # 1. Out-of-domain detection
    if is_out_of_domain_query(raw_query):
        output.needs_clarification = True
        output.hard_constraints.category = None
        output.hard_constraints.brand = None
        reason = "Out-of-domain request or unsupported product category."
        output.clarification_reason = reason
        all_warnings.append(reason)

    # 2. Hard constraints refinement
    refined_hc, hc_warn = refine_hard_constraints_rules(
        output.hard_constraints,
        raw_query=raw_query,
        catalog_brands=catalog_brands,
        is_clarification=output.needs_clarification,
    )
    output.hard_constraints = refined_hc  # type: ignore
    all_warnings.extend(hc_warn)

    # 3. Clean product nouns from soft preferences (Fix P8-02)
    clean_prefs, pt_warn = clean_product_type_from_preferences(
        output.soft_preferences,
        product_type=None,
        semantic_query=output.semantic_query,
    )
    output.soft_preferences = clean_prefs
    all_warnings.extend(pt_warn)

    return output, all_warnings


def apply_rule_based_refinement_v2(
    output: RefinedQueryUnderstandingOutput,
    raw_query: str,
    catalog_brands: set[str] | None = None,
) -> tuple[RefinedQueryUnderstandingOutput, list[str]]:
    """Apply full rule-based post-processing on Schema v2.0.0 output."""
    all_warnings: list[str] = []

    # 1. Out-of-domain detection (Fix P8-07 & P8-12)
    if is_out_of_domain_query(raw_query):
        output.needs_clarification = True
        output.hard_constraints.category = None
        output.hard_constraints.brand = None
        reason = "Out-of-domain request or unsupported product category."
        output.clarification_reason = reason
        all_warnings.append(reason)

    # 2. Hard constraints refinement with boundary operators (Fix P8-04)
    refined_hc, hc_warn = refine_hard_constraints_rules(
        output.hard_constraints,
        raw_query=raw_query,
        catalog_brands=catalog_brands,
        is_clarification=output.needs_clarification,
    )
    output.hard_constraints = refined_hc  # type: ignore
    all_warnings.extend(hc_warn)

    # 3. Deterministic exclusion extraction & negation resolution (Fix P8-03)
    text_excls = extract_exclusions_from_text(raw_query)
    combined_excls = list(output.exclusions)
    existing_vals = {e.value.lower() for e in combined_excls}
    for te in text_excls:
        if te.value.lower() not in existing_vals:
            combined_excls.append(te)
            existing_vals.add(te.value.lower())

    clean_prefs, final_excls, neg_warn = resolve_negation_conflicts(
        output.soft_preferences,
        combined_excls,
    )
    output.soft_preferences = clean_prefs
    output.exclusions = final_excls
    all_warnings.extend(neg_warn)

    # 4. Clean product nouns from soft preferences (Fix P8-02)
    clean_prefs, pt_warn = clean_product_type_from_preferences(
        output.soft_preferences,
        product_type=output.product_type,
        semantic_query=output.semantic_query,
    )
    output.soft_preferences = clean_prefs
    all_warnings.extend(pt_warn)

    return output, all_warnings
