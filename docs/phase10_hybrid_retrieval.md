# Phase 10 — Hybrid Retrieval

**Contract version:** `1.0.0`  
**Status:** **PASS — offline component scope**. Phase 10 unit tests and the offline regression suite pass. Phase 10 live database behavior and catalog-scale retrieval quality are not verified.

## Scope and runtime interface

`HybridRetrievalService.retrieve(query_result, preference_result, *, top_n=None, price_boundary_semantics=None)` consumes the frozen Phase 8 production v1 result and Phase 9 result. The caller supplies an existing SQLAlchemy async engine and a fitted Phase 6 `TFIDFIndex`; Phase 10 does not mutate the database or build either artifact.

- The dense branch sends the validated Phase 9 384D unit vector to pgvector when Phase 9 status is `SUCCESS`.
- With `NO_PREFERENCES`, the service uses the Phase 7 `DenseQueryEncoder` on `semantic_query`.
- The lexical branch searches the existing TF-IDF index using `preference_query` on success or `semantic_query` when there are no preferences.
- SQL enforces category, brand, and minimum rating. Null product ratings do not satisfy a minimum rating. The same constraints are applied to local lexical candidates.
- Dense and lexical ranked lists are merged with deterministic Reciprocal Rank Fusion (RRF), de-duplicated by `product_id`, and capped at Top-N.
- A read-only filtered row count measures SQL filter time separately from the pgvector nearest-neighbor query. Results include this count, branch rank/score provenance, applied constraints, and separate SQL filter, dense retrieval, lexical and fusion timings. The count adds one query to the request path.

The public result statuses are `SUCCESS`, `NO_RESULTS`, `INVALID_INPUT`, `CLARIFICATION_REQUIRED`, `UNSUPPORTED_INTENT`, `EMBEDDING_FAILURE`, and `RETRIEVAL_FAILURE`. Dense database execution has a configurable 10 second default timeout. Database exceptions and timeouts are represented by exception type only; raw error text is not returned.

## Safety and known contract boundary

The Phase 8 production v1 schema has `min_price` and `max_price`, but it does not carry the `min_inclusive`/`max_inclusive` flags documented in the experimental v2 schema. Therefore, Phase 10 returns `UNSUPPORTED_INTENT` for a price-bounded v1 request unless the caller supplies independently verified `price_boundary_semantics` (`min_inclusive` and/or `max_inclusive`). The service never infers `<` versus `<=` from a numeric bound. A clarification path or a future versioned Phase 8 contract is required for normal end-to-end use of strict price language.

Foreign currency, invalid queries, clarification-required queries, and Phase 9 unsupported/error states stop before database access. A conservative Phase 9 negative-intent guard is also applied to the original query text, so recognized exclusions stop even if Phase 8 omitted them. Exclusions are never used as positive evidence. This guard recognizes common direct English patterns only; Phase 8 v1 extraction can still omit or misclassify other intent, so candidate retrieval is not a guarantee of semantic or constraint correctness beyond the validated fields.

Vector metadata and numeric properties are checked before the query: model ID must match the catalog model, dimension must be 384, values finite, nonzero, and unit-normalized within `1e-4`. SQL also restricts products to the configured catalog embedding model. User strings and vectors are bound parameters; SQL structure and operators are fixed by the implementation.

## Example

```python
service = HybridRetrievalService(engine, tfidf_index)
result = await service.retrieve(query_understanding_result, preference_representation)
if result.status == HybridRetrievalStatus.SUCCESS:
    candidates = result.candidates
else:
    # Route invalid, clarification, unsupported, and failure statuses explicitly.
    handle_retrieval_status(result.status, result.diagnostic_reason)
```

Only a caller that has separately established the original price operator may pass it explicitly:

```python
result = await service.retrieve(
    query_understanding_result,
    preference_representation,
    price_boundary_semantics={"max_inclusive": False},  # verified “under” operator
)
```

This metadata must come from a trusted typed source; it must not be guessed from an LLM's Phase 8 v1 numeric field.

## Verification and limitations

`tests/test_hybrid_retrieval.py` covers bound SQL values, price boundary comparisons, null ratings, vector validation, status gates, deterministic fusion, de-duplication, provenance, no-result behavior, no-preference base encoding, sanitized database failures and timeout behavior. Verification on 2026-10-10:

| Command | Result |
| --- | --- |
| `python -m pytest tests/test_hybrid_retrieval.py -q` | **21 passed** in 6.25s |
| `python -m pytest --ignore=tests/test_gemini_integration.py -m "not integration" -k "not live" -q` | **405 passed, 14 deselected** in 46.22s |
| Python in-memory syntax compilation for `hybrid.py`, retrieval `__init__.py`, and the Phase 10 test module | Passed |
| `git diff --check` | Passed |

The final regression command explicitly excluded integration-marked tests, tests named `live`, and the Gemini integration module. No Gemini call or Phase 10 database query was made during those final runs. An earlier, broader command (`python -m pytest --ignore=tests/test_gemini_integration.py -q`) passed 419 tests but included 14 live/integration checks from earlier phases; those included read-only Supabase validation. No writes or deletes were run. That broad run is recorded for transparency and is not counted as offline verification.

No representative labeled retrieval set exists yet. Passing component tests does not establish catalog-wide Recall@K, constraint satisfaction, or recommendation quality. Stage timings collected by the service are per-request observations, not an SLO.
