# Phase 9 Preference Representation Contract

**Contract version:** `1.0.0`  
**Input version:** Phase 8 production Schema v1  
**Encoder:** `BAAI/bge-small-en-v1.5`, 384 dimensions, Phase 7 query instruction and L2 normalization.

## Input

```python
from shopassist.llm.schemas import QueryUnderstandingResult
from shopassist.preferences.service import PreferenceRepresentationService

result = PreferenceRepresentationService().represent(query_result)
```

The accepted input is a `QueryUnderstandingResult`. Required nested fields are `output.semantic_query`, `output.soft_preferences`, `is_valid`, and `output.needs_clarification`. `clarification_reason` and hard-constraint currency are optional safety context. Numeric or brand constraints are not transformed.

The existing schema bounds the raw query to 500 characters and soft preferences to ten items. Phase 9 additionally bounds each normalized preference to 200 characters and composed query to 1000 characters. Input strings use NFC normalization, whitespace collapse, Unicode case-folding for preferences, stable first-occurrence deduplication, and empty-item removal. No synonym expansion, translation, or negation removal is performed.

## Output

`PreferenceRepresentationResult` is JSON-serializable and contains:

| Field | Meaning |
| --- | --- |
| `contract_version` | Phase 9 result schema version (`1.0.0`) |
| `semantic_query` | Normalized Phase 8 product context |
| `normalized_preferences` | Stable normalized positive phrases |
| `preference_query` | Neutral deterministic composition; absent when no preferences exist |
| `preference_embedding` | Optional list of 384 finite unit-normalized floats |
| `embedding_model`, `embedding_dimension` | Encoder identity, present with a successful vector |
| `has_preferences` | Whether normalized preference phrases were present |
| `status` | One of the statuses below |
| `warnings`, `diagnostic_reason` | Safe integration guidance, no raw provider exception text |

Statuses are `SUCCESS`, `NO_PREFERENCES`, `CLARIFICATION_REQUIRED`, `INVALID_INPUT`, `UNSUPPORTED_INTENT`, and `EMBEDDING_FAILURE`. Only `SUCCESS` has a vector. A valid request with no positive preferences returns `NO_PREFERENCES`, preserves its base semantic query, and generates no empty-string or base-query preference vector. Phase 7 may encode the base query separately.

## Composition and vector semantics

The current deterministic strategy is:

```text
normalized preference 1; normalized preference 2 — semantic query context
```

For example, `comfortable; breathable; for daily jogging — running shoes`. The separator is structural; it does not claim a new attribute. The shared Phase 7 encoder prepends `Represent this sentence for searching relevant passages: `, calls the cached `EmbeddingModel.encode_queries`, and returns a 384D float vector normalized to L2 norm 1 within `1e-4`. The vector is compatible with cosine similarity and can be serialized for pgvector after the consumer validates it.

Do not infer hard filters from this text. An embedding is a soft relevance signal, not a guarantee that each phrase is satisfied.

## Safety, errors and unsupported requests

- `is_valid=False` → `INVALID_INPUT`; do not encode.
- `needs_clarification=True` → `CLARIFICATION_REQUIRED`; do not encode.
- Currency other than INR → `UNSUPPORTED_INTENT`; ask for supported-currency clarification.
- Recognized direct negative/exclusion wording (`without X`, `avoid X`, `except X`, `anything except X`, most `not X`, `no less than ...`) → `UNSUPPORTED_INTENT`; do not vectorize as positive evidence.
- Conservative safe phrases `not too ...`, `not only ...`, `not necessarily ...` are retained verbatim. The guard is not a general negation-scope parser; novel or ambiguous expressions must be adjudicated upstream.
- Invalid input → `INVALID_INPUT`; wrong model/dimension/vector, model load or inference failure → `EMBEDDING_FAILURE`.

Hard-constraint enforcement, unsupported product categories, out-of-catalog compatibility, strict price operators, and complete foreign-currency interpretation remain outside Phase 9. A consumer that cannot establish these semantics must stop and clarify rather than silently discard them.

## Versioning and Phase 10 example

Version `1.0.0` accepts production v1. A future Schema v2 adapter must be separately versioned and must keep typed exclusions, product type, price operators and provenance out of positive preference text. No automatic v1/v2 migration is implied.

```python
representation = service.represent(query_result)
if representation.status == RepresentationStatus.SUCCESS:
    assert representation.embedding_model == "BAAI/bge-small-en-v1.5"
    assert representation.embedding_dimension == 384
    preference_vector = representation.preference_embedding
elif representation.status == RepresentationStatus.NO_PREFERENCES:
    preference_vector = None  # encode semantic_query with Phase 7 if needed
else:
    # Route to clarification/unsupported/error handling; do not retrieve silently.
    stop_request(representation.status, representation.diagnostic_reason)
```
