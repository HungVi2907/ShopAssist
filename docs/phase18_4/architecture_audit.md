# Phase 18.4 architecture and safety audit

2026-11-26 (Asia/Saigon). Starting checkout: clean `main` at `757552e`, equal to `origin/main` after fetch. Phase 18.1–18.3 reports and the Phase 18 handover supplied the prior limitations. Q1S is frozen experimental input, not production-approved. Query Understanding was not modified or reoptimized.

## Actual Phase 12 flow

| Stage | Source and behavior |
|---|---|
| Entry and upstream checks | `recommendation/core.py`, `RecommendationService.generate`: checks typed Phase 8 and Phase 11 input, propagates clarification and reranking terminal statuses, slices supplied order to configured top K. The audit found `QueryUnderstandingResult.is_valid=False` was not checked and Phase 9 embedding failure was not explicitly terminal; both now stop before inference. |
| Context preparation | `context.py:142`, `EvidenceContextBuilder.build_context`: original/semantic request, hard constraints, preferences and ordered product blocks. `extract_product_evidence` (`:39`) creates deterministic per-product evidence IDs for names, brand, category, price, rating, bounded specs and descriptions. |
| Prompt | `prompts.py:11`, `RECOMMENDATION_SYSTEM_PROMPT`, and `build_recommendation_user_prompt` (`:45`): product coverage/order, factual claims with evidence IDs, caveats, comparisons, untrusted catalog text and English/Vietnamese policy. |
| Internal schema | `schemas.py:60-105`: `LLMProductClaim` nested inside `LLMProductExplanation` and `LLMRecommendationPayload`; repeated product IDs, summary, strength/limitation objects and citation arrays, plus comparison/overview prose. |
| Dispatch | `core.py` builds a Gateway request with `phase12.recommendation.v1` or calls the legacy `BaseRecommendationProvider.generate_recommendation_payload`. `provider.py` owns external provider implementations and JSON parsing. None was called in this phase. |
| Validation/assembly | `validation.py:35`, `GroundednessValidator.validate_and_merge`: filters unknown/duplicate IDs, restores supplied order, checks citation existence/ownership, fills missing product explanations, merges authoritative Phase 11 metadata. |
| Fallback | `validation.py:183`, `generate_deterministic_fallback`; also used on provider/Gateway failure. The public result has explicit `DETERMINISTIC_FALLBACK`, metadata, usage, warnings and model attribution. Partial omitted-product fallback historically still returns `SUCCESS`, so it must be counted separately. |
| Result | Public `RecommendedProduct` (`schemas.py:108`) and `RecommendationResult` (`:148`). URLs are not a field of this public recommendation item; no schema addition was made. Existing URLs remain upstream metadata, not LLM replacements. |

The provider/Gateway paths track usage and latency, actual Gateway model and deadlines. Legacy exception strings can still enter legacy fallback diagnostics; the new native candidate uses fixed safe result diagnostics, keeping raw evaluation detail isolated. Phase 18 Gateway route approval and T17 exhaustion remain in force. Configured recommendation HTTP timeout is 30 seconds, API request timeout 90 seconds and bot request timeout 95 seconds; these are whole-pipeline constraints, not permission to allocate all time to generation.

## Complexity and verified risks

The LLM is asked to repeat already known identifiers/order and produce several independent free-text fields per product. Context repeats product metadata both outside and inside evidence blocks; the existing builder limits specs/descriptions but does not retain every source attribute. Those production bounds and the exact supplied evidence are preserved in baseline artifacts. Five-product nested output can exhaust the 4096-token context/output window. That is measured behavior, not proof that prompt length alone causes extraction or claim failures.

The isolated R0 pilot used the real production prompt, builder, schema and validator on 20 frozen local-catalog fixtures. It deliberately benchmarks the **generation stage** even for negative/upstream-invalid fixtures; it is not a faithful claim that the service would dispatch a clarification request. Service propagation is tested separately. The snapshots under `frozen_baseline` preserve the original validator before wording corrections. JSON parse errors were later assembled through this frozen fallback in a separate offline replay, without overwriting raw baseline results.

| Risk | Controlled evidence | Finding |
|---|---|---|
| Citation ownership does not prove entailment | Sparse catalog fixture with a valid name evidence ID attached to durability/all-device compatibility; `safety_reproduction_before.json` | Original validator retains the claim. |
| Invalid citation does not remove false text | Nonexistent evidence ID on “Best performance” | Original validator removes the reference but retains the claim text. |
| Unverified summaries/comparisons/overview | Waterproof/authentic/battery summary and cheapest/best comparison without supporting facts | Free text is accepted independently of citation checks. |
| Contradiction and absence inference | Same controlled result claims waterproof in summary and not waterproof in limitations | No contradiction/entailment check exists; missing evidence is not evidence of absence. |
| Fallback overclaims | Omitted-product fallback says “Authentic”; full fallback says verified candidate meeting retrieval criteria | Neither follows merely from supplied product metadata. Wording/citation fixes are narrowly scoped and tested. |
| Wrong product type | Charging pad→Lightning cable, speaker→headset, body cover→steering cover | Broad-category retrieval success is not product relevance. The native candidate now refuses these controlled cases without generating explanations. Retrieval algorithms are unchanged; track for Phase 18.6. |

The initial reproduction artifact's `input` was subsequently mutated to an empty list by the harness; its retained unsupported output demonstrates the failure, and the exact frozen-validator replay artifact supplies an unmutated input for reproduction. This is an evaluation artifact limitation, not hidden evidence repair.

Existing Phase 12 reports are seven-scenario historical external-provider experiments and explicitly defer semantic entailment/human review. Their “grounded” checks primarily establish citation ownership, not full claim support. The preserved T17 Groq review links PVC/synthetic leather to “durability” and contains limitations such as no other color options; these require semantic review and were not treated as approved native evidence. No historical score or exhausted T17 budget was overwritten.

## Responsibility decision

Python already owns authoritative metadata, order, selection, prices, ratings, evidence IDs and final assembly. Native R3 also owns prose templates, unknown-information caveats and relevance/failure gates. The model only selects indices of supplied facts. It cannot insert a new product/price/attribute into the final response. Exact catalog attribution replaces unverified free paraphrase; it does not certify catalog truth or user suitability. This is a measured simplification after R0, R1 and R2 failures, not a new recommendation framework.

The historical free-text validator remains an ownership checker outside the opt-in native path. Its general entailment weakness is documented, not claimed solved by a keyword filter. Production activation requires separate approved native schema binding and quality review.
