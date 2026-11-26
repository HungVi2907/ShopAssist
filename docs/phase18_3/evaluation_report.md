# Phase 18.3 evaluation report

2026-11-26, Asia/Saigon. **Targets remain unmet; no production acceptance or route activation.** The final research freeze is Q1S: original P0 extraction prompt plus improved grounding and conservative brand safety. Q2's targeted preference prompt failed to generalize. Phase 18 and T17 remain open.

## Protocol and evidence

Live requests use the unchanged `qwen2.5:1.5b-instruct-local` model, digest `d010eb818583111cfafeb3523cc17802f85dcb7f4fe5e8ecdd4927dca40e3174`, native `/api/chat`, temperature 0, seed 42, 4096 context, 512 prediction cap, stream false. Model/hardware details are in the manifests: local RTX 3050 Laptop GPU with 4 GB VRAM. No external inference, new model, fine-tuning or dependency was used. A request makes one LLM call; comparing candidate architectures requires separate experimental requests, not multiple passes within a request.

Q0 loads the exact Phase 18.2 frozen transformer and numeric parser. Q1 uses the new deterministic logic on **identical P0 raw extraction outputs**. Q2 uses Q1 logic with the selected preference prompt P1. P2 is an additional development-only prompt, not another architecture. All outputs use the same flat schema and unchanged public v1 output. There were three prompt candidates total and one bounded safety-repair iteration; no repeated search for a passing prompt after provisional results.

Development: 24 inherited pilot cases. Regression: 20 previously evaluated legacy held-out cases. New provisional set: 50 agent-labeled cases covering all canonical categories plus boundaries, ambiguity, currency, exclusions, adversarial and limited multilingual input. The latter was constructed after the initial P1 freeze and evaluated before any safety correction. Independent human review is **unavailable**: labels and correction decisions remain provisional and cannot support production acceptance. After its failures drove a safety repair, this set is also seen regression material for future work.

Each run retains raw text/envelope, parsed extraction, transformed output, semantic diagnostics, final output, token counts, termination status and latency. Prompt/schema/source/model/catalog/dataset identities are hashed. The initial live runs and initial/intermediate freezes remain preserved. Final safety revalidation applies identical stored raw outputs without more inference. Final table latency is **inherited live time plus measured revalidation overhead**, a conservative diagnostic estimate rather than a fresh end-to-end benchmark. Original live times remain in the unsuffixed runs; no cold-start or contention-controlled speed claim is made.

Scoring reuses Phase 18.1 shared-slot rules: exact case-folded category/brand/numeric/currency fields, literal preference sets and clarification flag. All attempts are in denominators; no clarification or malformed response is excluded. Shared-slot exact excludes semantic/reason wording and v2-only fields. Inversion means an extra opposite-direction bound for a one-sided expected bound. Hallucination covers an unexpected non-null brand, numeric price or rating. Missing counts absent expected category, brand or numeric constraints, including gated outputs. It is not a count of silent retrieval violations. Exact correctness among answered includes strict preference wording and is not human semantic adequacy. Clarification precision/unnecessary rates use existing labels, whose V2 exclusion policy differs from current V1-safe behavior.

## Development prompt experiment

| Prompt | Count | Category | Preference P / R / F1 | Exact | Answerable coverage | Live P95 ms |
|---|---:|---:|---:|---:|---:|---:|
| Q0 | 24 | 22/24 | 66.7% / 72.7% / 69.6% | 15/24 | 13/18 | 472.9 |
| Q1 | 24 | 23/24 | 69.2% / 81.8% / 75.0% | 16/24 | 14/18 | 483.5 |
| P1 | 24 | 23/24 | 75.0% / 81.8% / 78.3% | 17/24 | 14/18 | 495.0 |
| P2 | 24 | 22/24 | 60.0% / 81.8% / 69.2% | 16/24 | 13/18 | 348.4 |

P1 improved development preference F1 to 78.3%, while P2's extra examples produced more unwanted preferences (69.2% F1). The initial P1 candidate was frozen before regression/new-set evaluation. But P1 provisional F1 was 37.4%, below Q1/P0's 46.7%; extra instructions did not yield general language extraction reliability. Preference prompt tuning stopped and final selection reverted to simpler P0, retaining the measured grounding gains.

## Final development replay (24 cases)

