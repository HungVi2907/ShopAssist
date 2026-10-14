"""Asynchronous HTTP client connecting Telegram Bot to FastAPI backend (Phase 16)."""

from __future__ import annotations

import logging
import time
from typing import Any
import httpx
from pydantic import ValidationError

from shopassist.api.schemas import HealthResponse, RecommendationRequest, RecommendationResponse

logger = logging.getLogger(__name__)


class BotClientError(Exception):
    """Base exception for bot HTTP client operations."""


class BackendConnectionError(BotClientError):
    """Raised when unable to connect to the FastAPI backend."""


class BackendTimeoutError(BotClientError):
    """Raised when the backend request exceeds the timeout threshold."""


class BackendResponseError(BotClientError):
    """Raised when the backend returns a non-200 HTTP response code."""

    def __init__(self, status_code: int, detail: str, request_id: str | None = None) -> None:
        super().__init__(f"Backend returned HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.request_id = request_id


class BackendSchemaError(BotClientError):
    """Raised when the backend returns a payload that does not match the schema."""

    def __init__(self, message: str, raw_payload: Any = None) -> None:
        super().__init__(message)
        self.raw_payload = raw_payload


class FastAPIRecommendationClient:
    """Asynchronous HTTP client for ShopAssist FastAPI backend."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout_seconds: float = 95.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            headers={"User-Agent": "ShopAssist-TelegramBot/1.0"},
        )

    async def recommend(
        self,
        query: str,
        top_k: int = 5,
        language: str = "auto",
        session_id: str | None = None,
    ) -> RecommendationResponse:
        """Call POST /api/v1/recommend with validated payload.

        Args:
            query: User's natural language shopping query.
            top_k: Desired maximum number of recommendations (1–20).
            language: Preferred language ('auto', 'en', 'vi').
            session_id: Optional session identifier for tracking.

        Returns:
            Validated RecommendationResponse.

        Raises:
            BackendConnectionError: If network connection to FastAPI fails.
            BackendTimeoutError: If request times out.
            BackendResponseError: If backend returns HTTP 4xx or 5xx.
            BackendSchemaError: If response fails Pydantic schema validation.
        """
        req_model = RecommendationRequest(
            query=query,
            top_k=top_k,
            language=language,
            session_id=session_id,
        )
        payload = req_model.model_dump(exclude_none=True)

        url = f"{self.base_url}/api/v1/recommend"
        start_time = time.perf_counter()

        try:
            response = await self._client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            elapsed = time.perf_counter() - start_time
            logger.error("FastAPI recommendation timed out after %.2fs: %s", elapsed, exc)
            raise BackendTimeoutError(
                f"Backend request timed out after {elapsed:.1f}s."
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.error("Failed to connect to FastAPI backend at %s: %s", self.base_url, exc)
            raise BackendConnectionError(
                f"Cannot connect to ShopAssist backend at {self.base_url}. Ensure FastAPI is running."
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("Unexpected HTTP error communicating with FastAPI: %s", exc)
            raise BackendConnectionError(f"HTTP transport failure: {exc}") from exc

        elapsed = time.perf_counter() - start_time

        if response.status_code != 200:
            detail = response.text
            request_id = response.headers.get("x-request-id")
            try:
                error_json = response.json()
                detail = error_json.get("detail", response.text)
            except Exception:
                pass
            logger.warning(
                "FastAPI returned HTTP %d (req_id=%s, elapsed=%.2fs): %s",
                response.status_code,
                request_id,
                elapsed,
                detail,
            )
            raise BackendResponseError(
                status_code=response.status_code,
                detail=str(detail),
                request_id=request_id,
            )

        try:
            data = response.json()
        except Exception as exc:
            logger.error("Backend response is not valid JSON: %s", exc)
            raise BackendSchemaError("Backend returned invalid non-JSON payload.") from exc

        try:
            return RecommendationResponse.model_validate(data)
        except ValidationError as exc:
            logger.error("Backend response failed Pydantic validation: %s", exc)
            raise BackendSchemaError(
                f"Response schema mismatch: {exc.error_count()} validation errors",
                raw_payload=data,
            ) from exc

    async def check_health(self) -> HealthResponse:
        """Query GET /api/v1/health to verify backend readiness.

        Returns:
            Validated HealthResponse.

        Raises:
            BackendConnectionError: If health check cannot connect.
            BackendResponseError: If backend reports degraded/unhealthy status.
        """
        url = f"{self.base_url}/api/v1/health"
        try:
            response = await self._client.get(url, timeout=10.0)
            data = response.json()
            return HealthResponse.model_validate(data)
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise BackendConnectionError(f"Health check connection failed: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise BackendTimeoutError("Health check timed out.") from exc
        except Exception as exc:
            raise BackendResponseError(
                status_code=getattr(response, "status_code", 500) if "response" in locals() else 500,
                detail=str(exc),
            ) from exc

    async def aclose(self) -> None:
        """Close the underlying HTTP client session."""
        if not self._external_client and not self._client.is_closed:
            await self._client.aclose()
            logger.debug("FastAPIRecommendationClient connection pool closed.")
