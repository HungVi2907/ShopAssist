"""Request tracing, context management, and latency measurement middleware (Phase 15)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware establishing request_id, tracing context, and telemetry headers."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        start_time = time.perf_counter()

        # Extract existing X-Request-ID or generate new UUID
        incoming_id = request.headers.get("x-request-id")
        request_id = incoming_id.strip() if incoming_id and incoming_id.strip() else str(uuid.uuid4())
        request.state.request_id = request_id
        request.state.start_time = start_time

        logger.info(
            "[%s] HTTP %s %s from %s",
            request_id,
            request.method,
            request.url.path,
            request.client.host if request.client else "unknown",
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            logger.exception("[%s] Unhandled exception in request processing after %.2fms: %s", request_id, latency_ms, type(exc).__name__)
            from starlette.responses import JSONResponse
            response = JSONResponse(
                status_code=500,
                content={
                    "request_id": request_id,
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred while processing the request. Details have been logged securely.",
                },
            )

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-MS"] = f"{latency_ms:.2f}"

        logger.info(
            "[%s] HTTP %s %s completed with status %d in %.2fms",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
        )

        return response
