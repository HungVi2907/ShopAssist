"""Data contracts and Pydantic schemas for LLM Query Understanding (Phase 8).

Defines structured schema models for:
- HardConstraints (category, brand, price range, rating, currency)
- QueryUnderstandingOutput (semantic intent, hard constraints, soft preferences, clarification)
- TokenUsageMetadata and QueryUnderstandingResult
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HardConstraints(BaseModel):
    """Hard filter constraints extracted from user shopping query."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    category: str | None = Field(
        default=None,
        description="Canonical product category matching one of the 16 approved catalog categories.",
    )
    brand: str | None = Field(
        default=None,
        description="Brand name if explicitly requested (e.g. 'Puma', 'Samsung'). None if unspecified.",
    )
    min_price: float | None = Field(
        default=None,
        description="Minimum price threshold in specified currency (e.g. 'at least 500' -> 500.0).",
    )
    max_price: float | None = Field(
        default=None,
        description="Maximum price budget ceiling in specified currency (e.g. 'under 2000' -> 2000.0).",
    )
    min_rating: float | None = Field(
        default=None,
        description="Minimum product rating on a 1.0 to 5.0 scale (e.g. 'at least 4 stars' -> 4.0).",
    )
    currency: str | None = Field(
        default="INR",
        description="Currency code for prices (default: 'INR', or 'USD', 'EUR' if explicitly stated).",
    )

    @field_validator("category", "brand", mode="before")
    @classmethod
    def normalize_empty_strings(cls, v: Any) -> Any:
        """Convert empty or whitespace-only strings to None."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("min_price", "max_price")
    @classmethod
    def validate_non_negative_price(cls, v: float | None) -> float | None:
        """Validate price values are non-negative."""
        if v is not None and v < 0.0:
            raise ValueError(f"Price constraint cannot be negative, got {v}")
        return v

    @field_validator("min_rating")
    @classmethod
    def validate_rating_bounds(cls, v: float | None) -> float | None:
        """Validate rating is between 1.0 and 5.0."""
        if v is not None and not (1.0 <= v <= 5.0):
            raise ValueError(f"Rating must be between 1.0 and 5.0, got {v}")
        return v

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency_code(cls, v: Any) -> str | None:
        """Standardize currency string to uppercase code."""
        if v is None:
            return "INR"
        if isinstance(v, str):
            clean = v.strip().upper()
            if not clean:
                return "INR"
            if clean in ("RUPEES", "RUPEE", "RS", "INR", "₹"):
                return "INR"
            if clean in ("DOLLARS", "DOLLAR", "USD", "$"):
                return "USD"
            if clean in ("EUROS", "EURO", "EUR", "€"):
                return "EUR"
            return clean
        return str(v).upper()

    @model_validator(mode="after")
    def validate_price_range(self) -> HardConstraints:
        """Validate that min_price does not exceed max_price."""
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError(
                f"min_price ({self.min_price}) cannot be greater than max_price ({self.max_price})"
            )
        return self


class QueryUnderstandingOutput(BaseModel):
    """Canonical structured representation of a user shopping query."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    semantic_query: str = Field(
        description="Cleaned, focused search query representing the core product type and essential features, with conversational filler removed.",
    )
    hard_constraints: HardConstraints = Field(
        default_factory=HardConstraints,
        description="Structured hard filters (category, brand, price boundaries, rating, currency).",
    )
    soft_preferences: list[str] = Field(
        default_factory=list,
        description="List of qualitative, subjective, or lifestyle preferences (e.g. 'comfortable', 'lightweight', 'durable', 'portable').",
    )
    needs_clarification: bool = Field(
        default=False,
        description="True if the user query is excessively ambiguous, contradicts itself, or asks for an unsupported category.",
    )
    clarification_reason: str | None = Field(
        default=None,
        description="Explanation of why clarification is required, or null if query is clear.",
    )

    @field_validator("semantic_query", mode="before")
    @classmethod
    def validate_semantic_query(cls, v: Any) -> str:
        """Ensure semantic query is non-empty string, fallback to default for adversarial/ambiguous queries."""
        if not v or not str(v).strip():
            return "unspecified product query"
        return str(v).strip()

    @field_validator("soft_preferences", mode="before")
    @classmethod
    def clean_and_deduplicate_preferences(cls, v: Any) -> list[str]:
        """Normalize, clean, and deduplicate soft preferences list."""
        if not v:
            return []
        if isinstance(v, str):
            v = [v]
        cleaned_list: list[str] = []
        seen = set()
        for item in v:
            if isinstance(item, str):
                s = item.strip().lower()
                if s and s not in seen:
                    seen.add(s)
                    cleaned_list.append(s)
        # Limit to max 10 soft preferences
        return cleaned_list[:10]

    @field_validator("clarification_reason", mode="before")
    @classmethod
    def normalize_clarification_reason(cls, v: Any) -> str | None:
        """Normalize clarification reason string."""
        if isinstance(v, str) and not v.strip():
            return None
        return v


class TokenUsageMetadata(BaseModel):
    """Token consumption and usage metadata reported by the Gemini API."""

    prompt_tokens: int = 0
    candidates_tokens: int = 0
    total_tokens: int = 0


class QueryUnderstandingResult(BaseModel):
    """End-to-end result of processing a user query through the Query Understanding pipeline."""

    query: str
    output: QueryUnderstandingOutput
    raw_response_text: str = ""
    model: str = ""
    latency_ms: float = 0.0
    token_usage: TokenUsageMetadata | None = None
    is_valid: bool = True
    validation_errors: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return self.model_dump()

    def to_serializable_dict(self) -> dict[str, Any]:
        """Convert result to JSON-serializable dictionary representation."""
        return self.model_dump()
