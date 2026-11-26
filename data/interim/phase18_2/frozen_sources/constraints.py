"""Conservative, query-grounded numeric parsing for the opt-in extraction path."""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from shopassist.llm.normalization import normalize_currency
from shopassist.llm.refinement_rules import IN_QUERY_CORRECTION_REGEX

NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
MONEY = r"(?:INR|rs\.?|rupees?|USD|dollars?|EUR|euros?|GBP|pounds?|₹|\$|€|£)"
AMOUNT = rf"(?:{MONEY}\s*)?(?P<value>{NUMBER})"
UPPER = r"under|below|less than|up to|at most|maximum|max|within|dưới|tối đa"
LOWER = r"above|over|more than|at least|minimum|min|trên|ít nhất"
BOUND = re.compile(rf"\b(?P<operator>{UPPER}|{LOWER})\s+{AMOUNT}", re.I)
RANGE = re.compile(rf"\bbetween\s+(?:{MONEY}\s*)?(?P<lo>{NUMBER})\s+and\s+(?:{MONEY}\s*)?(?P<hi>{NUMBER})", re.I)
RATING = re.compile(rf"(?:(?:at least|minimum|min|rated|rating(?: of)?|ít nhất)\s+)?(?P<rating>{NUMBER})\s*(?:stars?|sao|star rating)\b|(?:minimum|min|at least)\s+(?P<other>{NUMBER})\s+rating\b|(?:rated|rating)\s+(?:above|over|at least|minimum|min|of)\s+(?P<bare>{NUMBER})\b", re.I)
SPEC = re.compile(r"^\s*(?:gb|tb|mb|mah|hz|watts?|w|inches|inch|cm|mm|kg|pairs?|pieces?|units?|stars?|sao|rating)\b", re.I)
CURRENCIES = re.compile(r"\b(?:INR|rs\.?|rupees?|USD|dollars?|EUR|euros?|GBP|pounds?|JPY|VND|CAD|AUD|CNY|CHF|SGD|AED|yen|đồng)\b|[₹$€£]", re.I)


@dataclass
class ParsedConstraints:
    min_price: float | None = None
    max_price: float | None = None
    min_rating: float | None = None
    currency: str = 'INR'
    issues: list[str] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)


def amount(value: str) -> float:
    return float(value.replace(',', ''))


def parse_constraints(raw_query: str) -> ParsedConstraints:
    """Interpret only relational monetary phrases; never infer from bare numbers.

    Corrections supersede earlier prices only when the correction contains an
    explicit replacement bound. All original currency/rating evidence is retained.
    Unhandled money-looking or negated expressions fail closed instead of guessing.
    """
    result = ParsedConstraints()
    symbols = {'₹':'INR','$':'USD','€':'EUR','£':'GBP'}
    currencies = {symbols.get(x.group(),normalize_currency(x.group().rstrip('.'))) for x in CURRENCIES.finditer(raw_query)}
    if len(currencies) > 1:
        result.issues.append('Multiple currencies require clarification.')
    if currencies:
        result.currency = sorted(currencies)[0]
    if result.currency != 'INR':
        result.issues.append('Non-INR currency requires clarification; no conversion performed.')
    ratings = list(RATING.finditer(raw_query))
    values = {amount(m['rating'] or m['other'] or m['bare']) for m in ratings}
    if any(re.search(r'\b(?:under|below|at most|exactly)\s*$',raw_query[:m.start()],re.I) for m in ratings):
        result.issues.append('V1 supports minimum ratings only; clarify other rating operators.')
    if len(values) > 1 or any(not 1 <= x <= 5 for x in values):
        result.issues.append('Conflicting or invalid rating requirement.')
    elif values:
        result.min_rating = values.pop()
    rating_spans = [m.span() for m in ratings]
    result.spans.extend(rating_spans)
    corrections = list(IN_QUERY_CORRECTION_REGEX.finditer(raw_query))
    start = corrections[-1].end() if corrections else 0
    if corrections and not BOUND.search(raw_query[start:]) and not RANGE.search(raw_query[start:]):
        result.issues.append('Correction lacks an explicit replacement price boundary.')
    prices: dict[str, list[float]] = {'min_price': [], 'max_price': []}
    ranges = list(RANGE.finditer(raw_query))
    for match in ranges:
        if SPEC.search(raw_query[match.end():]):
            result.issues.append('Numeric specification range is not a verified budget.')
            continue
        result.spans.append(match.span())
        if match.start() >= start:
            prices['min_price'].append(amount(match['lo']))
            prices['max_price'].append(amount(match['hi']))
    for match in BOUND.finditer(raw_query):
        if any(a <= match.start() < b or a <= match.end()-1 < b for a,b in rating_spans):
            continue
        if any(a <= match.start() < b for a,b in [m.span() for m in ranges]):
            continue
        if SPEC.search(raw_query[match.end():]):
            continue
        if re.match(r'\s*(?:shoes|laptops|phones|chairs|bottles)\b',raw_query[match.end():],re.I):
            result.issues.append('Possible quantity instead of budget requires clarification.')
            continue
        result.spans.append(match.span())
        if match.start() < start:
            continue
        prefix = raw_query[max(0,match.start()-20):match.start()]
        if re.search(r"\b(?:not|no|without|không)\s*$", prefix, re.I):
            result.issues.append('Negated price operator requires clarification.')
            continue
        suffix = raw_query[match.end():]
        if re.match(r"\d|,\d|\.\d|\s*(?:[kKmM]|thousand|million|lakh|crore)\b", suffix):
            result.issues.append('Unsupported numeric price notation.')
            continue
        key = 'max_price' if re.fullmatch(UPPER, match['operator'], re.I) else 'min_price'
        prices[key].append(amount(match['value']))
    for key, values in prices.items():
        if len(set(values)) > 1:
            result.issues.append('Competing price boundaries require clarification.')
        elif values:
            setattr(result, key, values[0])
    if result.min_price is not None and result.max_price is not None and result.min_price > result.max_price:
        result.issues.append('Minimum exceeds maximum; bounds were not swapped.')
        result.min_price = result.max_price = None
    residual = raw_query
    for a,b in sorted(result.spans, reverse=True):
        residual = residual[:a] + ' '*(b-a) + residual[b:]
    # Bare money and unhandled budget/rating syntax cannot be silently discarded.
    if re.search(rf"(?:budget|price|cost|priced|rating|rated|ngân sách)\s*(?:of|is|:|around|about)?\s*{NUMBER}|{NUMBER}\s*{MONEY}|{MONEY}\s*{NUMBER}|\bbetween\b.*\d", residual, re.I):
        result.issues.append('Unresolved numeric budget/rating expression.')
    if re.search(rf'\bfor\s+{NUMBER}(?!\w)',residual,re.I):
        result.issues.append('Bare numeric amount after for requires clarification.')
    if re.search(r'\b(?:under|below|above|over)\s*-\d',residual,re.I):
        result.issues.append('Negative or malformed price requirement.')
    if re.search(r'[<>≤≥]|\b(?:under|below|above|over)\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\b',residual,re.I):
        result.issues.append('Unrecognized relational requirement needs clarification.')
    return result
