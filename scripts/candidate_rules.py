"""High-recall candidate rules for small kitchen appliances.

These rules flag uncertain records; they do not make final cleaning decisions.
"""

from __future__ import annotations

import re
from typing import Any


FAMILY_TERMS: dict[str, tuple[str, ...]] = {
    "coffee_maker": (
        r"\bcoffee\s*makers?\b", r"\bcoffee\s*machines?\b",
        r"\bcoffee\s*brewers?\b", r"\bespresso\s*machines?\b",
        r"\bespresso\s*makers?\b", r"\bsingle[ -]serve\s*brewers?\b",
    ),
    "blender": (r"\bblenders?\b",),
    "air_fryer": (r"\bair[ -]fryers?\b",),
    # Broad at candidate stage; manual/stovetop kettles are flagged below.
    "electric_kettle": (r"\bkettles?\b",),
    "rice_cooker": (
        r"\brice\s*cookers?\b", r"\brice\s*makers?\b",
        r"\bmulti[ -]?cookers?\b.{0,60}\brice\b",
        r"\brice\b.{0,60}\bmulti[ -]?cookers?\b",
    ),
}
ACCESSORY_TERMS = (
    r"\breplacements?\b", r"\bspares?\b", r"\baccessor(?:y|ies)\b",
    r"\bparts?\b", r"\bblades?\b", r"\blids?\b", r"\bcovers?\b",
    r"\badapters?\b", r"\battachments?\b", r"\bfilters?\b",
    r"\bliners?\b", r"\bracks?\b", r"\btrays?\b",
    r"\bbaskets?\b", r"\binner\s+pots?\b", r"\bgaskets?\b",
    r"\bseals?\b", r"\bcords?\b", r"\bparchment\b",
    r"\b(?:jars?|cups?)\b",
)
MANUAL_COFFEE_TERMS = (
    r"\bfrench\s+press(?:es)?\b", r"\bpour[ -]over\b",
    r"\bmoka\b", r"\bmanual\b", r"\bdrippers?\b",
    r"\bstovetop\s+espresso\b", r"\bstove[ -]top\s+espresso\b",
)
STOVETOP_KETTLE_TERMS = (
    r"\bstove[ -]?top\b", r"\bwhistling\b",
)

COMPILED_FAMILIES = {
    family: tuple(re.compile(pattern, re.I) for pattern in patterns)
    for family, patterns in FAMILY_TERMS.items()
}
COMPILED_ACCESSORY = tuple(re.compile(pattern, re.I) for pattern in ACCESSORY_TERMS)
COMPILED_MANUAL = tuple(re.compile(pattern, re.I) for pattern in MANUAL_COFFEE_TERMS)
COMPILED_STOVETOP = tuple(re.compile(pattern, re.I) for pattern in STOVETOP_KETTLE_TERMS)


def _hits(patterns: tuple[re.Pattern[str], ...], text: str) -> list[str]:
    return sorted({match.group(0).lower() for pattern in patterns if (match := pattern.search(text))})


def detect_candidate(record: dict[str, Any]) -> dict[str, Any] | None:
    """Return match evidence and flags, or None for an unrelated record."""
    title = record.get("title")
    title_text = title if isinstance(title, str) else ""
    categories = record.get("categories")
    category_text = " > ".join(value for value in categories if isinstance(value, str)) if isinstance(categories, list) else ""

    details = {}
    for family, patterns in COMPILED_FAMILIES.items():
        title_hits = _hits(patterns, title_text)
        taxonomy_hits = _hits(patterns, category_text)
        if title_hits or taxonomy_hits:
            details[family] = {
                "matched_by": (["title"] if title_hits else []) + (["taxonomy"] if taxonomy_hits else []),
                "matched_keywords": sorted(set(title_hits + taxonomy_hits)),
            }
    if not details:
        return None

    families = list(details)
    accessory_hits = _hits(COMPILED_ACCESSORY, title_text + " > " + category_text)
    manual_hits = _hits(COMPILED_MANUAL, title_text + " > " + category_text)
    stovetop_hits = _hits(COMPILED_STOVETOP, title_text + " > " + category_text)
    if "electric_kettle" in families and "Tea Kettles" in category_text and not re.search(r"\belectric\b", title_text + " " + category_text, re.I):
        stovetop_hits.append("tea kettles taxonomy without electric signal")

    return {
        "candidate_family": families[0] if len(families) == 1 else None,
        "candidate_families": families,
        "matched_by": sorted({reason for detail in details.values() for reason in detail["matched_by"]}),
        "matched_keywords": sorted({keyword for detail in details.values() for keyword in detail["matched_keywords"]}),
        "match_details": details,
        "possible_accessory": bool(accessory_hits),
        "matched_accessory_keywords": accessory_hits,
        "possible_manual_product": "coffee_maker" in families and bool(manual_hits),
        "matched_manual_keywords": manual_hits if "coffee_maker" in families else [],
        "possible_stovetop_kettle": "electric_kettle" in families and bool(stovetop_hits),
        "matched_stovetop_keywords": stovetop_hits if "electric_kettle" in families else [],
        "ambiguous_family": len(families) > 1,
    }
