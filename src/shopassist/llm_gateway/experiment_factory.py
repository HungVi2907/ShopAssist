"""Trusted composition for CLI experiment use of the configured Gateway."""
from __future__ import annotations

import json
import os

from shopassist.evaluation.phase14_judge import LLMJudgeResponseSchema
from shopassist.llm.schema_variants import RefinedQueryUnderstandingOutput, RequiredV2
from shopassist.llm.schemas import QueryUnderstandingOutput
from shopassist.llm_gateway.adapters.gemini import GeminiAdapter
from shopassist.llm_gateway.adapters.groq import GroqAdapter
from shopassist.llm_gateway.config import GatewaySettings
from shopassist.llm_gateway.gateway import Gateway
from shopassist.llm_gateway.registry import ProviderRegistry
from shopassist.llm_gateway.schema_ids import EXPERIMENTAL_SCHEMA_IDS
from shopassist.llm_gateway.schemas import SCHEMA_IDS, TaskType
from shopassist.llm_gateway.telemetry import TelemetrySink
from shopassist.recommendation.schemas import LLMRecommendationPayload


def experiment_schema_bindings() -> dict[str, type]:
    return {
        SCHEMA_IDS[TaskType.QUERY_UNDERSTANDING]: QueryUnderstandingOutput,
        SCHEMA_IDS[TaskType.RECOMMENDATION_GENERATION]: LLMRecommendationPayload,
        SCHEMA_IDS[TaskType.LLM_JUDGE]: LLMJudgeResponseSchema,
        EXPERIMENTAL_SCHEMA_IDS["query_understanding"]["query_v1"]: QueryUnderstandingOutput,
        EXPERIMENTAL_SCHEMA_IDS["query_understanding"]["query_refined_v1"]: RefinedQueryUnderstandingOutput,
        EXPERIMENTAL_SCHEMA_IDS["query_understanding"]["query_required_v2_v1"]: RequiredV2,
    }


def build_experiment_gateway(
    settings: GatewaySettings,
    *,
    attempt_accounting=None,
) -> Gateway:
    """Build one Gateway from YAML; credentials are read only by adapters at dispatch."""
    registry = ProviderRegistry(settings, experiment_schema_bindings())

    def estimate(route, request):
        schema = json.dumps(request.response_schema.model_json_schema(), sort_keys=True)
        input_bytes = len((request.system_prompt + request.user_prompt + schema).encode("utf-8"))
        # UTF-8 input bytes deliberately over-reserve visible tokens; add the
        # route output ceiling plus safety headroom for tokenizer variance.
        return input_bytes + route.options["max_output_tokens"] + 512, None

    return Gateway(
        settings,
        registry,
        {
            "gemini": GeminiAdapter(lambda: os.environ.get("GEMINI_API_KEY", "")),
            "gemini_recommendation": GeminiAdapter(lambda: os.environ.get("GEMINI_API_KEY_2", "")),
            "groq": GroqAdapter(lambda: os.environ.get("GROQ_API_KEY", "")),
        },
        telemetry=TelemetrySink(settings),
        budget_estimator=estimate,
        attempt_accounting=attempt_accounting,
    )
