"""Pure query-grounded transformation and semantic validation; no inference."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
import re

from pydantic import BaseModel, ConfigDict
from shopassist.llm.constraints import parse_constraints
from shopassist.llm.normalization import CATEGORY_SYNONYM_MAP, normalize_brand, normalize_category
from shopassist.llm.refinement_rules import is_out_of_domain_query
from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput


class ExtractedShoppingIntent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    product: str | None
    brand: str | None
    budget: str | None
    rating: str | None
    preferences: list[str]


class SemanticStatus(str, Enum):
    VERIFIED = 'VERIFIED'
    DETERMINISTICALLY_CORRECTABLE = 'DETERMINISTICALLY_CORRECTABLE'
    CLARIFICATION_REQUIRED = 'CLARIFICATION_REQUIRED'


@dataclass
class SemanticValidation:
    output: QueryUnderstandingOutput
    status: SemanticStatus
    issues: list[str]
    corrections: list[str]
    transformed: QueryUnderstandingOutput | None = None


@lru_cache(maxsize=4096)
def phrase_pattern(text: str):
    return re.compile(r'(?<!\w)' + re.escape(text.strip()) + r'(?!\w)', re.I)


def mentioned(text: str | None, query: str) -> bool:
    return bool(text and phrase_pattern(text).search(query))


def normalized_phrase(text: str) -> str:
    """Bounded lexical equivalents, not edit-distance or category-wide matching."""
    text = re.sub(r'[-_]', ' ', text.casefold()).strip()
    for source,target in (('wireless charging pad','wireless charger'),
                          ('running footwear','running shoes'),('gaming notebook','gaming laptop')):
        text = re.sub(r'\b'+source+r'\b',target,text)
    tokens = text.split()
    singular = {k[:-1] for k in CATEGORY_SYNONYM_MAP if k.endswith('s') and ' ' not in k}
    return ' '.join(t[:-3]+'y' if t.endswith('ies') else
                    t[:-1] if t.endswith('s') and (t[:-1] in singular or t in CATEGORY_SYNONYM_MAP or t in ('parties','chargers','laptops','speakers')) else t
                    for t in tokens)


def grounded_phrase(text: str | None, query: str) -> bool:
    return bool(text and (mentioned(text,query) or mentioned(normalized_phrase(text),normalized_phrase(query))))


def grounded_preferences(preferences: list[str], query: str) -> list[str]:
    """Copy supported source wording; only repair bounded plural/style variants."""
    result = []
    words = list(re.finditer(r"[\w'-]+",query))
    for preference in preferences:
        candidate = preference.strip().lower()
        if mentioned(candidate,query):
            result.append(candidate); continue
        if candidate in ("men's","men's style","women's","women's style"):
            candidate = 'for women' if candidate.startswith('women') else 'for men'
        candidate = re.sub(r'\s+(?:material|style)$','',candidate)
        for start in range(len(words)):
            for size in range(1,min(8,len(words)-start)+1):
                source = query[words[start].start():words[start+size-1].end()]
                if normalized_phrase(source)==normalized_phrase(candidate):
                    result.append(source.lower()); break
            else:
                continue
            break
    return list(dict.fromkeys(result))


def resolve_category(product: str | None) -> str | None:
    if not product:
        return None
    # Longest product phrase wins; reject unresolved ties across categories.
    product = normalized_phrase(product)
    aliases = {**{normalized_phrase(k):v for k,v in CATEGORY_SYNONYM_MAP.items()},
               'bluetooth speaker':'Mobiles & Accessories', 'giày': 'Footwear', 'điện thoại': 'Mobiles & Accessories',
               'máy tính xách tay': 'Computers', 'đồng hồ': 'Watches', 'tai nghe': 'Mobiles & Accessories'}
    matches = [(len(k),v) for k,v in aliases.items() if mentioned(k, product)]
    if not matches:
        return normalize_category(product) if product in aliases.values() else None
    longest = max(n for n,v in matches)
    categories = {v for n,v in matches if n == longest}
    return categories.pop() if len(categories) == 1 else None


def validate_against_query(raw_query: str, output: QueryUnderstandingOutput,
                           catalog_brands: set[str] | None = None) -> SemanticValidation:
    """Replace numeric slots only from raw evidence; fail closed on uncertainty."""
    out = output.model_copy(deep=True)
    parsed = parse_constraints(raw_query)
    issues = list(parsed.issues); corrections = []
    for key in ('min_price','max_price','min_rating','currency'):
        before, after = getattr(out.hard_constraints,key), getattr(parsed,key)
        if before != after:
            corrections.append(f'{key}: {before!r} -> {after!r} from original query')
        setattr(out.hard_constraints,key,after)
    raw_brand = out.hard_constraints.brand
    brand = None if (raw_brand or '').strip().casefold() in ('unknown','not specified','not provided') else normalize_brand(raw_brand,catalog_brands)
    # Ignore catalog compatibility targets; a cover for Honda is not a Honda cover.
    manufacturer_query = re.split(r'\b(?:for|compatible with)\b',raw_query,flags=re.I)[0]
    known = {b for b in catalog_brands or set() if len(b)>2 and mentioned(b,manufacturer_query)}
    if not brand and len(known)==1:
        found = next(iter(known))
        # Recover only explicit maker syntax, not every incidental catalog token.
        if re.search(r'(?:^|\b(?:by|brand|from)\s+)' + re.escape(found) + r'\b',raw_query,re.I):
            brand = found
            corrections.append('Recovered explicitly named catalog manufacturer from original query.')
    if brand and not mentioned(brand, raw_query):
        out.hard_constraints.brand = None
        issues.append('Extracted brand is unsupported by the original query.')
    else:
        out.hard_constraints.brand = normalize_brand(brand,catalog_brands)
    # Compatibility targets and competing brands cannot become a scalar filter.
    if brand and re.search(r'\b(?:for|compatible with)\s+' + re.escape(brand) + r'\b', raw_query, re.I):
        out.hard_constraints.brand = None
        corrections.append('Removed compatibility target from manufacturer filter; source remains in semantic query.')
        known.discard(brand)
        brand = None
    # Tiny catalog names such as "AT" are ordinary function words, not reliable NER.
    if len(known) > 1:
        issues.append('Multiple named catalog brands require clarification.')
        out.hard_constraints.brand = None
        corrections.append('Removed arbitrary scalar brand from competing-maker request.')
    if brand and brand.casefold() not in {b.casefold() for b in catalog_brands or set()} and any(mentioned(brand,p) for p in out.soft_preferences):
        out.hard_constraints.brand = None
        issues.append('Unrecognized manufacturer overlaps a qualitative attribute; clarify its role.')
        corrections.append('Removed unverified attribute-derived manufacturer filter.')
    if not brand and known:
        issues.append('Named brand was not reliably extracted.')
    if not brand and (raw_brand or '').casefold()=='unknown' and re.match(r'^[A-Z][a-z]+\b',manufacturer_query):
        first = manufacturer_query.split()[0]
        if first.casefold() not in ('i','find','show','can','need','cheap','portable','lightweight','waterproof') and not resolve_category(first) and not any(mentioned(first,p) for p in out.soft_preferences):
            issues.append('Possible manufacturer was not reliably extracted.')
    nonnumeric = raw_query
    for a,b in sorted(parsed.spans,reverse=True):
        nonnumeric = nonnumeric[:a]+' '*(b-a)+nonnumeric[b:]
    if re.search(r'\b(?:not|no|without|except|excluding|không)\b',nonnumeric,re.I):
        issues.append('V1 cannot safely represent exclusions or negated requirements.')
    if is_out_of_domain_query(raw_query):
        out.hard_constraints.category = None
        if out.hard_constraints.brand:
            corrections.append('Suppressed brand filter for unsupported domain.')
            out.hard_constraints.brand = None
        issues.append('Unsupported product domain.')
    if re.search(r'\b(?:ignore .*instructions|ignore .*rules|system prompt|generate sql|write sql)\b',raw_query,re.I):
        issues.append('Instruction-like content requires review; extraction alone cannot establish trust.')
    if out.hard_constraints.category is None:
        issues.append('Missing or unsupported product category.')
    if issues:
        out.needs_clarification = True
        out.clarification_reason = ' '.join(dict.fromkeys(issues))
    status = SemanticStatus.CLARIFICATION_REQUIRED if out.needs_clarification else (SemanticStatus.DETERMINISTICALLY_CORRECTABLE if corrections else SemanticStatus.VERIFIED)
    return SemanticValidation(out,status,list(dict.fromkeys(issues)),corrections,output.model_copy(deep=True))


def transform_extraction(raw_query: str, extracted: ExtractedShoppingIntent,
                         catalog_brands: set[str] | None = None) -> SemanticValidation:
    issues = []
    product = extracted.product
    if not grounded_phrase(product,raw_query):
        issues.append('Product is absent or not grounded in original wording.')
        product = None
    prefs = grounded_preferences(extracted.preferences,raw_query)
    discarded = prefs != [p.strip().lower() for p in extracted.preferences]
    for word in ('cheap','affordable','budget-friendly'):
        if mentioned(word,raw_query) and word not in prefs:
            prefs.append(word)
    # Raw text preserves specs that a small extractor may omit; remove only recognized
    # numeric constraint spans and conversational boilerplate, not product descriptors.
    semantic = raw_query
    for a,b in sorted(parse_constraints(raw_query).spans,reverse=True):
        semantic = semantic[:a] + ' '*(b-a) + semantic[b:]
    semantic = re.sub(r'^(?:I need|show me|can you find me|find me|find|I want)\s+', '',semantic,flags=re.I)
    semantic = re.sub(r'\b(?:rupees?|rs|INR|dollars?|USD|euros?|EUR)\b','',semantic,flags=re.I)
    semantic = re.sub(r'\s+',' ',semantic).strip(' .,') or product or 'unspecified product query'
    category = resolve_category(product)
    if product and normalized_phrase(product)=='speaker' and mentioned('bluetooth speaker',raw_query):
        category = resolve_category('bluetooth speaker')
    out = QueryUnderstandingOutput(semantic_query=semantic,
        hard_constraints=HardConstraints(category=category,brand=extracted.brand),
        soft_preferences=prefs,needs_clarification=bool(issues),clarification_reason=' '.join(issues) or None)
    result = validate_against_query(raw_query,out,catalog_brands)
    if discarded:
        result.corrections.append('Normalized or removed optional preferences using original wording.')
        if result.status == SemanticStatus.VERIFIED:
            result.status = SemanticStatus.DETERMINISTICALLY_CORRECTABLE
    result.issues = issues + result.issues
    if issues:
        result.output.needs_clarification = True
        result.output.clarification_reason = ' '.join(result.issues)
        result.status = SemanticStatus.CLARIFICATION_REQUIRED
    return result
