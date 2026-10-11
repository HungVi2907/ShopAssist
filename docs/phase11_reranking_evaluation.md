# Phase 11 Offline Evaluation

## Objective and controls

This experiment checks that the Phase 11 component preserves Phase 10 candidate identity and compares two implementable methods: the Phase 10 RRF ordering and an untrained symmetric dense/lexical rank aggregation. All methods use the same frozen ten-candidate set per query and the same labels. Top-K is five. Candidate text and metadata come from the real canonical catalog artifact.

The four queries cover apparel attributes, product/use, and vehicle-specific automotive accessories. Candidate pools were formed with exact local cosine scoring over the already saved Phase 7 embeddings and saved Phase 6 TF-IDF ranking, then fused with the Phase 10 RRF constant (`k=60`). This is not a live Phase 10 database run.

## Annotation rubric

Relevance is graded 0–3 from product identity and visible query attributes: 3 means all visible positive attributes match; 2 means a relevant product with a missing/mismatched detail; 1 means weak family match with an important mismatch; 0 means irrelevant or contradictory. Judgments are recorded in `data/interim/phase11/phase11_reranking_cases.json`, were made from canonical product text before comparing method scores, and have one engineer reviewer. They are not independent qrels.

For MRR and Precision@5, grade ≥2 is relevant. nDCG uses gain `2^grade - 1`, discount `log2(rank+1)`, normalized by the ideal ranking of the judged fixed pool. MRR uses the first grade ≥2. Precision@5 divides relevant results by five. No aggregate confidence intervals are claimed because four examples cannot support them.

## Results

| Method | nDCG@5 | MRR | Precision@5 | Median warm scoring latency |
| --- | ---: | ---: | ---: | ---: |
| RRF | 0.960520 | 0.875000 | 0.900000 | 0.096525 ms |
| Multi-Signal | 0.989459 | 1.000000 | 0.850000 | 0.073650 ms |
| Cross-Encoder | 0.928403 | 0.833333 | 0.850000 | 75.986725 ms |
| Combined | Not run | Not run | Not run | Disabled |

RRF places a relevant candidate first on three of four queries; Multi-Signal does so on all four in this set. Real Cross-Encoder CPU inference achieved nDCG@5 of 0.9284 and MRR of 0.8333, which underperforms default RRF pass-through on these four queries while adding ~76 ms of latency. Differences are not statistically tested and reflect the small manually judged sample. RRF remains the default to avoid premature selection.

## Per-query interpretation

The difficult boot query contains an explicitly artificial/non-leather item at rank one, while products with brown leather, women, and zipper evidence are split across candidates. Rank aggregation improved the first judged relevant result on this case. Other queries have many same-family relevant candidates, so ranking changes have little practical room to improve graded relevance. The small scope does not cover price-bound edge cases, exclusions, missing-text failures, adversarial queries, or category breadth sufficiently.

## Performance

Scoring timing is a warm `RerankingService.rerank` call over 10 candidates with Top-5 output, measured 25 times per query and summarized by per-query median then averaged across four queries. RRF: 0.096525 ms; Multi-Signal: 0.073650 ms; Cross-Encoder CPU inference: 75.986725 ms. Environment: Python 3.10.11, PyTorch 2.6.0+cu124, CUDA available with cached BGE encoder on `cuda:0`; CPU model string `Intel64 Family 6 Model 154 Stepping 3, GenuineIntel`. Top-10 / 20 / 25 candidate pool warm CPU latencies measured by `benchmark_phase11_cross_encoder.py` are 103.03 ms, 229.69 ms, and 269.46 ms respectively.

## Decision and limitations

Keep RRF as the default. Do not use the measured four-query Multi-Signal result or the lower Cross-Encoder score as definitive catalog-wide claims. Cross-Encoder CPU execution is verified and functional. Evaluation over live Phase 10 results, independent labels, a larger frozen set (40-query plan), and a development/held-out split remain required before method promotion or weight tuning.

## Reproducible expansion plan

Target 40 real user queries, prepared from product-category coverage and query requirements before inspecting ranking scores:

| Stratum | Target |
| --- | ---: |
| Simple product identity | 5 |
| Multiple hard constraints | 7 |
| Soft preferences | 6 |
| Product use cases | 5 |
| Mixed hard and soft requirements | 7 |
| Semantically similar but incorrect candidates | 5 |
| Category-specific attributes and difficult ranking | 5 |
| **Total** | **40** |

For each query, freeze the typed Phase 10 candidate set (target 20 candidates), candidate IDs, branch ranks/scores, canonical text snapshot checksum, and applicable constraints before annotation. Use the existing 0–3 rubric and the same fixed pool for each method. Two reviewers should grade independently without seeing model scores; disagreements should be adjudicated and recorded. Split by query into development and held-out sets only after the qrels are complete. Report query-level nDCG@5, MRR, Precision@5, constraint violations, and latency; do not tune on held-out cases.

`data/interim/phase11/phase11_annotation_template.csv` is a blank schema only. It contains no invented queries, candidates, or labels. Until actual Phase 10 output and human annotations are added, this expansion is a plan and not measured evidence.

## Real-model execution

The pinned repository revision, configuration, and file SHA-256 values are recorded by `scripts/download_phase11_model.py` in `phase11_model_manifest.json`. Model weights live under the ignored `.models/phase11/` directory. New results are written to files ending in `_current.json`, preserving the historical JSON evidence. With project dependencies and a local checkpoint installed, run:

```powershell
$env:PYTHONPATH = "src"
$env:HF_HUB_OFFLINE = "1"
python scripts/evaluate_phase11.py
python scripts/benchmark_phase11_cross_encoder.py
```

The evaluator adds Cross-Encoder metrics only after real local inference succeeds. Its four existing judgments are preliminary and do not establish effectiveness. The benchmark reports model load and CPU inference separately, uses the actual tokenizer over canonical text, and emits examples for human truncation review. Its Top-20/25 latency pools extend the 10 frozen examples with catalog rows and are performance-only, not Phase 10 integration evidence.
