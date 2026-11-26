# Phase 18.5 integration test report

2026-11-26, Asia/Saigon. Tested the existing frozen local Qwen2.5 1.5B model through Gateway with native `/api/chat`, temperature 0, seed 42, context 4096, and QU/R3 output caps 512/256. Fresh `/api/tags` matched frozen digest `d010eb818583111cfafeb3523cc17802f85dcb7f4fe5e8ecdd4927dca40e3174`.

## Offline evidence

Final guarded selection: **728 passed, 1 warning**, covering native protocol/security/configuration, both integrated consumers, dynamic schemas, upstream/relevance guards, deadlines/cancellation/quota, lifecycle/readiness, existing Gateway providers, prior Q1S/R3, retrieval/reranking contracts and API/bot mocked tests. This is a scoped applicable regression, not the entire repository live suite. The runner denies external DNS/socket connections and enables Hugging Face/Transformers offline mode; no neural checkpoint is downloaded.

```powershell
.venv\Scripts\python.exe data/interim/phase18_5/run_offline_regression.py
```

See [final report](../../data/interim/phase18_5/offline_regression_03.txt). The existing warning is an unawaited `AsyncMock` coroutine in `test_api_orchestrator.py::test_deterministic_fallback_flow`. It does not fail the selection and is not hidden.

The first broad run recorded 710 passes and 16 failures: old OpenRouter adapter fixtures referenced a production route removed before this phase. Replacing only that test setup with a synthetic route yielded 726 passes. Two final attribution tests brought the final selection to 728. An initial focused parametrization also caused Windows temporary-directory filename errors for the large-response fixture; stable short parameter IDs fixed those setup errors. Both are harness/test setup corrections, with no production route restoration or guard relaxation.

Mocked Test C covers server unavailable/network errors, HTTP errors, timeout, malformed/non-string/empty/truncated output, unexpected reported model, negative/bool/inconsistent usage, invalid durations, duplicate keys/indices, non-finite JSON, bounds/shape/context/size failures, stale or mismatched digest, disabled/tampered evidence, invalid upstream/relevance, parent exhaustion, cancellation and quota release. Failures use MockTransport; the operator's live server was not stopped. No cloud adapter participates. Request-level parent deadlines propagate as typed Gateway errors; R3 only uses deterministic fallback for eligible input after provider/structural failure.

## Live local Gateway evidence

The supervised harness uses prior real native artifacts, a passing offline report and fresh tags to create time-limited, test-scoped route evidence with exact fingerprints. It loads that isolated config through normal approval/artifact-hash/expiry/eligibility checks. Synthetic unit-test evidence is not used as live route evidence. The checked-in experimental and production YAML remain disabled/pending.

```powershell
.venv\Scripts\python.exe scripts/validate_phase18_5.py --out data/interim/phase18_5/live_new --offline-report data/interim/phase18_5/offline_regression_03.txt
```

Use a new output directory and the unchanged frozen local model; this command makes real local inference calls. Saved run: [results](../../data/interim/phase18_5/live_02/integration_results/results.json), [telemetry](../../data/interim/phase18_5/live_02/integration_results/telemetry/gateway.jsonl), and [route artifact](../../data/interim/phase18_5/live_02/route_validation/artifact.json). Their index hashes and source freeze are under `experiment_manifests` and `frozen_candidate`.

| Test | Verified result | Native inference calls | Observed service wall time |
|---|---|---:|---:|
| A: `I need lightweight Puma running shoes under 2000 rupees.` | Valid public QU; Footwear/Puma; max price 2000, no minimum; one exact flat schema | 1 | 5811 ms |
| B: frozen D01, 1 product | Success, canonical dynamic schema, valid selected indices, exact IDs/order/metadata and product-owned source quotations | 1 | 189 ms |
| B: frozen D02, 3 products | Same checks passed | 1 | 458 ms |
| B: frozen D03, 5 products | Same checks passed | 1 | 690 ms |
| D: `running shoes under 2000` | Live Q1S → typed mocked retrieval candidates → existing RRF reranker → live R3 → successful public result | 2 | 806 ms |

Total: **6 native inference POSTs**, **2 control-plane `/api/tags` GETs**, **0 external inference calls**, **0 repair/judge calls**. A and B each used at most one call per task; D used exactly two for the eligible complete request. One shared Gateway/adapter/client served all tests. The first QU attempt included a reported 5357 ms model load; its 5703 ms Gateway attempt latency is not representative warm latency. The sample is too small to establish a production P95 or SLA.

Reported input/output tokens: A 179/32; B 236/11, 459/45 and 712/73; D QU 171/32 and R3 465/45. Native timings, expected digest and schema fingerprints are captured per attempt. No API fee is charged by this local endpoint; hardware/electricity cost was not measured and no monetary cost estimate is asserted.

`live_01` stopped before any HTTP or inference because PowerShell had saved the offline report in UTF-16 while the harness expected UTF-8. The harness now recognizes the BOM; `live_02` passed all checks. This failure is recorded in the experiment notes rather than removed.

## Scope and acceptance

Protocol, shared transport/lifecycle, model identity, schema admission, one-attempt policy, usage/telemetry, cancellation/deadlines, safe fallback and the explicit FastAPI experimental composition pass the exercised checks. Public business schemas and production routing are unchanged. Frozen prompt/parser/semantic transformations remain unchanged; narrow duplicate-index structural enforcement is documented.

FastAPI composition/cleanup/readiness used mocked resources. Test D used frozen catalog-derived candidate fixtures and mocked retrieval/preference vectors, with real typed contracts and RRF reranking. **No live database, pgvector, TF-IDF/dense retrieval or Telegram user delivery was validated in this phase.** Source quotation fidelity is not independent catalog truth, semantic usefulness or full relevance acceptance. Q1S preference F1 68.4% and answerable coverage 11/16 remain historical limitations, not metrics improved by this integration. No production activation is approved.
