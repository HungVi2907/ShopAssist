"""LLM Query Understanding module for ShopAssist.

Extracts structured hard constraints, soft preferences, semantic search query,
and clarification requirements from natural language shopping requests using
Google Gemini API.
"""

from shopassist.llm.config import LLMSettings, get_llm_settings
from shopassist.llm.gemini_client import GeminiClient
from shopassist.llm.normalization import (
    CANONICAL_CATEGORIES,
    normalize_brand,
    normalize_category,
    normalize_currency,
)
from shopassist.llm.prompts import (
    SYSTEM_INSTRUCTION,
    build_user_prompt,
)
from shopassist.llm.query_understanding import QueryUnderstandingEngine
from shopassist.llm.schemas import (
    HardConstraints,
    QueryUnderstandingOutput,
    QueryUnderstandingResult,
    TokenUsageMetadata,
)

__all__ = [
    "LLMSettings",
    "get_llm_settings",
    "GeminiClient",
    "CANONICAL_CATEGORIES",
    "normalize_brand",
    "normalize_category",
    "normalize_currency",
    "SYSTEM_INSTRUCTION",
    "build_user_prompt",
    "QueryUnderstandingEngine",
    "HardConstraints",
    "QueryUnderstandingOutput",
    "QueryUnderstandingResult",
    "TokenUsageMetadata",
]
