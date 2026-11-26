"""Versioned task schema identifiers shared by config and runtime contracts."""
from __future__ import annotations

from types import MappingProxyType

PRODUCTION_SCHEMA_IDS = MappingProxyType({
    "query_understanding": "phase8.query.v1",
    "recommendation_generation": "phase12.recommendation.v1",
    "llm_judge": "phase14.judge.v1",
})

EXPERIMENTAL_SCHEMA_IDS = MappingProxyType({
    "query_understanding": MappingProxyType({
        "intent_flat_v1": "phase8.intent.flat.v1",
        "query_v1": "phase8.query.experiment.v1",
        "query_refined_v1": "phase8.query.refined.experiment.v1",
        "query_required_v2_v1": "phase8.query.required-v2.experiment.v1",
    }),
    "recommendation_generation": MappingProxyType({"catalog_selection_v2":"phase12.catalog-selection.v2"}),
})

TASK_SCHEMA_IDS = MappingProxyType({
    task: frozenset((schema_id, *EXPERIMENTAL_SCHEMA_IDS.get(task, {}).values()))
    for task, schema_id in PRODUCTION_SCHEMA_IDS.items()
})
ALL_SCHEMA_IDS = frozenset(
    schema_id for values in TASK_SCHEMA_IDS.values() for schema_id in values
)
