# Phase 11 — Product Reranking

**Contract version:** `1.0.0`  
**Status:** **VALIDATED FOR PROTOTYPE — Environment restored, real Cross-Encoder downloaded and executed on CPU, live Phase 10 database integration verified, and catalog snapshot consistency validated. Production promotion pending 40-query independent evaluation.**

## Scope and architecture

Phase 11 consumes the frozen Phase 10 candidate set and returns an ordered Top-K subset. It does not query the catalog or expand the candidate pool. The service is implemented in `src/shopassist/reranking/core.py` and exported from `shopassist.reranking`.

The service checks Phase 8/9 status and compatibility, guards unsupported exclusions and foreign currency, checks available hard-constraint evidence, resolves canonical product text by product ID, scores the candidate pairs or rank provenance, and emits typed output with stable ordering and timings. The exact contract is in [phase11_reranking_contract.md](phase11_reranking_contract.md).

## Research and method decision

The Phase 10 `HybridCandidate` contains an RRF score, dense/lexical source rank and score where available, product identity, price, rating, and metadata. The Phase 10 object does not include canonical retrieval text. The Phase 5.2/Phase 7 artifact does contain `retrieval_text` for all 8,405 product IDs, so the Phase 11 adapter resolves text from that artifact by exact ID.

The configured Cross-Encoder is `cross-encoder/ms-marco-MiniLM-L2-v2`, pinned to repository revision `1b5cd67b15209f24824c50370e0397743aa9b787`. The official repository identifies the model as Apache-2.0 and provides `model.safetensors`, configuration, and tokenizer artifacts; the config specifies a two-layer, 384-hidden-size BERT with a 512-token position limit ([model repository](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L2-v2), [pinned revision](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L2-v2/commit/1b5cd67b15209f24824c50370e0397743aa9b787)). The checkpoint is downloaded locally to `.models/phase11/ms-marco-MiniLM-L2-v2` with verified SHA-256 hashes recorded in `data/interim/phase11/phase11_model_manifest.json`.

The selected default is RRF pass-through because it preserves a previously defined Phase 10 order with no new unvalidated weighting. Multi-Signal is implemented as an experiment: the arithmetic mean of normalized dense and lexical rank utilities, with absent branch evidence receiving zero. There is no trainable weight and the two branch weights are symmetric. Combined Cross-Encoder mode requires explicit weights and no default is supplied without a development-set selection. Ratings and constraint match are omitted from scoring: ratings are mostly missing (89.36%), and hard-constraint satisfaction is identical among candidates admitted by Phase 10.

## Quality evaluation

`scripts/evaluate_phase11.py` evaluates the four engineer-curated queries over fixed top-ten pools generated from local exact dense similarity on stored product embeddings and Phase 6 TF-IDF results. Real Cross-Encoder inference was executed on CPU for all pairs. Judgments are based on canonical product text, not model scores, and are single-reviewer labels.

| Method | nDCG@5 | MRR (grade ≥2) | Precision@5 | Warm Phase 11 median latency |
| --- | ---: | ---: | ---: | ---: |
| Phase 10 RRF pass-through | 0.9605 | 0.8750 | 0.9000 | 0.0965 ms |
| Multi-Signal | 0.9895 | 1.0000 | 0.8500 | 0.0736 ms |
| Cross-Encoder | 0.9284 | 0.8333 | 0.8500 | 75.9867 ms |
| Combined | Not run | Not run | Not run | Disabled |

The measured Cross-Encoder results on these four queries show lower nDCG@5 (0.9284 vs 0.9605) and lower MRR (0.8333 vs 0.8750) compared to RRF pass-through, while requiring ~76 ms of CPU inference. Multi-Signal has a slightly higher mean nDCG but lower precision (0.85 vs 0.90). This confirms that RRF must remain the default ranker, and no promotion or Combined weights should be adopted until a larger, multi-annotator evaluation is executed.

## Constraints and failure handling

Phase 10 non-success statuses are propagated without ranking. Phase 11 validates visible category, brand, minimum-rating, and price violations; it fails closed if a candidate contradicts a verified constraint. Equality at price bounds follows Phase 10's successful verified boundary decision, because Phase 8 v1 itself lacks strict/inclusive flags. Missing rating is accepted unless a minimum rating constraint exists. Foreign currencies and exclusions are unsupported, not treated as positive signals.

## Performance and runtime benchmarking

Benchmarking via `scripts/benchmark_phase11_cross_encoder.py` on Intel Core i7 CPU with 30 iterations per query:

- **Model loading**: 221.79 ms cold initialization; Process RSS delta +15.48 MB.
- **Top-10 candidate pool**: Median latency 103.03 ms; P95 120.39 ms.
- **Top-20 candidate pool**: Median latency 229.69 ms; P95 303.00 ms.
- **Top-25 candidate pool**: Median latency 269.46 ms; P95 310.64 ms.
- **Token truncation**: Evaluated across 33,620 query-catalog pairs. P50 token count: 184, P95: 426, max: 870. Only 708 pairs (2.11%) exceed the 512-token limit.

Deterministic rankers (RRF and Multi-Signal) execute in <0.1 ms on warm CPU Python.

Commands executed in the restored Python 3.10 environment:

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_reranking.py -v
python -m pytest tests/test_reranking_real_model.py -v
$env:SHOPASSIST_PHASE11_LIVE_DB = "1"
python -m pytest tests/test_phase10_to_phase11_integration.py -v
$env:HF_HUB_OFFLINE = "1"
python scripts/evaluate_phase11.py
python scripts/benchmark_phase11_cross_encoder.py
```

## Implementation audit and validation

- **Verified working:** Typed Phase 8/9/10 to Phase 11 handoff, RRF pass-through, Multi-Signal rank aggregation, real Cross-Encoder CPU inference, candidate subset integrity, hard-constraint fail-closed guards, Phase 12 evidence fields, and canonical product text resolution.
- **Real model validation:** Pinned checkpoint `cross-encoder/ms-marco-MiniLM-L2-v2` (`1b5cd67b15209f24824c50370e0397743aa9b787`) verified locally, offline loading verified, CPU inference and batching verified, token truncation distribution measured, and cold-start/warm inference latency profiled.
- **Live Phase 10 DB integration:** Executed against live Supabase PostgreSQL (8,405 rows) with pgvector and TF-IDF. All assertions passed for candidate subset preservation, unique IDs, original rank provenance, and Top-K capping.
- **Catalog snapshot consistency:** Parquet SHA-256 (`bd9bac023368289629c903ad04fc98bae85c347777f646dca63ad4bdfb029cdc`) validated against manifest. Live Supabase database verified to have exact 8,405 matching product IDs (0 symmetric difference).

## Phase 12 readiness

**Phase 12 readiness: VALIDATED FOR PROTOTYPE.**  
Phase 11 is contract-compatible and integration-verified with live Phase 10 retrieval. Phase 12 can safely consume Top-K reranked products with preserved retrieval provenance, canonical text, structured attributes, and diagnostic reasons.

**Production gating items (Phase 13–14):**
1. 40-query multi-annotator evaluation and adjudication (P11-01).
2. Development-set tuning for Combined ranking weights (P11-04).
3. Optional ONNX runtime / INT8 quantization if Cross-Encoder inference latency SLO (<50 ms) is required in production.
