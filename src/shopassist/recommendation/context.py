"""Evidence extraction and token-conscious context construction (Phase 12).

Transforms Phase 8/9 requirements and Phase 11 Top-K products into compact,
traceable evidence blocks with prompt injection safeguards.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from shopassist.llm.schemas import QueryUnderstandingResult
from shopassist.preferences.schemas import PreferenceRepresentationResult
from shopassist.reranking.core import RerankedProduct
from shopassist.recommendation.schemas import ProductEvidence


# Boilerplate patterns commonly found in raw marketplace descriptions
BOILERPLATE_PATTERNS = [
    r"Flipkart\.com: Buy .+?(?:from Flipkart\.com|\bRs\.?\s*\d+[^.]*?\.)",
    r"Only Genuine Products\.",
    r"\d+\s*Day Replacement Guarantee\.",
    r"Free Shipping\.",
    r"Cash On Delivery[!.]?",
    r"Shop for .+?online at [^.]+?\.",
]


def clean_description_text(text: str) -> str:
    """Strip promotional marketplace boilerplate from product descriptions."""
    cleaned = text
    for pattern in BOILERPLATE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    # Remove excessive whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_product_evidence(
    product: RerankedProduct,
    *,
    currency: str = "INR",
    max_spec_items: int = 8,
    max_desc_sentences: int = 3,
    strip_boilerplate: bool = True,
) -> list[ProductEvidence]:
    """Extract verifiable evidence items from a single RerankedProduct.

    Each evidence item receives a deterministic, traceable identifier:
    `{product_id}-E{counter}`.
    """
    evidence_list: list[ProductEvidence] = []
    pid = product.product_id
    counter = 1

    def add_evidence(source_field: str, val: str) -> None:
        nonlocal counter
        clean_val = val.strip()
        if clean_val:
            eid = f"{pid}-E{counter}"
            evidence_list.append(
                ProductEvidence(
                    evidence_id=eid,
                    product_id=pid,
                    source_field=source_field,
                    text=clean_val,
                )
            )
            counter += 1

    # E1: Product name
    add_evidence("product_name", product.product_name)

    # E2: Brand (if present)
    if product.brand and product.brand.strip():
        add_evidence("brand", product.brand)

    # E3: Category
    add_evidence("category", product.category)

    # E4: Price
    add_evidence("discounted_price", f"{product.discounted_price:.2f} {currency}")

    # E5: Rating (if present)
    if product.rating is not None:
        add_evidence("rating", f"{product.rating:.1f} / 5.0")

    # Specifications from metadata (if present as dict)
    metadata_specs = product.metadata.get("product_specifications")
    specs_added = 0
    if isinstance(metadata_specs, dict):
        for k, v in metadata_specs.items():
            if specs_added >= max_spec_items:
                break
            if k and v:
                add_evidence("specifications", f"{str(k).strip()}: {str(v).strip()}")
                specs_added += 1

    # Extract from canonical retrieval_text if available
    retrieval_text = product.retrieval_text or ""
    if retrieval_text:
        parts = [p.strip() for p in retrieval_text.split("|") if p.strip()]
        for part in parts:
            if part.startswith("Specifications:") and specs_added < max_spec_items:
                spec_content = part[len("Specifications:"):].strip()
                spec_pairs = [s.strip() for s in spec_content.split(";") if s.strip()]
                for pair in spec_pairs:
                    if specs_added >= max_spec_items:
                        break
                    if ":" in pair:
                        add_evidence("specifications", pair)
                        specs_added += 1
            elif part.startswith("Description:"):
                raw_desc = part[len("Description:"):].strip()
                cleaned_desc = clean_description_text(raw_desc) if strip_boilerplate else raw_desc
                if cleaned_desc:
                    # Break into sentences
                    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned_desc) if s.strip()]
                    for s in sentences[:max_desc_sentences]:
                        if len(s) > 10:
                            add_evidence("description", s)

    return evidence_list


class EvidenceContextBuilder:
    """Builds token-optimized context and traceable evidence dictionaries."""

    def __init__(
        self,
        *,
        default_currency: str = "INR",
        max_spec_items: int = 8,
        max_desc_sentences: int = 3,
        strip_boilerplate: bool = True,
    ):
        self.default_currency = default_currency
        self.max_spec_items = max_spec_items
        self.max_desc_sentences = max_desc_sentences
        self.strip_boilerplate = strip_boilerplate

    def build_context(
        self,
        query_result: QueryUnderstandingResult,
        preference_result: PreferenceRepresentationResult | None,
        products: Sequence[RerankedProduct],
    ) -> tuple[str, dict[str, list[ProductEvidence]], dict[str, ProductEvidence]]:
        """Construct prompt context and evidence tables.

        Returns:
            Tuple of:
            - formatted_context: Compact prompt string containing user requirements and evidence blocks.
            - product_evidence_store: Mapping from product_id to list of ProductEvidence.
            - flat_evidence_map: Mapping from evidence_id to ProductEvidence.
        """
        # Determine currency from constraints or default
        currency = query_result.output.hard_constraints.currency or self.default_currency

        # Build evidence items per product
        product_evidence_store: dict[str, list[ProductEvidence]] = {}
        flat_evidence_map: dict[str, ProductEvidence] = {}

        for product in products:
            items = extract_product_evidence(
                product,
                currency=currency,
                max_spec_items=self.max_spec_items,
                max_desc_sentences=self.max_desc_sentences,
                strip_boilerplate=self.strip_boilerplate,
            )
            product_evidence_store[product.product_id] = items
            for item in items:
                flat_evidence_map[item.evidence_id] = item

        # Build context string
        context_parts: list[str] = []

        # 1. User requirements section
        context_parts.append("### USER REQUIREMENTS")
        context_parts.append(f"- Original query: {query_result.query}")
        if query_result.output.semantic_query and query_result.output.semantic_query != query_result.query:
            context_parts.append(f"- Semantic intent: {query_result.output.semantic_query}")

        hc = query_result.output.hard_constraints
        constraints_str: list[str] = []
        if hc.category:
            constraints_str.append(f"Category='{hc.category}'")
        if hc.brand:
            constraints_str.append(f"Brand='{hc.brand}'")
        if hc.min_price is not None:
            constraints_str.append(f"MinPrice={hc.min_price} {currency}")
        if hc.max_price is not None:
            constraints_str.append(f"MaxPrice={hc.max_price} {currency}")
        if hc.min_rating is not None:
            constraints_str.append(f"MinRating={hc.min_rating}")
        if constraints_str:
            context_parts.append(f"- Hard constraints: {', '.join(constraints_str)}")

        # Soft preferences
        prefs = query_result.output.soft_preferences or []
        if preference_result and preference_result.normalized_preferences:
            prefs = preference_result.normalized_preferences
        if prefs:
            context_parts.append(f"- Soft preferences: {', '.join(prefs)}")
        if preference_result and preference_result.preference_query:
            context_parts.append(f"- Preference focus: {preference_result.preference_query}")

        context_parts.append("\n### CANDIDATE PRODUCTS (ORDERED BY RELEVANCE RANK)")

        # 2. Product blocks with XML-delimited untrusted evidence
        for idx, product in enumerate(products, 1):
            pid = product.product_id
            evidence_items = product_evidence_store.get(pid, [])
            rating_display = f"{product.rating:.1f}/5.0" if product.rating is not None else "Not specified"
            brand_display = product.brand or "Not specified"

            block_lines = [
                f"[CANDIDATE #{idx}]",
                f"Product ID: {pid}",
                f"Product Name: {product.product_name}",
                f"Brand: {brand_display}",
                f"Category: {product.category}",
                f"Price: {product.discounted_price:.2f} {currency}",
                f"Rating: {rating_display}",
                f"Phase 11 Rank: {product.reranked_rank} (RRF score: {product.rrf_score:.4f})",
                f"<product_evidence product_id=\"{pid}\">",
            ]

            for item in evidence_items:
                block_lines.append(f"  [{item.evidence_id}] ({item.source_field}): {item.text}")

            block_lines.append("</product_evidence>\n")
            context_parts.append("\n".join(block_lines))

        formatted_context = "\n".join(context_parts)
        return formatted_context, product_evidence_store, flat_evidence_map
