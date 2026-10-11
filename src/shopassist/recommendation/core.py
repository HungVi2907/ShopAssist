"""Core recommendation service implementation (Phase 12).

Orchestrates input validation, evidence extraction, prompt construction, Groq LLM inference,
groundedness validation, authoritative metadata merging, and observability.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Sequence

from shopassist.llm.schemas import QueryUnderstandingResult
from shopassist.preferences.schemas import PreferenceRepresentationResult
from shopassist.reranking.core import RerankingResult, RerankingStatus
from shopassist.recommendation.config import RecommendationSettings, get_recommendation_settings
from shopassist.recommendation.context import EvidenceContextBuilder
from shopassist.recommendation.prompts import (
    RECOMMENDATION_SYSTEM_PROMPT,
    build_recommendation_user_prompt,
)
from shopassist.recommendation.provider import (
    BaseRecommendationProvider,
    GroqProvider,
    OpenRouterProvider,
    get_recommendation_provider,
)
from shopassist.recommendation.schemas import (
    RecommendationResult,
    RecommendationStatus,
    TokenUsage,
)
from shopassist.recommendation.validation import GroundednessValidator

logger = logging.getLogger(__name__)


class RecommendationService:
    """Independent service converting Phase 11 Top-K products into grounded recommendations."""

    def __init__(
        self,
        *,
        settings: RecommendationSettings | None = None,
        provider: BaseRecommendationProvider | None = None,
        context_builder: EvidenceContextBuilder | None = None,
        validator: GroundednessValidator | None = None,
    ) -> None:
        self.settings = settings or get_recommendation_settings()
        self.provider = provider or get_recommendation_provider(self.settings)
        self.context_builder = context_builder or EvidenceContextBuilder()
        self.validator = validator or GroundednessValidator()

    async def generate(
        self,
        query_result: QueryUnderstandingResult,
        preference_result: PreferenceRepresentationResult | None,
        reranking_result: RerankingResult,
        *,
        top_k: int | None = None,
        language: str | None = None,
    ) -> RecommendationResult:
        """Generate evidence-grounded recommendations for Phase 11 products.

        Args:
            query_result: Phase 8 Query Understanding result.
            preference_result: Phase 9 Preference Representation result (or None).
            reranking_result: Phase 11 Reranking result with candidate products.
            top_k: Optional override for number of products to recommend.
            language: Optional language override ("auto", "en", "vi").

        Returns:
            Typed RecommendationResult with status, overview, products, and usage.
        """
        # 1. Input Contract and Status Validation
        if not isinstance(query_result, QueryUnderstandingResult):
            return RecommendationResult(
                status=RecommendationStatus.INVALID_INPUT,
                overview="Invalid query understanding result input.",
                diagnostic_reason=f"Expected QueryUnderstandingResult, got {type(query_result)}",
            )

        if not isinstance(reranking_result, RerankingResult):
            return RecommendationResult(
                status=RecommendationStatus.INVALID_INPUT,
                overview="Invalid reranking result input.",
                diagnostic_reason=f"Expected RerankingResult, got {type(reranking_result)}",
            )

        # Propagate Phase 8 Query Understanding statuses
        output = getattr(query_result, "output", None)
        q8_status = getattr(query_result, "status", None)
        needs_clarify = (
            q8_status == "CLARIFICATION_REQUIRED"
            or (output is not None and getattr(output, "needs_clarification", False))
        )
        if needs_clarify:
            clarify_text = (
                getattr(output, "clarification_reason", None)
                or getattr(output, "clarification_prompt", None)
            )
            return RecommendationResult(
                status=RecommendationStatus.CLARIFICATION_REQUIRED,
                overview=clarify_text or "Your query requires clarification before recommendations can be generated.",
                diagnostic_reason=clarify_text,
            )
        if q8_status == "UNSUPPORTED_INTENT":
            return RecommendationResult(
                status=RecommendationStatus.UNSUPPORTED_INTENT,
                overview="The requested shopping intent is not currently supported.",
            )
        if q8_status == "INVALID_INPUT":
            return RecommendationResult(
                status=RecommendationStatus.INVALID_INPUT,
                overview="Invalid search query input.",
            )

        # Propagate Phase 9 Preference Representation statuses
        if preference_result and hasattr(preference_result, "status"):
            p9_status = getattr(preference_result.status, "value", preference_result.status)
            if p9_status == "CLARIFICATION_REQUIRED":
                return RecommendationResult(
                    status=RecommendationStatus.CLARIFICATION_REQUIRED,
                    overview="Your preferences require clarification.",
                )
            if p9_status == "UNSUPPORTED_INTENT":
                return RecommendationResult(
                    status=RecommendationStatus.UNSUPPORTED_INTENT,
                    overview="The requested shopping intent is not currently supported.",
                )
            if p9_status == "INVALID_INPUT":
                return RecommendationResult(
                    status=RecommendationStatus.INVALID_INPUT,
                    overview="Invalid preference representation input.",
                )

        # Propagate upstream terminal and failure statuses
        rr_status = reranking_result.status
        if rr_status == RerankingStatus.NO_RESULTS:
            return RecommendationResult(
                status=RecommendationStatus.NO_RESULTS,
                overview="No products found matching your search criteria.",
                diagnostic_reason=reranking_result.diagnostic_reason,
                applied_constraints=reranking_result.applied_constraints,
            )

        if rr_status == RerankingStatus.CLARIFICATION_REQUIRED:
            return RecommendationResult(
                status=RecommendationStatus.CLARIFICATION_REQUIRED,
                overview="Your query requires clarification before recommendations can be generated.",
                diagnostic_reason=reranking_result.diagnostic_reason,
                applied_constraints=reranking_result.applied_constraints,
            )

        if rr_status == RerankingStatus.UNSUPPORTED_INTENT:
            return RecommendationResult(
                status=RecommendationStatus.UNSUPPORTED_INTENT,
                overview="The requested shopping intent is not currently supported.",
                diagnostic_reason=reranking_result.diagnostic_reason,
                applied_constraints=reranking_result.applied_constraints,
            )

        if rr_status in (RerankingStatus.INVALID_INPUT, RerankingStatus.CONSTRAINT_VIOLATION):
            return RecommendationResult(
                status=RecommendationStatus.INVALID_INPUT,
                overview="Invalid search parameters or constraint violation detected.",
                diagnostic_reason=reranking_result.diagnostic_reason,
                applied_constraints=reranking_result.applied_constraints,
            )

        if rr_status != RerankingStatus.SUCCESS:
            return RecommendationResult(
                status=RecommendationStatus.GENERATION_FAILURE,
                overview="Upstream reranking did not succeed.",
                diagnostic_reason=f"Upstream status: {rr_status.value}. Reason: {reranking_result.diagnostic_reason}",
                applied_constraints=reranking_result.applied_constraints,
            )

        # Empty candidate list check
        if not reranking_result.products:
            return RecommendationResult(
                status=RecommendationStatus.NO_RESULTS,
                overview="No candidate products available for recommendation.",
                diagnostic_reason="Phase 11 returned 0 products with status SUCCESS",
                applied_constraints=reranking_result.applied_constraints,
            )

        # 2. Slice candidate products to Top-K
        effective_k = top_k if top_k is not None else self.settings.phase12_top_k
        effective_k = max(1, min(effective_k, 20))
        candidates = reranking_result.products[:effective_k]

        # Determine target language
        effective_language = language or self.settings.phase12_output_language

        # 3. Context & Evidence Construction
        context_str, evidence_store, flat_evidence = self.context_builder.build_context(
            query_result,
            preference_result,
            candidates,
        )

        user_prompt = build_recommendation_user_prompt(context_str, language=effective_language)

        # 4. Groq Inference
        try:
            payload, usage = await self.provider.generate_recommendation_payload(
                RECOMMENDATION_SYSTEM_PROMPT,
                user_prompt,
            )
        except Exception as exc:
            logger.warning(f"LLM recommendation generation failed ({type(exc).__name__}): {exc}. Falling back to deterministic metadata.")
            return self.validator.generate_deterministic_fallback(
                candidates,
                evidence_store,
                reason=f"LLM generation failed: {exc}",
                model_name=self.settings.phase12_llm_model,
                applied_constraints=reranking_result.applied_constraints,
                language=effective_language,
            )

        # 5. Groundedness Validation & Metadata Merging
        result = self.validator.validate_and_merge(
            payload,
            candidates,
            evidence_store,
            flat_evidence,
            usage=usage,
            model_name=self.settings.phase12_llm_model,
            language=effective_language,
            applied_constraints=reranking_result.applied_constraints,
        )

        return result

    def generate_sync(
        self,
        query_result: QueryUnderstandingResult,
        preference_result: PreferenceRepresentationResult | None,
        reranking_result: RerankingResult,
        *,
        top_k: int | None = None,
        language: str | None = None,
    ) -> RecommendationResult:
        """Synchronous convenience wrapper for generate()."""
        return asyncio.run(
            self.generate(
                query_result,
                preference_result,
                reranking_result,
                top_k=top_k,
                language=language,
            )
        )
