"""Rigorous evaluation metrics calculator for Phase 8.1 experiments.

Provides:
- Independent precision, recall, and F1 calculation for hard constraints, soft preferences, and exclusions.
- Strict Complete-Output Exact Match (ALL fields must match simultaneously).
- Legacy Exact Match (Hard constraints + clarification, auditing the historical Phase 8 metric).
- Granular error attribution and false-positive / false-negative classification.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence
import numpy as np

logger = logging.getLogger(__name__)


def evaluate_refined_case(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate extraction accuracy of a single query result against ground truth expectations.

    Supports both Schema v1.0.0 and Refined Schema v2.0.0 formats.
    """
    # 1. Hard constraints extraction
    act_hc = actual.get("hard_constraints", {})
    exp_hc = expected.get("hard_constraints", {})

    exp_cat = exp_hc.get("category")
    exp_brand = exp_hc.get("brand")
    exp_min_price = exp_hc.get("min_price")
    exp_max_price = exp_hc.get("max_price")
    exp_rating = exp_hc.get("min_rating")
    exp_currency = exp_hc.get("currency", "INR")
    exp_clarif = expected.get("needs_clarification", False)

    act_cat = act_hc.get("category")
    act_brand = act_hc.get("brand")
    act_min_price = act_hc.get("min_price")
    act_max_price = act_hc.get("max_price")
    act_rating = act_hc.get("min_rating")
    act_currency = act_hc.get("currency", "INR")
    act_clarif = actual.get("needs_clarification", False)

    # Category matching
    cat_match = (act_cat == exp_cat) or (exp_cat is None and act_cat is None)

    # Brand matching
    brand_match = False
    if exp_brand is None:
        brand_match = act_brand is None
    elif act_brand is not None:
        brand_match = str(exp_brand).strip().lower() == str(act_brand).strip().lower()

    # Price bounds matching
    min_price_match = act_min_price == exp_min_price
    max_price_match = act_max_price == exp_max_price
    price_match = min_price_match and max_price_match

    # Boundary strictness matching (if present in expected)
    min_incl_match = True
    max_incl_match = True
    if "min_inclusive" in exp_hc and "min_inclusive" in act_hc:
        min_incl_match = act_hc.get("min_inclusive") == exp_hc.get("min_inclusive")
    if "max_inclusive" in exp_hc and "max_inclusive" in act_hc:
        max_incl_match = act_hc.get("max_inclusive") == exp_hc.get("max_inclusive")
    boundary_operator_match = min_incl_match and max_incl_match

    # Rating, currency, clarification
    rating_match = act_rating == exp_rating
    currency_match = (act_currency or "INR") == (exp_currency or "INR")
    clarif_match = act_clarif == exp_clarif

    # 2. Product type matching (if in expected)
    exp_pt = expected.get("product_type")
    act_pt = actual.get("product_type")
    pt_match = True
    if exp_pt is not None:
        pt_match = bool(act_pt and (str(exp_pt).strip().lower() == str(act_pt).strip().lower()))

    # 3. Soft preferences evaluation
    exp_soft = set(s.strip().lower() for s in expected.get("soft_preferences", []))
    act_soft = set(s.strip().lower() for s in actual.get("soft_preferences", []))

    if not exp_soft and not act_soft:
        soft_prec = 1.0
        soft_rec = 1.0
        soft_f1 = 1.0
    elif not exp_soft and act_soft:
        soft_prec = 0.0
        soft_rec = 1.0
        soft_f1 = 0.0
    elif exp_soft and not act_soft:
        soft_prec = 1.0
        soft_rec = 0.0
        soft_f1 = 0.0
    else:
        inter = len(exp_soft.intersection(act_soft))
        soft_prec = inter / float(len(act_soft))
        soft_rec = inter / float(len(exp_soft))
        soft_f1 = (2 * soft_prec * soft_rec) / (soft_prec + soft_rec) if (soft_prec + soft_rec) > 0 else 0.0

    soft_exact_match = (exp_soft == act_soft)

    # 4. Exclusions evaluation (if present in expected)
    exp_excl = set()
    for e in expected.get("exclusions", []):
        if isinstance(e, dict):
            exp_excl.add(f"{e.get('target_type', 'attribute')}:{e.get('value', '').lower()}")
        elif isinstance(e, str):
            exp_excl.add(f"attribute:{e.lower()}")

    act_excl = set()
    for e in actual.get("exclusions", []):
        if isinstance(e, dict):
            act_excl.add(f"{e.get('target_type', 'attribute')}:{e.get('value', '').lower()}")
        elif isinstance(e, str):
            act_excl.add(f"attribute:{e.lower()}")

    if not exp_excl and not act_excl:
        excl_f1 = 1.0
        excl_match = True
    elif not exp_excl or not act_excl:
        excl_f1 = 0.0
        excl_match = False
    else:
        e_inter = len(exp_excl.intersection(act_excl))
        e_prec = e_inter / float(len(act_excl))
        e_rec = e_inter / float(len(exp_excl))
        excl_f1 = (2 * e_prec * e_rec) / (e_prec + e_rec) if (e_prec + e_rec) > 0 else 0.0
        excl_match = (exp_excl == act_excl)

    # 5. Hard constraints field-level TP / FP / FN
    fields_checked = ["category", "brand", "min_price", "max_price", "min_rating", "currency"]
    tp = 0
    fp = 0
    fn = 0

    for f in fields_checked:
        ev = exp_hc.get(f)
        av = act_hc.get(f)

        if ev is not None and av is not None:
            if str(ev).lower() == str(av).lower():
                tp += 1
            else:
                fp += 1
                fn += 1
        elif ev is not None and av is None:
            fn += 1
        elif ev is None and av is not None:
            if f == "currency" and av == "INR":
                pass  # Default currency is safe
            else:
                fp += 1

    # 6. Exact match designations
    # Legacy exact match: Hard constraints + Clarification only (matches Phase 8 reported 98%)
    is_legacy_exact_match = (
        cat_match
        and brand_match
        and price_match
        and rating_match
        and currency_match
        and clarif_match
    )

    # Strict Complete-Output Exact Match: MUST include soft_preferences, exclusions, product_type, and boundary operators!
    is_strict_complete_exact_match = (
        is_legacy_exact_match
        and soft_exact_match
        and excl_match
        and pt_match
        and boundary_operator_match
    )

    return {
        "category_match": cat_match,
        "brand_match": brand_match,
        "price_match": price_match,
        "min_price_match": min_price_match,
        "max_price_match": max_price_match,
        "min_inclusive_match": min_incl_match,
        "max_inclusive_match": max_incl_match,
        "boundary_operator_match": boundary_operator_match,
        "rating_match": rating_match,
        "currency_match": currency_match,
        "clarification_match": clarif_match,
        "product_type_match": pt_match,
        "is_legacy_exact_match": is_legacy_exact_match,
        "is_strict_complete_exact_match": is_strict_complete_exact_match,
        "soft_exact_match": soft_exact_match,
        "soft_preferences_precision": round(soft_prec, 4),
        "soft_preferences_recall": round(soft_rec, 4),
        "soft_preferences_f1": round(soft_f1, 4),
        "soft_false_positives": sorted(list(act_soft - exp_soft)),
        "soft_false_negatives": sorted(list(exp_soft - act_soft)),
        "exclusions_f1": round(excl_f1, 4),
        "exclusions_match": excl_match,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
    }


