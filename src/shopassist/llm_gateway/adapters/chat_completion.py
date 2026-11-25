"""Single-request OpenAI-compatible transport for Gateway adapters."""
from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

import httpx

from shopassist.llm_gateway.adapters.base import AdapterResult, PreparedRequest
from shopassist.llm_gateway.errors import ErrorCategory, ProviderAttemptError, ReasonCode
from shopassist.llm_gateway.registry import ResolvedRoute
from shopassist.llm_gateway.schemas import GatewayRequest, GatewayUsage


def failure(category, *, status=None, usage=None, retry_after=None):
    return ProviderAttemptError(
        category=category, reason_code=ReasonCode(category.value), http_status=status,
        usage=usage, retry_after_s=retry_after,
    )


def strict_schema(schema):
    """Project Pydantic JSON schema to strict structured-output object shape."""
    if isinstance(schema, list):
        return [strict_schema(value) for value in schema]
    if not isinstance(schema, dict):
        return schema
    result = {key: strict_schema(value) for key, value in schema.items() if key != "default"}
    if result.get("type") == "object":
        result["additionalProperties"] = False
        result["required"] = list(result.get("properties", {}))
    return result


def retry_after_seconds(value):
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


class ChatCompletionAdapter:
    kind: str

    def __init__(self, credential: Callable[[], str], *, transport: httpx.AsyncBaseTransport | None = None):
        self._credential = credential
        self._client = httpx.AsyncClient(
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
            trust_env=False, follow_redirects=False,
        )
        self._identity = None
        self._closed = False

    def prepare(self, request: GatewayRequest, route: ResolvedRoute) -> PreparedRequest:
        if route.provider != self.kind or route.structured_mode not in {"json_schema", "json_object"} or request.schema_id not in route.schema_ids:
            raise failure(ErrorCategory.INCOMPATIBLE_ROUTE)
        response_format = {"type": route.structured_mode}
        if route.structured_mode == "json_schema":
            response_format["json_schema"] = {
                "name": request.schema_id.replace(".", "_"), "strict": True,
                "schema": strict_schema(request.response_schema.model_json_schema()),
            }
        body = {
            "model": route.model,
            "messages": [{"role": "system", "content": request.system_prompt},
                         {"role": "user", "content": request.user_prompt}],
            "response_format": response_format,
        }
        token_parameter = "max_completion_tokens" if self.kind == "groq" else "max_tokens"
        body[token_parameter] = route.options["max_output_tokens"]
        if route.options.get("temperature") is not None:
            body["temperature"] = route.options["temperature"]
        if self.kind == "groq" and route.options.get("reasoning_effort") is not None:
            body["reasoning_effort"] = route.options["reasoning_effort"]
        if self.kind == "openrouter":
            body["provider"] = {"allow_fallbacks": False}
        return PreparedRequest(route, request, json.dumps(body).encode("utf-8"))

    async def complete_once(self, prepared: PreparedRequest, *, timeout_s: float,
                            on_dispatch: Callable[[], None]) -> AdapterResult:
        if self._closed or timeout_s <= 0 or not math.isfinite(timeout_s):
            raise failure(ErrorCategory.INVALID_REQUEST)
        route = prepared.route
        identity = (route.provider_profile, route.endpoint)
        if self._identity is not None and self._identity != identity:
            raise failure(ErrorCategory.INCOMPATIBLE_ROUTE)
        try:
            key = self._credential()
            if not key or not key.strip():
                raise failure(ErrorCategory.AUTHENTICATION)
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        except ProviderAttemptError:
            raise
        except Exception:
            raise failure(ErrorCategory.INTERNAL_ERROR) from None
        self._identity = identity
        on_dispatch()
        try:
            response = await asyncio.wait_for(self._client.post(
                route.endpoint.rstrip("/") + "/chat/completions",
                content=prepared.body, headers=headers, timeout=timeout_s,
            ), timeout=timeout_s)
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise failure(ErrorCategory.ATTEMPT_TIMEOUT) from None
        except httpx.NetworkError:
            raise failure(ErrorCategory.NETWORK_ERROR) from None
        except Exception:
            raise failure(ErrorCategory.INTERNAL_ERROR) from None
        return self._result(response)

    @staticmethod
    def _result(response):
        status = response.status_code
        if status != 200:
            category = {
                401: ErrorCategory.AUTHENTICATION, 403: ErrorCategory.PERMISSION_DENIED,
                404: ErrorCategory.INCOMPATIBLE_ROUTE, 408: ErrorCategory.ATTEMPT_TIMEOUT,
                429: ErrorCategory.RATE_LIMITED,
            }.get(status, ErrorCategory.PROVIDER_UNAVAILABLE if status >= 500 else ErrorCategory.PROVIDER_REJECTED)
            raise failure(category, status=status, retry_after=retry_after_seconds(response.headers.get("retry-after")))
        usage = GatewayUsage()
        try:
            envelope = response.json()
            metadata = envelope.get("usage") or {}
            usage = GatewayUsage(
                input_tokens=metadata.get("prompt_tokens"),
                output_tokens=metadata.get("completion_tokens"),
                total_tokens=metadata.get("total_tokens"),
                reasoning_tokens=(metadata.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            )
            message = envelope["choices"][0]["message"]
            if message.get("refusal"):
                raise failure(ErrorCategory.PROVIDER_REJECTED, status=status, usage=usage)
            text = message.get("content")
            if not isinstance(text, str) or not text.strip() or len(text) > 1_000_000:
                raise failure(ErrorCategory.INVALID_OUTPUT, status=status, usage=usage)
            return AdapterResult(raw_text=text, usage=usage, http_status=status,
                                 reported_model=envelope.get("model"))
        except ProviderAttemptError:
            raise
        except Exception:
            raise failure(ErrorCategory.INVALID_OUTPUT, status=status, usage=usage) from None

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self._client.aclose()
