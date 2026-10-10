"""Deterministic, meaning-preserving soft preference normalization."""

from __future__ import annotations

import re
import unicodedata

MAX_PREFERENCES = 10
MAX_PREFERENCE_LENGTH = 200
MAX_COMPOSED_QUERY_LENGTH = 1000


class PreferenceInputError(ValueError):
    """Raised when a Phase 8 preference payload violates representation limits."""


def normalize_preferences(values: object) -> list[str]:
    """Trim, case-fold, whitespace-normalize and stably deduplicate phrases.

    The function does not remove negation, translate text, or expand synonyms.
    """
    if not isinstance(values, list):
        raise PreferenceInputError("soft_preferences must be a list of strings")
    if len(values) > MAX_PREFERENCES:
        raise PreferenceInputError(f"soft_preferences cannot exceed {MAX_PREFERENCES} items")

    normalized: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, str):
            raise PreferenceInputError(f"soft_preferences[{index}] must be a string")
        phrase = unicodedata.normalize("NFC", value)
        phrase = re.sub(r"\s+", " ", phrase.strip()).casefold()
        if not phrase:
            continue
        if len(phrase) > MAX_PREFERENCE_LENGTH:
            raise PreferenceInputError(
                f"soft_preferences[{index}] exceeds {MAX_PREFERENCE_LENGTH} characters"
            )
        if phrase not in seen:
            seen.add(phrase)
            normalized.append(phrase)
    return normalized


def normalize_semantic_query(value: object) -> str:
    if not isinstance(value, str):
        raise PreferenceInputError("semantic_query must be a string")
    query = unicodedata.normalize("NFC", value)
    query = re.sub(r"\s+", " ", query.strip())
    if not query:
        raise PreferenceInputError("semantic_query cannot be empty")
    if len(query) > 500:
        raise PreferenceInputError("semantic_query cannot exceed 500 characters")
    return query
