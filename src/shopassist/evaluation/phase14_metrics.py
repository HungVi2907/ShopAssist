"""Phase 14 Evaluation Metrics & Ranking Analysis for ShopAssist.

This module implements mathematically rigorous, transparent evaluation metrics
for retrieval and reranking systems under incomplete/pooled AI-Silver judgments.

Key Design Principles:
1. Rank Preservation: Candidates maintain their original 1-based ranks during
   discounting and reciprocal rank calculation; unjudged items do NOT shift
   subsequent ranks upwards.
2. Incomplete Judgment Transparency: Distinguishes judged-only metrics from
   standard IR conservative metrics (where unjudged items yield zero gain).
3. Ideal DCG Against Universe: IDCG@K is calculated against the declared relevant
   judgment universe (the highest grades available in the candidate pool for
   that query), not just the returned subset.
4. Pool-Conditional Recall: Explicitly labeled as conditioned on the pooled
   candidates, avoiding false catalog-wide recall claims.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import random
import statistics
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class RankingItem:
    """A single retrieved item at a specific rank with judgment provenance."""

    product_id: str
    original_rank: int
    score: float
    is_judged: bool
    relevance_grade: int | None = None
    is_relevant: bool = False  # Grade >= 2


@dataclass
class QueryCutoffMetrics:
    """Metrics evaluated at a specific cutoff K."""

    k: int
    returned_count: int
    judged_count: int
    relevant_count: int
    judgment_coverage: float

    # Precision
    precision_judged: float | None
    precision_conservative: float

    # Reciprocal Rank (evaluated at K)
    reciprocal_rank: float
    first_relevant_rank: int | None

    # nDCG
    dcg: float
    idcg: float
    ndcg: float

    # Pool-conditional Recall
    pool_conditional_recall: float | None

    # Constraint compliance
    constraint_violations: int = 0
    constraint_satisfaction_rate: float = 1.0


def compute_dcg(rank_and_grade_pairs: Sequence[tuple[int, int]]) -> float:
    """Compute Discounted Cumulative Gain preserving original 1-based ranks.

    Formula: DCG = sum_{i} (2^{grade_i} - 1) / log2(rank_i + 1)
    """
    dcg = 0.0
    for original_rank, grade in rank_and_grade_pairs:
        if original_rank <= 0:
            raise ValueError(f"original_rank must be >= 1, got {original_rank}")
        if grade > 0:
            gain = (2.0**grade) - 1.0
            discount = math.log2(original_rank + 1)
            dcg += gain / discount
    return dcg


def compute_idcg(universe_grades: Sequence[int], k: int) -> float:
    """Compute Ideal DCG@K from the query's judgment universe.

    Takes all available relevance grades in the query candidate pool, sorts
    descending, and places the top-K grades in ideal positions 1..K.
    """
    if k <= 0:
        raise ValueError(f"k must be > 0, got {k}")
    best_grades = sorted([g for g in universe_grades if g > 0], reverse=True)[:k]
    idcg = 0.0
    for idx, grade in enumerate(best_grades, start=1):
        gain = (2.0**grade) - 1.0
        discount = math.log2(idx + 1)
        idcg += gain / discount
    return idcg


def evaluate_query_cutoff(
    items: Sequence[RankingItem],
    universe_grades: Sequence[int],
    k: int,
    *,
    catalog_metadata: Mapping[str, Mapping[str, Any]] | None = None,
    hard_constraints: Mapping[str, Any] | None = None,
) -> QueryCutoffMetrics:
    """Evaluate retrieval metrics for a single query at cutoff K.

    Parameters:
        items: List of returned items ordered by system rank.
        universe_grades: All relevance grades available in the pool for this query.
        k: The cutoff threshold (e.g. 3, 5, 10).
        catalog_metadata: Optional product metadata lookup.
        hard_constraints: Optional query constraints for compliance check.
    """
    if k <= 0:
        raise ValueError("k must be positive")

    top_k = list(items)[:k]
    returned_count = len(top_k)

    judged_items = [it for it in top_k if it.is_judged]
    judged_count = len(judged_items)
    relevant_items = [it for it in judged_items if it.is_relevant]
    relevant_count = len(relevant_items)

    coverage = (judged_count / returned_count) if returned_count > 0 else 1.0

    # Precision
    precision_judged = (relevant_count / judged_count) if judged_count > 0 else None
    precision_conservative = relevant_count / k

    # MRR / Reciprocal Rank: preserving original rank
    first_rel_rank = None
    reciprocal_rank = 0.0
    for it in top_k:
        if it.is_relevant:
            first_rel_rank = it.original_rank
            reciprocal_rank = 1.0 / it.original_rank
            break

    # DCG & IDCG
    dcg_pairs = [
        (it.original_rank, it.relevance_grade or 0)
        for it in top_k
        if it.is_judged and (it.relevance_grade or 0) > 0
    ]
    dcg = compute_dcg(dcg_pairs)
    idcg = compute_idcg(universe_grades, k)
    ndcg = (dcg / idcg) if idcg > 0.0 else 0.0

    # Pool-conditional Recall
    total_relevant_in_pool = sum(1 for g in universe_grades if g >= 2)
    pool_recall = (
        (relevant_count / total_relevant_in_pool)
        if total_relevant_in_pool > 0
        else None
    )

    # Constraint violations check (if metadata and constraints provided)
    violations = 0
    if catalog_metadata and hard_constraints:
        for it in top_k:
            meta = catalog_metadata.get(it.product_id)
            if meta and not check_product_constraints(meta, hard_constraints):
                violations += 1
    satisfaction_rate = (
        ((returned_count - violations) / returned_count)
        if returned_count > 0
        else 1.0
    )

    return QueryCutoffMetrics(
        k=k,
        returned_count=returned_count,
        judged_count=judged_count,
        relevant_count=relevant_count,
        judgment_coverage=round(coverage, 6),
        precision_judged=(
            round(precision_judged, 6) if precision_judged is not None else None
        ),
        precision_conservative=round(precision_conservative, 6),
        reciprocal_rank=round(reciprocal_rank, 6),
        first_relevant_rank=first_rel_rank,
        dcg=round(dcg, 6),
        idcg=round(idcg, 6),
        ndcg=round(ndcg, 6),
        pool_conditional_recall=(
            round(pool_recall, 6) if pool_recall is not None else None
        ),
        constraint_violations=violations,
        constraint_satisfaction_rate=round(satisfaction_rate, 6),
    )


def check_product_constraints(
    product: Mapping[str, Any], constraints: Mapping[str, Any]
) -> bool:
    """Check if a product satisfies declared hard constraints."""
    # Category constraint
    category_target = constraints.get("category")
    if category_target and isinstance(category_target, str) and category_target.strip():
        prod_cat = str(product.get("category") or "")
        if category_target.casefold() not in prod_cat.casefold():
            return False

    # Brand constraint
    brand_target = constraints.get("brand")
    if brand_target and isinstance(brand_target, str) and brand_target.strip():
        prod_brand = str(product.get("brand") or "")
        if brand_target.casefold() != prod_brand.casefold():
            return False

    # Price constraints
    price = product.get("discounted_price")
    if price is not None:
        try:
            num_price = float(price)
            min_price = constraints.get("min_price")
            if min_price is not None and num_price < float(min_price):
                return False
            max_price = constraints.get("max_price")
            if max_price is not None and num_price > float(max_price):
                return False
        except (ValueError, TypeError):
            pass

    # Rating constraint (null ratings do not satisfy threshold per project rule)
    min_rating = constraints.get("min_rating")
    if min_rating is not None:
        prod_rating = product.get("rating")
        if prod_rating is None or str(prod_rating).strip().lower() in ("", "nan", "none"):
            return False
        try:
            if float(prod_rating) < float(min_rating):
                return False
        except (ValueError, TypeError):
            return False

    return True


def bootstrap_ci(
    values: Sequence[float],
    *,
    samples: int = 1000,
    alpha: float = 0.05,
    seed: int = 14014,
) -> dict[str, float | None]:
    """Calculate bootstrap mean and percentile confidence interval."""
    valid_data = [v for v in values if v is not None and math.isfinite(v)]
    if not valid_data:
        return {"mean": None, "ci_lower": None, "ci_upper": None, "samples": 0}
    if len(valid_data) == 1:
        val = round(valid_data[0], 6)
        return {"mean": val, "ci_lower": val, "ci_upper": val, "samples": 1}

    rng = random.Random(seed)
    n = len(valid_data)
    bootstrap_means = [
        sum(rng.choice(valid_data) for _ in range(n)) / n for _ in range(samples)
    ]
    bootstrap_means.sort()

    lower_idx = int(samples * (alpha / 2.0))
    upper_idx = min(samples - 1, int(samples * (1.0 - alpha / 2.0)))

    return {
        "mean": round(statistics.mean(valid_data), 6),
        "ci_lower": round(bootstrap_means[lower_idx], 6),
        "ci_upper": round(bootstrap_means[upper_idx], 6),
        "samples": n,
    }


def aggregate_cutoff_metrics(
    query_metrics: Sequence[QueryCutoffMetrics],
    *,
    seed: int = 14014,
) -> dict[str, Any]:
    """Aggregate per-query cutoff metrics across an evaluation partition."""
    if not query_metrics:
        return {
            "query_count": 0,
            "judgment_coverage": None,
            "precision_judged": None,
            "precision_conservative": None,
            "mrr": None,
            "ndcg": None,
            "pool_conditional_recall": None,
            "constraint_satisfaction_rate": None,
        }

    total_returned = sum(m.returned_count for m in query_metrics)
    total_judged = sum(m.judged_count for m in query_metrics)
    overall_coverage = (total_judged / total_returned) if total_returned > 0 else 1.0

    p_judged = [m.precision_judged for m in query_metrics if m.precision_judged is not None]
    p_cons = [m.precision_conservative for m in query_metrics]
    mrr_vals = [m.reciprocal_rank for m in query_metrics]
    ndcg_vals = [m.ndcg for m in query_metrics]
    rec_vals = [m.pool_conditional_recall for m in query_metrics if m.pool_conditional_recall is not None]
    cs_vals = [m.constraint_satisfaction_rate for m in query_metrics]

    return {
        "k": query_metrics[0].k,
        "query_count": len(query_metrics),
        "total_returned": total_returned,
        "total_judged": total_judged,
        "judgment_coverage": round(overall_coverage, 6),
        "precision_judged": bootstrap_ci(p_judged, seed=seed),
        "precision_conservative": bootstrap_ci(p_cons, seed=seed),
        "mrr": bootstrap_ci(mrr_vals, seed=seed),
        "ndcg": bootstrap_ci(ndcg_vals, seed=seed),
        "pool_conditional_recall": bootstrap_ci(rec_vals, seed=seed),
        "constraint_satisfaction_rate": bootstrap_ci(cs_vals, seed=seed),
    }
