"""Deterministic semantic query composition for positive preferences."""

from __future__ import annotations

from shopassist.preferences.normalization import (
    MAX_COMPOSED_QUERY_LENGTH,
    normalize_preferences,
    normalize_semantic_query,
)


def build_preference_query(
    semantic_query: str,
    soft_preferences: list[str],
) -> str | None:
    """Compose positive preferences with their product context.

    Returns ``None`` for no preferences; callers must not encode an empty string
    as a preference vector. The separator is intentionally neutral and adds no
    inferred requirement.
    """
    context = normalize_semantic_query(semantic_query)
    preferences = normalize_preferences(soft_preferences)
    if not preferences:
        return None
    composed = f"{'; '.join(preferences)} — {context}"
    if len(composed) > MAX_COMPOSED_QUERY_LENGTH:
        raise ValueError(
            f"composed preference query exceeds {MAX_COMPOSED_QUERY_LENGTH} characters"
        )
    return composed
