"""Groundedness validation and authoritative metadata merging (Phase 12).

Inspects LLM output for:
- Product identity fidelity (Top-K subset, no foreign/duplicate IDs, sequence preservation)
- Evidence citation validity (valid IDs, product ownership, no cross-product citations)
- Merging authoritative structured metadata directly from Phase 11
- Generating safe deterministic fallbacks on failure
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from shopassist.reranking.core import RerankedProduct
from shopassist.recommendation.schemas import (
    LLMRecommendationPayload,
    ProductClaim,
    ProductEvidence,
    RecommendationResult,
    RecommendationStatus,
    RecommendedProduct,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class GroundednessValidator:
    """Validates LLM-generated recommendations against canonical upstream evidence."""

    def __init__(self, *, default_currency: str = "INR") -> None:
        self.default_currency = default_currency

    def validate_and_merge(
        self,
        payload: LLMRecommendationPayload,
        candidate_products: Sequence[RerankedProduct],
        product_evidence_store: dict[str, list[ProductEvidence]],
        flat_evidence_map: dict[str, ProductEvidence],
        *,
        usage: TokenUsage | None = None,
        model_name: str | None = None,
        language: str = "auto",
        applied_constraints: dict[str, Any] | None = None,
    ) -> RecommendationResult:
        """Validate LLM output against candidate products and merge authoritative fields.

        Returns:
            RecommendationResult with status SUCCESS (or VALIDATION_FAILURE if severe invariants violated).
        """
        warnings: list[str] = []
        candidate_map = {p.product_id: p for p in candidate_products}
        candidate_ids = [p.product_id for p in candidate_products]

        # 1. Product ID Verification
        llm_products = payload.products
        seen_pids: set[str] = set()
        llm_map = {}

        for item in llm_products:
            pid = item.product_id
            if pid not in candidate_map:
                warnings.append(f"LLM generated product ID '{pid}' which is not in candidate set. Dropping invalid product.")
                continue
            if pid in seen_pids:
                warnings.append(f"LLM generated duplicate product ID '{pid}'. Keeping first occurrence.")
                continue
            seen_pids.add(pid)
            llm_map[pid] = item

        # If zero valid products matched
        if not llm_map:
            logger.error("Groundedness validation failed: Zero candidate products recognized in LLM output.")
            return self.generate_deterministic_fallback(
                candidate_products,
                product_evidence_store,
                reason="Groundedness validation failed: No valid candidate IDs found in LLM response.",
                usage=usage,
                model_name=model_name,
                applied_constraints=applied_constraints,
                language=language,
            )

        # 2. Reassemble products in original candidate order
        recommended_products: list[RecommendedProduct] = []

        for p in candidate_products:
            pid = p.product_id
            llm_exp = llm_map.get(pid)
            available_ev = product_evidence_store.get(pid, [])
            currency = applied_constraints.get("currency") if applied_constraints else self.default_currency
            if not currency:
                currency = self.default_currency

            if llm_exp is None:
                # LLM omitted this product: synthesize deterministic explanation
                warnings.append(f"Candidate product '{pid}' was omitted by LLM; generated fallback explanation.")
                summary_reason = f"{p.product_name} matches the requested {p.category} category."
                strengths = [
                    ProductClaim(
                        claim=f"Authentic {p.brand or p.category} product priced at {p.discounted_price:.2f} {currency}",
                        evidence_ids=[f"{pid}-E1"] if f"{pid}-E1" in flat_evidence_map else [],
                    )
                ]
                limitations = [
                    ProductClaim(
                        claim="Full detailed explanation was omitted by model generation.",
                        evidence_ids=[],
                    )
                ]
                comp_note = "Alternative option in the retrieved set."
            else:
                summary_reason = llm_exp.summary_reason

                # Validate strengths evidence
                strengths: list[ProductClaim] = []
                for claim_item in llm_exp.strengths:
                    valid_eids = []
                    for eid in claim_item.evidence_ids:
                        ev = flat_evidence_map.get(eid)
                        if ev is None:
                            warnings.append(f"Claim for product '{pid}' cited non-existent evidence ID '{eid}'.")
                        elif ev.product_id != pid:
                            warnings.append(f"Claim for product '{pid}' cited evidence '{eid}' belonging to another product '{ev.product_id}'.")
                        else:
                            valid_eids.append(eid)
                    strengths.append(ProductClaim(claim=claim_item.claim, evidence_ids=valid_eids))

                # Validate limitations evidence
                limitations: list[ProductClaim] = []
                for claim_item in llm_exp.limitations:
                    valid_eids = []
                    for eid in claim_item.evidence_ids:
                        ev = flat_evidence_map.get(eid)
                        if ev is None:
                            warnings.append(f"Limitation for product '{pid}' cited non-existent evidence ID '{eid}'.")
                        elif ev.product_id != pid:
                            warnings.append(f"Limitation for product '{pid}' cited evidence '{eid}' belonging to another product '{ev.product_id}'.")
                        else:
                            valid_eids.append(eid)
                    limitations.append(ProductClaim(claim=claim_item.claim, evidence_ids=valid_eids))

                comp_note = llm_exp.comparison_note

            # Merge authoritative fields directly from RerankedProduct
            rec_product = RecommendedProduct(
                product_id=p.product_id,
                product_name=p.product_name,
                brand=p.brand,
                category=p.category,
                discounted_price=float(p.discounted_price),
                rating=float(p.rating) if p.rating is not None else None,
                currency=currency,
                original_rank=p.original_rank,
                reranked_rank=p.reranked_rank,
                rrf_score=float(p.rrf_score),
                summary_reason=summary_reason,
                strengths=strengths,
                limitations=limitations,
                comparison_note=comp_note,
                available_evidence=available_ev,
            )
            recommended_products.append(rec_product)

        overview_text = payload.overview.strip() if payload.overview and payload.overview.strip() else "Here are the top recommended products matching your criteria:"

        return RecommendationResult(
            contract_version="1.0.0",
            status=RecommendationStatus.SUCCESS,
            overview=overview_text,
            products=recommended_products,
            total_candidates_received=len(candidate_products),
            recommended_count=len(recommended_products),
            applied_constraints=applied_constraints or {},
            language=language,
            model_name=model_name,
            usage=usage or TokenUsage(),
            warnings=warnings,
            diagnostic_reason=None,
        )

    def generate_deterministic_fallback(
        self,
        candidate_products: Sequence[RerankedProduct],
        product_evidence_store: dict[str, list[ProductEvidence]],
        *,
        reason: str,
        usage: TokenUsage | None = None,
        model_name: str | None = None,
        applied_constraints: dict[str, Any] | None = None,
        language: str = "auto",
    ) -> RecommendationResult:
        """Create a safe, deterministic fallback recommendation directly from verified metadata."""
        currency = applied_constraints.get("currency") if applied_constraints else self.default_currency
        if not currency:
            currency = self.default_currency

        recommended_products: list[RecommendedProduct] = []
        for p in candidate_products:
            pid = p.product_id
            available_ev = product_evidence_store.get(pid, [])
            rating_str = f" with rating {p.rating:.1f}/5.0" if p.rating is not None else ""
            brand_str = f" by {p.brand}" if p.brand else ""

            rec = RecommendedProduct(
                product_id=p.product_id,
                product_name=p.product_name,
                brand=p.brand,
                category=p.category,
                discounted_price=float(p.discounted_price),
                rating=float(p.rating) if p.rating is not None else None,
                currency=currency,
                original_rank=p.original_rank,
                reranked_rank=p.reranked_rank,
                rrf_score=float(p.rrf_score),
                summary_reason=f"{p.product_name}{brand_str} in {p.category} at {p.discounted_price:.2f} {currency}{rating_str}.",
                strengths=[
                    ProductClaim(
                        claim=f"Verified {p.category} candidate meeting query retrieval criteria.",
                        evidence_ids=[f"{pid}-E1"] if any(e.evidence_id == f"{pid}-E1" for e in available_ev) else [],
                    )
                ],
                limitations=[
                    ProductClaim(
                        claim="Generated via deterministic fallback; natural language explanation unavailable.",
                        evidence_ids=[],
                    )
                ],
                comparison_note=f"Rank #{p.reranked_rank} candidate in retrieval results.",
                available_evidence=available_ev,
            )
            recommended_products.append(rec)

        overview = "Here are the top products matching your query (generated via verified metadata fallback):"
        if language.lower() in ("vi", "vietnamese"):
            overview = "Dưới đây là các sản phẩm hàng đầu phù hợp với yêu cầu của bạn (thông tin xác thực từ danh mục):"

        return RecommendationResult(
            contract_version="1.0.0",
            status=RecommendationStatus.DETERMINISTIC_FALLBACK,
            overview=overview,
            products=recommended_products,
            total_candidates_received=len(candidate_products),
            recommended_count=len(recommended_products),
            applied_constraints=applied_constraints or {},
            language=language,
            model_name=model_name,
            usage=usage or TokenUsage(),
            warnings=[reason],
            diagnostic_reason=reason,
        )
