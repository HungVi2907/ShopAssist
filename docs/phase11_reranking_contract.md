# Phase 11 Reranking Contract

**Contract version:** `1.0.0`  
**Input:** Phase 8 `QueryUnderstandingResult`, Phase 9 `PreferenceRepresentationResult`, and Phase 10 `HybridRetrievalResult`  
**Output:** Phase 11 `RerankingResult`

## Request and candidate boundary

`RerankingService.rerank(query_result, preference_result, retrieval_result, *, top_k=None, method=None)` accepts the actual typed production-phase objects. A successful Phase 10 result must contain unique `HybridCandidate` objects. Phase 11 scores only those IDs and cannot add, search for, or substitute products.

The canonical Phase 5.2 `retrieval_text` is loaded from the local catalog artifact and resolved strictly by `product_id`. A missing or duplicate catalog ID/text fails the request. The loader computes a SHA-256 and product/text counts and checks them against `data/interim/phase11/phase11_catalog_manifest.json` when present; this manifest is added to returned product metadata. Phase 10 v1 does not carry a matching catalog snapshot identifier, so the hash identifies the Phase 11 text source but cannot prove that the database rows came from the same snapshot. Candidate metadata is not used as an alternate text source because the Phase 10 lexical branch does not carry all canonical fields.

The query pair uses Phase 9 `preference_query` when status is `SUCCESS`, which is verified against the Phase 8 semantic query and positive preference list using the Phase 9 deterministic composer. When Phase 9 returns `NO_PREFERENCES`, Phase 11 verifies that Phase 8 and Phase 9 both contain no preferences, then uses Phase 8 `semantic_query`. The original raw user query is not concatenated into the positive query pair.

## Methods

| Method | Formula / behavior | Intended use |
| --- | --- | --- |
| `RRF` | Stable pass-through ordered by Phase 10 `rrf_score` descending; then original rank, then ID | Conservative default |
| `MULTI_SIGNAL` | Mean of dense and lexical branch rank utilities. Per branch: `(max_rank_in_fixed_pool - rank + 1) / max_rank_in_fixed_pool`; missing branch evidence is zero; final utility is the arithmetic mean of the two branches | Experimental, untrained rank aggregation |
| `CROSS_ENCODER` | Batch score `(query, canonical retrieval_text)` pairs; sort score descending; equal scores map to `0.5` for diagnostics and fall back to original rank | Experimental when an explicitly loaded local model is supplied |
| `COMBINED` | `w_ce * minmax(CE score) + w_ms * multi_signal_utility`, with nonnegative weights normalized by their sum | Disabled until weights are selected on a development split; both weights must be passed explicitly |

Constraint match is not added as a ranking signal: Phase 10 is responsible for applying eligibility filters, so a Boolean match would be constant for eligible products. Rating is carried to Phase 12 but not used for ranking; 89.36% of catalog ratings are null and no evaluation supports a rating weight. Phase 10 RRF itself is unchanged.

Cross-Encoder scores are treated as ordering signals, not calibrated probabilities. The selected model is pinned to revision `1b5cd67b15209f24824c50370e0397743aa9b787`, with local-only loading as the default. The default `max_length` is 512, matching the selected model's position limit; actual tokenization must use the pinned model tokenizer. Combined mode applies per-query min-max normalization; a constant score vector maps to `0.5`. Raw model outputs remain in `score_components`. Combined mode requires explicitly configured weights because no development split exists to justify defaults.

## Safety and status behavior

Phase 10 failure states map to equivalent Phase 11 statuses. Phase 11 also stops on invalid Phase 8/9 data, foreign-currency constraints, detected exclusion intent, duplicate IDs, missing canonical text, invalid numerical candidate values, missing Cross-Encoder, and model scoring failures. It returns no products on failure.

Before scoring, Phase 11 checks category, brand, minimum rating, and clear price-bound violations against the received candidate. At an exactly equal price threshold, strict/inclusive semantics cannot be inferred from Phase 8 v1; a successful Phase 10 result is trusted to have applied its verified boundary contract. Phase 11 does not silently filter inconsistent candidates: a visible mismatch produces `CONSTRAINT_VIOLATION` and an empty list.

## Output invariants

On `SUCCESS`:

- Product IDs are unique and are a subset of the Phase 10 candidate IDs.
- Product count is at most `top_k`; a short list stays short.
- Each product preserves Phase 10 metadata and dense/lexical provenance, includes exact canonical `retrieval_text`, original rank, final rank, Phase 10 RRF score, method score, and score components.
- Stable tie-breaking is final score descending, original Phase 10 rank ascending, product ID ascending.
- `applied_constraints` is carried through unchanged.

`RerankedProduct` contains: `product_id`, `original_rank`, `reranked_rank`, `product_name`, `retrieval_text`, `category`, `brand`, `discounted_price`, `rating`, `rrf_score`, `sources`, `metadata`, `final_score`, and `score_components`.

`RerankingResult` contains: `status`, `method`, `products`, `total_candidates`, `returned_count`, `model_name`, `stage_latency_ms`, `applied_constraints`, `warnings`, and safe `diagnostic_reason`.

## Phase 12 handoff

Phase 12 can consume the Top-K identity, canonical evidence text, verified structured metadata, source ranks/scores, original/final rank, applied constraints, and Phase 11 score components. The score is not a probability or a generated explanation. Phase 12 must still ground claims in the supplied product evidence and must not infer absent attributes.
