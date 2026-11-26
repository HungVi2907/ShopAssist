"""Core Query Understanding Engine for ShopAssist (Phase 8).

Orchestrates input validation, Gemini API prompt execution, Pydantic schema validation,
category & brand normalization, business rules enforcement, and diagnostic reporting.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
import time
from typing import Any, Callable

import pandas as pd

from shopassist.core.config import PROCESSED_DATA_DIR
from shopassist.llm.config import LLMSettings, llm_settings
from shopassist.llm.gemini_client import GeminiClient
from shopassist.llm_gateway.errors import GatewayError
from shopassist.llm_gateway.gateway import Gateway
from shopassist.llm_gateway.schemas import GatewayRequest, SCHEMA_IDS, TaskType
from shopassist.llm.normalization import validate_and_normalize_output
from shopassist.llm.prompts import SYSTEM_INSTRUCTION, build_user_prompt
from shopassist.llm.schemas import (
    HardConstraints,
    QueryUnderstandingOutput,
    QueryUnderstandingResult,
    TokenUsageMetadata,
)

logger = logging.getLogger(__name__)

MAX_QUERY_LENGTH: int = 500
CANONICAL_PARQUET_PATH = PROCESSED_DATA_DIR / "products.parquet"


def load_catalog_brands_set() -> set[str]:
    """Load known catalog brands from canonical Parquet if available."""
    try:
        if CANONICAL_PARQUET_PATH.exists():
            df = pd.read_parquet(CANONICAL_PARQUET_PATH, columns=["brand"])
            return set(df["brand"].dropna().unique().tolist())
    except Exception as exc:
        logger.debug("Could not load catalog brands from Parquet: %s", exc)
    return set()


class QueryUnderstandingEngine:
    """Production Query Understanding Engine powered by Google Gemini."""

    def __init__(
        self,
        client: GeminiClient | None = None,
        gateway: Gateway | None = None,
        settings: LLMSettings | None = None,
        catalog_brands: set[str] | None = None,
        *,
        intent_extractor=None,
    ) -> None:
        """Initialize Query Understanding engine.

        Args:
            client: Optional pre-configured GeminiClient.
            settings: Optional LLMSettings instance.
            catalog_brands: Optional pre-loaded set of catalog brands.
        """
        self.settings = settings or llm_settings
        self._client = client
        self.gateway = gateway
        if intent_extractor is not None and gateway is not None:
            raise ValueError('Experimental native extraction cannot use Gateway routes.')
        self.intent_extractor = intent_extractor
        self._catalog_brands = catalog_brands if catalog_brands is not None else load_catalog_brands_set()
        logger.info(
            "QueryUnderstandingEngine initialized with %d catalog brands.",
            len(self._catalog_brands),
        )

    @property
    def client(self) -> GeminiClient:
        """Lazily initialize GeminiClient."""
        if self._client is None:
            self._client = GeminiClient(settings=self.settings)
        return self._client

    def validate_input_query(self, query: Any) -> str:
        """Validate input query type and bounds.

        Args:
            query: Raw user query input.

        Returns:
            Stripped query string.

        Raises:
            TypeError: If query is not a string.
            ValueError: If query is empty or exceeds max length.
        """
        if not isinstance(query, str) or isinstance(query, bool):
            raise TypeError(f"Query must be a string, got {type(query).__name__}")

        clean = query.strip()
        if not clean:
            raise ValueError("Query cannot be empty or whitespace-only.")

        if len(clean) > MAX_QUERY_LENGTH:
            raise ValueError(
                f"Query length ({len(clean)} chars) exceeds maximum allowed limit of {MAX_QUERY_LENGTH} chars."
            )

        return clean

    async def parse_query_async(
        self,
        query: str,
        system_instruction: str = SYSTEM_INSTRUCTION,
        *,
        request_id: str | None = None,
        task_id: str | None = None,
        parent_deadline_mono: float | None = None,
    ) -> QueryUnderstandingResult:
        """Asynchronously parse natural language query into structured QueryUnderstandingResult.

        Args:
            query: User shopping query.
            system_instruction: Custom system instruction override.

        Returns:
            QueryUnderstandingResult containing validated output and diagnostics.
        """
        # 1. Input Validation
        try:
            clean_query = self.validate_input_query(query)
        except Exception as val_exc:
            return QueryUnderstandingResult(
                query=str(query),
                output=QueryUnderstandingOutput(
                    semantic_query=str(query),
                    hard_constraints=HardConstraints(),
                    needs_clarification=True,
                    clarification_reason=str(val_exc),
                ),
                is_valid=False,
                validation_errors=[str(val_exc)],
            )

        # 2. Build Prompt
        prompt_text = build_user_prompt(clean_query)

        # 3. Call Gemini API
        try:
            if self.intent_extractor is not None:
                from shopassist.llm.transformation import transform_extraction, ExtractedShoppingIntent
                start = time.perf_counter()
                extracted, raw_json, _, usage = await self.intent_extractor.extract(clean_query)
                extracted = ExtractedShoppingIntent.model_validate(extracted)
                validation = transform_extraction(clean_query, extracted, self._catalog_brands)
                return QueryUnderstandingResult(
                    query=clean_query, output=validation.output, raw_response_text=raw_json,
                    model=self.intent_extractor.model, latency_ms=(time.perf_counter()-start)*1000,
                    token_usage=usage, is_valid=True,
                    validation_errors=[validation.status.value, *validation.issues, *validation.corrections],
                )
            if self.gateway is not None:
                response = await self.gateway.complete(
                    GatewayRequest[QueryUnderstandingOutput](
                        task=TaskType.QUERY_UNDERSTANDING,
                        profile="default",
                        request_id=request_id or uuid.uuid4().hex,
                        task_id=task_id or uuid.uuid4().hex,
                        system_prompt=system_instruction,
                        user_prompt=prompt_text,
                        schema_id=SCHEMA_IDS[TaskType.QUERY_UNDERSTANDING],
                        response_schema=QueryUnderstandingOutput,
                        parent_deadline_mono=parent_deadline_mono,
                    )
                )
                parsed_output = response.payload
                raw_json = response.raw_text or ""
                latency_ms = response.latency_ms
                source_usage = response.usage
                prompt_tokens = source_usage.input_tokens
                output_tokens = source_usage.output_tokens
                total_tokens = source_usage.total_tokens
                if total_tokens is None and prompt_tokens is not None and output_tokens is not None:
                    total_tokens = prompt_tokens + output_tokens
                token_usage = TokenUsageMetadata(
                    prompt_tokens=prompt_tokens if prompt_tokens is not None else 0,
                    candidates_tokens=output_tokens if output_tokens is not None else 0,
                    total_tokens=total_tokens if total_tokens is not None else 0,
                )
                result_model = response.model
            else:
                (
                    parsed_output,
                    raw_json,
                    latency_ms,
                    token_usage,
                ) = await self.client.generate_structured_async(
                    prompt=prompt_text,
                    response_schema=QueryUnderstandingOutput,
                    system_instruction=system_instruction,
                )
                result_model = self.settings.gemini_model

            # 4. Normalization and Business Rule Validation
            normalized_output, business_warnings = validate_and_normalize_output(
                output=parsed_output,
                catalog_brands=self._catalog_brands,
            )

            return QueryUnderstandingResult(
                query=clean_query,
                output=normalized_output,
                raw_response_text=raw_json,
                model=result_model,
                latency_ms=latency_ms,
                token_usage=token_usage,
                is_valid=True,
                validation_errors=business_warnings,
            )

        except asyncio.CancelledError:
            raise
        except GatewayError as exc:
            if exc.deadline_scope == "parent":
                raise
            # An unavailable/invalid provider result is not a semantic request
            # for clarification. Keep constraints empty and let API mapping see
            # `is_valid=False` before it checks clarification state.
            logger.warning("Query understanding Gateway failed (%s); failing closed.", exc.category.value)
            safe_failure = f"LLM Gateway failure ({exc.category.value}); query constraints were not inferred."
            return QueryUnderstandingResult(
                query=clean_query,
                output=QueryUnderstandingOutput(
                    semantic_query=clean_query,
                    hard_constraints=HardConstraints(),
                    needs_clarification=False,
                ),
                raw_response_text="",
                model="",
                is_valid=False,
                validation_errors=[safe_failure],
            )
        except Exception as exc:
            logger.error("Query understanding processing error: %s", type(exc).__name__)
            return QueryUnderstandingResult(
                query=clean_query,
                output=QueryUnderstandingOutput(
                    semantic_query=clean_query,
                    hard_constraints=HardConstraints(),
                    needs_clarification=True,
                    clarification_reason=f"Processing failure: {type(exc).__name__}. Please try again.",
                ),
                is_valid=False,
                validation_errors=[f"Processing failure: {type(exc).__name__}"],
            )

    def parse_query(
        self,
        query: str,
        system_instruction: str = SYSTEM_INSTRUCTION,
        *,
        request_id: str | None = None,
        task_id: str | None = None,
        parent_deadline_mono: float | None = None,
    ) -> QueryUnderstandingResult:
        """Synchronous wrapper for parse_query_async."""
        async def parse_and_close():
            try:
                return await self.parse_query_async(
                    query, system_instruction=system_instruction,
                    request_id=request_id, task_id=task_id,
                    parent_deadline_mono=parent_deadline_mono,
                )
            finally:
                await self.aclose()
        return asyncio.run(parse_and_close())

    async def aclose(self) -> None:
        """Cleanly close client resources."""
        if self._client is not None:
            await self._client.aclose()
        if self.intent_extractor is not None:
            await self.intent_extractor.aclose()
