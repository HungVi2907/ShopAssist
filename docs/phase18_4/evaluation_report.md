# Phase 18.4 local recommendation evaluation

2026-11-26, Asia/Saigon. **R3 is selected for guarded experimental native Gateway compatibility, not production deployment.** The original free-text contract is unreliable on this model. Evidence-selection outputs are assembled as source quotations; they are not independently reviewed natural-language suitability explanations. Phase 18 and T17 remain open.

## Fixtures and protocol

Twenty development fixtures freeze actual local catalog products: one, three and five candidates; sparse evidence ablations; rich specs; similar products; missing ratings; English/Vietnamese; user preferences and hard constraints; injected user/catalog instructions; the three known wrong-product-type examples; mandatory waterproof evidence missing; upstream clarification and invalid input. Sparse cases remove evidence explicitly, and catalog-injection cases append attack text explicitly. No factual product attributes were invented. The catalog hash and complete original fields are preserved in fixtures. The existing evidence builder bounds specs/descriptions; native projections and excluded descriptions are recorded separately, not silently discarded from the evidence record.

All live calls use `qwen2.5:1.5b-instruct-local`, digest `d010eb818583111cfafeb3523cc17802f85dcb7f4fe5e8ecdd4927dca40e3174`, native `/api/chat`, stream false, temperature 0, seed 42 and 4096 context on the same local GPU. No external LLM or semantic self-judge was called. Initial R0/R1/R2/R3 comparisons used 1536 output tokens. The final R3 selection cap of 256 was separately measured after seeing outputs of at most 73 tokens.

R0/R1 benchmark the generation stage with the actual original schema, context builder and validator, deliberately dispatching all 20 frozen cases to expose model behavior even on upstream-negative inputs. They are **not** end-to-end service propagation tests. The original service would already stop clarification; its missing `is_valid` check is now corrected. Service propagation and one-call behavior are tested independently. Raw parse errors originally had no assembled result in the runner; separate `_assembly_replay` directories apply the **frozen original** fallback offline and complete total usage from the native envelope. Those replays make public schema/metadata handling visible without turning fallback into LLM success.

Generation-stage wall times include HTTP, parsing and validation; the R0/R1 timer begins after existing context building. Local candidate timings additionally include native preparation/client lifecycle. These are not full API/bot pipeline latency or perfectly identical-overhead microbenchmarks. Native inference/load/eval durations remain in every envelope. Only executed-call latencies and tokens are used below; gate-only cases cannot artificially lower the generation latency.

## Bounded comparison

| Candidate / run | Cases | Native responses | JSON / internal schema valid | Accepted model selection | Full fallback | Pre-inference terminal cases | Executed P50 / P95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| R0 original | 20 | 20 | 12/20 | not established; 12 schema-valid outputs | 8/20 | 0/20 | 8025.9 / 13536.1 |
| R1 compact / original schema | 20 | 20 | 12/20 | not established; 12 schema-valid outputs | 8/20 | 0/20 | 8914.9 / 15043.8 |
| R2 free reason / source guard | 20 | 11 | 11/11 | 0/11 | 11/20 | 9/20 | 1582.9 / 2352.1 |
| R3 initial list form (failed) | 20 | 10 | 10/10 | 0/10 | 11/20 | 9/20 | 1510.2 / 1731.9 |
| R3 required keys, 1536 cap | 20 | 11 | 11/11 | 11/11 | 0/20 | 9/20 | 733.9 / 968.5 |
| R3 final, 256 cap | 20 | 13 | 13/13 | 13/13 | 0/20 | 7/20 | 689.6 / 946.3 |
| D0 safe deterministic | 20 | 0 | 0/0 | N/A | 13/20 | 7/20 | N/A (no model) |

R0 and R1 each parsed/validated 12/20 (60%) and truncated 8/20 (40%). After frozen fallback replay, public schema compliance is 20/20, **not** 20 successful LLM generations. One R0 and two R1 schema-valid cases also required omitted-product fallback inside a `SUCCESS` result. Raw product order/identity was exact on 9/20 R0 and 7/20 R1 cases. The legacy validator restores public order/metadata, so raw fidelity and assembled fidelity are deliberately separate.

R0 raw risk screening flagged at least 3/20 cases and R1 at least 2/20 with critical wording absent from supplied evidence. These are provisional lexical lower bounds; other summaries, overviews and paraphrases remain unreviewed. They do not establish a supported-claim percentage. A controlled sparse-evidence replay conclusively retained authenticity/waterproof/battery/compatibility claims and an internally contradictory waterproof/not-waterproof pair. A valid name citation did not support those claims, and removing an invalid reference did not remove its text.

