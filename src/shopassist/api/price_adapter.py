"""Price-boundary semantics adapter (Phase 15).

Safely bridges Phase 8 Schema v1 numeric constraints to Phase 10's strict boundary semantics.
Phase 10 deliberately rejects queries with ambiguous boundary semantics (neither strictly `<`
nor inclusive `<=`). This adapter deterministically inspects the original query text for explicit
operator phrasing in English and Vietnamese without guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class PriceBoundaryResolution:
    """Result of price operator analysis on original query text."""

    is_resolved: bool
    semantics: dict[str, bool] = field(default_factory=dict)
    unresolved_reason: str | None = None


class PriceBoundaryAdapter:
    """Deterministic extractor of price boundary inclusivity flags from user queries."""

    # Explicit Range patterns (inclusive on both ends)
    _RANGE_PATTERNS = [
        re.compile(r"\b(?:between|from)\s+(?:rs\.?|inr|₹)?\s*\d+(?:\.\d+)?\s+(?:and|to)\s+(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r"\btừ\s+(?:rs\.?|inr|₹|đ|vnd)?\s*\d+(?:\.\d+)?\s+(?:đến|tới)\s+(?:rs\.?|inr|₹|đ|vnd)?\s*\d+", re.IGNORECASE),
        re.compile(r"\b\d+(?:\.\d+)?\s*(?:-|to)\s*\d+(?:\.\d+)?\s*(?:rs|inr|₹|vnd)?\b", re.IGNORECASE),
    ]

    # Strict Less Than (<, exclusive)
    _MAX_STRICT_PATTERNS = [
        re.compile(r"\b(?:under|below|strictly under|less than|cheaper than)\s+(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r"<\s*(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r"\b(?:dưới|thấp hơn|nhỏ hơn)\s+(?:rs\.?|inr|₹|đ|vnd)?\s*\d+", re.IGNORECASE),
    ]

    # Inclusive At Most (<=, inclusive)
    _MAX_INCLUSIVE_PATTERNS = [
        re.compile(r"\b(?:up to|at most|maximum|max|not exceeding|within)\s+(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r"<=\s*(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r"\b(?:tối đa|không quá|nhiều nhất)\s+(?:rs\.?|inr|₹|đ|vnd)?\s*\d+", re.IGNORECASE),
        re.compile(r"\b\d+(?:\.\d+)?\s*(?:đổ lại|trở xuống)\b", re.IGNORECASE),
    ]

    # Strict Greater Than (>, exclusive)
    _MIN_STRICT_PATTERNS = [
        re.compile(r"\b(?:above|over|strictly over|more than|greater than|higher than)\s+(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r">\s*(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r"\b(?:trên|cao hơn|lớn hơn)\s+(?:rs\.?|inr|₹|đ|vnd)?\s*\d+", re.IGNORECASE),
    ]

    # Inclusive At Least (>=, inclusive)
    _MIN_INCLUSIVE_PATTERNS = [
        re.compile(r"\b(?:at least|minimum|min|from)\s+(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r">=\s*(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r"\b(?:tối thiểu|ít nhất|từ)\s+(?:rs\.?|inr|₹|đ|vnd)?\s*\d+", re.IGNORECASE),
        re.compile(r"\b\d+(?:\.\d+)?\s*(?:đổ lên|trở lên)\b", re.IGNORECASE),
    ]

    # Explicit Ambiguous Budget Patterns
    _AMBIGUOUS_PATTERNS = [
        re.compile(r"\b(?:around|about|approx|approximately)\s+(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r"\b(?:khoảng|tầm)\s+(?:rs\.?|inr|₹|đ|vnd)?\s*\d+", re.IGNORECASE),
        re.compile(r"\bbudget\s*(?:of|is|:)?\s*(?:rs\.?|inr|₹)?\s*\d+", re.IGNORECASE),
        re.compile(r"\bngân sách\s*(?:là|khoảng|:)?\s*(?:rs\.?|inr|₹|đ|vnd)?\s*\d+", re.IGNORECASE),
    ]

    @classmethod
    def resolve(
        cls,
        query: str,
        min_price: float | None,
        max_price: float | None,
    ) -> PriceBoundaryResolution:
        """Analyze query text to determine explicit strict vs inclusive price operator semantics.

        Args:
            query: Raw user query string.
            min_price: Minimum price threshold extracted by Phase 8.
            max_price: Maximum price ceiling extracted by Phase 8.

        Returns:
            PriceBoundaryResolution with is_resolved flag and verified semantics mapping.
        """
        # If no price constraints were extracted, nothing needs resolution
        if min_price is None and max_price is None:
            return PriceBoundaryResolution(is_resolved=True, semantics={})

        query_text = query.strip()

        # Check for explicit ambiguous phrasing first
        for pat in cls._AMBIGUOUS_PATTERNS:
            if pat.search(query_text):
                # An ambiguous budget phrase was used (e.g. "around 2000" / "khoảng 2000")
                return PriceBoundaryResolution(
                    is_resolved=False,
                    unresolved_reason="Query expresses an approximate or ambiguous budget ('around' / 'khoảng'). Explicit boundary operator (<, <=, >, >=) is required.",
                )

        semantics: dict[str, bool] = {}

        # Range check: if both bounds are present and match an explicit range pattern
        if min_price is not None and max_price is not None:
            for pat in cls._RANGE_PATTERNS:
                if pat.search(query_text):
                    semantics["min_inclusive"] = True
                    semantics["max_inclusive"] = True
                    return PriceBoundaryResolution(is_resolved=True, semantics=semantics)

        # Resolve max_price operator if present
        if max_price is not None and "max_inclusive" not in semantics:
            is_strict = any(pat.search(query_text) for pat in cls._MAX_STRICT_PATTERNS)
            is_inclusive = any(pat.search(query_text) for pat in cls._MAX_INCLUSIVE_PATTERNS)

            if is_strict and not is_inclusive:
                semantics["max_inclusive"] = False
            elif is_inclusive and not is_strict:
                semantics["max_inclusive"] = True
            elif is_strict and is_inclusive:
                # Conflicting signals in query
                return PriceBoundaryResolution(
                    is_resolved=False,
                    unresolved_reason="Query contains conflicting upper price boundary indicators.",
                )
            else:
                # No identifiable operator pattern for max_price
                return PriceBoundaryResolution(
                    is_resolved=False,
                    unresolved_reason=f"Upper price boundary {max_price} lacks a verified explicit operator ('under' vs 'up to').",
                )

        # Resolve min_price operator if present
        if min_price is not None and "min_inclusive" not in semantics:
            is_strict = any(pat.search(query_text) for pat in cls._MIN_STRICT_PATTERNS)
            is_inclusive = any(pat.search(query_text) for pat in cls._MIN_INCLUSIVE_PATTERNS)

            if is_strict and not is_inclusive:
                semantics["min_inclusive"] = False
            elif is_inclusive and not is_strict:
                semantics["min_inclusive"] = True
            elif is_strict and is_inclusive:
                # Conflicting signals in query
                return PriceBoundaryResolution(
                    is_resolved=False,
                    unresolved_reason="Query contains conflicting lower price boundary indicators.",
                )
            else:
                # No identifiable operator pattern for min_price
                return PriceBoundaryResolution(
                    is_resolved=False,
                    unresolved_reason=f"Lower price boundary {min_price} lacks a verified explicit operator ('above' vs 'at least').",
                )

        return PriceBoundaryResolution(is_resolved=True, semantics=semantics)
