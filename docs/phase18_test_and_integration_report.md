# Phase 18 V1 — Test and Integration Report

**2026-11-26 (Asia/Saigon).** This report distinguishes mocked Gateway evidence from isolated live provider evidence. It does not mark production routes approved.

## Test evidence

| Scope | Result | Evidence and limit |
| --- | --- | --- |
| T16 full offline regression, before the Phase 12 route change | 902 passed, 13 deselected, 1 baseline AsyncMock warning; 0 external connection attempts | [Execution log](phase18_execution_log.md), `.deps/phase18-t16-regression.xml`. Includes Gateway failover, deadline/cancellation, task fallback, API and Telegram mocks. |
| T17 harness offline implementation, before the route change | 928 passed, 13 deselected; 0 external attempts | [Execution log](phase18_execution_log.md), `.deps/phase18-t17-harness-regression.xml`. Synthetic evidence and mocked adapters are not live provider proof. |
| Phase 12 Gemini/Groq route and final T17 harness | 110 focused tests passed | Config/registry/Gateway/lifecycle/experiment/CLI/harness tests. Covers the separate `GEMINI_API_KEY_2` adapter profile, pending routes, persistent budgets and redacted groundedness-review artifacts. |
| Broad selection before the final removal of OpenRouter from Gateway YAML | 910 passed, 7 skipped, 26 deselected | `.deps/phase18-route-change-offline.xml`. This is not a regression pass for the final source snapshot. |
| Full regression after the final route and T17 harness changes | **Not established** | The attempted unfiltered run exercised unmarked live Supabase tests and a Hugging Face model download, so it is not valid offline acceptance evidence. Rerun with the T00 network guard and local model assets before claiming a full regression pass. |

The focused tests use no provider or database dispatch. The unexpected external attempts in the earlier unfiltered test run are documented in the [execution log](phase18_execution_log.md); their count was not captured. Do not report external attempts as zero for that run.

## Current isolated live results

| Route | Verified | Still open |
| --- | --- | --- |
| `query_gemini` | Exact model `gemini-3.5-flash-lite`, `phase8.query.v1` output, 155 reported tokens. | This used `GEMINI_API_KEY`, not the Phase 12 key. Its short-lived entitlement artifact has expired. |
| `recommendation_gemini` | One successful request reported the exact model, valid `phase12.recommendation.v1`, catalog product ID and evidence citations; 664 reported tokens, 4,640 ms. | Successful text was not retained for semantic groundedness review. One later request returned `PROVIDER_UNAVAILABLE` without usage/model output; no retry. Route remains pending/disabled. |
| `recommendation_groq` | Latest request reported `openai/gpt-oss-20b`, valid Phase 12 schema/product ID/citations; 1,112 reported tokens, 6,328 ms. [Review artifact](../data/interim/phase18_t17/validation_groq_groundedness_review_recommendation_groq_groundedness_review.json). | Human groundedness decision pending. The output infers durability from material type and suggests beige is the only color; the fixture does not establish either claim. Route remains pending/disabled. |

The [current route validation artifact](../data/interim/phase18_t17/validation_current_routes.json) records Gemini success, Gemini unavailable, and Groq success. The persistent T17 ledger is **10/10 requests and 20,316/50,000 tokens**, with no pending reservations. Provider responses did not report actual cost; the authorized paid-spend ceiling was USD $0 and account tier was operator-attested. Historical OpenRouter attempts remain in the cumulative ledger but OpenRouter is absent from the Phase 18 Gateway YAML and live candidate allowlist.

## Integration boundary

The FastAPI composition root creates one Gateway and injects it into Query Understanding and Recommendation services. Lifecycle and API/Telegram behavior were tested with mocks. T17 live calls used the isolated validation harness; they did **not** exercise a provider-backed FastAPI/Telegram request, production route approval, or actual Gateway failover. Phase 8 fail-closed and Phase 12 deterministic catalog fallback remain the configured service behavior when no route is eligible. Public API schemas, prompts, dataset, retrieval and reranking were not changed for Phase 18.

**T17 acceptance:** incomplete. **T18 documentation:** may proceed by explicit operator direction. **Phase 18 V1 status:** `IMPLEMENTED_PENDING_BACKUP_VALIDATION`, not `COMPLETE`.
