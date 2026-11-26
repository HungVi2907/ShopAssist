"""Phase 12 — Grounded Product Recommendation Generation with Groq LLM.

Exports core recommendation service, schemas, provider, and context builder.
"""

from __future__ import annotations

from shopassist.recommendation.config import (
    RecommendationSettings,
    get_recommendation_settings,
    mask_api_key,
)
from shopassist.recommendation.context import (
    EvidenceContextBuilder,
    clean_description_text,
    extract_product_evidence,
)
from shopassist.recommendation.core import RecommendationService
from shopassist.recommendation.prompts import (
    RECOMMENDATION_SYSTEM_PROMPT,
    build_recommendation_user_prompt,
)
from shopassist.recommendation.provider import (
    BaseRecommendationProvider,
    GROQ_STRICT_RECOMMENDATION_SCHEMA,
    GroqProvider,
    OpenRouterProvider,
    get_recommendation_provider,
)
from shopassist.recommendation.schemas import (
    LLMProductClaim,
    LLMProductExplanation,
    LLMRecommendationPayload,
    ProductClaim,
    ProductEvidence,
    RecommendationResult,
    RecommendationStatus,
    RecommendedProduct,
    TokenUsage,
)
from shopassist.recommendation.validation import GroundednessValidator

__all__ = [
    "BaseRecommendationProvider",
    "EvidenceContextBuilder",
    "GROQ_STRICT_RECOMMENDATION_SCHEMA",
    "GroundednessValidator",
    "GroqProvider",
    "LLMProductClaim",
    "LLMProductExplanation",
    "LLMRecommendationPayload",
    "OpenRouterProvider",
    "ProductClaim",
    "ProductEvidence",
    "RecommendationResult",
    "RecommendationService",
    "RecommendationSettings",
    "RecommendationStatus",
    "RecommendedProduct",
    "RECOMMENDATION_SYSTEM_PROMPT",
    "TokenUsage",
    "build_recommendation_user_prompt",
    "clean_description_text",
    "extract_product_evidence",
    "get_recommendation_provider",
    "get_recommendation_settings",
    "mask_api_key",
]
