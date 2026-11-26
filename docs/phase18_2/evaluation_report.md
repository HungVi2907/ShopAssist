# Phase 18.2 evaluation report

2026-11-26, Asia/Saigon. **No candidate accepted for production.** E2 is the selected research candidate; source and selection were frozen before the regression run in `data/interim/phase18_2/candidate_freeze.json`. There is no fresh independently reviewed held-out dataset, and no production readiness claim.

## Experiment and scoring

The final development dataset is exactly the Phase 18.1 24-case pilot; the previously used 20-case held-out fixture is explicitly **regression data**, not independent validation. No regression feedback was used to change the frozen candidate. The model remains `qwen2.5:1.5b-instruct-local`, digest `d010eb818583111cfafeb3523cc17802f85dcb7f4fe5e8ecdd4927dca40e3174`, Ollama 0.40.18. NVIDIA GeForce RTX 3050 Laptop GPU, 4 GB VRAM; `ollama ps` observed 100% GPU and 4096 context. Requests use native `/api/chat`, temperature 0, seed 42, context 4096, prediction cap 512, stream false. Other parameters inherit the unchanged custom model. No external inference was performed.

E0 uses the frozen Phase 18.1 P4 prompt file and the production v1 schema, followed by the existing normalization. E1 processes **the same raw response** with the new deterministic parser/validation; no extra inference is made. E2 uses the new flat required schema and short extraction prompt, with the same model/options/dataset and same final public contract. Changing both prompt and internal schema is intentional: E2 compares architectures, not a schema-only ablation. Raw extraction quality cannot be inferred solely from final numeric accuracy because Python reads the original query.

Every JSONL row records raw query, raw response/envelope, parsed response, pre-validation transformed production output, semantic status/issues/corrections and final production output. It includes wall time, token counts and Ollama termination metadata. Manifests identify source, model, prompt, schema, dataset and catalog-brand hashes; source snapshots are under `frozen_sources`. E0/E1 records are paired. Summaries and prompt/schema snapshots are isolated by run directory; historical Phase 18.1 artifacts were preserved.

Scoring reuses Phase 18.1's case-folded six-hard-slot matches, exact preference-string sets and clarification flag. Shared-slot exact includes preferences and excludes free-form semantic/reason wording and v2-only fields. All attempted cases are in the denominator; no failures or refusals are discarded. Preference scores are micro precision/recall/F1 over exact strings, not semantic-equivalence annotation. Case-level inversion, hallucination and missing diagnostics follow Phase 18.1 definitions and may overlap. Hallucination covers brand, price and rating; a null category is separately a missing constraint. Clarification precision means agreement with existing labels, which do not encode every new conservative guard. Answerable coverage is non-clarifying valid outputs divided by labeled answerable requests, not correctness of those answered requests.

End-to-end wall time includes model request, parsing, transformation and validation, excludes artifact writing, and uses nearest-rank P95. E1 is the paired E0 time plus deterministic processing; E2 is a fresh single extraction. P50/P95 use all measured requests, including any load overhead. Ollama load/generation timing remains in the raw envelope; this was not a controlled cold-start benchmark. Repeatability is limited: newly observed E0 results differ somewhat from Phase 18.1 despite the same model/prompt/options. No mathematical determinism claim is made.

## Final development comparison (24 cases)

