"""Conservative guard for negative constraints leaking through Phase 8 v1."""

from __future__ import annotations

import re

# These patterns identify likely exclusions only when the wording is direct.
# Ambiguous scopes are returned for clarification instead of embedded.
_EXCLUSION_PATTERNS = (
    re.compile(r"\bwithout\s+\S", re.IGNORECASE),
    re.compile(r"\bavoid\s+\S", re.IGNORECASE),
    re.compile(r"\banything\s+except\s+\S", re.IGNORECASE),
    re.compile(r"\bexcept\s+\S", re.IGNORECASE),
    re.compile(r"\bno\s+(?!fuss\b|frills\b|problem\b)\S", re.IGNORECASE),
    re.compile(r"\bno\s+(?!fuss\b|frills\b|problem\b)\S", re.IGNORECASE),
    re.compile(r"\bno\s+less\s+than\b", re.IGNORECASE),
    re.compile(r"\bnot\s+(?!only\b|too\b|necessarily\b)\S", re.IGNORECASE),
)


def find_unsafe_negative_preferences(preferences: list[str]) -> list[str]:
    """Return phrases whose polarity cannot safely be represented as positive.

    ``not too heavy`` is retained as a user's positive soft description because
    it expresses a degree preference. Other ``not ...`` forms remain ambiguous;
    this deliberately errs toward clarification instead of vectorizing them.
    """
    unsafe: list[str] = []
    for phrase in preferences:
        if any(pattern.search(phrase) for pattern in _EXCLUSION_PATTERNS):
            unsafe.append(phrase)
    return unsafe
