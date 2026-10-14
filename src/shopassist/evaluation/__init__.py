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

__all__ = [
    "OpenAICompatibleJudgeProvider",
    "build_candidate_pool",
    "deterministic_audit",
    "evaluate_retrieval_runs",
    "plan_grouped_split",
    "select_pilot_queries",
    "validate_silver_dataset",
    "weighted_kappa",
]
