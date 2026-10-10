"""Structured schema refinements and evolution for Query Understanding (Phase 8.1).

Introduces Schema v2.0.0 (and additive v1.1.0) with explicit:
1. Product Type representation (isolating core product nouns from qualitative preferences).
2. Typed Exclusions / Negative Constraints (target_type + value).
3. Price Boundary Semantics (strict vs inclusive operators: min_inclusive, max_inclusive).
4. Full backward-compatibility mapping to Schema v1.0.0.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput


class ExclusionConstraint(BaseModel):
    """Explicitly unwanted product type, brand, category, or attribute constraint."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    target_type: Literal["product_type", "brand", "category", "attribute", "feature"] = Field(
        default="attribute",
        description="Type of exclusion: 'product_type', 'brand', 'category', 'attribute', or 'feature'.",
    )
    value: str = Field(
        description="Specific term or characteristic to exclude (e.g., 'running shoes', 'leather', 'wired').",
    )

    @field_validator("value", mode="before")
    @classmethod
    def normalize_value(cls, v: Any) -> str:
        """Strip whitespace and lowercase exclusion value."""
        if not v or not str(v).strip():
            raise ValueError("Exclusion value cannot be empty.")
        clean = str(v).strip().lower()
        # Remove leading negative prefixes if LLM included them
        for prefix in ("not ", "no ", "without ", "non-", "non "):
            if clean.startswith(prefix):
                clean = clean[len(prefix):].strip()
        return clean


class RefinedHardConstraints(BaseModel):
    """Hard filter constraints with explicit strict/inclusive boundary semantics."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    category: str | None = Field(
        default=None,
        description="Canonical product category matching one of the 16 approved catalog categories.",
    )
    brand: str | None = Field(
        default=None,
        description="Brand name if explicitly requested. None if unspecified.",
    )
    min_price: float | None = Field(
        default=None,
        description="Minimum price threshold in specified currency.",
    )
    max_price: float | None = Field(
        default=None,
        description="Maximum price budget ceiling in specified currency.",
    )
    min_inclusive: bool = Field(
        default=True,
        description="True for inclusive lower bound ('>=' e.g. 'at least 500'); False for strict ('>' e.g. 'above 500').",
    )
    max_inclusive: bool = Field(
        default=True,
        description="True for inclusive upper bound ('<=' e.g. 'at most 2000'); False for strict ('<' e.g. 'under 2000').",
    )
    min_rating: float | None = Field(
        default=None,
        description="Minimum product rating on a 1.0 to 5.0 scale.",
    )
    currency: str | None = Field(
        default="INR",
        description="Currency code for prices (default: 'INR').",
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
    def validate_price_range(self) -> RefinedHardConstraints:
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

    def to_v1(self) -> HardConstraints:
        """Convert refined constraints to Schema v1.0.0 HardConstraints."""
        return HardConstraints(
            category=self.category,
            brand=self.brand,
            min_price=self.min_price,
            max_price=self.max_price,
            min_rating=self.min_rating,
            currency=self.currency,
        )


class RefinedQueryUnderstandingOutput(BaseModel):
    """Schema v2.0.0: Refined structured representation of user shopping intent."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    product_type: str | None = Field(
        default=None,
        description="The specific product noun phrase requested by the user (e.g. 'running shoes', 'wireless keyboard', 'smartphone').",
    )
    semantic_query: str = Field(
        description="Cleaned, focused search query representing the core product intent with conversational filler removed.",
    )
    hard_constraints: RefinedHardConstraints = Field(
        default_factory=RefinedHardConstraints,
        description="Structured hard filters (category, brand, price boundaries with strict/inclusive flags, rating, currency).",
    )
    exclusions: list[ExclusionConstraint] = Field(
        default_factory=list,
        description="Explicit negative constraints and exclusions requested by user (e.g. 'not running shoes', 'without leather').",
    )
    soft_preferences: list[str] = Field(
        default_factory=list,
        description="List of qualitative, subjective, or lifestyle preferences (e.g. 'comfortable', 'lightweight', 'for marathon').",
    )
    needs_clarification: bool = Field(
        default=False,
        description="True if query is excessively ambiguous, contradictory, or for an unsupported domain.",
    )
    clarification_reason: str | None = Field(
        default=None,
        description="Explanation when clarification is required, or null if query is clear.",
    )

    @field_validator("product_type", mode="before")
    @classmethod
    def normalize_product_type(cls, v: Any) -> str | None:
        """Normalize product type string."""
        if not v or not str(v).strip():
            return None
        return str(v).strip().lower()

    @field_validator("semantic_query", mode="before")
    @classmethod
    def validate_semantic_query(cls, v: Any) -> str:
        """Ensure semantic query is non-empty string."""
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
        return cleaned_list[:10]

    def to_v1(self) -> QueryUnderstandingOutput:
        """Downgrade/adapt to Schema v1.0.0 output contract for backward compatibility.

        - Maps exclusions into soft_preferences if any (e.g. 'not running shoes').
        - Preserves existing v1.0.0 fields exactly.
        """
        adapted_preferences = list(self.soft_preferences)
        for excl in self.exclusions:
            adapted_pref = f"not {excl.value}"
            if adapted_pref not in adapted_preferences:
                adapted_preferences.append(adapted_pref)

        return QueryUnderstandingOutput(
            semantic_query=self.semantic_query,
            hard_constraints=self.hard_constraints.to_v1(),
            soft_preferences=adapted_preferences,
            needs_clarification=self.needs_clarification,
            clarification_reason=self.clarification_reason,
        )

    @classmethod
    def from_v1(cls, v1_output: QueryUnderstandingOutput) -> RefinedQueryUnderstandingOutput:
        """Upgrade Schema v1.0.0 output to Schema v2.0.0.

        Separates negative preferences into exclusions where detectable.
        """
        clean_prefs: list[str] = []
        excls: list[ExclusionConstraint] = []

        for p in v1_output.soft_preferences:
            p_lower = p.lower().strip()
            if p_lower.startswith("not ") or p_lower.startswith("without ") or p_lower.startswith("no "):
                val = p_lower
                for prefix in ("not ", "without ", "no "):
                    if val.startswith(prefix):
                        val = val[len(prefix):].strip()
                        break
                excls.append(ExclusionConstraint(target_type="attribute", value=val))
            else:
                clean_prefs.append(p)

        refined_hc = RefinedHardConstraints(
            category=v1_output.hard_constraints.category,
            brand=v1_output.hard_constraints.brand,
            min_price=v1_output.hard_constraints.min_price,
            max_price=v1_output.hard_constraints.max_price,
            min_inclusive=True,
            max_inclusive=True,
            min_rating=v1_output.hard_constraints.min_rating,
            currency=v1_output.hard_constraints.currency,
        )

        return cls(
            product_type=None,
            semantic_query=v1_output.semantic_query,
            hard_constraints=refined_hc,
            exclusions=excls,
            soft_preferences=clean_prefs,
            needs_clarification=v1_output.needs_clarification,
            clarification_reason=v1_output.clarification_reason,
        )
