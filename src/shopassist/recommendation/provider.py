"""Recommendation LLM provider transport and client integrations (Phase 12).

Supports:
1. OpenRouter (default: google/gemma-4-26b-a4b-it:free) via standard OpenAI-compatible async REST.
2. Groq (openai/gpt-oss-20b) via official AsyncGroq SDK.

Handles JSON parsing (including markdown fence stripping), bounded exponential retries,
rate-limit backoff, token usage metrics, and cost calculation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Mapping, Protocol

import httpx

from shopassist.recommendation.config import RecommendationSettings, get_recommendation_settings
from shopassist.recommendation.schemas import LLMRecommendationPayload, TokenUsage

logger = logging.getLogger(__name__)

# Strict JSON Schema defining the expected output structure
RECOMMENDATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {
            "type": "string",
            "description": "Natural language summary introducing the recommendations in the user's language.",
        },
        "products": {
            "type": "array",
            "description": "Ordered explanations for each provided candidate product.",
            "items": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Exact product ID matching one of the candidate products.",
                    },
                    "summary_reason": {
                        "type": "string",
                        "description": "1-2 sentences explaining why this product satisfies user requirements.",
                    },
                    "strengths": {
                        "type": "array",
                        "description": "Verified claims supported by cited evidence IDs.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "claim": {"type": "string"},
                                "evidence_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["claim", "evidence_ids"],
                            "additionalProperties": False,
                        },
                    },
                    "limitations": {
                        "type": "array",
                        "description": "Limitations or missing specifications (empty evidence_ids if not specified).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "claim": {"type": "string"},
                                "evidence_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["claim", "evidence_ids"],
                            "additionalProperties": False,
                        },
                    },
                    "comparison_note": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Brief comparative note against other candidates, or null.",
                    },
                },
                "required": [
                    "product_id",
                    "summary_reason",
                    "strengths",
                    "limitations",
                    "comparison_note",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "products"],
    "additionalProperties": False,
}

# Alias for backwards compatibility
GROQ_STRICT_RECOMMENDATION_SCHEMA = RECOMMENDATION_JSON_SCHEMA


def clean_json_content(content: str) -> str:
    """Strip markdown code fences (```json ... ```) or whitespace from LLM output."""
    raw = content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


def parse_recommendation_payload(content: str) -> LLMRecommendationPayload:
    """Parse raw LLM string output into a validated LLMRecommendationPayload.

    Handles markdown fences and unwraps single-item list responses if generated.
    """
    if not content or not content.strip():
        raise RuntimeError("LLM provider returned empty completion content")

    cleaned = clean_json_content(content)
    try:
        raw_val = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Failed to parse LLM response as JSON: {err}. Raw: {content[:200]}") from err

    # If the model wrapped the payload in a single-element list, unwrap it
    if isinstance(raw_val, list) and len(raw_val) == 1 and isinstance(raw_val[0], dict):
        raw_val = raw_val[0]

    if not isinstance(raw_val, dict):
        raise RuntimeError(f"Expected JSON object for recommendation payload, got {type(raw_val).__name__}")

    # Normalize 'recommendations' alias to 'products' if present
    if "products" not in raw_val and "recommendations" in raw_val:
        raw_val["products"] = raw_val.pop("recommendations")

    # If the model emitted strengths or limitations as strings instead of dicts, normalize them
    if isinstance(raw_val.get("products"), list):
        for prod in raw_val["products"]:
            if isinstance(prod, dict):
                for field in ("strengths", "limitations"):
                    if field in prod and isinstance(prod[field], list):
                        normalized_items = []
                        for item in prod[field]:
                            if isinstance(item, str):
                                eids = re.findall(r"([A-Za-z0-9_\-]+-E\d+)", item)
                                clean_text = re.sub(r"\[\s*([^\]]*)\s*\]", "", item).strip()
                                normalized_items.append({"claim": clean_text or item, "evidence_ids": eids})
                            else:
                                normalized_items.append(item)
                        prod[field] = normalized_items

    try:
        return LLMRecommendationPayload.model_validate(raw_val)
    except Exception as parse_err:
        raise RuntimeError(f"Failed to validate LLM response against schema: {parse_err}") from parse_err


class BaseRecommendationProvider:
    """Base class for recommendation LLM providers."""

    def __init__(self, settings: RecommendationSettings | None = None) -> None:
        self.settings = settings or get_recommendation_settings()

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated cost in USD based on configured token pricing."""
        in_cost_per_m = self.settings.phase12_cost_input_per_m or 0.0
        out_cost_per_m = self.settings.phase12_cost_output_per_m or 0.0
        prompt_cost = (prompt_tokens / 1_000_000.0) * in_cost_per_m
        completion_cost = (completion_tokens / 1_000_000.0) * out_cost_per_m
        return round(prompt_cost + completion_cost, 6)

    async def generate_recommendation_payload(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[LLMRecommendationPayload, TokenUsage]:
        raise NotImplementedError


class OpenRouterProvider(BaseRecommendationProvider):
    """Manages asynchronous calls to OpenRouter API (e.g. google/gemma-4-26b-a4b-it:free)."""

    def __init__(
        self,
        settings: RecommendationSettings | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(settings)
        self._http_client = http_client

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.phase12_llm_timeout_seconds),
            )
        return self._http_client

    async def generate_recommendation_payload(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[LLMRecommendationPayload, TokenUsage]:
        """Execute chat completion with OpenRouter using JSON schema response format."""
        api_key = self.settings.get_api_key()
        client = self._get_http_client()

        endpoint = f"{self.settings.openrouter_base_url.rstrip('/')}/chat/completions"
        headers: dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.openrouter_http_referer:
            headers["HTTP-Referer"] = self.settings.openrouter_http_referer
        if self.settings.openrouter_app_title:
            headers["X-Title"] = self.settings.openrouter_app_title

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Use json_schema response format (supported by OpenRouter for Gemma 4)
        response_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": "recommendation_payload",
                "strict": True,
                "schema": RECOMMENDATION_JSON_SCHEMA,
            },
        }

        # Request payload: Do NOT include Groq-specific reasoning_effort
        payload_data: dict[str, Any] = {
            "model": self.settings.phase12_llm_model,
            "messages": messages,
            "response_format": response_format,
            "max_tokens": self.settings.phase12_llm_max_completion_tokens,
        }

        retries = 0
        max_retries = self.settings.phase12_llm_max_retries
        backoff_delay = 1.0

        while True:
            start_time = time.perf_counter()
            try:
                response = await client.post(endpoint, headers=headers, json=payload_data)
                latency_ms = (time.perf_counter() - start_time) * 1000.0

                # 429 Rate Limit handling
                if response.status_code == 429:
                    retries += 1
                    if retries > max_retries:
                        raise RuntimeError(
                            f"OpenRouter API rate limit (429) exceeded after {max_retries} retries: {response.text[:300]}"
                        )
                    retry_header = response.headers.get("retry-after")
                    sleep_s = backoff_delay
                    if retry_header and retry_header.isdigit():
                        sleep_s = max(float(retry_header), sleep_s)
                    logger.warning(
                        f"Rate limited by OpenRouter. Retrying in {sleep_s:.1f}s (attempt {retries}/{max_retries})..."
                    )
                    await asyncio.sleep(sleep_s)
                    backoff_delay *= 2.0
                    continue

                # 5xx Server Error handling
                if response.status_code in (500, 502, 503, 504):
                    if retries < max_retries:
                        retries += 1
                        logger.warning(
                            f"OpenRouter HTTP {response.status_code} error. Retrying in {backoff_delay:.1f}s..."
                        )
                        await asyncio.sleep(backoff_delay)
                        backoff_delay *= 2.0
                        continue
                    else:
                        raise RuntimeError(
                            f"OpenRouter API server error (HTTP {response.status_code}): {response.text[:300]}"
                        )

                # 400 Bad Request: if json_schema was rejected, try with generic json_object
                if response.status_code == 400 and payload_data.get("response_format", {}).get("type") == "json_schema":
                    logger.warning("OpenRouter rejected json_schema; retrying with generic json_object mode...")
                    payload_data["response_format"] = {"type": "json_object"}
                    continue

                # Other 4xx Client Errors fail immediately
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"OpenRouter API error (HTTP {response.status_code}): {response.text[:300]}"
                    )

                resp_json = response.json()
                choices = resp_json.get("choices", [])
                if not choices:
                    raise RuntimeError(f"OpenRouter returned empty choices: {resp_json}")

                content = choices[0].get("message", {}).get("content", "")
                payload = parse_recommendation_payload(content)

                # Token usage extraction
                usage_meta = resp_json.get("usage") or {}
                prompt_tokens = usage_meta.get("prompt_tokens", 0) or 0
                completion_tokens = usage_meta.get("completion_tokens", 0) or 0
                total_tokens = usage_meta.get("total_tokens", prompt_tokens + completion_tokens) or 0
                reasoning_tokens = (
                    usage_meta.get("completion_tokens_details", {}).get("reasoning_tokens", 0) or 0
                )

                estimated_cost = self.calculate_cost(prompt_tokens, completion_tokens)

                usage = TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    reasoning_tokens=reasoning_tokens,
                    latency_ms=round(latency_ms, 2),
                    estimated_cost_usd=estimated_cost,
                )

                return payload, usage

            except httpx.TimeoutException as timeout_err:
                retries += 1
                if retries > max_retries:
                    raise RuntimeError(
                        f"OpenRouter timeout after {max_retries} retries ({self.settings.phase12_llm_timeout_seconds}s timeout)"
                    ) from timeout_err
                logger.warning(f"OpenRouter timeout error: {timeout_err}. Retrying in {backoff_delay:.1f}s...")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2.0

            except httpx.NetworkError as net_err:
                retries += 1
                if retries > max_retries:
                    raise RuntimeError(
                        f"OpenRouter network error after {max_retries} retries: {net_err}"
                    ) from net_err
                logger.warning(f"OpenRouter network error: {net_err}. Retrying in {backoff_delay:.1f}s...")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2.0


