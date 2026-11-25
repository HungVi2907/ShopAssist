"""Single-call Gemini adapter using the existing Gemini client transport."""
from __future__ import annotations

import asyncio
import json
import math
from typing import Callable

import httpx
from google.genai import types
from google.genai.errors import APIError

from shopassist.llm.config import LLMSettings
from shopassist.llm.gemini_client import GeminiClient
from shopassist.llm_gateway.adapters.base import AdapterResult, PreparedRequest
from shopassist.llm_gateway.errors import ErrorCategory, ProviderAttemptError, ReasonCode
from shopassist.llm_gateway.registry import ResolvedRoute
from shopassist.llm_gateway.schemas import GatewayRequest, GatewayUsage


def _failure(category: ErrorCategory, *, status=None, usage=None):
    return ProviderAttemptError(category=category, reason_code=ReasonCode(category.value),
                                http_status=status, usage=usage)


class GeminiAdapter:
    def __init__(self, credential: Callable[[], str], *, client: GeminiClient | None = None):
        self._credential = credential
        self._client = client
        self._closed = False
        self._endpoint: str | None = None

    def prepare(self, request: GatewayRequest, route: ResolvedRoute) -> PreparedRequest:
        if route.provider != "gemini" or route.structured_mode != "gemini_schema" or request.schema_id not in route.schema_ids:
            raise _failure(ErrorCategory.INCOMPATIBLE_ROUTE)
        body = json.dumps({
            "system_instruction": request.system_prompt,
            "response_mime_type": "application/json",
            "response_json_schema": request.response_schema.model_json_schema(),
            "temperature": route.options.get("temperature"),
            "max_output_tokens": route.options["max_output_tokens"],
        }).encode("utf-8")
        return PreparedRequest(route, request, body)

    async def complete_once(self, prepared: PreparedRequest, *, timeout_s: float,
                            on_dispatch: Callable[[], None]) -> AdapterResult:
        if self._closed or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise _failure(ErrorCategory.INVALID_REQUEST)
        config = types.GenerateContentConfig(**json.loads(prepared.body))
        route = prepared.route
        if self._endpoint is not None and self._endpoint != route.endpoint:
            raise _failure(ErrorCategory.INCOMPATIBLE_ROUTE)
        try:
            if self._client is None:
                key = self._credential()
                if not key or not key.strip():
                    raise _failure(ErrorCategory.AUTHENTICATION)
                settings = LLMSettings(
                    _env_file=None, gemini_api_key=key, gemini_model=route.model,
                    gemini_temperature=route.options.get("temperature") or 0,
                    gemini_max_output_tokens=route.options["max_output_tokens"],
                    gemini_timeout_seconds=timeout_s, gemini_max_retries=0,
                )
                self._client = GeminiClient(settings, http_options=types.HttpOptions(
                    base_url=route.endpoint, retry_options=types.HttpRetryOptions(attempts=1),
                    client_args={"trust_env": False, "follow_redirects": False,
                                 "transport": httpx.HTTPTransport(retries=0)},
                    async_client_args={"trust_env": False, "follow_redirects": False,
                                       "transport": httpx.AsyncHTTPTransport(retries=0)},
                ))
            self._endpoint = route.endpoint
            # Initialize locally before counting the provider submission.
            self._client.client
        except ProviderAttemptError:
            raise
        except Exception:
            raise _failure(ErrorCategory.INTERNAL_ERROR) from None
        on_dispatch()
        try:
            response = await asyncio.wait_for(self._client.generate_content_once(
                model=route.model, prompt=prepared.request.user_prompt, config=config,
            ), timeout=timeout_s)
        except APIError as exc:
            status = exc.code
            category = {
                401: ErrorCategory.AUTHENTICATION, 403: ErrorCategory.PERMISSION_DENIED,
                429: ErrorCategory.RATE_LIMITED, 408: ErrorCategory.ATTEMPT_TIMEOUT,
                404: ErrorCategory.INCOMPATIBLE_ROUTE,
            }.get(status, ErrorCategory.PROVIDER_UNAVAILABLE if status and status >= 500 else ErrorCategory.PROVIDER_REJECTED)
            raise _failure(category, status=status) from None
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise _failure(ErrorCategory.ATTEMPT_TIMEOUT) from None
        except (ConnectionError, httpx.NetworkError):
            raise _failure(ErrorCategory.NETWORK_ERROR) from None
        except Exception:
            raise _failure(ErrorCategory.INTERNAL_ERROR) from None
        return self._result(response)

    @staticmethod
    def _result(response) -> AdapterResult:
        metadata = getattr(response, "usage_metadata", None)
        usage = GatewayUsage(
            input_tokens=getattr(metadata, "prompt_token_count", None),
            output_tokens=getattr(metadata, "candidates_token_count", None),
            total_tokens=getattr(metadata, "total_token_count", None),
            reasoning_tokens=getattr(metadata, "thoughts_token_count", None),
        )
        try:
            text = response.text or ""
        except Exception:
            raise _failure(ErrorCategory.INVALID_OUTPUT, usage=usage) from None
        if not text.strip() or len(text) > 1_000_000:
            raise _failure(ErrorCategory.INVALID_OUTPUT, usage=usage)
        return AdapterResult(raw_text=text, usage=usage, http_status=200,
                             reported_model=getattr(response, "model_version", None))

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            if self._client is not None:
                await self._client.aclose()
