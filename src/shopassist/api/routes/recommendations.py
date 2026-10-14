"""Primary recommendation endpoints for ShopAssist REST API (Phase 15)."""

from __future__ import annotations

import asyncio
import logging
from fastapi import APIRouter, Depends, Request, status

from shopassist.api.config import APISettings
from shopassist.api.dependencies import get_orchestrator, get_settings
from shopassist.api.exceptions import PipelineTimeoutException
from shopassist.api.schemas import RecommendationRequest, RecommendationResponse
from shopassist.api.services.orchestrator import RecommendationOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Recommendations"])


@router.post(
    "/recommend",
    response_model=RecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate Grounded Product Recommendations",
    description=(
        "Executes the full end-to-end AI pipeline: "
        "LLM Query Understanding (Phase 8) -> Preference Representation (Phase 9) -> "
        "Hybrid pgvector + TF-IDF Retrieval (Phase 10) -> Reranking (Phase 11) -> "
        "Grounded LLM Recommendation Generation (Phase 12)."
    ),
)
async def generate_recommendations(
    payload: RecommendationRequest,
    request: Request,
    orchestrator: RecommendationOrchestrator = Depends(get_orchestrator),
    settings: APISettings = Depends(get_settings),
) -> RecommendationResponse:
    """Handle recommendation request with timeout enforcement and tracing."""
    request_id = getattr(request.state, "request_id", "req-unknown")
    timeout_s = settings.api_request_timeout_seconds

    try:
        response = await asyncio.wait_for(
            orchestrator.orchestrate(request=payload, request_id=request_id),
            timeout=timeout_s,
        )
        return response
    except asyncio.TimeoutError:
        logger.error("[%s] Orchestration timed out after %.1fs", request_id, timeout_s)
        raise PipelineTimeoutException(timeout_seconds=timeout_s) from None