| Metric | Q0 | Q1S | Q2 (P1) |
|---|---:|---:|---:|
| JSON validity | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Internal schema compliance | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Final schema compliance | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Category | 22/24 (91.7%) | 23/24 (95.8%) | 23/24 (95.8%) |
| Brand | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Min price | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Max price | 23/24 (95.8%) | 23/24 (95.8%) | 23/24 (95.8%) |
| Rating | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Currency | 24/24 (100.0%) | 24/24 (100.0%) | 24/24 (100.0%) |
| Price inversions | 0/24 (0.0%) | 0/24 (0.0%) | 0/24 (0.0%) |
| Hallucinated constraint cases | 0/24 (0.0%) | 0/24 (0.0%) | 0/24 (0.0%) |
| Missing constraint cases | 2/24 (8.3%) | 1/24 (4.2%) | 1/24 (4.2%) |
| Shared-slot exact match | 15/24 (62.5%) | 16/24 (66.7%) | 17/24 (70.8%) |
| Preference micro precision | 66.7% | 69.2% | 75.0% |
| Preference micro recall | 72.7% | 81.8% | 81.8% |
| Preference micro f1 | 69.6% | 75.0% | 78.3% |
| Preference TP / FP / FN | 8 / 4 / 3 | 9 / 4 / 2 | 9 / 3 / 2 |
| Clarification precision | 6/11 (54.5%) | 6/10 (60.0%) | 6/10 (60.0%) |
| Unnecessary clarification rate (legacy labels) | 5/18 (27.8%) | 4/18 (22.2%) | 4/18 (22.2%) |
| Answerable coverage | 13/18 (72.2%) | 14/18 (77.8%) | 14/18 (77.8%) |
| Exact correctness among answered | 11/13 (84.6%) | 12/14 (85.7%) | 12/14 (85.7%) |
| P50 ms | 282.1 | 288.6 | 315.5 |
| P95 ms | 472.9 | 492.0 | 505.3 |
| Mean prompt tokens | 175.3 | 175.3 | 222.3 |
| Mean completion tokens | 32.4 | 32.4 | 35.1 |

## Final legacy regression replay (20 cases)

