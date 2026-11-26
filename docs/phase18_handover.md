# Phase 18 V1 — Configuration and Baseline Handover

**2026-11-26 (Asia/Saigon).** [Architecture](phase18_architecture.md) · [Gateway contract](phase18_gateway_contract.md) · [Test and integration report](phase18_test_and_integration_report.md) · [Execution log](phase18_execution_log.md)

## Current operating state

The Gateway package and automatic failover controls are implemented. Phase 12 default routing in [the YAML](../config/llm_gateway.yaml) is `recommendation_gemini` (`GEMINI_API_KEY_2`, `gemini-3.5-flash-lite`) followed by `recommendation_groq` (`openai/gpt-oss-20b`). OpenRouter is absent from this Gateway YAML and from application Gateway adapter construction. Legacy OpenRouter settings still exist for Gateway-disabled mode.

Every production route remains `enabled: false`, approval `pending`, and cost class `unknown`. `LLM_GATEWAY_ENABLED` defaults to `false`; `LLM_GATEWAY_ALLOW_PAID_MODELS` defaults to `false`. Enabling the Gateway flag alone does not make a route eligible: Phase 8 fails closed and Phase 12 uses deterministic catalog fallback when no valid route exists. No production provider-backed failover was demonstrated in T17. The operator authorized T18 documentation while accepting that T17 quality and activation gates remain open. Phase 18 status is **`IMPLEMENTED_PENDING_BACKUP_VALIDATION`**.

## Configuration guide

| Setting/source | Purpose |
| --- | --- |
| `LLM_GATEWAY_ENABLED` | Selects Gateway at startup; `false` retains legacy composition. Restart the process after changing it. |
| `LLM_GATEWAY_CONFIG_PATH` | Optional path to the version 1 YAML, resolved from the project root. The YAML alone determines route order when Gateway is enabled. |
| `GEMINI_API_KEY` | Phase 8/14 Gemini profile credential. |
| `GEMINI_API_KEY_2` | Phase 12 Gemini primary profile credential. It is sent to the Google endpoint, not to OpenRouter. |
| `GROQ_API_KEY` | Phase 12 backup candidate credential. |
| `LLM_GATEWAY_AUTO_FAILOVER`, `LLM_GATEWAY_ALLOW_PAID_MODELS` | Local failover and paid-model policy. Keep paid models disabled under the current Free Tier policy. |
| `LLM_GATEWAY_TELEMETRY_ENABLED`, `LLM_GATEWAY_TELEMETRY_DIR` | Local JSONL attempt/task summaries. Prompt and response content logging are forbidden by settings validation. |

`GatewaySettings` also bounds one outbound attempt per route, two attempts per task, a 25-second default attempt timeout and task deadlines. Secrets remain in local environment configuration; the YAML refers only to credential variable names. The provider endpoint and credential names are allowlisted by the loader. A route needs exact task/schema/model/endpoint/mode evidence, approval, cost evidence and `enabled: true` before dispatch. The T17 isolated operator attestations do not automatically satisfy production route approval.

## Provider switching and rollback

1. Record the proposed provider, endpoint, model, task, schema, structured output mode and account cost policy. Confirm the model can produce the required schema and grounded recommendations with a controlled validation artifact.
2. Add or change the provider profile and route in `config/llm_gateway.yaml`; put eligible route IDs in priority order under the task's `default` profile. Use a separate adapter binding for a different credential profile. Keep the route disabled/pending until evidence and cost validation have passed.
3. Review the exact route evidence and the [test report](phase18_test_and_integration_report.md). Run mocked routing/failover and guarded offline regression. Approve/enable the route only through a separate recorded operator decision, then restart and verify local readiness and telemetry. Do not use account credential presence as approval evidence.
4. For an immediate Phase 12 provider stop, disable its YAML route and restart. With no eligible Phase 12 route, the service uses deterministic catalog fallback. Phase 8 has a separate fail-closed rule.
5. A full Gateway rollback sets `LLM_GATEWAY_ENABLED=false` and restarts. **Check legacy Phase 12 settings first:** the current legacy default is OpenRouter, so full rollback can reintroduce it outside Gateway. Restoring OpenRouter *inside* Gateway requires a deliberate code/config change and new validation; it is not a YAML-only switch in the current snapshot.