Corrected raw citation ownership counts: R0 65/69 references valid (94.2%); R1 85/92 valid (92.4%). Each had one strength without citations. Exact source-text matches were only 7/54 and 7/58 claim objects respectively; nonmatching paraphrases are **unverified**, not automatically false. Initial audit diagnostics overflagged empty limitation citations, which are legal for missing-information notes; `citation_audit.json` recomputes actual reference ownership, and the runner diagnostic is corrected. Original raw audit records remain preserved. Citation validity is not semantic entailment.

R2 initially repeated products and added unverified reason text. Even after bounding fact arrays, 0/11 calls passed all identity/selection/exact-fact requirements; all 11 used honest catalog fallback. This candidate was rejected. Initial R3 list output also repeated indices or selected too many facts, accepting 0/10 responses (one additional eligible case was context-gated). Replacing model-generated index lists with required per-product keys and bounded arrays was the single targeted schema correction. It yielded 11/11 accepted development responses before limited Vietnamese type support and 13/13 afterward. No further prompt search was conducted.

## Final R3 structural/reliability evidence

- Development: 13/20 cases execute and succeed as model-selected facts (65% overall, 100% of 13 eligible calls); 0/13 generation fallbacks; 5 relevance/mandatory-data validation failures, 1 upstream clarification and 1 invalid upstream result. These seven terminal cases do not count as successful recommendations.
- All 20 returned public results validate against the unchanged public schema. All 33 returned development product items preserve original IDs, names, brands, categories, prices, ratings and ranks; 13/13 accepted request orders match supplied order. URLs remain upstream metadata because the public item has no URL field.
- All 95 selected development strength statements are exactly the provided fact under an explicit catalog-attribution wrapper; all 95/95 citations exist, belong to the product, and map to fact content supplied to the model under its alias. There are zero accepted model-invented products/attributes, zero changed authoritative fields and zero invalid accepted citations under these checks.
- Source quotation fidelity is a deterministic property, not a claim that the catalog is independently true, current or suitable. No semantic judge has approved arbitrary generated prose; none is released from R3. Missing ratings yield unknown-information caveats rather than poor-rating claims.
- D0 returns deterministic fallback for the same 13 eligible cases and the same seven terminal cases, preserving the same 33 product metadata items with zero inference calls. Its fallback is measured separately and never counted as LLM generation.

Useful model contribution is fact choice: development selections include 58 specification facts, 24 price facts, 8 product-name facts and 5 category facts. This is more than returning fallback for every request. But selection relevance is imperfect: for lightweight jogging shoes, one three-product response chose price/occasion/intended user rather than weight; for lace closure, one candidate selected the listed closure and others selected unrelated fields. **Usefulness and requirement alignment remain provisional and unscored without independent review.** D0 may be sufficient in some cases; R3 is selected only for the bounded evidence-choice experiment, not on an invented usefulness score.

## Context/output observations and deadlines

R0 prompt counts ranged 1037?3302, with mean 2072.1; mean completion 973.6 and max 1536. R1 prompt counts ranged 555?2820, mean 1638.3; mean completion 1031.5 and max 1536. Some baseline prompt-plus-requested-completion budgets exceed 4096, so full-window instruction/evidence retention cannot be assumed. Raw input and termination evidence is retained, and baseline results do not claim complete attention.

The sparse D05 output-budget probe changed only num_predict from 1536 to 2048 with measured prompt count 1069 (within the nominal window). It still terminated with length at 2048 and invalid JSON. This one-case result supports more than a simple 512-token-cap explanation; it is not proof that every longer budget fails or prompt complexity is the only cause.

Final R3 development executed-call prompt range is 150?712 (mean 399.9), completion mean 34.5 / maximum 73, generation throughput mean about 111.1 tokens/s. Executed wall P50/P95 is 689.6/946.3 ms (13 calls). Final cap 256 leaves headroom above measured structured selection outputs and is enforced with a conservative explicit-prompt byte bound plus margin; excess context is rejected, never silently shortened. A reported-count check also refuses a response that leaves insufficient reserved completion context.

R0 first observed request took 7492 ms including reported 4336 ms model loading; later requests were warm. Final R3 first request took 726 ms with reported load 3.4 ms, a warm observation. No model unload or repeated controlled cold-start benchmark was performed. Initial comparison caps are 1536; final cap optimization is reported separately rather than attributed solely to a prompt improvement.

Existing timeouts are recommendation 30 s, API 90 s and bot 95 s. No arbitrary new latency SLA or usefulness threshold was imposed. Observed selection latency leaves experimental headroom on this host, but full-pipeline timing, concurrency, longer contexts and parent-deadline integration still need Phase 18.5 validation.

## Post-freeze provisional cases