def compute_experiment_metrics(case_results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate benchmark metrics across a collection of evaluated cases."""
    total_cases = len(case_results)
    if total_cases == 0:
        return {"total_cases": 0}

    n = float(total_cases)
    valid_count = sum(1 for c in case_results if c.get("is_valid", True))
    legacy_em_count = sum(1 for c in case_results if c["metrics"]["is_legacy_exact_match"])
    strict_em_count = sum(1 for c in case_results if c["metrics"]["is_strict_complete_exact_match"])
    cat_count = sum(1 for c in case_results if c["metrics"]["category_match"])
    brand_count = sum(1 for c in case_results if c["metrics"]["brand_match"])
    price_count = sum(1 for c in case_results if c["metrics"]["price_match"])
    operator_count = sum(1 for c in case_results if c["metrics"].get("boundary_operator_match", True))
    rating_count = sum(1 for c in case_results if c["metrics"]["rating_match"])
    curr_count = sum(1 for c in case_results if c["metrics"]["currency_match"])
    clarif_count = sum(1 for c in case_results if c["metrics"]["clarification_match"])
    pt_count = sum(1 for c in case_results if c["metrics"].get("product_type_match", True))

    total_tp = sum(c["metrics"]["true_positives"] for c in case_results)
    total_fp = sum(c["metrics"]["false_positives"] for c in case_results)
    total_fn = sum(c["metrics"]["false_negatives"] for c in case_results)

    hc_prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    hc_rec = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    hc_f1 = (2 * hc_prec * hc_rec) / (hc_prec + hc_rec) if (hc_prec + hc_rec) > 0 else 0.0

    soft_f1_scores = [c["metrics"]["soft_preferences_f1"] for c in case_results]
    soft_prec_scores = [c["metrics"]["soft_preferences_precision"] for c in case_results]
    soft_rec_scores = [c["metrics"]["soft_preferences_recall"] for c in case_results]
    excl_f1_scores = [c["metrics"].get("exclusions_f1", 1.0) for c in case_results]

    latencies = [c.get("latency_ms", 0.0) for c in case_results if c.get("latency_ms", 0.0) > 0]
    prompt_tokens = [c.get("token_usage", {}).get("prompt_tokens", 0) for c in case_results]
    candidates_tokens = [c.get("token_usage", {}).get("candidates_tokens", 0) for c in case_results]
    total_tokens = [c.get("token_usage", {}).get("total_tokens", 0) for c in case_results]

    def _stats(arr: list[float]) -> dict[str, float]:
        if not arr:
            return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
        return {
            "mean": round(float(np.mean(arr)), 2),
            "p50": round(float(np.percentile(arr, 50)), 2),
            "p95": round(float(np.percentile(arr, 95)), 2),
            "min": round(float(np.min(arr)), 2),
            "max": round(float(np.max(arr)), 2),
        }

    return {
        "total_cases_evaluated": total_cases,
        "schema_validity_rate": round(valid_count / n, 4),
        "category_accuracy": round(cat_count / n, 4),
        "brand_accuracy": round(brand_count / n, 4),
        "price_accuracy": round(price_count / n, 4),
        "boundary_operator_accuracy": round(operator_count / n, 4),
        "rating_accuracy": round(rating_count / n, 4),
        "currency_accuracy": round(curr_count / n, 4),
        "clarification_accuracy": round(clarif_count / n, 4),
        "product_type_accuracy": round(pt_count / n, 4),
        "hard_constraints_metrics": {
            "precision": round(hc_prec, 4),
            "recall": round(hc_rec, 4),
            "f1_score": round(hc_f1, 4),
            "true_positives": total_tp,
            "false_positives": total_fp,
            "false_negatives": total_fn,
        },
        "soft_preferences_metrics": {
            "mean_f1": round(float(np.mean(soft_f1_scores)), 4),
            "mean_precision": round(float(np.mean(soft_prec_scores)), 4),
            "mean_recall": round(float(np.mean(soft_rec_scores)), 4),
            "exact_match_count": sum(1 for c in case_results if c["metrics"]["soft_exact_match"]),
        },
        "exclusions_mean_f1": round(float(np.mean(excl_f1_scores)), 4),
        "legacy_exact_match_rate": round(legacy_em_count / n, 4),
        "strict_complete_exact_match_rate": round(strict_em_count / n, 4),
        "latency_stats_ms": _stats(latencies),
        "token_usage_stats": {
            "total_prompt_tokens": sum(prompt_tokens),
            "total_candidates_tokens": sum(candidates_tokens),
            "total_tokens": sum(total_tokens),
            "avg_tokens_per_request": round(float(np.mean(total_tokens)), 1) if total_tokens else 0.0,
        },
    }
