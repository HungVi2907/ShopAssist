"""Evaluation module for Query Understanding accuracy, latency, and token metrics (Phase 8).

Compares extracted structured representations against curated ground truth fixtures,
calculating field-level precision, recall, F1, exact match, and latency quantiles.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import time
from typing import Any, Sequence

import numpy as np

from shopassist.llm.query_understanding import QueryUnderstandingEngine
from shopassist.llm.schemas import QueryUnderstandingResult

logger = logging.getLogger(__name__)

DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "query_understanding_cases.json"


def load_evaluation_cases(fixture_path: Path | str = DEFAULT_FIXTURE_PATH) -> list[dict[str, Any]]:
    """Load curated ground truth query understanding evaluation cases from JSON fixture."""
    p = Path(fixture_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Evaluation fixture not found at {p}")
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "cases" in data:
        return data["cases"]
    elif isinstance(data, list):
        return data
    raise ValueError(f"Unrecognized fixture format in {p}")


def evaluate_single_case(
    actual_result: QueryUnderstandingResult,
    expected: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate extraction accuracy of a single query result against ground truth expectations."""
    out = actual_result.output
    hc = out.hard_constraints

    exp_hc = expected.get("hard_constraints", {})
    exp_cat = exp_hc.get("category")
    exp_brand = exp_hc.get("brand")
    exp_min_price = exp_hc.get("min_price")
    exp_max_price = exp_hc.get("max_price")
    exp_rating = exp_hc.get("min_rating")
    exp_currency = exp_hc.get("currency", "INR")
    exp_clarif = expected.get("needs_clarification", False)

    # Field matching checks
    cat_match = (hc.category == exp_cat) or (exp_cat is None and hc.category is None)

    brand_match = False
    if exp_brand is None:
        brand_match = hc.brand is None
    elif hc.brand is not None:
        brand_match = exp_brand.lower() == hc.brand.lower()

    min_price_match = hc.min_price == exp_min_price
    max_price_match = hc.max_price == exp_max_price
    price_match = min_price_match and max_price_match

    rating_match = hc.min_rating == exp_rating
    currency_match = hc.currency == exp_currency
    clarif_match = out.needs_clarification == exp_clarif

    # Soft preference overlap
    exp_soft = set(s.lower() for s in expected.get("soft_preferences", []))
    act_soft = set(s.lower() for s in out.soft_preferences)

    if not exp_soft and not act_soft:
        soft_f1 = 1.0
    elif not exp_soft or not act_soft:
        soft_f1 = 0.0
    else:
        inter = len(exp_soft.intersection(act_soft))
        prec = inter / float(len(act_soft))
        rec = inter / float(len(exp_soft))
        soft_f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

    # Hard constraints field level count
    fields_checked = ["category", "brand", "min_price", "max_price", "min_rating", "currency"]
    true_positives = 0
    false_positives = 0
    false_negatives = 0

    for f in fields_checked:
        exp_val = exp_hc.get(f)
        act_val = getattr(hc, f)

        if exp_val is not None and act_val is not None:
            # Both present
            if str(exp_val).lower() == str(act_val).lower():
                true_positives += 1
            else:
                false_positives += 1
                false_negatives += 1
        elif exp_val is not None and act_val is None:
            false_negatives += 1
        elif exp_val is None and act_val is not None:
            # Extracted something not expected (except default currency INR if unspecified)
            if f == "currency" and act_val == "INR":
                pass
            else:
                false_positives += 1

    # Exact match across all key fields
    is_exact_match = (
        actual_result.is_valid
        and cat_match
        and brand_match
        and price_match
        and rating_match
        and currency_match
        and clarif_match
    )

    return {
        "is_valid": actual_result.is_valid,
        "is_exact_match": is_exact_match,
        "category_match": cat_match,
        "brand_match": brand_match,
        "price_match": price_match,
        "min_price_match": min_price_match,
        "max_price_match": max_price_match,
        "rating_match": rating_match,
        "currency_match": currency_match,
        "clarification_match": clarif_match,
        "soft_preferences_f1": round(soft_f1, 4),
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "latency_ms": actual_result.latency_ms,
        "token_usage": actual_result.token_usage.model_dump() if actual_result.token_usage else {},
    }