| Metric | E0: P4 | E1: P4 + Python | E2: flat extraction + Python |
|---|---:|---:|---:|
| JSON validity | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Internal schema compliance | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Final public schema compliance | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Category | 20/24 (83.3%) | 21/24 (87.5%) | 22/24 (91.7%) |
| Brand | 22/24 (91.7%) | 23/24 (95.8%) | 24/24 (100.0%) |
| Min price | 17/24 (70.8%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Max price | 17/24 (70.8%) | 23/24 (95.8%) | 23/24 (95.8%) |
| Rating | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Currency | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Inversion cases | 6/24 (25.0%) | 0/24 (0.0%) | 0/24 (0.0%) |
| Hallucinated constraint cases | 8/24 (33.3%) | 0/24 (0.0%) | 0/24 (0.0%) |
| Missing constraint cases | 9/24 (37.5%) | 4/24 (16.7%) | 2/24 (8.3%) |
| Shared-slot exact match | 8/24 (33.3%) | 11/24 (45.8%) | 15/24 (62.5%) |
| Clarification flag accuracy | 22/24 (91.7%) | 18/24 (75.0%) | 19/24 (79.2%) |
| Preference micro precision | 50.0% | 50.0% | 66.7% |
| Preference micro recall | 27.3% | 27.3% | 72.7% |
| Preference micro f1 | 35.3% | 35.3% | 69.6% |
| Clarification rate | 4/24 (16.7%) | 12/24 (50.0%) | 11/24 (45.8%) |
| Correct among clarified | 4/4 (100.0%) | 6/12 (50.0%) | 6/11 (54.5%) |
| Answerable-query coverage | 18/18 (100.0%) | 12/18 (66.7%) | 13/18 (72.2%) |
| P50 end-to-end ms | 813.6 | 816.1 | 284.1 |
| P95 end-to-end ms | 930.8 | 933.3 | 348.3 |
| Mean prompt tokens | 837.1 | 837.1 | 175.3 |
| Mean completion tokens | 86.4 | 86.4 | 31.7 |

E1 changed 13 numeric/currency slots; **0/13** changed a label-correct value into an incorrect value. This is a narrow, automatically checkable false-correction rate, not an independent review of every semantic correction. E2 has no pre-transformation numeric slots, so this same statistic is not defined; its preference removals and category/brand decisions need independent correction review. Reporting zero for E2 would be unsupported. The raw extraction often invents optional preferences or emits strings such as ?null?; those remain observable and are normalized/removed with diagnostics. Unsupported product/brand information is gated rather than promoted.

The one development maximum-price mismatch is LOCAL09: the inherited query literally contains replacement question marks in Vietnamese words. The parser rejects the unresolved numeric expression and requests clarification. The historical fixture was not edited to improve the score. Proper Unicode Vietnamese operators/category aliases are tested offline; broad Vietnamese model support is not established. Other E2 refusals include the unsupported/ambiguous and foreign-currency cases, two adversarial instruction cases, an ungrounded ?wireless charger? paraphrase for a charging-pad request, and negated shoe type that v1 cannot represent.

## Frozen-candidate regression comparison (20 previously seen cases)

| Metric | E0: P4 | E1: P4 + Python | E2: flat extraction + Python |
|---|---:|---:|---:|
| JSON validity | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Internal schema compliance | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Final public schema compliance | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Category | 14/20 (70.0%) | 15/20 (75.0%) | 19/20 (95.0%) |
| Brand | 18/20 (90.0%) | 19/20 (95.0%) | 19/20 (95.0%) |
| Min price | 11/20 (55.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Max price | 12/20 (60.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Rating | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Currency | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Inversion cases | 9/20 (45.0%) | 0/20 (0.0%) | 0/20 (0.0%) |
| Hallucinated constraint cases | 10/20 (50.0%) | 0/20 (0.0%) | 0/20 (0.0%) |
| Missing constraint cases | 9/20 (45.0%) | 2/20 (10.0%) | 2/20 (10.0%) |
| Shared-slot exact match | 3/20 (15.0%) | 7/20 (35.0%) | 9/20 (45.0%) |
| Clarification flag accuracy | 17/20 (85.0%) | 16/20 (80.0%) | 15/20 (75.0%) |
| Preference micro precision | 66.7% | 66.7% | 75.0% |
| Preference micro recall | 9.5% | 9.5% | 57.1% |
| Preference micro f1 | 16.7% | 16.7% | 64.9% |
| Clarification rate | 3/20 (15.0%) | 8/20 (40.0%) | 9/20 (45.0%) |
| Correct among clarified | 2/3 (66.7%) | 4/8 (50.0%) | 4/9 (44.4%) |
| Answerable-query coverage | 15/16 (93.8%) | 12/16 (75.0%) | 11/16 (68.8%) |
| P50 end-to-end ms | 817.2 | 820.6 | 295.3 |
| P95 end-to-end ms | 936.6 | 943.6 | 356.2 |
| Mean prompt tokens | 837.9 | 837.9 | 176.2 |
| Mean completion tokens | 92.0 | 92.0 | 32.5 |

E1 made 17 numeric/currency slot changes on regression: **0/17** false corrections by the same narrow definition. Both E1 and E2 removed all nine observed E0 inversions and all ten E0 hallucinated-constraint cases. E2 improves category, preferences and exact match materially over E1, but its 11/16 answerable coverage is below E1's 12/16. High numeric accuracy does not establish full intent correctness. E2 preference micro counts are TP=12, FP=4, FN=9; literal copied terms, missed intended uses, exact-match wording policy and remaining unsupported paraphrases all matter.

Observed E2 clarification cases include HELD004/006 exclusions, HELD009 foreign currency, HELD010 unresolved category, HELD012/013/019 unsupported or missing product intent, and HELD014/020 ungrounded brand strings. Five of its nine clarifications disagree with the old clarification labels. Some are deliberate fail-closed handling of v1 limitations, but this remains a practical coverage cost and cannot be hidden by quoting accuracy alone. Complete failures and diagnostics are in `regression_frozen/responses.jsonl`.

## Acceptance and selection

Neither candidate meets all existing quality gates or the proposed experimental targets. E2 development category is 22/24 (91.7%, below 95%), maximum price 23/24 (95.8%, below 98%) and preference F1 69.6% (below 80%). Regression preference F1 is 64.9%. Observed inversions and hallucinations are zero after Python processing on these sets, but the samples are small, previously seen, and include gates rather than guaranteed complete interpretation. Independent correction review and a fresh independently reviewed held-out set are absent. The existing no-silent-loss, foreign-currency, exclusion and route-validation requirements were not lowered.

E2 is retained for continued research because its flat task materially improves preference F1, category quality, shared-slot exact and latency relative to E1; this justifies its limited opt-in branch. E1 is the simpler numeric guard and remains the reference if later E2 improvements fail to justify complexity. **Neither is activated.** The production default and Gateway routes remain unchanged. No retrieval, embedding, reranking or recommendation redesign is warranted by these results.

## Tests, iterations and failed experiments

Final guarded regression: **250 passed in 13.96 seconds**, covering 53 new candidate tests plus applicable query-understanding and downstream selections. The reproducible runner `data/interim/phase18_2/run_offline_regression.py` forbids external DNS/socket connections and sets Hugging Face/Transformers offline modes. It permits loopback for Windows asyncio; it does not need a real local database or inference server. Evidence: `offline_regression_loopback.txt`. The earlier unguarded broad selection passed 245 tests before the last added cases; a final candidate-only run passed 53 tests. These are selected regression tests, not a claim that the entire repository integration suite was executed.

An initial strict socket guard blocked Windows asyncio's own socketpair loopback and caused **36 failures / 214 passes** before async test bodies could run. This test-harness failure and warnings are preserved in `offline_regression.txt`; the guard was corrected rather than weakening application assertions. The initial standalone evaluation script import also failed before inference (`ModuleNotFoundError` for the scorer import); direct-script import resolution was fixed. No provider fallback or external service was used to recover either failure.

All development iterations remain under `dev_01`, `dev_02`, `dev_03`, `dev_final`, and `dev_frozen`, each with its source hashes. Early E2 over-clarified because ungrounded optional preferences were treated as mandatory ambiguity and because catalog brand AT matched ?at?. Subsequent development removed unsupported optional preference additions with diagnostics, normalized missing-brand sentinels using existing code, excluded short incidental brand tokens, added bounded phrase-pattern caching, and hardened ambiguity checks. Later runs separate pre-validation output from final output and exclude artifact writes from paired latency. **Use dev_frozen for the final development comparison**; earlier runs are development evidence, not additional independent samples or pooled acceptance data. Regression was run only after source/candidate freeze.

## Reproduction and next work

From the repository root, with existing dependencies and the retained local model:

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_phase18_2.py --dataset data/interim/phase18_1/dev_pilot.json --out data/interim/phase18_2/new_dev_run
.\.venv\Scripts\python.exe scripts/evaluate_phase18_2.py --dataset tests/fixtures/heldout_evaluation_cases.json --out data/interim/phase18_2/new_regression_run
.\.venv\Scripts\python.exe data/interim/phase18_2/run_offline_regression.py
```

Use new output directories. Inspect preserved prompt/schema/source hashes before comparing runs; optional-field baseline compliance does not imply a complete raw response. The public schemas remain byte-for-byte unchanged. An independent reviewer must adjudicate new preference/category/clarification labels and semantic corrections before a genuinely fresh held-out evaluation. Further work should improve extraction preference recall and product/brand grounding, expand numeric/security tests without growing a generalized rule engine, review unnecessary clarification, and validate native deadline and catalog-backed retrieval integration. Phase 18 and T17 remain open.