| Metric | Q0 | Q1S | Q2 (P1) |
|---|---:|---:|---:|
| JSON validity | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Internal schema compliance | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Final schema compliance | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Category | 19/20 (95.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Brand | 18/20 (90.0%) | 19/20 (95.0%) | 19/20 (95.0%) |
| Min price | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Max price | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Rating | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Currency | 20/20 (100.0%) | 20/20 (100.0%) | 20/20 (100.0%) |
| Price inversions | 0/20 (0.0%) | 0/20 (0.0%) | 0/20 (0.0%) |
| Hallucinated constraint cases | 1/20 (5.0%) | 0/20 (0.0%) | 0/20 (0.0%) |
| Missing constraint cases | 2/20 (10.0%) | 1/20 (5.0%) | 1/20 (5.0%) |
| Shared-slot exact match | 9/20 (45.0%) | 9/20 (45.0%) | 9/20 (45.0%) |
| Preference micro precision | 73.3% | 76.5% | 70.0% |
| Preference micro recall | 52.4% | 61.9% | 66.7% |
| Preference micro f1 | 61.1% | 68.4% | 68.3% |
| Preference TP / FP / FN | 11 / 4 / 10 | 13 / 4 / 8 | 14 / 6 / 7 |
| Clarification precision | 4/9 (44.4%) | 4/9 (44.4%) | 4/8 (50.0%) |
| Unnecessary clarification rate (legacy labels) | 5/16 (31.2%) | 5/16 (31.2%) | 4/16 (25.0%) |
| Answerable coverage | 11/16 (68.8%) | 11/16 (68.8%) | 12/16 (75.0%) |
| Exact correctness among answered | 6/11 (54.5%) | 6/11 (54.5%) | 6/12 (50.0%) |
| P50 ms | 289.7 | 295.3 | 344.3 |
| P95 ms | 382.4 | 396.7 | 411.9 |
| Mean prompt tokens | 176.2 | 176.2 | 223.2 |
| Mean completion tokens | 32.4 | 32.4 | 35.1 |

The old stored E2 baseline had 0/20 hallucinated constraints. The new live P0 extraction produced leather as a wallet manufacturer, so its Q0 replay now has 1/20. Temperature zero and a fixed seed are not a guarantee of identical language extraction. The final brand guard removes this filter and asks for clarification. Q1S coverage remains 11/16, matching the historical reported coverage rather than reaching 90%. It newly recovers some harmless grounding/compatibility failures while correctly gating no telephoto and the attribute-derived brand. Increased refusal in those cases is disclosed instead of counted as a quality gain.

## Final provisional replay (50 cases, no independent human review)

| Metric | Q0 | Q1S | Q2 (P1) |
|---|---:|---:|---:|
| JSON validity | 50/50 (100.0%) | 50/50 (100.0%) | 50/50 (100.0%) |
| Internal schema compliance | 50/50 (100.0%) | 50/50 (100.0%) | 50/50 (100.0%) |
| Final schema compliance | 50/50 (100.0%) | 50/50 (100.0%) | 50/50 (100.0%) |
| Category | 43/50 (86.0%) | 43/50 (86.0%) | 42/50 (84.0%) |
| Brand | 48/50 (96.0%) | 50/50 (100.0%) | 50/50 (100.0%) |
| Min price | 50/50 (100.0%) | 50/50 (100.0%) | 50/50 (100.0%) |
| Max price | 48/50 (96.0%) | 50/50 (100.0%) | 50/50 (100.0%) |
| Rating | 50/50 (100.0%) | 50/50 (100.0%) | 50/50 (100.0%) |
| Currency | 50/50 (100.0%) | 50/50 (100.0%) | 50/50 (100.0%) |
| Price inversions | 0/50 (0.0%) | 0/50 (0.0%) | 0/50 (0.0%) |
| Hallucinated constraint cases | 2/50 (4.0%) | 0/50 (0.0%) | 0/50 (0.0%) |
| Missing constraint cases | 9/50 (18.0%) | 7/50 (14.0%) | 8/50 (16.0%) |
| Shared-slot exact match | 14/50 (28.0%) | 16/50 (32.0%) | 10/50 (20.0%) |
| Preference micro precision | 63.6% | 63.6% | 50.0% |
| Preference micro recall | 36.8% | 36.8% | 29.8% |
| Preference micro f1 | 46.7% | 46.7% | 37.4% |
| Preference TP / FP / FN | 21 / 12 / 36 | 21 / 12 / 36 | 17 / 17 / 40 |
| Clarification precision | 10/20 (50.0%) | 11/20 (55.0%) | 11/21 (52.4%) |
| Unnecessary clarification rate (legacy labels) | 10/38 (26.3%) | 9/38 (23.7%) | 10/38 (26.3%) |
| Answerable coverage | 28/38 (73.7%) | 29/38 (76.3%) | 28/38 (73.7%) |
| Exact correctness among answered | 8/30 (26.7%) | 8/30 (26.7%) | 2/29 (6.9%) |
| P50 ms | 272.3 | 277.0 | 336.4 |
| P95 ms | 380.2 | 394.6 | 420.7 |
| Mean prompt tokens | 176.0 | 176.0 | 223.0 |
| Mean completion tokens | 31.3 | 31.3 | 35.6 |

Before the safety correction, **both Q1 and P1 had two hallucinated-brand cases on the provisional set**, including a served handmade-vase query. Those failed initial results are retained in `provisional_01`. A competing-maker query retained Nike despite clarification; that scalar was also removed. Two unit tests reproduced the defects before correction. Revalidation initially exposed the same attribute/maker problem in the new P0 leather-wallet output; the guard was extended to unknown lowercase manufacturer claims lacking explicit maker evidence. Final Q1S has 0/24, 0/20 and 0/50 inversions and hallucinated-constraint cases on these stored outputs. This is observed post-repair evidence only, not zero-risk proof or independent validation.

False correction audit: Q1S changed one hard slot on development, two on regression and four on provisional data relative to paired Q0 output; **0/1, 0/2 and 0/4** changed a label-correct hard slot to an incorrect value. This narrow automated rate excludes clarification and free-form/preference semantics; those require independent review, which is absent. No broader false-correction guarantee is claimed. Q2 uses a different model extraction and has no paired deterministic-only correction rate.

The remaining development maximum-price miss is the corrupted Vietnamese LOCAL09 string. The final parser clarifies rather than guessing the missing operator; the historical input was not rewritten to improve metrics. On proper Unicode inputs, limited Vietnamese aliases/operators work in deterministic tests, but new-set category/extraction failures show that broad language support is unproven. The final candidate has 7/50 missing hard-slot cases, chiefly unresolved categories; refusing them avoids silently executing incomplete filters but does not meet coverage or classification goals.

## Downstream investigation

`downstream_final.json` records 27 configurations: Q0, final Q1S and the unreviewed fixture reference for nine representative cases. The experiment used the actual 8,405-row local catalog, existing TF-IDF index and already installed CPU `ms-marco-MiniLM-L2-v2` CrossEncoder. No model was downloaded and no database call was made. It is a scoped lexical-plus-pair-scoring ablation, **not** a full dense/pgvector/RRF pipeline evaluation. Prices were explicitly inclusive for this V1 ablation. Reference labels and product relevance have not received independent human review.

All nine cases preserved the same semantic input between Q0 and Q1S. With unchanged filters and open gates, lexical result IDs were unchanged; HELD007's altered preference wording changed reranker order on the same lexical pool. Dell laptop and Casio watch examples had no catalog candidates under their filters. Cello remained gated. Three recovered queries began returning candidates, but spot inspection identified important relevance limitations: the charging-pad query returned Lightning cables; the Bluetooth-speaker query returned headset/headphone products; the Honda body-cover query returned a steering cover and unrelated bike covers. Those are broad-category matches, not evidence of the requested product type or compatibility being satisfied. Zero returned candidates violated the tested numeric/category/brand filters, but those filters do not prove every user requirement.

Preference-list omissions often preserve their terms in semantic_query, limiting their effect on base lexical/dense input. They still change the separate preference representation and reranking query; absence of preferences also skips the preference vector. No quality gain is inferred from a changed rank alone. Product-type scarcity/coarse filtering and catalog relevance appear material in these inspected cases; more prompt-F1 tuning alone is not justified. No retrieval or reranking algorithm was modified, no human relevance precision/NDCG is reported, and a live dense/catalog-backed end-to-end acceptance run remains open.

The existing downstream raw-query exclusion guard rejects some not exceeding expressions even though new Query Understanding correctly parses them. Keep that mismatch visible; this phase did not relax downstream safety or redesign retrieval. Native deadline integration, semantic-query conversational fragments and complete injection resistance are also unresolved.

## Tests and failed experiments

Final guarded selection: **279 passed in 14.58 seconds**, including 82 current candidate tests plus applicable query understanding, preferences, retrieval-text, hybrid-filtering, reranking, recommendation, experimental schema/rules and Gateway lifecycle tests. The reproducible runner denies external DNS/sockets, enables offline model modes and permits Windows asyncio loopback. An earlier selection passed 277 tests before the two reproduced brand failures were added. The two failing tests and subsequent pass are preserved; no failing assertion was weakened to pass. This is selected regression, not the entire live/integration suite.

P2 failed to improve development; P1 failed provisional generalization; initial frozen P1 had brand safety defects; Q0 itself changed outputs across repeated local runs; initial and intermediate results were not overwritten. The first safety replay still exposed leather as a manufacturer under P0, which led to the bounded final maker-evidence guard. No claims are based only on corrected final metrics. There were no external model/provider calls, model downloads, production route changes, T17 ledger changes or commits/pushes.

## Decision and next boundary

The final freeze is `frozen_candidate/final/manifest.json` (Q1S), with original P0 prompt and unchanged internal schema/model/options. Full result and dataset hashes are in `experiment_manifests/index.json`; old freezes show the initial P1 selection and subsequent post-provisional revisions. Source equality is checked against the final freeze.

Experimental targets are **not all met**: regression preference F1 68.4% and coverage 68.8%; provisional preference F1 46.7%, coverage 76.3%, category 86%. Zero observed final constraint failures and sub-second inherited latency do not override those deficits. Brand/category grounding, missing intended uses, broad negation, compound requirements, unreviewed labels and product relevance remain blockers. No production candidate has passed authoritative acceptance.

Q1S can be injected for supervised, offline/end-to-end experimental Phase 18.4 compatibility work with explicit clarification behavior and known limitations. It is not ready to activate for production customers. Stop optimization here: obtain independent human review of new labels/corrections, create a genuinely new holdout after that review, investigate retrieval product-type quality with existing components, and perform Phase 12 compatibility experiments under the separate preparation handover. No production approval or change to Phase 18 status follows.

## Reproduction

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_phase18_3.py --dataset data/interim/phase18_1/dev_pilot.json --out data/interim/phase18_3/evaluation_results/new_dev
.\.venv\Scripts\python.exe scripts/evaluate_phase18_3.py --dataset tests/fixtures/heldout_evaluation_cases.json --prompts P0 P1 --out data/interim/phase18_3/evaluation_results/new_regression
.\.venv\Scripts\python.exe data/interim/phase18_3/run_offline_regression.py
```

The final replay script defaults to a new safety output directory; use a new `--suffix` when rerunning it. Never reuse an output directory. Live reruns use the current final safety transformer, while old stored initial outputs remain the authoritative record of the initial candidate. The provisional builder also refuses to overwrite its dataset.
