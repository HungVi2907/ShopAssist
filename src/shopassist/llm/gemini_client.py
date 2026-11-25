"""Official Google Gen AI SDK client wrapper for Gemini API (Phase 8).

Handles client initialization, synchronous & asynchronous structured generation,
retry logic with exponential backoff, timeout handling, and token usage measurement.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from typing import Any, Callable, Type, TypeVar

from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel

from shopassist.llm.config import LLMSettings, llm_settings, mask_api_key
from shopassist.llm.prompts import SYSTEM_INSTRUCTION
from shopassist.llm.schemas import TokenUsageMetadata
from shopassist.llm.security import redact

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# HTTP status codes eligible for automatic retry
RETRYABLE_STATUS_CODES: set[int] = {429, 500, 502, 503, 504}


class GeminiClient:
    """Production wrapper for Google Gen AI Gemini API."""

    def __init__(self, settings: LLMSettings | None = None, *,
                 http_options: types.HttpOptions | None = None) -> None:
        """Initialize Gemini client with settings.

        Args:
            settings: LLMSettings instance or None (uses default llm_settings).
        """
        self.settings = settings or llm_settings
        self._api_key = self.settings.get_api_key()
        self._client: genai.Client | None = None
        self._http_options = http_options

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
            # One retry layer owns accounting; disable hidden SDK retries.
            self._client = genai.Client(api_key=self._api_key,
                http_options=self._http_options or types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
        return self._client

    async def generate_content_once(self, *, model: str, prompt: str,
                                    config: types.GenerateContentConfig):
        """Return the raw SDK response for gateway-owned validation/accounting."""
        return await self.client.aio.models.generate_content(model=model, contents=prompt, config=config)

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

            is_available = (target in supported_names) or (target in short_names)

            matching_model = None
            for m in models_list:
                if target == m.name or target == m.name.replace("models/", ""):
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
            logger.error("Failed to query models list from Gemini API: %s", redact(str(exc), self._api_key))
            return {
                "is_available": False,
                "target_model": target,
                "error": redact(str(exc), self._api_key),
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
        on_attempt: Callable[[], None] | None = None,
        on_response: Callable[[TokenUsageMetadata | None], None] | None = None,
        diagnostics: dict[str, Any] | None = None,
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
        total_start = time.perf_counter()
        diag = diagnostics if diagnostics is not None else {}
        diag.update(attempts=0, retry_delay_ms=0.0, api_durations_ms=[], response_received=False,
                    json_valid=None, schema_valid=None, usage_known=False, response_usages=[])

        for attempt in range(max_retries + 1):
            t_start = time.perf_counter()
            try:
                if on_attempt is not None:
                    on_attempt()
                diag["attempts"] += 1
                t_start = time.perf_counter()  # Attempt pacing is separate from API duration.
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
                diag["api_durations_ms"].append(latency_ms)
                diag["response_received"] = True
                diag["model_version"] = getattr(response, "model_version", None)

                raw_text = response.text or ""

                # Extract token usage metadata from response
                usage_meta = TokenUsageMetadata(prompt_tokens=0, candidates_tokens=0, total_tokens=0)
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    diag["usage_known"] = True
                    um = response.usage_metadata
                    usage_meta.prompt_tokens = getattr(um, "prompt_token_count", 0) or 0
                    usage_meta.candidates_tokens = getattr(um, "candidates_token_count", 0) or 0
                    usage_meta.total_tokens = getattr(um, "total_token_count", 0) or 0
                diag["token_usage"] = usage_meta.model_dump() if diag["usage_known"] else None
                diag["response_usages"].append(diag["token_usage"])
                if on_response is not None:
                    on_response(usage_meta if diag["usage_known"] else None)
                if not raw_text.strip():
                    diag["json_valid"] = False
                    raise ValueError("Gemini API returned an empty response text.")

                # Validate with Pydantic
                import json
                try:
                    json.loads(raw_text)
                    diag["json_valid"] = True
                except (ValueError, TypeError):
                    diag["json_valid"] = False
                    raise ValueError("Gemini returned malformed JSON") from None
                validation_start = time.perf_counter()
                try:
                    parsed_obj = response_schema.model_validate_json(raw_text)
                    diag["schema_valid"] = True
                except Exception:
                    diag["schema_valid"] = False
                    raise
                finally:
                    diag["validation_ms"] = (time.perf_counter()-validation_start)*1000
                    diag["end_to_end_ms"] = (time.perf_counter()-total_start)*1000

                logger.debug(
                    "Successfully parsed Gemini structured response in %.2f ms (%d tokens).",
                    latency_ms,
                    usage_meta.total_tokens,
                )
                return parsed_obj, raw_text, round(latency_ms, 2), usage_meta

            except (APIError, asyncio.TimeoutError, ConnectionError) as exc:
                last_exception = exc
                latency_ms = (time.perf_counter() - t_start) * 1000.0
                diag["api_durations_ms"].append(latency_ms)
                is_retryable = False

                if isinstance(exc, asyncio.TimeoutError):
                    is_retryable = True
                    err_msg = f"Request timed out after {self.settings.gemini_timeout_seconds}s"
                elif isinstance(exc, APIError):
                    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                    is_retryable = status_code in RETRYABLE_STATUS_CODES
                    err_msg = f"APIError {status_code}"
                else:
                    is_retryable = True
                    err_msg = "ConnectionError"
                diag["last_error_type"] = type(exc).__name__
                diag["last_status_code"] = getattr(exc, "code", None)
                diag["end_to_end_ms"] = (time.perf_counter()-total_start)*1000

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
                        retry_match = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+(?:\.\d+)?)s?", exc_str, re.IGNORECASE)
                    if retry_match:
                        required_wait = float(retry_match.group(1)) + 1.0
                        sleep_time = max(sleep_time, required_wait)
                    elif "429" in exc_str or "quota" in exc_str.lower():
                        sleep_time = max(sleep_time, 8.0 * (attempt + 1))

                    logger.info("Backing off for %.2f seconds before retry...", sleep_time)
                    diag["retry_delay_ms"] += sleep_time*1000
                    await asyncio.sleep(sleep_time)
                else:
                    break

            except Exception as non_retry_exc:
                diag["end_to_end_ms"] = (time.perf_counter()-total_start)*1000
                diag["last_error_type"] = type(non_retry_exc).__name__
                logger.error("Non-retryable error during Gemini structured generation: %s", type(non_retry_exc).__name__)
                raise

        raise RuntimeError(
            f"Failed to generate structured content from Gemini after {diag['attempts']} attempts. "
            f"Last error type: {type(last_exception).__name__}"
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
        async def generate_and_close():
            try:
                return await self.generate_structured_async(
                prompt=prompt,
                response_schema=response_schema,
                system_instruction=system_instruction,
                model_name=model_name,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                )
            finally:
                await self.aclose()
        return asyncio.run(generate_and_close())

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
                self._client.close()
                self._client = None
                # aiohttp HTTPS transports need time to drain before loop shutdown.
                if os.name == "nt":
                    await asyncio.sleep(0.25)
                logger.debug("Gemini client aio session closed successfully.")
            except Exception as exc:
                logger.debug("Error closing Gemini aio session: %s", type(exc).__name__)

    async def close(self) -> None:
        """Alias for aclose() to support standard closing convention."""
        await self.aclose()
