"""Conservative candidate rules, deliberately isolated from historical E5-B."""
from __future__ import annotations
import re
from shopassist.llm.normalization import normalize_brand, normalize_category, normalize_currency
from shopassist.llm.schema_variants import ExclusionConstraint, RefinedQueryUnderstandingOutput

RULE_GROUPS = ("price", "negation", "product_type", "brand", "currency")
NUM = r"(?:₹|rs\.?|inr|usd|eur|\$|€)?\s*(\d+(?:,\d{3})*(?:\.\d+)?)"
BOUND = re.compile(r"\b(not\s+under|not\s+below|no\s+less\s+than|not\s+less\s+than|not\s+more\s+than|no\s+more\s+than|at\s+least|at\s+most|up\s+to|not\s+exceeding|under|below|less\s+than|above|more\s+than|greater\s+than|max(?:imum)?|min(?:imum)?)\s+" + NUM, re.I)
GUARD = re.compile(r"^(?:only|necessarily|just|too|under|below|less|more|at|without|not|no|never|wait)\b", re.I)
NEG = re.compile(r"\b(?:not|without|no|except)\s+([^,.;!?]+?)(?=\s+(?:and|but|with|under|below|above|for)\b|[,.;!?]|$)", re.I)


def boundary_evidence(query: str) -> dict:
    evidence = {}
    for match in BOUND.finditer(query):
        # Do not turn ratings, wattage, counts, or negated comparisons into prices.
        after = query[match.end():]
        if re.match(r"\s*(?:stars?|rating|watts?|w|kg|ml|litres?|gb|inch|items?)\b", after, re.I):
            continue
        if re.search(r"\b(?:not|no|without|never)\s*$", query[:match.start()], re.I):
            continue
        phrase = " ".join(match.group(1).lower().split())
        lower = phrase in {"above", "more than", "greater than", "at least", "min", "minimum", "no less than", "not less than", "not under", "not below"}
        strict = phrase in {"above", "more than", "greater than", "under", "below", "less than"}
        side = "min" if lower else "max"
        evidence[side] = {"value": float(match.group(2).replace(",", "")), "inclusive": not strict, "span": match.group(0)}
    return evidence


def direct_exclusions(query: str) -> list[ExclusionConstraint]:
    result = []
    for match in NEG.finditer(query):
        value = " ".join(match.group(1).casefold().split())
        if GUARD.match(value) or len(value) > 60:
            continue
        if re.search(r"\b(?:not|never|without)\s*$", query[:match.start()], re.I):
            continue
        target = "product_type" if re.search(r"\b(?:shoes?|laptops?|watches|watch|phones?|lenses|lens|earphones?)\b", value) else "attribute"
        if value in {"nike", "adidas", "puma", "samsung", "sony", "apple", "dell", "casio"}:
            target = "brand"
        result.append(ExclusionConstraint(target_type=target, value=value))
    return result


def apply(output: RefinedQueryUnderstandingOutput, query: str, groups: tuple[str, ...] = RULE_GROUPS,
          catalog_brands: set[str] | None = None) -> tuple[RefinedQueryUnderstandingOutput, list[str]]:
    out = output.model_copy(deep=True)
    notes = []
    hc = out.hard_constraints
    if "brand" in groups:
        hc.brand = normalize_brand(hc.brand, catalog_brands)
        hc.category = normalize_category(hc.category)
        # NER and catalog support are distinct. Never erase an explicit manufacturer.
    if "currency" in groups:
        hc.currency = normalize_currency(hc.currency)
        if hc.currency != "INR":
            out.needs_clarification = True
            out.clarification_reason = "Catalog prices are in INR; currency clarification required."
            notes.append("Foreign currency blocks filter activation.")
    if "price" in groups:
        for side, evidence in boundary_evidence(query).items():
            # Match evidence to the model's final numeric bound; never rewrite a number.
            if getattr(hc, side + "_price") == evidence["value"]:
                setattr(hc, side + "_inclusive", evidence["inclusive"])
                notes.append("Boundary matched numeric evidence: " + evidence["span"])
    if "negation" in groups:
        existing = list(out.exclusions)
        for exclusion in direct_exclusions(query):
            if not any(e.value == exclusion.value or e.value + " " in exclusion.value + " " or
                       exclusion.value + " " in e.value + " " for e in existing):
                existing.append(exclusion)
                notes.append("Added direct exclusion: " + exclusion.value)
        out.exclusions = existing
        # Exact contradiction only: leather must not delete 'faux leather'.
        values = {e.value for e in existing}
        out.soft_preferences = [p for p in out.soft_preferences if p not in values]
    if "product_type" in groups and out.product_type:
        # Known lexicalized product classes; not every modifier denotes a class.
        classes = {"running shoes": "running", "walking shoes": "walking", "analog watch": "analog",
                   "digital watch": "digital", "gaming mouse": "gaming"}
        forbidden = {out.product_type}
        if out.product_type in classes:
            forbidden.add(classes[out.product_type])
        removed = [p for p in out.soft_preferences if p in forbidden]
        out.soft_preferences = [p for p in out.soft_preferences if p not in forbidden]
        notes.extend("Removed repeated product class: " + p for p in removed)
    # Revalidate mutations and fail on impossible ranges; do not silently relax intent.
    return RefinedQueryUnderstandingOutput.model_validate(out.model_dump()), notes
