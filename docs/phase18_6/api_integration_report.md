# Phase 18.6 API integration report

2026-11-27, Asia/Saigon. **Genuine FastAPI + local Ollama + catalog/database retrieval integration passed the exercised positive cases.** Production readiness and independent semantic usefulness are separate decisions.

## Executed application

The real FastAPI application, lifecycle, orchestrator and services ran on `127.0.0.1:8000` with one worker. No retrieval products were substituted in the primary API run. The isolated observation harness delegates to the actual `shopassist.api.main.main()` entry point, preserves original call results and records stage outputs separately from production telemetry. The exact uninstrumented command `.\.venv\Scripts\python.exe -m shopassist.api.main` was also started and tested successfully under the normal 300-second identity TTL.

`GET /api/v1/health/live` returned 200/alive. The deliberately short 2-second TTL stress run could report stale identity at readiness after idle time; requests safely reverified it. Normal 300-second CLI and detailed profiling runs returned **200/healthy**, then **200/SUCCESS** for a real recommendation. All owned servers were stopped cleanly after testing. Ollama remained running.

The public request/response models and `/recommend` alias were preserved. E02 used the root alias successfully. A healthy HTTP 200 is not sufficient for business acceptance; the following table uses application statuses.

## Bounded preclassified evaluation

The first 21 cases were classified before execution using catalog availability and existing safety semantics. E22 was separately classified before execution as an explicit one-result rating check. It did not change the runtime's candidate count to bypass a failed schema or guard.

| Cases | Observed application result in the final run |
|---|---|
| E01 running shoes under 2000, E02 AMCO running shoes, E03 comfortable running shoes, E04 headphones under 1000, E05 cheap headphones, E19 numeric negation, E22 one rated headphone | **7 SUCCESS** |
| E09 foreign currency, E10 pet food, E11 missing intent, E15 competing makers, E17 Bluetooth speaker, E18 Honda City body cover, E20 Vietnamese input | **7 CLARIFICATION_REQUIRED** |
| E12–E14 genuine exclusions | **3 UNSUPPORTED_INTENT** |
| E06 rated headphones top-k 3, E07 laptop price range, E08 laptop 16 GB RAM, E16 wireless charging pad | **4 VALIDATION_FAILURE**, with no unsafe generation/fallback |
| E21 running shoes under 1 INR | **1 NO_RESULTS** |

All 22 requests returned HTTP 200 with valid public business responses. E01/E02/E03/E04/E22 provide successful actual cardinalities **3/2/4/5/1**. Mandatory-filter and product-type failures were retained rather than counted as recommendation success. Vietnamese handling remains a clarification/coverage limitation. The top-k 3 rating case was refused because the candidate set did not establish the requested product type; the preclassified top-k 1 case was eligible. E07's initial expectation overstated laptop catalog absence: actual retrieval found HP Notebook models mixed with a processor, while exact-name relevance matching also lacks this alias. The original expectation is retained; this is a known retrieval/coverage limitation, not a passed relevance case.

Evidence: [cases](../../data/interim/phase18_6/api_test_results/cases_preclassified.json), [additional rating case](../../data/interim/phase18_6/api_test_results/cases_additional_preclassified.json), [22 actual HTTP responses](../../data/interim/phase18_6/api_test_results/live_api_02.jsonl), [deterministic review](../../data/interim/phase18_6/performance_results/review_02.json), [direct CLI check](../../data/interim/phase18_6/api_test_results/direct_cli_01.json).

## Accepted result checks

All **21 accepted product occurrences** across seven successful requests preserved authoritative database IDs, names, categories, brands, prices, ratings, order and catalog-derived URLs/images. All mandatory price/category/brand/rating checks passed. No synthetic product or critical price violation was observed.

All **42 selected strength claims** were exact `Catalog lists: ...` quotations of product-owned evidence with valid citations. This establishes source quotation fidelity, not independent catalog truth or suitability. Selected facts such as occasion, material, price or gender can be catalog-grounded without being the most useful explanation for the user's needs; usefulness/language review remains provisional.

Every successful final-run request made **one QU plus one R3 inference call**, with a maximum of two for every tested request. The 22-case run made **26 inference POSTs** (19 QU, 7 R3), and **11 identity GETs** (one startup plus ten request-triggered refreshes under the 2-second stress TTL). Control-plane calls are not LLM inference. There was no repair pass, semantic judge or external/cloud inference. Known public token totals matched correlated Gateway usage, including terminal responses after QU: 6,286 input + 847 output = 7,133 tokens in this run.

