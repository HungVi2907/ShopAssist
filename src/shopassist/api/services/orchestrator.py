"""Recommendation Orchestrator coordinating Phases 8–12 (Phase 15).

Implements the central execution pipeline:
Input -> P8 (Query Understanding) -> Price Adapter -> P9 (Soft Preferences) ->
P10 (Hybrid Retrieval) -> P11 (Reranking) -> P12 (Grounded Generation) -> Public Response.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from shopassist.api.config import APISettings, get_api_settings
from shopassist.api.price_adapter import PriceBoundaryAdapter
from shopassist.api.schemas import (
    ProductClaimItem,
    ProductEvidenceItem,
    ProductResponseItem,
    RecommendationMetadata,
    RecommendationRequest,
    RecommendationResponse,
    RecommendationUsage,
)
from shopassist.api.session import InMemorySessionStore
from shopassist.llm.query_understanding import QueryUnderstandingEngine
from shopassist.preferences.safety import find_unsafe_negative_preferences
from shopassist.preferences.schemas import RepresentationStatus
from shopassist.preferences.service import PreferenceRepresentationService
from shopassist.recommendation.core import RecommendationService
from shopassist.recommendation.schemas import RecommendationStatus
from shopassist.reranking.core import RerankingMethod, RerankingService, RerankingStatus
from shopassist.retrieval.hybrid import HybridRetrievalService, HybridRetrievalStatus

logger = logging.getLogger(__name__)


class RecommendationOrchestrator:
    """Coordinates Phase 8 through Phase 12 into a cohesive, grounded recommendation flow."""

    def __init__(
        self,
        query_engine: QueryUnderstandingEngine,
        preference_service: PreferenceRepresentationService,
        hybrid_service: HybridRetrievalService,
        reranking_service: RerankingService,
        recommendation_service: RecommendationService,
        *,
        session_store: InMemorySessionStore | None = None,
        settings: APISettings | None = None,
    ) -> None:
        self.query_engine = query_engine
        self.preference_service = preference_service
        self.hybrid_service = hybrid_service
        self.reranking_service = reranking_service
        self.recommendation_service = recommendation_service
        self.session_store = session_store
        self.settings = settings or get_api_settings()

    async def orchestrate(
        self,
        request: RecommendationRequest,
        request_id: str,
    ) -> RecommendationResponse:
        """Execute end-to-end recommendation workflow with short-circuiting and telemetry.

        Args:
            request: Validated incoming recommendation request.
            request_id: Tracing UUID assigned by middleware.

        Returns:
            Structured RecommendationResponse.
        """
        pipeline_start = time.perf_counter()
        stage_latencies: dict[str, float] = {}

        query_text = request.query.strip()
        top_k = min(request.top_k, self.settings.api_max_top_k)
        language = request.language

        # ----------------------------------------------------------------------
        # Step 1: Input Safeguards (Direct Text-Level Guards)
        # ----------------------------------------------------------------------
        unsafe_exclusions = find_unsafe_negative_preferences([query_text])
        if unsafe_exclusions:
            msg = (
                "Negative or exclusion semantics cannot safely be processed: "
                + ", ".join(unsafe_exclusions)
            )
            return self._build_terminal_response(
                request_id=request_id,
                status="UNSUPPORTED_INTENT",
                overview=msg,
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )

        # ----------------------------------------------------------------------
        # Step 2: Phase 8 — LLM Query Understanding (Async)
        # ----------------------------------------------------------------------
        t0 = time.perf_counter()
        try:
            query_result = await self.query_engine.parse_query_async(query_text)
        except Exception as exc:
            logger.error("[%s] Phase 8 query understanding failed: %s", request_id, exc)
            return self._build_terminal_response(
                request_id=request_id,
                status="INVALID_INPUT",
                overview="Failed to parse query structure.",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies={"phase8_query_understanding": (time.perf_counter() - t0) * 1000.0},
            )
        stage_latencies["phase8_query_understanding"] = (time.perf_counter() - t0) * 1000.0

        # Phase 8 Short-Circuits
        if not query_result.is_valid:
            err = (
                query_result.validation_errors[0]
                if query_result.validation_errors
                else (query_result.output.clarification_reason or "Invalid shopping query.")
            )
            return self._build_terminal_response(
                request_id=request_id,
                status="INVALID_INPUT",
                overview=err,
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )

        if query_result.output.needs_clarification:
            reason = (
                query_result.output.clarification_reason
                or "Your shopping query requires clarification before we can recommend products."
            )
            return self._build_terminal_response(
                request_id=request_id,
                status="CLARIFICATION_REQUIRED",
                overview=reason,
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )

        currency = (query_result.output.hard_constraints.currency or "INR").upper()
        if currency != "INR":
            return self._build_terminal_response(
                request_id=request_id,
                status="UNSUPPORTED_INTENT",
                overview=f"Catalog prices are in INR; currency '{currency}' is not supported.",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )

        # ----------------------------------------------------------------------
        # Step 3: Price Boundary Semantics Adaptation
        # ----------------------------------------------------------------------
        hard_constraints = query_result.output.hard_constraints
        has_price_filter = (
            hard_constraints.min_price is not None or hard_constraints.max_price is not None
        )
        price_semantics: dict[str, bool] = {}

        if has_price_filter:
            resolution = PriceBoundaryAdapter.resolve(
                query=query_text,
                min_price=hard_constraints.min_price,
                max_price=hard_constraints.max_price,
            )
            if not resolution.is_resolved:
                logger.info(
                    "[%s] Price boundary could not be resolved safely: %s",
                    request_id,
                    resolution.unresolved_reason,
                )
                return self._build_terminal_response(
                    request_id=request_id,
                    status="CLARIFICATION_REQUIRED",
                    overview=resolution.unresolved_reason
                    or "Please clarify your budget operator (e.g. 'under 3000' or 'at least 1000').",
                    request=request,
                    pipeline_start=pipeline_start,
                    stage_latencies=stage_latencies,
                )
            price_semantics = resolution.semantics

        # ----------------------------------------------------------------------
        # Step 4: Phase 9 — Soft Preference Representation (Threadpool CPU)
        # ----------------------------------------------------------------------
        t0 = time.perf_counter()
        preference_result = await asyncio.to_thread(
            self.preference_service.represent, query_result
        )
        stage_latencies["phase9_preferences"] = (time.perf_counter() - t0) * 1000.0

        if preference_result.status == RepresentationStatus.CLARIFICATION_REQUIRED:
            return self._build_terminal_response(
                request_id=request_id,
                status="CLARIFICATION_REQUIRED",
                overview=preference_result.diagnostic_reason or "Your preferences require clarification.",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )
        elif preference_result.status == RepresentationStatus.UNSUPPORTED_INTENT:
            return self._build_terminal_response(
                request_id=request_id,
                status="UNSUPPORTED_INTENT",
                overview=preference_result.diagnostic_reason or "Requested shopping intent is not supported.",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )
        elif preference_result.status == RepresentationStatus.EMBEDDING_FAILURE:
            return self._build_terminal_response(
                request_id=request_id,
                status="EMBEDDING_FAILURE",
                overview="Failed to encode preference embedding vector.",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )
        elif preference_result.status == RepresentationStatus.INVALID_INPUT:
            return self._build_terminal_response(
                request_id=request_id,
                status="INVALID_INPUT",
                overview=preference_result.diagnostic_reason or "Invalid preference representation.",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )

        # ----------------------------------------------------------------------
        # Step 5: Phase 10 — Hybrid Candidate Retrieval (Async pgvector + TF-IDF)
        # ----------------------------------------------------------------------
        t0 = time.perf_counter()
        retrieval_result = await self.hybrid_service.retrieve(
            query_result=query_result,
            preference_result=preference_result,
            top_n=self.settings.api_retrieval_top_n,
            price_boundary_semantics=price_semantics if has_price_filter else None,
        )
        stage_latencies["phase10_hybrid_retrieval"] = (time.perf_counter() - t0) * 1000.0

        if retrieval_result.status == HybridRetrievalStatus.NO_RESULTS or not retrieval_result.candidates:
            return self._build_terminal_response(
                request_id=request_id,
                status="NO_RESULTS",
                overview="No products in our catalog match your specified criteria.",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
                applied_constraints=retrieval_result.applied_constraints,
            )
        elif retrieval_result.status == HybridRetrievalStatus.CLARIFICATION_REQUIRED:
            return self._build_terminal_response(
                request_id=request_id,
                status="CLARIFICATION_REQUIRED",
                overview=retrieval_result.diagnostic_reason or "Query requires clarification.",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )
        elif retrieval_result.status == HybridRetrievalStatus.UNSUPPORTED_INTENT:
            return self._build_terminal_response(
                request_id=request_id,
                status="UNSUPPORTED_INTENT",
                overview=retrieval_result.diagnostic_reason or "Intent unsupported by retrieval.",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )
        elif retrieval_result.status != HybridRetrievalStatus.SUCCESS:
            return self._build_terminal_response(
                request_id=request_id,
                status="RETRIEVAL_FAILURE",
                overview=f"Catalog retrieval encountered an issue ({retrieval_result.status.value}).",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )

        # ----------------------------------------------------------------------
        # Step 6: Phase 11 — Candidate Reranking (Threadpool CPU)
        # ----------------------------------------------------------------------
        rerank_method = RerankingMethod(self.settings.api_reranking_method)
        t0 = time.perf_counter()
        reranking_result = await asyncio.to_thread(
            self.reranking_service.rerank,
            query_result=query_result,
            preference_result=preference_result,
            retrieval_result=retrieval_result,
            top_k=top_k,
            method=rerank_method,
        )
        stage_latencies["phase11_reranking"] = (time.perf_counter() - t0) * 1000.0

        if reranking_result.status == RerankingStatus.NO_RESULTS or not reranking_result.products:
            return self._build_terminal_response(
                request_id=request_id,
                status="NO_RESULTS",
                overview="No candidate products remained after constraint validation.",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
                applied_constraints=reranking_result.applied_constraints,
            )
        elif reranking_result.status != RerankingStatus.SUCCESS:
            return self._build_terminal_response(
                request_id=request_id,
                status=reranking_result.status.value,
                overview=f"Reranking encountered an issue ({reranking_result.status.value}).",
                request=request,
                pipeline_start=pipeline_start,
                stage_latencies=stage_latencies,
            )

        # ----------------------------------------------------------------------
        # Step 7: Phase 12 — Grounded Recommendation Generation (Async LLM)
        # ----------------------------------------------------------------------
        t0 = time.perf_counter()
        rec_result = await self.recommendation_service.generate(
            query_result=query_result,
            preference_result=preference_result,
            reranking_result=reranking_result,
            top_k=top_k,
            language=language,
        )
        stage_latencies["phase12_recommendation"] = (time.perf_counter() - t0) * 1000.0

        # Handle Terminal States from Phase 12
        fallback_used = rec_result.status == RecommendationStatus.DETERMINISTIC_FALLBACK
        public_status = (
            "DETERMINISTIC_FALLBACK"
            if fallback_used
            else rec_result.status.value
        )

        # ----------------------------------------------------------------------
        # Step 8: Build Public Response
        # ----------------------------------------------------------------------
        product_items: list[ProductResponseItem] = []
        for prod in rec_result.products:
            strengths_list = [
                ProductClaimItem(claim=c.claim, evidence_ids=list(c.evidence_ids))
                for c in prod.strengths
            ]
            limitations_list = [
                ProductClaimItem(claim=c.claim, evidence_ids=list(c.evidence_ids))
                for c in prod.limitations
            ]
            evidence_items = [
                ProductEvidenceItem(
                    evidence_id=e.evidence_id,
                    source_field=e.source_field,
                    text=e.text,
                )
                for e in prod.available_evidence
            ]
            product_items.append(
                ProductResponseItem(
                    product_id=prod.product_id,
                    product_name=prod.product_name,
                    brand=prod.brand,
                    category=prod.category,
                    discounted_price=prod.discounted_price,
                    currency=prod.currency,
                    rating=prod.rating,
                    summary_reason=prod.summary_reason,
                    strengths=strengths_list,
                    limitations=limitations_list,
                    comparison_note=prod.comparison_note,
                    available_evidence=evidence_items,
                )
            )

        total_latency_ms = (time.perf_counter() - pipeline_start) * 1000.0

        # Token aggregation: Phase 8 + Phase 12
        p8_usage = query_result.token_usage
        p8_prompt_tokens = p8_usage.prompt_tokens if p8_usage else 0
        p8_candidate_tokens = p8_usage.candidates_tokens if p8_usage else 0
        p8_total_tokens = p8_usage.total_tokens if p8_usage else 0

        total_prompt_tokens = p8_prompt_tokens + rec_result.usage.prompt_tokens
        total_completion_tokens = p8_candidate_tokens + rec_result.usage.completion_tokens
        grand_total_tokens = p8_total_tokens + rec_result.usage.total_tokens

        usage = RecommendationUsage(
            total_tokens=grand_total_tokens,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            estimated_cost_usd=rec_result.usage.estimated_cost_usd,
            total_latency_ms=round(total_latency_ms, 2),
            stage_latencies_ms={k: round(v, 2) for k, v in stage_latencies.items()},
        )

        metadata = RecommendationMetadata(
            recommended_count=len(product_items),
            retrieval_method="HYBRID_RRF",
            reranking_method=reranking_result.method,
            fallback_used=fallback_used,
            session_id=request.session_id,
            applied_constraints=retrieval_result.applied_constraints,
        )

        response = RecommendationResponse(
            request_id=request_id,
            status=public_status,
            overview=rec_result.overview,
            products=product_items,
            metadata=metadata,
            usage=usage,
        )

        # Record in session history if session_id provided
        if self.session_store and request.session_id:
            await self.session_store.add_turn(
                session_id=request.session_id,
                user_query=query_text,
                assistant_overview=rec_result.overview,
                status=public_status,
            )

        return response

    def _build_terminal_response(
        self,
        request_id: str,
        status: str,
        overview: str,
        request: RecommendationRequest,
        pipeline_start: float,
        stage_latencies: dict[str, float],
        applied_constraints: dict[str, Any] | None = None,
    ) -> RecommendationResponse:
        """Helper generating short-circuit terminal response without calling downstream phases."""
        total_latency_ms = (time.perf_counter() - pipeline_start) * 1000.0
        return RecommendationResponse(
            request_id=request_id,
            status=status,
            overview=overview,
            products=[],
            metadata=RecommendationMetadata(
                recommended_count=0,
                retrieval_method="HYBRID_RRF",
                reranking_method=self.settings.api_reranking_method,
                fallback_used=False,
                session_id=request.session_id,
                applied_constraints=applied_constraints or {},
            ),
            usage=RecommendationUsage(
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost_usd=0.0,
                total_latency_ms=round(total_latency_ms, 2),
                stage_latencies_ms={k: round(v, 2) for k, v in stage_latencies.items()},
            ),
        )
