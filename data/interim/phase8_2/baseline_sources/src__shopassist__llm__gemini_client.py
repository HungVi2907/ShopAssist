"""Official Google Gen AI SDK client wrapper for Gemini API (Phase 8).

Handles client initialization, synchronous & asynchronous structured generation,
retry logic with exponential backoff, timeout handling, and token usage measurement.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from typing import Any, Type, TypeVar

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel

from shopassist.llm.config import LLMSettings, llm_settings, mask_api_key
from shopassist.llm.prompts import SYSTEM_INSTRUCTION
from shopassist.llm.schemas import TokenUsageMetadata

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# HTTP status codes eligible for automatic retry
RETRYABLE_STATUS_CODES: set[int] = {429, 500, 502, 503, 504}


class GeminiClient:
    """Production wrapper for Google Gen AI Gemini API."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        """Initialize Gemini client with settings.

        Args:
            settings: LLMSettings instance or None (uses default llm_settings).
        """
        self.settings = settings or llm_settings
        self._api_key = self.settings.get_api_key()
        self._client: genai.Client | None = None

        logger.info(
            "Initializing GeminiClient with model '%s' (temperature=%.1f, timeout=%.1fs, max_retries=%d)...",
            self.settings.gemini_model,
            self.settings.gemini_temperature,
            self.settings.gemini_timeout_seconds,
            self.settings.gemini_max_retries,
        )

    @property
    def client(self) -> genai.Client:
        """Lazily initialize and return the underlying genai.Client."""
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def verify_model_availability(self, model_name: str | None = None) -> dict[str, Any]:
        """Verify if the requested model is accessible via the current API key.

        Args:
            model_name: Model identifier or None (uses settings.gemini_model).

        Returns:
            Dictionary with verification status, model details, and supported models list.
        """
        target = model_name or self.settings.gemini_model
        try:
            models_list = list(self.client.models.list())
            supported_names = [m.name for m in models_list]
            short_names = [m.name.replace("models/", "") for m in models_list]

            is_available = (target in supported_names) or (target in short_names) or any(target in name for name in supported_names)

            matching_model = None
            for m in models_list:
                if target in m.name or target == m.name.replace("models/", ""):
                    matching_model = m
                    break

            return {
                "is_available": is_available,
                "target_model": target,
                "verified_model_name": matching_model.name if matching_model else None,
                "total_models_available": len(models_list),
                "supported_gemini_models": sorted([m.name for m in models_list if "gemini" in m.name.lower()]),
            }
        except Exception as exc:
            logger.error("Failed to query models list from Gemini API: %s", exc)
            return {
                "is_available": False,
                "target_model": target,
                "error": str(exc),
                "total_models_available": 0,
                "supported_gemini_models": [],
            }

    async def generate_structured_async(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: str = SYSTEM_INSTRUCTION,
        model_name: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> tuple[T, str, float, TokenUsageMetadata]:
        """Asynchronously generate schema-constrained JSON content from Gemini API with retries.

        Args:
            prompt: User prompt content.
            response_schema: Pydantic model class defining desired output JSON structure.
            system_instruction: System prompt guidelines.
            model_name: Optional model override.
            temperature: Optional temperature override.
            max_output_tokens: Optional token limit override.

        Returns:
            Tuple of (parsed Pydantic instance, raw JSON text, latency in ms, TokenUsageMetadata).

        Raises:
            APIError: If API call fails after retries exhausted or is non-retryable.
            ValueError: If response is empty or cannot be parsed.
        """
        model = model_name or self.settings.gemini_model
        temp = self.settings.gemini_temperature if temperature is None else temperature
        max_tokens = self.settings.gemini_max_output_tokens if max_output_tokens is None else max_output_tokens
        max_retries = self.settings.gemini_max_retries

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=temp,
            max_output_tokens=max_tokens,
        )

        last_exception: Exception | None = None
        base_delay = 1.0

        for attempt in range(max_retries + 1):
            t_start = time.perf_counter()
            try:
                logger.debug(
                    "Sending structured generation request to Gemini (model=%s, attempt=%d/%d)...",
                    model,
                    attempt + 1,
                    max_retries + 1,
                )

                # Execute asynchronous generation with timeout
                response = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=config,
                    ),
                    timeout=self.settings.gemini_timeout_seconds,
                )

                latency_ms = (time.perf_counter() - t_start) * 1000.0

                raw_text = response.text or ""
                if not raw_text.strip():
                    raise ValueError("Gemini API returned an empty response text.")

                # Extract token usage metadata from response
                usage_meta = TokenUsageMetadata(prompt_tokens=0, candidates_tokens=0, total_tokens=0)
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    um = response.usage_metadata
                    usage_meta.prompt_tokens = getattr(um, "prompt_token_count", 0) or 0
                    usage_meta.candidates_tokens = getattr(um, "candidates_token_count", 0) or 0
                    usage_meta.total_tokens = getattr(um, "total_token_count", 0) or 0

                # Validate with Pydantic
                parsed_obj = response_schema.model_validate_json(raw_text)

                logger.debug(
                    "Successfully parsed Gemini structured response in %.2f ms (%d tokens).",
                    latency_ms,
                    usage_meta.total_tokens,
                )
                return parsed_obj, raw_text, round(latency_ms, 2), usage_meta

            except (APIError, asyncio.TimeoutError, ConnectionError) as exc:
                last_exception = exc
                latency_ms = (time.perf_counter() - t_start) * 1000.0
                is_retryable = False

                if isinstance(exc, asyncio.TimeoutError):
                    is_retryable = True
                    err_msg = f"Request timed out after {self.settings.gemini_timeout_seconds}s"
                elif isinstance(exc, APIError):
                    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                    is_retryable = status_code in RETRYABLE_STATUS_CODES or "429" in str(exc) or "quota" in str(exc).lower()
                    err_msg = f"APIError {status_code}: {exc}"
                else:
                    is_retryable = True
                    err_msg = f"ConnectionError: {exc}"

                logger.warning(
                    "Gemini API attempt %d/%d failed (retryable=%s, latency=%.2f ms): %s",
                    attempt + 1,
                    max_retries + 1,
                    is_retryable,
                    latency_ms,
                    err_msg,
                )

                if attempt < max_retries and is_retryable:
                    sleep_time = (base_delay * (2 ** attempt)) + random.uniform(0.1, 0.5)
                    # Extract explicit retry delay from 429 rate limit errors if available
                    exc_str = str(exc)
                    retry_match = re.search(r"retry in (\d+(?:\.\d+)?)s", exc_str, re.IGNORECASE)
                    if not retry_match:
                        retry_match = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+)s?", exc_str, re.IGNORECASE)
                    if retry_match:
                        required_wait = float(retry_match.group(1)) + 1.0
                        sleep_time = max(sleep_time, required_wait)
                    elif "429" in exc_str or "quota" in exc_str.lower():
                        sleep_time = max(sleep_time, 8.0 * (attempt + 1))

                    logger.info("Backing off for %.2f seconds before retry...", sleep_time)
                    await asyncio.sleep(sleep_time)
                else:
                    break

            except Exception as non_retry_exc:
                logger.error("Non-retryable error during Gemini structured generation: %s", non_retry_exc)
                raise

        raise RuntimeError(
            f"Failed to generate structured content from Gemini after {max_retries + 1} attempts. "
            f"Last error: {last_exception}"
        ) from last_exception

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: str = SYSTEM_INSTRUCTION,
        model_name: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> tuple[T, str, float, TokenUsageMetadata]:
        """Synchronously generate schema-constrained JSON content from Gemini API."""
        return asyncio.run(
            self.generate_structured_async(
                prompt=prompt,
                response_schema=response_schema,
                system_instruction=system_instruction,
                model_name=model_name,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        )

    async def list_available_models(self) -> list[str]:
        """Asynchronously retrieve list of available model names from Gemini API."""
        loop = asyncio.get_running_loop()
        models = await loop.run_in_executor(None, lambda: [m.name for m in self.client.models.list()])
        return models

    async def aclose(self) -> None:
        """Cleanly close underlying asynchronous client sessions and SSL transports."""
        if self._client is not None and hasattr(self._client, "aio"):
            try:
                await self._client.aio.aclose()
                logger.debug("Gemini client aio session closed successfully.")
            except Exception as exc:
                logger.debug("Error closing Gemini aio session: %s", exc)

    async def close(self) -> None:
        """Alias for aclose() to support standard closing convention."""
        await self.aclose()
