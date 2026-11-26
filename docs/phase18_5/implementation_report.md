# Phase 18.5 implementation report

2026-11-26, Asia/Saigon. Started from `main` at `cdf560e`, equal to `origin/main` after fetch. Read the Phase 18 handover, Phase 18.2 implementation, Phase 18.3 implementation/evaluation and Phase 18.4 audit/implementation/evaluation/Gateway handover. The existing provider contract, configuration/registry, routing/decoding, endpoint security, deadlines, failover, quotas, health, telemetry, direct native clients and API lifecycle were audited before integration.

**Experimental native integration is implemented and locally validated.** Both frozen candidates use the same Gateway and native transport. Production activation is pending, and Phase 18 remains `IMPLEMENTED_PENDING_BACKUP_VALIDATION`. No commit, push, model download, additional model, external inference, paid call or T17 modification was performed.

| Files created/modified | Purpose |
|---|---|
| New `llm_gateway/adapters/ollama.py`, `json_utils.py` | Common one-dispatch native adapter and strict duplicate/non-finite JSON rejection. |
| `llm_gateway/adapters/base.py`, `schemas.py`, `errors.py` | Internal native timing and failure attribution; adds Ollama provider value without changing public business schemas. |
| `llm_gateway/config.py`, `registry.py`, `schema_ids.py`, `experiment_factory.py` | Native endpoint/options/evidence policy, separate internal bindings, canonical dynamic schema validation and fingerprint admission. |
| `llm_gateway/gateway.py`, `telemetry.py` | Reuses execution policy/leases; native readiness, strict output parsing, known failure metadata and correlated fallback telemetry. |
| New `llm_gateway/native_runtime.py` | Explicit Ollama-only composition through the existing registry and normal evidence loader. |
| `llm/query_understanding.py` | Explicit `gateway_native` injection; frozen prompt/schema/transformation, fail-closed behavior, usage, request/task IDs and parent deadline. |
| `recommendation/local.py`, `core.py` | Gateway-injected R3 transport with no local HTTP client; existing evidence projection, source assembly, relevance guards and safe fallback. Duplicate selection schema correction; parent expiry precedes context fallback. |
| `api/main.py`, `api/routes/health.py` | Explicit startup composition, shared ownership/shutdown, recent identity/configuration/cooldown readiness indicators. Standard runtime default preserved. |
| New `config/llm_gateway_ollama_experimental.yaml`; `.env.example` | Disabled/pending experimental template and single-source configuration example. |
| New `tests/ollama_support.py`, `test_llm_gateway_ollama_adapter.py`, `test_phase18_5.py` | Mocked native protocol/security/error tests and shared-consumer/lifecycle/reliability tests. |
| `tests/test_llm_gateway_chat_adapters.py` | Repairs obsolete test setup that looked up a previously removed production OpenRouter route. Uses an explicit synthetic route; assertions preserved, production route not restored. |
| New `scripts/validate_phase18_5.py`, `scripts/freeze_phase18_5.py`; artifact runner | Reproducible supervised local smoke test, evidence snapshot/index and external-network-denied selected offline regression. |
| README, development status, Phase 18 handover and four Phase 18.5 reports | Current verified progress and Phase 18.6 gates; historical reports retained. |

Frozen Q1S extraction prompt/schema, transformation, constraints and normalization are unchanged. R3 prompt, evidence projection, product ownership/order, source templates and groundedness validator are unchanged. Its factory now rejects duplicates during structural validation as well as in the existing business check. This is the narrow integration defect correction, not prompt or architecture optimization. Frozen Phase 18.3/18.4 files remain intact.

The existing `Gateway`, router, `TaskAttemptPolicy`, failover controller, process-local quota manager and health tracker remain the only reliability architecture. The native runtime requires exactly one provider, one route per profile, one attempt per task/route, no auto failover and one concurrent inference. The judge placeholder is disabled. Historical direct native runners are retained for reproducibility but are not constructed in integrated FastAPI mode.

The [architecture report](architecture_and_integration.md) documents runtime settings and operational limits. The [test report](integration_test_report.md) records 728 passing final offline tests and successful live Q1S/R3 integration. The six successful live inference calls were performed before the final failure-metadata/expired-parent edge corrections; final offline tests cover those corrections, and frozen success-path prompts/options/schema fingerprints remain identical. No repeated inference was needed to test those failure-only changes.

Production approval still requires independent semantic/usefulness review, current evidence for actual catalog schema shapes and catalog-backed FastAPI validation. Native local-only operation deliberately has no cloud backup; it does not satisfy the historical Phase 18 production backup/failover requirement. Changing that requirement would need a separate recorded product decision. No acceptance criterion was lowered.