class GroqProvider(BaseRecommendationProvider):
    """Manages asynchronous calls to the Groq Cloud API."""

    def __init__(
        self,
        settings: RecommendationSettings | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        super().__init__(settings)
        self._client = client

    def _get_client(self) -> Any:
        """Lazily initialize the AsyncGroq client."""
        if self._client is None:
            from groq import AsyncGroq
            api_key = self.settings.get_api_key()
            self._client = AsyncGroq(
                api_key=api_key,
                timeout=httpx.Timeout(self.settings.phase12_llm_timeout_seconds),
            )
        return self._client

    async def generate_recommendation_payload(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[LLMRecommendationPayload, TokenUsage]:
        """Execute chat completion with Groq using JSON Schema Strict Mode."""
        from groq import APIConnectionError, APIStatusError, RateLimitError

        client = self._get_client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "recommendation_payload",
                "strict": True,
                "schema": RECOMMENDATION_JSON_SCHEMA,
            },
        }

        retries = 0
        max_retries = self.settings.phase12_llm_max_retries
        backoff_delay = 1.0

        while True:
            start_time = time.perf_counter()
            try:
                response = await client.chat.completions.create(
                    model=self.settings.phase12_llm_model,
                    messages=messages,
                    response_format=response_format,
                    max_completion_tokens=self.settings.phase12_llm_max_completion_tokens,
                    reasoning_effort=self.settings.phase12_llm_reasoning_effort,
                )
                latency_ms = (time.perf_counter() - start_time) * 1000.0

                choice = response.choices[0]
                content = choice.message.content
                payload = parse_recommendation_payload(content)

                usage_meta = response.usage
                prompt_tokens = getattr(usage_meta, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage_meta, "completion_tokens", 0) or 0
                total_tokens = getattr(usage_meta, "total_tokens", prompt_tokens + completion_tokens) or 0

                reasoning_tokens = 0
                tokens_details = getattr(usage_meta, "completion_tokens_details", None)
                if tokens_details:
                    reasoning_tokens = getattr(tokens_details, "reasoning_tokens", 0) or 0

                estimated_cost = self.calculate_cost(prompt_tokens, completion_tokens)

                usage = TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    reasoning_tokens=reasoning_tokens,
                    latency_ms=round(latency_ms, 2),
                    estimated_cost_usd=estimated_cost,
                )

                return payload, usage

            except RateLimitError as rle:
                retries += 1
                if retries > max_retries:
                    raise RuntimeError(f"Groq API rate limit exceeded after {max_retries} retries: {rle}") from rle
                retry_after = getattr(rle, "response", None)
                sleep_s = backoff_delay
                if retry_after and hasattr(retry_after, "headers"):
                    header_val = retry_after.headers.get("retry-after")
                    if header_val and header_val.isdigit():
                        sleep_s = max(float(header_val), sleep_s)
                logger.warning(f"Rate limited by Groq API. Retrying in {sleep_s:.1f}s (attempt {retries}/{max_retries})...")
                await asyncio.sleep(sleep_s)
                backoff_delay *= 2.0

            except (APIConnectionError, httpx.TimeoutException) as conn_err:
                retries += 1
                if retries > max_retries:
                    raise RuntimeError(f"Groq API connection/timeout error after {max_retries} retries: {conn_err}") from conn_err
                logger.warning(f"Groq connection error: {conn_err}. Retrying in {backoff_delay:.1f}s...")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2.0

            except APIStatusError as status_err:
                status_code = status_err.status_code
                if status_code in (500, 502, 503, 504) and retries < max_retries:
                    retries += 1
                    logger.warning(f"Groq HTTP {status_code} server error. Retrying in {backoff_delay:.1f}s...")
                    await asyncio.sleep(backoff_delay)
                    backoff_delay *= 2.0
                else:
                    raise RuntimeError(f"Groq API status error (HTTP {status_code}): {status_err.message}") from status_err

            except Exception as e:
                raise RuntimeError(f"Unexpected Groq API error: {e}") from e


def get_recommendation_provider(
    settings: RecommendationSettings | None = None,
) -> BaseRecommendationProvider:
    """Factory creating the appropriate recommendation provider according to settings."""
    s = settings or get_recommendation_settings()
    provider_name = s.phase12_llm_provider.lower()
    if provider_name == "openrouter":
        return OpenRouterProvider(settings=s)
    elif provider_name == "groq":
        return GroqProvider(settings=s)
    else:
        raise ValueError(
            f"Unsupported recommendation provider: '{provider_name}'. Must be 'openrouter' or 'groq'."
        )