The generation source/prompt/schema was frozen before eight new catalog cases with product IDs excluded from development, spanning boots, water bottles, pens, curtains, backpack and Vietnamese flats. Independent human review is unavailable; semantic results are **provisional**, not independent acceptance. The original set produced 7/8 successful selections, 0 generation fallbacks and one conservative validation failure. Successful outputs preserve all 17 product items and 49/49 selected source citations. Executed P50/P95 was 645/831 ms; prompt maximum 769 and completion maximum 47.

F08 contained question marks introduced by PowerShell stdin encoding rather than the intended Vietnamese text. The original corrupted fixture/result remains. A separate UTF-8 escaped correction file was evaluated against unchanged frozen generation code: 1/1 success, one preserved product and 3/3 valid quoted facts/citations. Its 664 ms wall time is a single observation, not a percentile estimate for Vietnamese. Do not relabel the original run as 8/8. Proper Unicode Vietnamese development cases also succeeded with catalog-attribution templates. Catalog fact strings remain in their source language; fluent natural Vietnamese and usefulness still need human review.

The final composition snapshot additionally stops a contradictory Phase 9 embedding-failure input before dispatch and labels per-request schema artifacts correctly. Neither changed generation code or tuned to provisional responses. Legacy early `R3.schema.json` placeholders must not be used as bindings: `request_schema` on rows and frozen `request_schemas.json` are authoritative.

## Tests and preserved failures

The final selected offline suite passed **420 tests**, with one existing unawaited-AsyncMock warning in `test_api_orchestrator.py::test_deterministic_fallback_flow`. It includes Query Understanding/Q1S tests, Recommendation Generation, native HTTPX mocks, evidence/fallback tests, retrieval contracts, API orchestration/integration/config/price mapping and Gateway lifecycle. It is not the entire repository live/integration suite. A guarded runner denies external DNS/sockets, disables model downloads and permits loopback for Windows asyncio. No external provider/database was used.

Preserved failures include: R0/R1 truncation and unsupported prose; all-fallback R2 and initial R3; the larger-budget probe; the corrupted Unicode fixture; a new unit test initially omitted the required RerankingResult.method argument (fixed test fixture); and an early broad run failed 1/418 because the operator environment set API_DEFAULT_TOP_K=3 while a default-value test expected 5. The isolated test runner pins that expected test default only; application settings/.env are unchanged. Subsequent 419-test and final 420-test runs passed with the noted warning. The initial controlled-reproduction artifact mutated its input after retaining the unsupported output; `safety_reproduction_exact.json` replays the frozen validator with an unmutated input. All raw experiments and prior snapshots remain.

Offline negative tests cover unavailable/timeout native server, invalid/empty/truncated JSON, wrong model, missing/duplicate/unknown keys or products, cross-product index/order errors, invalid citations, free unsupported facts/compatibility/numeric comparisons, missing-information wording, invalid/clarifying upstream input, failure propagation, deadlines, cancellation, client ownership, usage and one-call dispatch. A real service-level smoke test explicitly injects the native generator, uses one request and preserves three product IDs; it does not activate API/Gateway routes.

## Readiness decisions

| Decision | Assessment |
|---|---|
| Structural compatibility | R0/R1 inadequate; R3 passes the measured 1/3/5-candidate structured selection cases with preserved public schema/metadata/order. |
| Experimental integration | R3 can proceed to guarded Phase 18.5 common-adapter/API composition tests with existing safe gates. |
| Semantic quality | Source attribution/citation ownership is verified for accepted outputs. Suitability, usefulness, catalog truth, free prose and language quality lack independent human validation. |
| Production readiness | Not approved: Q1S limits, relevance/coverage gaps, incomplete synonym/compatibility handling, provisional review and route-specific approval gates remain. |

The known pad?cable, speaker?headphones and body-cover?steering-cover cases return terminal validation failure without inference. No retrieval algorithm was redesigned; carry these issues to Phase 18.6. The relevance guard is conservative and incomplete, so it is not a universal suitability verifier. Missing mandatory data and upstream failures must stay terminal. Historical Phase 12 citation-based prototype claims do not establish entailment, and existing acceptance requirements were not lowered to accommodate this model.

## Reproduction

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_phase18_4.py --fixtures data/interim/phase18_4/fixtures/dev.json --candidates R3 D0 --out data/interim/phase18_4/evaluation_results/new_selection_run
.\.venv\Scripts\python.exe data/interim/phase18_4/run_offline_regression_isolated.py
```

Use a new output directory. R0/R1 historical comparisons must use frozen baseline source if reproducing original fallback wording; current default fallback is safety-corrected. Source/model/prompt/request-schema/fixture/results hashes and the final freeze are indexed under `experiment_manifests`. Do not use the old R3 list schema or reuse phase12.recommendation.v1 for the new internal meaning.
