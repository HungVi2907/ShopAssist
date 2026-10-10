"""Core Query Understanding Engine for ShopAssist (Phase 8).

Orchestrates input validation, Gemini API prompt execution, Pydantic schema validation,
category & brand normalization, business rules enforcement, and diagnostic reporting.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import pandas as pd

from shopassist.core.config import PROCESSED_DATA_DIR
from shopassist.llm.config import LLMSettings, llm_settings
from shopassist.llm.gemini_client import GeminiClient
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
        settings: LLMSettings | None = None,
        catalog_brands: set[str] | None = None,
    ) -> None:
        """Initialize Query Understanding engine.

        Args:
            client: Optional pre-configured GeminiClient.
            settings: Optional LLMSettings instance.
            catalog_brands: Optional pre-loaded set of catalog brands.
        """
        self.settings = settings or llm_settings
        self._client = client
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

            # 4. Normalization and Business Rule Validation
            normalized_output, business_warnings = validate_and_normalize_output(
                output=parsed_output,
                catalog_brands=self._catalog_brands,
            )

            return QueryUnderstandingResult(
                query=clean_query,
                output=normalized_output,
                raw_response_text=raw_json,
                model=self.settings.gemini_model,
                latency_ms=latency_ms,
                token_usage=token_usage,
                is_valid=True,
                validation_errors=business_warnings,
            )

        except Exception as exc:
            logger.error("Query understanding processing error for query '%s': %s", clean_query, exc)
            return QueryUnderstandingResult(
                query=clean_query,
                output=QueryUnderstandingOutput(
                    semantic_query=clean_query,
                    hard_constraints=HardConstraints(),
                    needs_clarification=True,
                    clarification_reason=f"Processing failure: {type(exc).__name__}: {exc}",
                ),
                is_valid=False,
                validation_errors=[str(exc)],
            )

    def parse_query(
        self,
        query: str,
        system_instruction: str = SYSTEM_INSTRUCTION,
    ) -> QueryUnderstandingResult:
        """Synchronous wrapper for parse_query_async."""
        return asyncio.run(
            self.parse_query_async(query, system_instruction=system_instruction)
        )

    async def aclose(self) -> None:
        """Cleanly close client resources."""
        if self._client is not None:
            await self._client.aclose()
