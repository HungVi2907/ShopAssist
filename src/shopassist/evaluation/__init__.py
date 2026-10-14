"""Evaluation-only components for ShopAssist.

The modules in this package deliberately do not change the Phase 8--12
production path.  Phase 13 AI-generated labels live in the separate
``phase13.ai_silver`` namespace and are always marked as Silver evidence.
"""

from .silver import (
    OpenAICompatibleJudgeProvider,
    build_candidate_pool,
    deterministic_audit,
    evaluate_retrieval_runs,
    plan_grouped_split,
    select_pilot_queries,
    validate_silver_dataset,
    weighted_kappa,
)
from .phase14_metrics import (
    QueryCutoffMetrics,
    RankingItem,
    aggregate_cutoff_metrics,
    bootstrap_ci,
    check_product_constraints,
    compute_dcg,
    compute_idcg,
    evaluate_query_cutoff,
)

__all__ = [
    "OpenAICompatibleJudgeProvider",
    "QueryCutoffMetrics",
    "RankingItem",
    "aggregate_cutoff_metrics",
    "bootstrap_ci",
    "build_candidate_pool",
    "check_product_constraints",
    "compute_dcg",
    "compute_idcg",
    "deterministic_audit",
    "evaluate_query_cutoff",
    "evaluate_retrieval_runs",
    "plan_grouped_split",
    "select_pilot_queries",
    "validate_silver_dataset",
    "weighted_kappa",
]