async def evaluate_query_understanding(
    engine: QueryUnderstandingEngine,
    cases: Sequence[dict[str, Any]],
    pacing_delay_sec: float = 0.5,
) -> dict[str, Any]:
    """Execute end-to-end evaluation against a dataset of query cases.

    Args:
        engine: QueryUnderstandingEngine instance.
        cases: Sequence of test case dictionaries.
        pacing_delay_sec: Delay between requests to respect API rate limits.

    Returns:
        Dictionary of comprehensive evaluation metrics and per-case results.
    """
    total_cases = len(cases)
    logger.info("Starting evaluation on %d test cases with pacing=%.2fs...", total_cases, pacing_delay_sec)

    case_evaluations: list[dict[str, Any]] = []
    latencies: list[float] = []
    prompt_tokens_list: list[int] = []
    candidates_tokens_list: list[int] = []
    total_tokens_list: list[int] = []

    valid_count = 0
    exact_match_count = 0
    cat_match_count = 0
    brand_match_count = 0
    price_match_count = 0
    rating_match_count = 0
    currency_match_count = 0
    clarif_match_count = 0
    total_tp = 0
    total_fp = 0
    total_fn = 0
    soft_f1_scores: list[float] = []

    for idx, c in enumerate(cases, start=1):
        q = c["query"]
        t_id = c.get("test_id", f"QU_{idx:03d}")
        logger.debug("[%d/%d] Evaluating '%s' (ID: %s)...", idx, total_cases, q, t_id)

        res = await engine.parse_query_async(q)
        eval_metrics = evaluate_single_case(res, c.get("expected", {}))

        if eval_metrics["is_valid"]:
            valid_count += 1
        if eval_metrics["is_exact_match"]:
            exact_match_count += 1
        if eval_metrics["category_match"]:
            cat_match_count += 1
        if eval_metrics["brand_match"]:
            brand_match_count += 1
        if eval_metrics["price_match"]:
            price_match_count += 1
        if eval_metrics["rating_match"]:
            rating_match_count += 1
        if eval_metrics["currency_match"]:
            currency_match_count += 1
        if eval_metrics["clarification_match"]:
            clarif_match_count += 1

        total_tp += eval_metrics["true_positives"]
        total_fp += eval_metrics["false_positives"]
        total_fn += eval_metrics["false_negatives"]
        soft_f1_scores.append(eval_metrics["soft_preferences_f1"])

        latencies.append(res.latency_ms)
        if res.token_usage:
            prompt_tokens_list.append(res.token_usage.prompt_tokens)
            candidates_tokens_list.append(res.token_usage.candidates_tokens)
            total_tokens_list.append(res.token_usage.total_tokens)

        case_evaluations.append({
            "test_id": t_id,
            "query": q,
            "category": c.get("category", "General"),
            "expected": c.get("expected", {}),
            "actual": res.output.model_dump(),
            "metrics": eval_metrics,
        })

        if pacing_delay_sec > 0:
            await asyncio.sleep(pacing_delay_sec)

    # Compute aggregate metrics
    n = float(total_cases) if total_cases > 0 else 1.0
    hc_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    hc_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    hc_f1 = (2 * hc_precision * hc_recall) / (hc_precision + hc_recall) if (hc_precision + hc_recall) > 0 else 0.0

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

    summary = {
        "total_cases_evaluated": total_cases,
        "schema_validity_rate": round(valid_count / n, 4),
        "overall_exact_match_rate": round(exact_match_count / n, 4),
        "category_accuracy": round(cat_match_count / n, 4),
        "brand_accuracy": round(brand_match_count / n, 4),
        "price_accuracy": round(price_match_count / n, 4),
        "rating_accuracy": round(rating_match_count / n, 4),
        "currency_accuracy": round(currency_match_count / n, 4),
        "clarification_accuracy": round(clarif_match_count / n, 4),
        "hard_constraints_metrics": {
            "precision": round(hc_precision, 4),
            "recall": round(hc_recall, 4),
            "f1_score": round(hc_f1, 4),
            "true_positives": total_tp,
            "false_positives": total_fp,
            "false_negatives": total_fn,
        },
        "soft_preferences_mean_f1": round(float(np.mean(soft_f1_scores)) if soft_f1_scores else 0.0, 4),
        "latency_stats_ms": _stats(latencies),
        "token_usage_stats": {
            "total_prompt_tokens": sum(prompt_tokens_list),
            "total_candidates_tokens": sum(candidates_tokens_list),
            "total_tokens": sum(total_tokens_list),
            "avg_tokens_per_request": round(float(np.mean(total_tokens_list)), 1) if total_tokens_list else 0.0,
        },
        "case_details": case_evaluations,
    }

    return summary