Server-generated internal IDs remain separate from public header IDs. For the serial 22-case run, the review correlates per-request native HTTP observations with ordered Gateway attempts and verifies equal dispatch/attempt counts. The later profiling harness also records explicit public/internal ID associations. Production telemetry excludes raw prompts, outputs, credentials and headers; isolated evaluation observations intentionally retain raw QU and catalog-stage data.

## Failure and reliability evidence

The initial 21-case live run occurred during database unavailability: 10 retrieval failures, seven clarifications and four unsupported outcomes, including the then-unfixed E19 preference guard. Those results are preserved in `live_api_01.jsonl`. No unavailable-database response became a fabricated recommendation. Database retry then succeeded; the final run used actual catalog-backed retrieval.

Controlled **offline API-boundary** tests cover native unavailable/malformed/truncated/wrong-model responses, unapproved schema, R3 deterministic fallback only for eligible candidates, quota contention, no results, database/retrieval/reranking failure, genuine exclusion, irrelevant candidates, expired parent deadline and request-task cancellation with lease release. Identity tests cover unavailable/changed digest, fresh/stale cache, concurrent checks, cancellation and expired route approval. The operator's server was not stopped to simulate provider failure. ASGI task cancellation was tested; this does not establish every deployment's TCP-disconnect cancellation behavior.

One real transient timeout occurred in the reference wireless retrieval ablation and was retained; its targeted retry passed. The final guarded offline selection passed **765 tests with one pre-existing unawaited AsyncMock warning**. Exact files and invocation are recorded in `data/interim/phase18_6/run_offline_regression.py`, extending the historical Phase 18.5 selection. Failed attempts and the Windows deadline correction are documented in the [implementation report](implementation_report.md).

## Performance

| Measurement | Executed samples | P50 | P95 |
|---|---:|---:|---:|
| Whole HTTP request, all business outcomes | 22 | 931 ms | 2059 ms |
| Successful HTTP requests | 7 | 1815 ms | 4626 ms |
| Warm successful requests, excluding first E01 | 6 | 1761 ms | 2010 ms |
| QU service, including transformation/identity as applicable | 19 | 343 ms | 737 ms |
| Python transformation | 19 | 7.4 ms | 29.0 ms |
| Preference representation, including no-preference fast path | 12 | 0.18 ms | 29.2 ms |
| SQL filtering/count | 12 | 154 ms | 288 ms |
| Dense database retrieval | 12 | 229 ms | 509 ms |
| Lexical retrieval/filtering | 12 | 49 ms | 499 ms |
| Hybrid fusion | 12 | 0.62 ms | 2.09 ms |
| Reranking (RRF) | 11 | 0.45 ms | 0.50 ms |
| Gateway R3 inference | 7 | 390 ms | 517 ms |

These are different executed-stage populations; they must not be summed as percentiles or interpreted as a production SLA. Preference timings include requests that need no embedding. RRF was the API method, so its recorded CrossEncoder time is zero; real existing CrossEncoder comparisons are separate retrieval diagnostics.

The first final-run request took 5720 ms, including a reported 2895 ms native model load. Backend startup separately took about 3820 ms. Initial database-outage requests commonly spent about ten seconds in retrieval timeout; these are excluded from the final healthy 22-case metrics, not discarded from evidence.

A separate **one-request** detailed profiling check measured Pydantic request validation 0.14 ms, R3 admission/evidence/schema/request preparation 13.61 ms, validated selection mapping plus Python assembly 0.80 ms, and FastAPI response-model serialization 0.12 ms. The harness calls original functions and measures boundaries without replacing results. HTTP transport, body decoding and middleware overhead are not mislabeled as pure model-validation time; these single samples support observability only. See [stage profile](../../data/interim/phase18_6/performance_results/stage_profile_01.json) and [branch metrics](../../data/interim/phase18_6/performance_results/branch_and_resource_summary.json).

API/bot configured budgets remain 90/95 seconds. No resource rebuild or speculative optimization was justified. Local Ollama has no external per-request API charge in this setup; hardware/electricity cost is unmeasured and no monetary estimate is claimed.

## Decisions

| Decision | Assessment |
|---|---|
| Backend integration | **Validated for the exercised local prototype** with actual database and full inference pipeline. |
| Experimental Telegram readiness | **Ready for supervised Phase 18.7 testing**, with fresh authorized evidence, healthy database and explicit native configuration. No live Telegram test occurred here. |
| Retrieval quality | Mixed; product-type/compatibility failures remain visible and safely refused. |
| Semantic usefulness/language | Provisional, no independent reviewer; historical Q1S preference/coverage limitations remain. |
| Production readiness | Not approved. Historical backup/failover, independent review, operational availability and deployment gates remain open; Phase 18 stays `IMPLEMENTED_PENDING_BACKUP_VALIDATION`. |
