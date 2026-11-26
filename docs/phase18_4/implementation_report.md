# Phase 18.4 implementation report

**Selected experimental candidate: R3 evidence selection with source-backed Python wording.** Public schemas, Q1S, retrieval, embeddings, reranking, historical artifacts and T17 are preserved. No production Gateway route is activated, no model downloaded/modified, and no commit or push was made. Phase 18 remains `IMPLEMENTED_PENDING_BACKUP_VALIDATION`.

## Minimal implementation

| File | Change |
|---|---|
| `src/shopassist/recommendation/local.py` | Opt-in `LocalRecommendationGenerator`, one native async HTTP call, conservative relevance/upstream checks, evidence projection, constrained per-product schema, strict JSON/citation checks, source-backed assembly, safe fallback and client/deadline handling. |
| `src/shopassist/recommendation/core.py` | Explicit `local_generator` injection, mutual exclusion with legacy provider/Gateway, client cleanup, and terminal handling for invalid Phase 8 / failed Phase 9 results. No default application binding. |
| `src/shopassist/recommendation/validation.py` | Removes unsupported authenticity/suitability wording from deterministic fallback and omitted explanations; omitted-price claim now cites actual price evidence rather than the product-name evidence. Legacy free-text entailment remains unresolved. |
| `scripts/evaluate_phase18_4.py` | Frozen catalog fixtures, isolated native R0–R3/D0 comparison and raw/intermediate/final diagnostics. |
| `tests/test_phase18_4.py` | Metadata, IDs/order, citations, free claims, missing information, upstream gates, transport failures, cancellation, ownership, token metadata, parent deadline and one-call tests with HTTPX MockTransport. |

The service is selected explicitly with `RecommendationService(local_generator=LocalRecommendationGenerator())`. `aclose()` closes an owned native client; a caller-supplied shared client remains caller-owned. A future Gateway should replace experimental client composition with one common native adapter for both tasks, not add permanent clients per stage. Async clients are created/used/closed on the same event loop in the runner. Repeated cross-loop synchronous client reuse has not been validated for production.

## Schema progression

R0 and R1 retain the existing public-facing internal payload. Both failed the bounded pilot. R2's shorter list of product index, reason and fact indices still produced duplicates and unverifiable paraphrases; none passed the strict source-fact guard in the measured comparison. The first R3 list form also failed by duplicating products and choosing too many facts. That failed experiment is retained.

Final R3 removes repeated identity/order from the model task:

```json
{"p1": [4, 6], "p2": [5, 7]}
```

`selection_schema(supplied)` creates required keys for exactly the provided product positions, forbids extra keys, constrains each array to 1–3 integer indices within that product's supplied fact list, and uses strict Pydantic types. Python rejects duplicate keys/indices and invalid values. Python maps these aliases to original evidence IDs and product IDs and always assembles the supplied product order. The model never reproduces authoritative product IDs or metadata. R2 retains the index-list schema only as an experimental control.

This is an incompatible internal meaning and must not bind to `phase12.recommendation.v1`. The proposed future ID is `phase12.catalog-selection.v2`. Actual per-request JSON schemas are recorded in each row and in the frozen schema collection. Early `R3.schema.json` files are unused pre-factory placeholders; they are not the schema binding authority. The corrected runner writes a factory descriptor and records actual request schemas. Public `RecommendedProduct` and `RecommendationResult` are unchanged.

The final concise prompt asks for useful supplied fact indices, one required product key per input position, untrusted-data handling, JSON only and no suitability inference. It carries no category list, pricing logic or final assembly instructions. Historical prompts remain untouched. No prompt examples use evaluation cases.

## Evidence and honest wording

The existing evidence builder supplies stable evidence IDs. The native projection provides product name, brand, category, price, rating and bounded structured specifications as indexed facts. Descriptions are deliberately excluded from model input and recorded separately in diagnostics. This is a declared evidence projection, not silent string truncation. All original user requirements remain in the request. Unsupported mandatory feature/compatibility questions stop before inference; optional features not explicitly evidenced remain unverified.

R2 reasons must equal one selected fact exactly; otherwise the whole request falls back. R3 accepts no free reason. A final strength is `Catalog lists: <exact supplied fact>` (Vietnamese attribution wrapper when requested), with the original owning evidence ID. No conclusion about comfort, durability, universal compatibility, authenticity or performance is inferred from materials or citations. Missing rating yields “The catalog does not specify a rating”, never “poor rating”. No numeric comparison is generated. Metadata, ranking and price/rating values are copied from trusted upstream products; existing public URL behavior is preserved.

Local relevance checks reuse existing product-type aliases plus the three demonstrated accessory mismatches and two limited Vietnamese product phrases. Unknown type, mismatched name/category/brand/price/rating, unsupported compatibility/mandatory-feature requirements, exclusions, foreign currency and invalid upstream state produce terminal responses. These conservative checks can reject legitimate synonyms and cannot prove product suitability or every mandatory feature. They do not repair retrieval and must not be interpreted as a complete relevance classifier. This limitation remains a production blocker.

Fallback uses safe catalog metadata and explicit `DETERMINISTIC_FALLBACK`, not model-generation credit. Transport failure has no fabricated model attribution; a valid reported model that subsequently returns invalid output remains an attempted model with fallback status and captured usage. Result diagnostics are fixed safe messages; detailed raw errors stay in isolated evaluation diagnostics. D0 runs the same upstream/relevance checks with zero model calls.

## Budgets and lifecycle

The original prompt/schema baseline used 1,536 output tokens, not the 512-token query-extraction cap. Eight of 20 R0 responses reached the cap; a separate sparse-case 2,048-token probe still truncated. Full-schema requirements are not reliably solved just by increasing a cap inside a fixed 4096-token context.

Final selection output measured at most 73 completion tokens on development, so R3 uses a separately validated 256-token cap with the same model, temperature 0, seed 42 and context 4096. Initial controlled comparisons used 1,536 for all candidates; the final cap is a documented output-budget optimization. R2's free-reason comparison retains 1,536. Explicit UTF-8 byte bounds plus template margin and completion reserve conservatively reject oversized native requests without dropping requirements/facts; reported token counts are checked again. This is a conservative admission policy, not a claim about unobserved server-internal attention/truncation.

One HTTP request is allowed; there is no repair/retry or second model judge. HTTP timeout uses fallback, parent deadline exhaustion propagates `asyncio.TimeoutError`, and cancellation propagates rather than becoming fallback. The experiment has a 30-second HTTP timeout; future Gateway must adapt parent deadline errors to its existing typed contract. API/bot whole-pipeline deadlines remain 90/95 seconds.

## Freeze and readiness

`frozen_candidate/manifest.json` freezes generation before new provisional catalog cases. `frozen_candidate/final/manifest.json` additionally records the core Phase 9 failure-propagation guard and evaluation-schema descriptor correction. Generation code/prompt/schema were unchanged by provisional results. The original and final source snapshots remain available, with result/dataset hashes in the experiment index.

R3 is structurally compatible and suitable for guarded experimental Phase 18.5 integration tests, not production deployment. It generates evidence selections, not independently verified fluent recommendations. Semantic usefulness, requirement alignment, localized catalog facts, catalog truth, synonym/relevance coverage and human-reviewed groundedness remain open. The unchanged legacy free-text path still cannot establish entailment. No acceptance requirement has been lowered and no route approval is implied.