No route has been approved or enabled as part of this handover.

**Phase 18.5 follow-up (2026-11-26):** frozen Q1S/R3 now share the existing Gateway, one native Ollama adapter and one HTTPX pool in an explicit experimental runtime. Production YAML remains disabled/pending and unchanged. Time-limited isolated smoke-test permissions use normal evidence checks and do not approve production semantics. The final applicable offline selection passed 728 tests (one existing mock warning); live QU and 1/3/5-product R3 passed, with two inference calls in a combined smoke using mocked retrieval. This closes the scoped native integration work, not Phase 18 production backup/quality gates. See [architecture](phase18_5/architecture_and_integration.md), [test evidence](phase18_5/integration_test_report.md) and [Phase 18.6 handover](phase18_5/phase18_6_handover.md). T17 is unchanged; overall status remains `IMPLEMENTED_PENDING_BACKUP_VALIDATION`.

## Telemetry report format

The local sink writes bounded `gateway.jsonl` files under `data/interim/llm_gateway` by default: 1 MiB per file, up to three files, with a queue of 1,000 records. It records one `attempt` event per finalized provider attempt and one `task_summary` per task. Useful fields are `request_id`, `task_id`, task/profile/schema, route/provider/model, attempt number, outcome/reason, latency, usage, failover flag, and skip reasons. The task summary names the actual winning route/provider/model and counts attempts; usage is null when the provider did not report it. Dropped telemetry increments a local counter without changing the business result. Prompts, responses, credentials, headers and raw driver/provider exceptions are excluded. The separate T17 groundedness review artifact contains parsed test recommendation content and catalog evidence; it is **not** Gateway production telemetry.

## Deferred issues and Baseline Testing handover

| Priority | Work needed before declaring Phase 18 V1 complete |
| --- | --- |
| Route quality | Obtain a reviewable successful Gemini Phase 12 response and decide semantic groundedness. Review the [Groq output and fixture](../data/interim/phase18_t17/validation_groq_groundedness_review_recommendation_groq_groundedness_review.json); its durability/color claims need a decision. Preserve the frozen catalog and prompts while assessing quality. |
| Approval and failover | Produce current route-specific evidence, record operator approval and enable an eligible Phase 12 backup. Then run controlled primary success, primary unavailable → backup success, and both unavailable → catalog fallback scenarios with actual provider/model attribution, usage and the two-attempt limit. No route has this gate today. |
| Regression | Rerun the complete offline suite on the final route/harness snapshot with the T00 DNS/socket guard, no DSN/provider credentials and local model assets. The last broad selection predates final route removal; an unguarded run attempted external DB and model-download calls. Version a reproducible guarded runner for future baselines. |
| Live integration | Validate a provider-backed Gateway request through FastAPI and, if required, Telegram. Current live results are isolated harness calls. Preserve public response contracts and deterministic fallback. |
| Cost/evidence | Provider responses reported no actual cost. Keep USD $0 paid-spend policy and refresh time-limited account evidence before any new live test or approval. T17 cumulative request budget is exhausted at 10/10. |
| Source plan | The canonical `docs/phase18_implementation_plan.md` is absent from this checkout; T18 used the operator-supplied Phase 18 plan attachment together with architecture/contract docs. Preserve a versioned canonical plan if the team needs future audits. |

Baseline Testing should start from the immutable catalog and existing public API fixtures, compare deterministic fallback and provider-attributed outcomes separately, and report request/attempt counts, schema/grounding decisions, token/latency/cost availability, and external connection attempts. The [test and integration report](phase18_test_and_integration_report.md) is the evidence index for this snapshot. Do not label Phase 18 `COMPLETE` until an approved and enabled Phase 12 backup and its failover acceptance evidence exist.
