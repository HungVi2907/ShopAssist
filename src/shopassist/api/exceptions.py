"""Custom API exceptions and global exception handlers (Phase 15)."""

from __future__ import annotations

import logging
from typing import Any
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ShopAssistAPIException(Exception):
    """Base exception for all ShopAssist API errors."""

    def __init__(self, message: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DependencyUnavailableException(ShopAssistAPIException):
    """Raised when an essential backend resource (DB, TF-IDF, model) is unavailable."""

    def __init__(self, component: str, details: str = "Component unavailable") -> None:
        super().__init__(
            message=f"Mandatory dependency '{component}' is not ready: {details}",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        self.component = component


class PipelineTimeoutException(ShopAssistAPIException):
    """Raised when the recommendation pipeline exceeds its execution deadline."""

    def __init__(self, timeout_seconds: float) -> None:
        super().__init__(
            message=f"Recommendation orchestration exceeded deadline of {timeout_seconds} seconds.",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )
        self.timeout_seconds = timeout_seconds


def register_exception_handlers(app: FastAPI) -> None:
    """Register uniform JSON exception handlers for the application."""

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        # Format Pydantic validation errors cleanly
        errors: list[dict[str, Any]] = []
        for err in exc.errors():
            loc = " -> ".join(str(item) for item in err.get("loc", []))
            errors.append({
                "field": loc,
                "message": err.get("msg", "Invalid value"),
                "type": err.get("type", "value_error"),
            })

        logger.warning("[%s] HTTP 422 Request validation failed: %s", request_id, errors)
        return JSONResponse(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            content={
                "request_id": request_id,
                "error": "Unprocessable Request",
                "message": "Input validation failed. Please check query and parameter constraints.",
                "details": errors,
            },
        )

    @app.exception_handler(DependencyUnavailableException)
    async def dependency_exception_handler(request: Request, exc: DependencyUnavailableException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error("[%s] HTTP 503 Dependency unavailable: %s", request_id, exc.message)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "request_id": request_id,
                "error": "Service Unavailable",
                "message": exc.message,
                "component": exc.component,
            },
        )

    @app.exception_handler(PipelineTimeoutException)
    async def timeout_exception_handler(request: Request, exc: PipelineTimeoutException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error("[%s] HTTP 504 Pipeline timeout: %s", request_id, exc.message)
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={
                "request_id": request_id,
                "error": "Gateway Timeout",
                "message": exc.message,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        # Sanitize exception message to avoid credential/token exposure
        logger.exception("[%s] HTTP 500 Unhandled internal server error: %s", request_id, type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "request_id": request_id,
                "error": "Internal Server Error",
                "message": "An unexpected error occurred while processing the request. Details have been logged securely.",
            },
        )
