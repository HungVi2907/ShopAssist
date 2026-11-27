# Phase 18.6 implementation report

**The backend completed genuine catalog-backed FastAPI requests through local Q1S and R3.** The final 22-case run returned seven successful recommendations, with exactly two inference calls for every success. All 21 accepted product occurrences and 42 selected claims passed deterministic metadata/order/constraint/citation checks. This closes the experimental backend integration objective, not production approval or independent semantic evaluation. Overall Phase 18 remains `IMPLEMENTED_PENDING_BACKUP_VALIDATION`.

## Narrow corrections

| Source | Change and demonstrated reason |
|---|---|
| `llm_gateway/adapters/ollama.py` | On-demand `ensure_identity` reuses the shared client and an async lock. A generation counter coalesces concurrent failed checks as well as successful checks. Fresh identity avoids I/O; stale identity verifies the exact tag/digest. |
| `llm_gateway/gateway.py` | Performs bounded native control-plane verification after static route eligibility and before preparation/dispatch. Lock waiting plus HTTP is bounded by the smaller of 5 seconds, configured attempt timeout and remaining task/parent budget. Cancellation propagates without inference or quota reservation. Route approval is checked again after verification; it is never renewed. |
| `llm_gateway/registry.py` | Canonical selection family admits 1–5 products, adding only legitimate 2/4 cardinalities. Strict factory schema comparison, 1–13 fact bounds, per-request fingerprints and exact route evidence remain required. No wildcard approval. |
| `preferences/safety.py` | Adds query-level exclusion detection that masks only numeric spans recognized by the frozen deterministic parser when parsing has no issues. Exclusions outside those spans remain protected. The original phrase-level helper remains available. |
| `api/services/orchestrator.py`, `retrieval/hybrid.py`, `reranking/core.py`, `recommendation/local.py` | Reuse that numeric-aware guard for raw queries. Four existing downstream guards previously rejected `not exceeding` after Q1S had correctly extracted its upper bound. |
| `preferences/service.py` | Uses the same numeric-aware check for preference phrases. Live E19 showed the frozen extractor retaining `not exceeding 2000 rupees` in soft preferences; it now remains encodable without dropping its mandatory hard bound or rewriting frozen Q1S. Genuine negative preferences still stop. |
| `api/services/orchestrator.py` | Empty products no longer mask a failed reranking status as `NO_RESULTS`. Known QU token usage is preserved in downstream terminal responses; the first real outage run had misleading public zeros despite a measured QU call. Usage is kept in a request-local closure, with no public schema change. |

Prompts, decoding settings, deterministic constraint parser, Q1S transformation/semantic logic, R3 source wording and evidence ownership rules remain frozen. Retrieval algorithms, embedding/reranking models, index resources and relevance guards were not redesigned or weakened. There was no database write, external LLM, model download, public Ollama exposure, production route activation, T17 change, commit or push.

## Identity and route admission

Default identity TTL stays 300 seconds. A stale inference request enters the single-flight identity check, with an outer async timeout covering lock acquisition and `/api/tags`. Failure leaves identity unverified and inference fails closed. Changed digests are rejected. A waiter may cancel without leaking its lock or quota. A check finishing after route evidence expiry does not reapprove the route.

A short-deadline regression exposed Windows clock/timer granularity: a verification timeout could occur just before the monotonic clock reflected parent expiry, yielding `NO_ELIGIBLE_ROUTE`. Verification now remembers whether the parent/task deadline limited its timeout, matching existing Gateway attempt-policy semantics. Tests cover fresh/stale/success/failure/changed identity, concurrent success/failure, cancellation, expired parent and expired route approval.

The live stress run used a **2-second identity TTL only in its isolated process**, serving across repeated expiries and recording 10 request-triggered rechecks over more than 40 seconds since startup. The normal 300-second profile then passed actual CLI startup, healthy readiness and a successful recommendation. No five-minute waiting test or indefinite cache extension is claimed. Idle readiness can report stale identity until a native task triggers verification; a verified smoke request refreshes it without restart. A production health policy remains separate operational work.

Supervised preflight replayed captured Q1S outputs through **real** preference encoding, PostgreSQL/pgvector, TF-IDF and RRF, before subsequent API execution. It collected exact schema shapes from eligible ranked products at requested top-k values 1–5. A separate explicit command issued time-limited experimental test permission for 22 fingerprints through the normal loader. New shapes during an ordinary request are never auto-approved; they remain ineligible. This finite reviewed manifest is maintainable for supervised tests. General production family-wide approval would be a separate policy decision, not a change introduced here.

## Validation and evidence

Final guarded offline selection: **765 passed, one existing unawaited AsyncMock warning**. The exact selection extends the unchanged Phase 18.5 runner with `tests/test_phase18_6.py`; external DNS/socket calls are denied and model-download libraries are offline. Native adapter staleness expectations were updated deliberately for the new refresh behavior.

New API-boundary tests use the real FastAPI route/orchestrator with controlled native/retrieval fixtures: unavailable/malformed/truncated/wrong-model QU, invalid R3 fallback, unapproved R3 shape, database failure, irrelevant products, numeric compatibility, genuine exclusions, parent expiry, cancellation, quota contention, reranking failure and no results. These are explicitly mocked failure tests, not claims that live services were interrupted. Existing Gateway cancellation/quota/expiry tests also remain passing.

Failed experiments are retained: focused 01 had one test-fixture mapping-proxy mutation error; focused 02 had five failures that exposed the remaining reranker guard/status mapping plus a test settings override issue; focused 03 passed 32 tests. Broad 01 passed 760; broad 02/03 exposed the real verification-deadline classification issue; broad 04 had one invalid synthetic reranking fixture missing its required method; broad 05 passed 765. Preflight 01 used a nonexistent dataclass `model_dump`; preflight 02 collected real retrieval successfully but refused route permission while the offline report still failed. Collection and explicit permission were then separated. No failed evidence was replaced with synthetic success.

New scripts provide safe runtime audit, catalog preparation, actual retrieval preflight, explicit test evidence generation, actual CLI server instrumentation, HTTP evaluation, deterministic result review, reference relevance ablations and artifact summaries. Harness timing wraps original functions and preserves their results; production telemetry remains content-free. Raw queries, extractions and catalog outputs are confined to the isolated artifacts requested for evaluation.

See [runtime audit](runtime_audit.md), [retrieval findings](retrieval_validation_report.md), [API evidence](api_integration_report.md) and [Telegram handover](phase18_7_handover.md). Source snapshots and a self-excluding SHA-256 index are saved under `data/interim/phase18_6/experiment_manifests/`.
