"""Health and readiness endpoints for ShopAssist API (Phase 15)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from shopassist.api.dependencies import get_db_engine
from shopassist.api.schemas import HealthResponse, LivenessResponse
from shopassist.llm.config import get_llm_settings
from shopassist.llm_gateway.schemas import TaskType
from shopassist.recommendation.config import get_recommendation_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health & Readiness"])

DATABASE_PROBE_TIMEOUT_SECONDS = 5.0


async def _probe_database(engine: AsyncEngine) -> bool:
    """Check checkout, connection establishment, and a minimal query together."""
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1;"))
        return result.scalar() == 1


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Liveness Probe",
    description="Lightweight endpoint returning process liveness status.",
)
async def check_liveness() -> LivenessResponse:
    """Liveness probe to verify process is alive."""
    return LivenessResponse(status="alive")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health & Readiness Check",
    description="Comprehensive readiness check verifying database connectivity, TF-IDF assets, embedding model, and LLM configuration without billable API calls.",
)
async def check_health(request: Request) -> JSONResponse:
    """Check readiness of all required backend components."""
    components: dict[str, str] = {}
    is_healthy = True

    # 1. Check Database Connectivity
    engine: AsyncEngine | None = getattr(request.app.state, "engine", None)
    if engine is not None:
        try:
            ready = await asyncio.wait_for(
                _probe_database(engine), timeout=DATABASE_PROBE_TIMEOUT_SECONDS
            )
            if ready:
                components["database"] = "healthy"
            else:
                components["database"] = "degraded"
                is_healthy = False
        except Exception as exc:
            logger.warning("Health check DB probe failed: %s", type(exc).__name__)
            components["database"] = "unhealthy"
            is_healthy = False
    else:
        components["database"] = "uninitialized"
        is_healthy = False

    # 2. Check TF-IDF Index
    tfidf_index = getattr(request.app.state, "tfidf_index", None)
    if tfidf_index is not None and getattr(tfidf_index, "is_fitted", False):
        components["tfidf"] = "ready"
    else:
        components["tfidf"] = "missing_or_unfitted"
        is_healthy = False

    # 3. Check Embedding Model
    query_encoder = getattr(request.app.state, "query_encoder", None)
    if query_encoder is not None:
        components["embedding"] = "ready"
    else:
        components["embedding"] = "unloaded"
        is_healthy = False

    gateway = getattr(request.app.state, "gateway", None)
    if gateway is not None:
        query_provider = gateway.primary_provider(TaskType.QUERY_UNDERSTANDING)
        recommendation_provider = gateway.primary_provider(TaskType.RECOMMENDATION_GENERATION)
        components["query_understanding"] = f"configured ({query_provider})" if query_provider else "unconfigured"
        components["recommendation_provider"] = (
            f"configured ({recommendation_provider})" if recommendation_provider else "unconfigured"
        )
        logger.debug("LLM Gateway local readiness snapshot: %s", gateway.readiness_snapshot())
    else:
        # Legacy rollback mode keeps its existing credential-based indicators.
        try:
            llm_cfg = get_llm_settings()
            if llm_cfg.gemini_api_key and llm_cfg.gemini_api_key.strip():
                components["query_understanding"] = "configured"
            else:
                components["query_understanding"] = "unconfigured"
        except Exception:
            components["query_understanding"] = "error"

        try:
            rec_cfg = get_recommendation_settings()
            api_key = rec_cfg.get_api_key()
            if api_key and api_key.strip():
                components["recommendation_provider"] = f"configured ({rec_cfg.phase12_llm_provider})"
            else:
                components["recommendation_provider"] = "unconfigured"
        except Exception:
            components["recommendation_provider"] = "error"

    # Determine overall status code and label
    overall_status = "healthy" if is_healthy else "degraded"
    status_code = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    payload = {
        "status": overall_status,
        "components": components,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return JSONResponse(status_code=status_code, content=payload)
