## 2026-11-26 (Asia/Saigon) - T18 Final Documentation and Handover

| Item | Result |
| --- | --- |
| Task ID | T18 — Final Documentation & Handover. |
| Operator direction | Operator accepted the Free Tier attestation as sufficient for this handover and explicitly directed T18 to start. This authorizes the documentation task; it does not create route approval evidence or increase the exhausted T17 request budget. |
| Status | **PASS for T18 documentation acceptance.** Phase 18 V1 remains **`IMPLEMENTED_PENDING_BACKUP_VALIDATION`**; T17 live acceptance remains incomplete. |
| Files changed | `docs/phase18_test_and_integration_report.md`, `docs/phase18_handover.md`, `docs/phase18_architecture.md`, `docs/phase18_gateway_contract.md`, `docs/phase18_execution_log.md`, `docs/development_status.md`. No Gateway/runtime code or production route activation in T18. |
| Deliverables | Architecture and contract links reconciled with Gemini `GEMINI_API_KEY_2` primary and Groq backup; test and integration evidence report; configuration guide, provider switching and rollback instructions, telemetry format, deferred issues and Baseline Testing handover. |
| Acceptance evidence | Report distinguishes earlier guarded regressions from final-snapshot focused tests and states that complete post-change offline regression is not established. Latest focused suite: **110 passed**. Isolated live outcomes, T17 ledger **10/10 requests, 20,316/50,000 tokens**, and unreviewed groundedness are recorded. No new live request or paid spend was initiated by T18. Documentation links and whitespace were checked locally. |
| Open gates | Gemini Phase 12 semantic groundedness lacks a reviewable successful response; Groq output needs human review; no Phase 12 backup is approved/enabled; production failover/live API or Telegram path has not been demonstrated; complete guarded offline regression on the final snapshot remains outstanding. Do not mark T17 or Phase 18 V1 `COMPLETE`. |
| Next step | Use the [handover](phase18_handover.md) and [test/integration report](phase18_test_and_integration_report.md) for Baseline Testing planning. Any further live requests need a new explicit budget. |

## 2026-11-25 (Asia/Saigon) - T17 Account Entitlement Evidence Recheck

| Item | Result |
| --- | --- |
| Task ID | T17 Free Tier entitlement verification |
| Budget Authorization | Existing operator approval retained: Gemini 2/10,000; OpenRouter 3/20,000; Groq 3/20,000; global 8/50,000; maximum paid spend USD $0. No additional budget approval requested. |
| Status | **BLOCKED before dispatch for all three providers.** |
| Evidence Checked | Inspected the harness contract/tests and searched local Phase 18/T17 evidence locations. The only T17 artifact is the prior blocked result. Other entitlement-shaped artifacts found under test output are explicitly synthetic fixtures and are not account evidence. No per-account Free Tier proof artifact exists at `data/interim/phase18_t17/free_tier_entitlements.json`. Local credential-variable presence does not identify/verify the associated provider account, project tier, exact-model entitlement or paid billing state. |
| Required Evidence Format | Each `FreeTierEvidence` entry must bind exact `provider`, `model`, hashed account reference, `tier=free`, `entitlement_verified=true`, `paid_billing_disabled=true`, provenance `source_ref`, a local proof `artifact_ref` and matching SHA-256, and UTC `verified_at`/`expires_at`. The referenced proof must be trustworthy, account-specific, current, and demonstrate exact model access under Free Tier with no paid fallback. The harness verifies structure, binding, expiry and digest; it cannot establish truth without genuine provider-account proof. |
| Provider Results | Gemini `gemini-3.5-flash-lite`: **BLOCKED**; OpenRouter `baidu/ernie-5.5-flash-preview:free`: **BLOCKED**; Groq `openai/gpt-oss-20b`: **BLOCKED**. Groq remains a candidate and is not classified as paid by default; its Free Tier entitlement is simply unverified. |
| Actual Counters | No API/model-list/inference requests made. Existing T17 artifact remains at **0 requests, 0 tokens, USD $0**, `attempt_count=0` for each route, no pending reservations. No provider calls were used to probe account entitlement. |
| Route State | Production routes remain disabled/pending with YAML cost class unknown. No route approval or configuration changes. `LLM_GATEWAY_ALLOW_PAID_MODELS=false`. |
| Next Step | Operator supplies genuine, redacted account-specific proof artifacts locally in the harness format. Until then keep all unverified candidates BLOCKED. T18 is not allowed. |

## 2026-11-25 (Asia/Saigon) - T17 Authorized Live Validation Attempt (Blocked at Free Tier Preflight)

| Item | Result |
| --- | --- |
| Task ID | T17 live validation preflight |
| Operator Authorization | Received for Gemini 2 requests/10,000 tokens, OpenRouter 3/20,000, Groq 3/20,000; global max 8/50,000; USD $0 maximum spend. Attempt timeout 25s, run deadline 120s and output max 2,048 were supplied to the harness. |
| Status | **BLOCKED before provider dispatch**. Operator budget approval does not satisfy the mandatory account Free Tier evidence gate. T18 is not allowed. |
| Candidate Preflight | All three route identities, models, task/schema mappings, endpoints, structured modes and output-token caps matched YAML. Credential variable presence was confirmed without reading or displaying values. `LLM_GATEWAY_ALLOW_PAID_MODELS=false`. YAML candidates remain disabled/pending and cost class unknown. |
| Entitlement Gate | Expected evidence file `data/interim/phase18_t17/free_tier_entitlements.json` does not exist. No trusted account-level Free Tier proof was available for Gemini, OpenRouter or Groq. All three candidates were therefore marked `BLOCKED`; no provider-specific request was sent. Groq was not classified as paid by default, but also lacked the required Free Tier proof. |
| Budget Evidence | Harness artifact `data/interim/phase18_t17/validation.json` records all three statuses as `blocked`, each with `attempt_count=0`; aggregate and per-provider totals are **0 requests / 0 tokens**, pending reservations 0, maximum cost USD $0. Artifact SHA-256: `d52ae0f924f3bf44715d99aa867f08de395b9c04259d8a56f280ce8d754041b1`. No budget ledger was created because no reservation/dispatch occurred. |
| Live Results | None. Model response identity, structured output, token usage, latency, error handling, catalog grounding and human review remain NOT RUN. No route approval or YAML change was made. |
| Next Step | Operator supplies valid, unexpired local Free Tier entitlement artifacts bound to each exact provider/model/account, then rerun preflight. Keep any provider without evidence BLOCKED. No T18. |

## 2026-11-25 (Asia/Saigon) - T17 Isolated Free Tier Validation Harness (Offline Only)

| Item | Result |
| --- | --- |
| Task ID | T17 harness implementation / offline validation |
| Status | **PASS for offline harness implementation. T17 live provider validation remains NOT RUN / BLOCKED. T18 is not allowed.** |
| Files Changed | `src/shopassist/llm_gateway/validation_harness.py`, `scripts/validate_phase18_providers.py`, `tests/test_phase18_validation_harness.py`, this execution log. |
| Implementation | Added an isolated exact-route candidate allowlist for the three selected routes, validating provider, endpoint, model, task/profile schema, structured-output mode and 2,048 max output tokens against YAML. Candidate routes must remain production-disabled/pending. The harness calls adapters directly only after all selected routes pass preflight; there is no Gateway failover, nested retry or route mutation. Live CLI requires `--live`, operator approval, zero-paid-spend approval, explicit aggregate request/token/zero-cost limits and an unexpired Free Tier evidence JSON whose local proof artifact is SHA-256 bound to provider/model/account reference. Credentials are checked for presence only. `LLM_GATEWAY_ALLOW_PAID_MODELS=false` is explicitly set for the harness and was verified false in local configuration. |
| Budget Safety | Persistent single-process-locked ledger enforces per-provider proposed request/token ceilings (Gemini 2/10,000; OpenRouter 3/20,000; Groq 3/20,000) plus total hard maximum 8 requests/50,000 tokens. Reservation is persisted before dispatch; request is counted at dispatch; reported usage settles the reservation and unknown usage retains the conservative reservation across restart. Maximum cost is hard-coded to USD $0; any provider-reported nonzero estimated cost fails the run. Output token cap, attempt timeout and run deadline cannot exceed 2,048, 25s and 120s. |
| Validation Scope | Query response is Pydantic-validated and reported model must exactly match. Recommendation response is Pydantic-validated against the existing Phase 12 generation schema, exact product ID and citation IDs are checked against a deterministic read-only sample from `data/processed/products.parquet`; the artifact records the dataset hash. Semantic groundedness remains explicitly flagged for human review. Unit tests use synthetic product/evidence and entitlement artifacts only; they are not live evidence. |
| Tests Executed | Focused offline harness tests: **26 passed**; Gateway config/registry/runtime/adapter integration tests also passed in the full regression. Full offline regression used the T00 harness with repository `.env` suppressed, credentials removed from the test process, external DNS/socket blocked, and live suites excluded. Python compile check and `git diff --check` passed. |
| Test Results | Full offline regression: **928 passed, 13 deselected, 1 baseline AsyncMock warning**, exit 0, 35.76s. External connection attempts: **0**. JUnit: `.deps/phase18-t17-harness-regression.xml`. CLI dry-run reported candidate metadata and confirmed no provider requests. |
| Remaining Preflight | Local API-key variable presence was confirmed without displaying values, but account-level Free Tier eligibility and the proof artifacts are still unverified/not supplied. The proposed budgets have not been confirmed as live authorization. No live request was made. Routes remain disabled/pending and YAML pricing remains unknown. |
| Next Task Allowed | **T17 live dispatch only after the operator explicitly approves the exact budgets and verifies each selected account's Free Tier entitlement with local evidence artifacts. T18 is not allowed.** |

## 2026-11-25 (Asia/Saigon) - T17 Live Provider Validation Authorization Preflight

| Item | Result |
| --- | --- |
| Task ID | T17 preflight (live validation NOT RUN) |
| Status | **BLOCKED before dispatch** at the time of this entry. The later Free Tier only policy correction supersedes the earlier paid-route assumption. No live provider or database request was made. |
| Selected Scope | `query_gemini` maps to Gemini `gemini-3.5-flash-lite`, `query_understanding`, `phase8.query.v1`; `recommendation_openrouter` maps to OpenRouter `baidu/ernie-5.5-flash-preview:free`, `recommendation_generation`, `phase12.recommendation.v1`; `recommendation_groq` maps to Groq `openai/gpt-oss-20b`, same recommendation task/schema. Exact endpoints from YAML: Google Generative Language API, OpenRouter `/api/v1`, and Groq `/openai/v1`. Structured modes: Gemini schema and JSON Schema for OpenRouter/Groq. Configured max output is 2,048 tokens per request for all three. |
| Proposed Budgets (Not Yet Approved) | Gemini: 2 requests / 10,000 tokens / 25 s per attempt; OpenRouter: 3 / 20,000 / 25 s; Groq: 3 / 20,000 / 25 s. Aggregate proposal: 8 requests / 50,000 tokens; 2,048 max output tokens/request; 120 s run deadline. These figures were proposals only and were superseded by the later Free Tier only, zero-paid-spend correction. Groq remains a candidate subject to verified account Free Tier entitlement; do not infer paid eligibility or authorize paid requests from the published token price. No retries beyond approved limits. |
| Local Credential Check | Presence-only inspection found `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, and `GROQ_API_KEY` configured locally in `.env`. Values were not read out or printed. Account-level free-tier/entitlement status is not visible from the local environment and remains unverified. |
| Route/Policy Check | YAML identities and schemas match the selected scope. All three routes remain `enabled=false`, approval `pending`, and `cost.class=unknown`. At the time of this preflight entry, the T17 harness had not yet been implemented; the offline harness implementation is recorded in the newer T17 entry above. Do not route these pending candidates through production Gateway. |
| Public Pricing/Capability Evidence | Google lists Gemini 3.5 Flash-Lite with a free tier and paid rates; account entitlement must still be verified in the operator's account: [Google Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing). OpenRouter lists the exact ERNIE free model at $0 and describes structured output support; account availability/rate limits still require account verification: [OpenRouter model page](https://openrouter.ai/baidu/ernie-5.5-flash-preview:free/). Groq lists GPT-OSS 20B at $0.075/M input and $0.30/M output and JSON Schema capability: [Groq supported models and pricing](https://console.groq.com/docs/models), [Groq model page](https://console.groq.com/docs/model/openai/gpt-oss-20b). Published provider pricing is not proof of account entitlement or a substitute for Gateway cost evidence. |
| Blocking Requirements | Operator must confirm exact request/token ceilings and verify Free Tier eligibility for each selected account, including Groq. Paid usage is not authorized. A controlled T17 harness must enforce per-provider and aggregate request/token/cost ceilings before dispatch. Cost/entitlement remains unknown for runtime route eligibility. |
| Safety | No credentials were exposed. No route was enabled/approved. No live API calls were attempted. No production eligibility or pricing evidence was fabricated. |
| Next Step | Remain at preflight until operator confirmation and controlled harness readiness. T17 remains **NOT RUN**; T18 is not allowed. |

## 2026-11-25 (Asia/Saigon) - T16 Full Offline Gateway & Application Regression

| Item | Result |
| --- | --- |
| Task ID | T16 |
| Status | **PASS** for offline acceptance. No live provider validation or activation was performed. |
| Source Reviewed | T16 acceptance in `phase18_architecture.md`, Gateway contract, T15-FIX implementation and existing Gateway/provider/lifecycle/API/orchestrator tests. |
| Implementation Summary | No source changes were required. The full offline suite exercises primary success; 429/503/timeout and invalid JSON/schema failover; both routes failing; authentication and missing-credential paths; missing/known usage; cooldown/half-open/quota; one/two-attempt limits; paid-route denial; cancellation/deadlines; and Phase 8 fail-closed, Phase 12 deterministic fallback and FastAPI/API compatibility. |
| Tests Executed | Full regression used the T00 harness: repository `.env` suppressed, provider/database credentials removed, Hugging Face offline flags set, external DNS and socket connections blocked, and live-marked/provider-real suites excluded. |
| Test Results | **902 passed, 13 deselected, 1 baseline AsyncMock warning**, exit 0, 54.20s. External connection attempts: **0**. JUnit: `.deps/phase18-t16-regression.xml`. |
| Compatibility Impact | No public API, schema, prompt, dataset, retrieval, reranking or business behavior changes. Experimental and production provider routes remain disabled/pending pending route evidence. |
| Next Task Allowed | **T17 only after explicit authorization and approved provider/model, credential scope, request/token/cost ceilings and deadline.** No T17 live request was made. |

## 2026-11-25 (Asia/Saigon) - T15-FIX Experimental Profiles, Gateway Integration & Persistent Budget

| Item | Result |
| --- | --- |
| Task ID | T15-FIX |
| Status | **PASS** for offline acceptance. All experimental provider routes remain disabled/pending; this does not claim live route evidence or authorize provider activation. |
| Files Changed | `src/shopassist/llm_gateway/schema_ids.py`, `src/shopassist/llm_gateway/config.py`, `src/shopassist/llm_gateway/schemas.py`, `src/shopassist/llm_gateway/registry.py`, `src/shopassist/llm_gateway/experiment_factory.py`, `src/shopassist/llm_gateway/errors.py`, `src/shopassist/llm_gateway/gateway.py`, `src/shopassist/api/main.py`, `config/llm_gateway.yaml`, `src/shopassist/llm/schema_variants.py`, `src/shopassist/llm/experiments/runner.py`, `src/shopassist/llm/experiments/phase82/candidates.py`, `src/shopassist/llm/experiments/phase82/runner.py`, `src/shopassist/llm/experiments/phase82/persistent_budget.py`, `scripts/run_phase8_experiments.py`, `scripts/run_phase8_2_experiments.py`, `tests/test_llm_gateway_registry.py`, `tests/test_phase18_experiment_cli_safety.py`, `tests/test_phase18_experiment_budget.py`, `tests/test_phase18_experiment_integration.py`, `tests/test_phase18_lifecycle.py`. |
| Implementation Summary | Added distinct experimental schema IDs bound to exact Pydantic response classes while preserving production `phase8.query.v1`. Added 20 Phase 8.1/8.2 YAML experiment profiles/routes with per-profile schema/model/temperature; every experimental route remains `enabled=false`, approval pending. Both experiment runners use the shared Gateway and YAML profile exclusively when Gateway is enabled; rollback to legacy provider is retained only when Gateway is disabled and explicit `--live` is supplied. Cache identity includes task/profile/schema ID and schema fingerprint, prompts, provider/endpoint/model/route options, and candidate version; only successful validated outputs are cached with actual route provenance. Cache hits do not enter current-run outbound usage. Added crash-safe JSON budget ledger reserving before each provider dispatch, counting requests at dispatch, settling every attempt from reported usage or conservatively retaining estimate when unknown, retaining dispatched reservations across restart, and blocking further dispatch when ceilings are reached. No blocking `time.sleep` was introduced in async Gateway flows. Lifecycle test adapter mocks now accept the credential callback constructor contract. |
| Evidence & Safety | Tests use synthetic schemas, artifacts and mocked adapters solely to validate control flow; they do not establish provider/model compatibility. No credentials, paid models, live LLM/database calls, or external network access were used. Gateway-enabled routes with no eligible YAML route fail closed. Production Phase 8 behavior/schema and public API, prompts, datasets, retrieval and reranking remain unchanged. |
| Tests Executed | Focused integration/budget/CLI/config/registry/schema/Gateway/Phase 8.1+8.2 suite: **124 passed**. Lifecycle focused after correcting inert adapter factory signature: **4 passed**. Full offline regression repeated using T00 harness, repository `.env` suppressed, relevant credentials removed, DNS/socket external access blocked, and live tests excluded. `git diff --check` clean. |
| Test Results | Full offline regression: **902 passed, 13 deselected, 1 baseline AsyncMock warning**, exit 0. External connection attempts: **0**. JUnit: `.deps/phase18-t15fix-regression.xml`. |
| Remaining Unverified Routes | All Phase 8.1/8.2 experiment profiles and provider routes remain disabled/pending. Provider endpoint/model/schema compatibility, account entitlement and pricing require the evidence/authorization gate in T17. No route was auto-approved or enabled. |
| Compatibility Impact | No public API contract, production schema, prompt, dataset, retrieval/reranking or recommendation business behavior changes. Gateway-disabled rollback remains explicit-live only; Gateway-enabled experiments cannot use legacy environment/model selection. |
| Next Task Allowed | **T16 may proceed in a separate turn. T16 was not started in this turn.** |

## 2026-11-25 (Asia/Saigon) - T15 Phase 8 Experiment Runner Safety & Gateway Profile Integration

| Item | Result |
| --- | --- |
| Task ID | T15 |
| Status | **FAIL / incomplete**. Phase 8.1 now defaults to dry-run; Phase 8.1 and 8.2 refuse to call legacy Gemini directly when Gateway is enabled. Full experiment execution through YAML Gateway profiles, profile-aware cache identity and shared request/token budget accounting are not yet implemented. |
| Files Changed | `scripts/run_phase8_experiments.py`, `scripts/run_phase8_2_experiments.py`, `tests/test_phase18_experiment_cli_safety.py`, this log. |
| Implementation Summary | Added explicit `--live` gate to Phase 8.1; no live client/settings/cache is initialized by the default dry-run. Added fail-closed guards before provider creation in both experiment runners when `LLM_GATEWAY_ENABLED=true`, preventing a legacy environment/model path from bypassing YAML. Existing Phase 8.2 request/token ceilings and cache fingerprint continue to apply in the legacy rollback path. Config, schema evidence validation, endpoint allowlist, secret redaction and bounded telemetry behavior were verified through existing tests. |
| Tests Executed | Focused Phase 8 experiment safety, Phase 8.2 runner, Gateway config, telemetry and registry tests. Full offline regression used the T00 harness with repo dotenv/credentials removed, external DNS/socket blocked, and live-marked tests excluded. |
| Test Results | Focused: **69 passed**, exit 0. Offline regression: **890 passed, 13 deselected, 1 warning**, exit 0. AsyncMock warning at `test_api_orchestrator.py::test_deterministic_fallback_flow` is baseline. External connection attempts: **0**. JUnit: `.deps/phase18-t15-focused.xml`, `.deps/phase18-t15-regression.xml`. |
| Unresolved Acceptance | `GatewayRequest` / registry currently constrain task profiles to the production `phase8.query.v1` contract; Phase 8.2 candidates use `RefinedQueryUnderstandingOutput`/`RequiredV2`. There is no approved isolated experiment profile or schema binding for these variants, and persistent experiment budget callbacks are not connected to Gateway dispatch/usage events. Adding such a profile/schema/evidence policy must preserve the production Phase 8 schema and must not approve or enable provider routes without evidence. |
| Next Task Allowed | **T16 is not allowed** until T15 acceptance is met. |

## 2026-11-25 (Asia/Saigon) - T14 CLI Live Gates & Phase 14 Evaluation

| Item | Result |
| --- | --- |
| Task ID | T14 |
| Status | **PASS** for explicit live authorization and Phase 14 Gateway/demo/failure handling. Phase 12 CLI is fail-closed while Gateway is enabled; complete Phase 12 experiment runner migration remains in T15. |
| Files Changed | `scripts/evaluate_phase12.py`, `scripts/test_gemini_connection.py`, `scripts/run_phase14_evaluation.py`, `src/shopassist/evaluation/phase14_judge.py`, `tests/test_phase18_cli_safety.py`, execution log. |
| Implementation Summary | Phase 12 runner now exits with `LIVE_SKIPPED` before loading dataset or constructing a provider unless `--live` is passed. If Gateway is enabled, it rejects legacy CLI provider/model path before dispatch; YAML is not bypassed. Gemini model-discovery/smoke diagnostics require `--live`. Phase 14 gained an async Gateway bridge using `phase14.judge.v1`, preserves rubric/result fields and actual route provider/model attribution, and has a pre-dispatch eligibility check: pending/disabled or credential-missing routes become `LIVE_SKIPPED` with offline demonstration. In rollback mode, client initialization failure is safely redacted and becomes demo/skip. Generation failure after live initialization writes only `LIVE_FAILURE` diagnostics and returns failure; it does not create a demo judge artifact. Run diagnostics are included in the Phase 14 manifest. |
| Tests Executed | Focused `tests/test_phase18_cli_safety.py` and `tests/test_phase14_evaluation.py`; tests use synthetic output and mocks. Full offline regression used the T00 harness with repo dotenv/credentials removed, external DNS/socket blocked, and live-marked tests excluded. |
| Test Results | Focused: **17 passed**, exit 0. Offline regression: **887 passed, 13 deselected, 1 warning**, exit 0. The AsyncMock warning in `test_api_orchestrator.py::test_deterministic_fallback_flow` is baseline. External connection attempts: **0**. JUnit: `.deps/phase18-t14-focused.xml`, `.deps/phase18-t14-regression.xml`. |
| Compatibility Impact | Existing Phase 14 rubric and `LLMJudgeResult` schema unchanged. Legacy CLI provider/model flags remain available only in explicit live rollback mode with Gateway disabled. New diagnostics are an additional manifest artifact. No datasets, prompts, retrieval, reranking, or recommendation behavior changed. |
| Remaining Work | Phase 12 CLI's live evaluation path still uses the legacy provider only when Gateway is disabled. Gateway-enabled experiment profiles, cache identity and request/token budget integration remain for T15. |
| Next Task Allowed | **T15** in a separate turn. |

## 2026-11-25 (Asia/Saigon) ? T13 FastAPI Lifecycle & Dependency Injection

| Item | Result |
| --- | --- |
| Task ID | T13 |
| Status | **PASS**. One Gateway is initialized after configuration validation, shared by Phase 8 and 12, and cleaned up by one shutdown owner, including partial startup failure. |
| Files Changed | `src/shopassist/api/main.py`, `src/shopassist/api/routes/health.py`, `src/shopassist/api/routes/recommendations.py`, `src/shopassist/api/services/orchestrator.py`, `src/shopassist/llm_gateway/gateway.py`, `src/shopassist/llm_gateway/registry.py`, `tests/test_phase18_lifecycle.py`, `tests/test_api_integration_mocked.py`, `tests/test_api_orchestrator.py`, this log. |
| Implementation Summary | FastAPI lifespan validates Gateway config/registry before allocating database/adapters; creates adapters and local telemetry, injects the same Gateway into `QueryUnderstandingEngine` and `RecommendationService`, and cleans up owned resources in `finally`. Gateway exposes configured primary routes and local-only readiness snapshots. Health preserves component keys/status semantics, performs no provider probes, and retains legacy indicators when Gateway is disabled. The recommendation route creates a parent monotonic deadline, retains its outer timeout, and maps Gateway parent-deadline errors to HTTP 504. The orchestrator generates internal correlation/task IDs, passes the same request ID/deadline to Phase 8 and 12 with distinct task IDs, and avoids raw exception logging. The composition root registers the Phase 12 decoder. |
| Tests Executed | Lifecycle tests use inert mocked adapters and mocked DB engine; API and Telegram integration tests are mocked. Verified health readiness, parent deadline forwarding, 504 mapping, shared instance/cleanup, partial startup cleanup, disabled rollback and invalid config startup. Offline regression used the T00 harness with repo dotenv/provider/DB credentials removed, external DNS/socket blocked, and live tests excluded per procedure. |
| Test Results | Focused lifecycle/API/orchestrator/Telegram: **49 passed, 1 warning**, exit 0. Offline regression: **881 passed, 13 deselected, 1 warning**, exit 0. The AsyncMock warning at `test_api_orchestrator.py::test_deterministic_fallback_flow` is baseline. External connection attempts: **0**. JUnit: `.deps/phase18-t13-focused-integration.xml`, `.deps/phase18-t13-regression.xml`. `git diff --check` clean. |
| Compatibility Impact | No changes to public API schemas/component keys, retrieval/reranking, prompts or Telegram behavior; Gateway disabled retains legacy injection. The Gateway health label reports configured YAML primary and does not prove provider health. Production routes remain disabled/pending; no provider dispatch or live evidence was used. |
| Next Task Allowed | **T14** in a separate turn. |

# ShopAssist Phase 18 V1 — Execution log

**Current status** | T00-T16 **PASS**. T17 isolated harness implementation is PASS offline; all three live candidates remain BLOCKED before dispatch because genuine account-specific Free Tier entitlement artifacts are absent. T18 is not allowed.

## 2026-11-25 (Asia/Saigon) — T12 Phase 8 QueryUnderstanding Gateway Integration

| Mục | Kết quả |
| --- | --- |
| Task ID | T12 |
| Status | **PASS**. QueryUnderstandingEngine hỗ trợ Gateway, giữ schema v1/business normalization và fail closed khi Gateway không cung cấp output hợp lệ. |
| Source Files Reviewed | T12 trong plan đính kèm, Gateway request/response/error/deadline contract, Phase 8 engine/prompt/schema/normalization/API short-circuit và Query Understanding/reliability tests. Canonical plan path chưa có trong checkout. |
| Files Changed | `src/shopassist/llm/query_understanding.py`, `tests/test_query_understanding.py` và execution log này. |
| Implementation Summary | Thêm optional Gateway injection và internal request/task ID cùng parent deadline; gửi `GatewayRequest[QueryUnderstandingOutput]` với task/schema IDs đã chốt, system instruction và user prompt Phase 8 hiện tại. Output thành công tiếp tục qua `validate_and_normalize_output` không đổi; model/raw response/latency/usage ánh xạ từ route thắng. `GatewayError` ngoài parent deadline trả invalid result, constraints rỗng, `needs_clarification=False` và diagnostic chỉ chứa category an toàn, để API short-circuit thành `INVALID_INPUT`. Parent deadline và cancellation propagate; legacy Gemini path/error behavior giữ nguyên nếu Gateway không inject. |
| Tests Executed | Focused Query Understanding và Phase 8.2 reliability tests, sau đó offline regression dùng harness T00, dotenv/credentials bị loại, external DNS/socket bị chặn và live tests bị bỏ qua. |
| Test Results | Focused **53 passed**, exit 0. Offline regression **875 passed, 13 deselected, 1 warning**, exit 0. External connection attempts **0**. JUnit: `.deps/phase18-t12-focused.xml` và `.deps/phase18-t12-regression.xml`. Warning AsyncMock ở API orchestrator trùng baseline. |
| Compatibility Impact | Không đổi `QueryUnderstandingOutput` schema v1, prompt, category/brand/currency normalization, constraints, public API schema hoặc legacy fallback path. Provider failure không sinh clarification semantics/constraints giả. |
| Known Issues | T13 sẽ inject Gateway dùng chung và truyền correlation ID/parent deadline từ orchestrator; khi Gateway mode được bật, provider thật vẫn bị route evidence/approval gates khóa tới T17. |
| Next Task Allowed | **T13** ở lượt riêng. |

## 2026-11-25 (Asia/Saigon) — T11 Phase 12 RecommendationService Gateway Integration

| Mục | Kết quả |
| --- | --- |
| Task ID | T11 |
| Status | **PASS**. RecommendationService hỗ trợ Gateway route đã validate và giữ deterministic catalog fallback. |
| Source Files Reviewed | T11 trong plan đính kèm, Phase 12 service/context/prompts/provider/schema/groundedness/fallback, Gateway request/response/error contracts, orchestrator call boundary và Recommendation regression tests. Canonical plan path chưa có trong checkout. |
| Files Changed | `src/shopassist/recommendation/core.py`, `src/shopassist/recommendation/provider.py`, `tests/test_recommendation.py` và execution log này. |
| Implementation Summary | Thêm injection Gateway vào `RecommendationService`; khi Gateway có mặt, không khởi tạo/gọi legacy provider. Gửi `GatewayRequest[LLMRecommendationPayload]` với task/schema/profile, generated internal IDs mặc định và optional request/task/parent deadline từ composition caller. Giữ nguyên candidate Top-K=3 setting, EvidenceContextBuilder, system/user prompts và GroundednessValidator. Successful result chuyển numeric usage theo quy ước legacy và gán model_name từ route thắng; log actual provider/model nội bộ. Gateway failure không phải parent deadline dùng deterministic catalog fallback với reason cố định, không ghi model provider giả. Parent deadline và cancellation propagate. Thêm decoder Phase 12 dùng parser hiện có để giữ normalization fence, recommendations alias và string claims; composition root T13 cần đăng ký decoder theo schema ID. Legacy provider path vẫn chạy khi Gateway không được inject. |
| Tests Executed | Focused Phase 12 recommendation suite; sau đó offline regression dùng harness T00, workspace dotenv và credentials bị loại khỏi process, external DNS/socket bị chặn và live tests bị bỏ qua. |
| Test Results | Focused **28 passed**, exit 0. Offline regression **871 passed, 13 deselected, 1 warning**, exit 0. External connection attempts **0**. JUnit: `.deps/phase18-t11-focused.xml` và `.deps/phase18-t11-regression.xml`. Cảnh báo AsyncMock trong API orchestrator trùng baseline. |
| Compatibility Impact | Không thay đổi public API schemas, prompt text, retrieval/reranking, evidence, groundedness, product IDs/citations hoặc deterministic fallback. Thêm optional internal service kwargs; orchestrator sẽ truyền cùng request ID và parent deadline ở T13. Gateway usage unknown được ánh xạ về numeric zero ở public Phase 12 contract; attempt-level usage đầy đủ vẫn nằm trong telemetry. |
| Known Issues | T13 cần inject shared Gateway và đăng ký `decode_recommendation_gateway_output` cho `phase12.recommendation.v1`. Production routes vẫn pending/disabled nên chưa có provider runtime dispatch. |
| Next Task Allowed | **T12** ở lượt riêng. |

## 2026-11-25 (Asia/Saigon) — T10 Automatic Failover Engine

| Mục | Kết quả |
| --- | --- |
| Task ID | T10 |
| Status | **PASS** cho Gateway route traversal, dispatch, validation và automatic failover engine. |
| Source Files Reviewed | Phase 18 architecture, Gateway contract (request/response, routing/deadline/failover, health/quota, errors, telemetry), T10 trong plan đính kèm, registry, adapters, retry policy, health/quota managers, telemetry sink và route configuration. Canonical `docs/phase18_implementation_plan.md` chưa có trong checkout. |
| Files Changed | `src/shopassist/llm_gateway/gateway.py`, `router.py`, `failover.py`, `policies.py`, `tests/test_llm_gateway_gateway.py` và execution log này. |
| Implementation Summary | Gateway duyệt route theo YAML order; kiểm static eligibility, adapter/credential presence, prepare, profile/route health và quota; rồi dispatch một lần tại hook. Dùng budget tối đa hai attempt và một lần mỗi route. Adapter output được decode/validate trong effective deadline; output/model mismatch được chuẩn hóa; usage vẫn gắn với attempt lỗi. Chỉ lỗi retryable được failover; deadline và cancellation dừng ngay. Finalized attempt/task được gửi tới bounded telemetry; response/error giữ actual provider/model, skip attribution và ordered records. Cleanup đóng mỗi adapter object duy nhất. Điều chỉnh `run_attempt` để timeout giới hạn bởi task/parent deadline không bị hiểu nhầm là timeout attempt khi event loop wake-up sớm. |
| Tests Executed | Synthetic YAML/evidence fixtures (ghi rõ chỉ kiểm tra logic, không phải provider evidence), mocked adapters và fake/injected health/quota/telemetry. Focused Gateway, toàn bộ Gateway, Recommendation, Query Understanding và API orchestrator tests; sau đó full offline regression bằng harness T00, dotenv/credentials bị loại, external DNS/socket bị chặn và live tests bị bỏ qua. |
| Test Results | Focused **250 passed, 1 baseline warning**, exit 0. Offline regression **866 passed, 13 deselected, 1 baseline warning**, exit 0. External connection attempts **0**. JUnit: `.deps/phase18-t10-focused.xml` và `.deps/phase18-t10-regression.xml`. Warning AsyncMock tại `test_api_orchestrator.py::test_deterministic_fallback_flow` đã có từ baseline. |
| Compatibility Impact | Gateway chỉ thêm API nội bộ; Phase 12/8 services và public API chưa được chuyển ở T11–T13. Prompts, retrieval, reranking, grounding và business fallback tiếp tục nằm ở caller. YAML production routes hiện vẫn disabled/pending nên engine fail closed và không gửi provider request khi không có route được duyệt. |
| Known Issues | Integration vào RecommendationService, QueryUnderstandingEngine và FastAPI lifecycle là T11–T13. Budget estimator chỉ được inject từ tokenizer/cost bound đáng tin; thiếu upper bound khi hard token/cost cap áp dụng sẽ deny route theo contract. Provider live/model compatibility vẫn chưa kiểm chứng tới T17. |
| Next Task Allowed | **T11** ở lượt riêng. |

## 2026-11-25 (Asia/Saigon) — T09 Provider Health & Quota Manager

| Mục | Kết quả |
| --- | --- |
| Task ID | T09 |
| Status | **PASS** cho health/cooldown và local quota admission primitives. |
| Source Files Reviewed | Gateway contract (health scopes, cooldown, half-open, concurrent generations, reservation/settlement), T09 trong plan đính kèm, registry route limits, normalized error categories và telemetry records. Canonical plan path chưa có trong checkout. |
| Files Changed | `src/shopassist/llm_gateway/health.py`, `src/shopassist/llm_gateway/quota.py`, `tests/test_llm_gateway_health_quota.py` và execution log này. |
| Implementation Summary | Health state chạy theo provider profile và route/schema, dùng monotonic cooldown, exponential backoff capped cho default, Retry-After delta/HTTP-date chuyển một lần sang monotonic, một atomic half-open probe, generation guard cho success cũ, recovery khi probe thành công, profile block cho authentication và route-level block cho incompatibility. Lỗi invalid output cooldown riêng route/schema. Quota manager reserve request rolling-60s, in-flight slot, daily token/cost upper bounds atomically; thiếu estimate khi hard cap có hiệu lực bị deny. Commit rate request tại dispatch, settle usage đúng một lần, unknown usage giữ reservation estimate đến reset ngày UTC; request rolling window tồn tại qua UTC midnight. State chỉ local theo worker, không claim vendor quota và không dùng raw credentials làm key. |
| Tests Executed | Focused health/quota, telemetry, policy và registry tests với fake clocks/thread concurrency; sau đó offline regression dùng harness T00 với DNS/socket external guard và không có live tests. |
| Test Results | Focused **58 passed**, exit 0. Offline regression **846 passed, 13 deselected, 1 warning**, exit 0. External connection attempts **0**. JUnit: `.deps/phase18-t09-focused.xml` và `.deps/phase18-t09-regression.xml`. Warning AsyncMock trùng baseline. |
| Compatibility Impact | T09 cung cấp manager APIs nội bộ; T10 sẽ nối route traversal, health/quota reservations và attempt settlement. Không thay đổi legacy providers, API contracts hay task fallback. |
| Known Issues | Accounting là per-process/worker như contract; rollout nhiều worker cần chia quota từng worker trong tổng ngân sách. Health/quota readiness chỉ đọc local snapshot và không probe provider. |
| Next Task Allowed | **T10** ở lượt riêng. |

## 2026-11-25 (Asia/Saigon) — T08 Centralized Telemetry

| Mục | Kết quả |
| --- | --- |
| Task ID | T08 |
| Status | **PASS** cho telemetry contracts và sink local. T10 sẽ nối vòng đời Gateway dispatch/finalization vào API sink này. |
| Source Files Reviewed | Gateway contract (telemetry/usage invariants), T08 trong plan đính kèm, attempt/usage/history schemas, config settings và adapter interface. Canonical `docs/phase18_implementation_plan.md` chưa có trong checkout. |
| Files Changed | `src/shopassist/llm_gateway/telemetry.py`, `tests/test_llm_gateway_telemetry.py` và execution log này. |
| Implementation Summary | Thêm task summary có actual winning route/provider/model, skip reasons, failover và per-attempt usage aggregation. Mỗi token/cost total là null nếu dữ liệu của bất kỳ attempt nào không biết; 0 attempts có tổng 0. Sink chỉ nhận typed allowlisted records, dùng queue bounded 1,000, JSONL local rotating (1 MiB/file, tối đa 3 files), bỏ record trùng `(task_id, attempt_number)`, và đếm drop/write errors mà không truyền lỗi telemetry sang business flow. Prompt/response, credentials, headers và exception payload không được nhận hoặc ghi. |
| Tests Executed | Focused telemetry, schemas và policies tests; offline regression cuối với harness T00, workspace dotenv và credentials bị loại khỏi process, DNS/socket bên ngoài bị chặn, live tests bị bỏ qua. |
| Test Results | Focused **60 passed**, exit 0. Offline regression **832 passed, 13 deselected, 1 warning**, exit 0. External connection attempts **0**. JUnit: `.deps/phase18-t08-focused.xml` và `.deps/phase18-t08-regression.xml`. Cảnh báo AsyncMock trùng baseline tại `test_api_orchestrator.py::test_deterministic_fallback_flow`. |
| Compatibility Impact | Chỉ thêm API nội bộ telemetry; chưa nối vào application runtime vì Gateway engine được triển khai tại T10. Không thay đổi API công khai, provider requests hay business behavior. |
| Known Issues | Attempt records phải được Gateway T10 phát đúng một lần khi finalize; telemetry file I/O hiện đồng bộ trong writer task nhưng payload và queue đều bounded. Provider live behavior chưa được kiểm chứng và tiếp tục bị khóa tới T17. |
| Next Task Allowed | **T09** ở lượt riêng. |

## 2026-11-25 (Asia/Saigon) — T07 Unified Retry & Deadline Policy

| Mục | Kết quả |
| --- | --- |
| Task ID | T07 |
| Status | **PASS**. Policy giới hạn attempt/deadline đã được triển khai và kiểm thử offline. |
| Source Files Reviewed | Phase 18 architecture, Gateway contract (routing/deadline/failover và taxonomy), T07 trong plan đính kèm, cấu hình Gateway, schema/error contracts và adapter interface. Canonical `docs/phase18_implementation_plan.md` không có trong checkout; dùng plan đính kèm đã dùng ở T01. |
| Files Changed | `src/shopassist/llm_gateway/policies.py`, `tests/test_llm_gateway_policies.py` và execution log này. |
| Implementation Summary | Tạo policy theo task với monotonic effective deadline `min(task, parent)`, timeout mỗi attempt `min(configured attempt timeout, remaining deadline)`, giới hạn dispatch theo task, route duy nhất mỗi task, kiểm deadline ngay trước dispatch, và failover eligibility theo category. Timeout một attempt được chuẩn hóa thành `ATTEMPT_TIMEOUT`; hết task/parent budget thành `DEADLINE_EXCEEDED`; cancellation của caller tiếp tục propagate nguyên dạng. Policy không tự dispatch/retry adapter; một outbound call vẫn tương ứng một attempt. |
| Tests Executed | Focused policy, schema và provider adapter tests; sau đó offline regression dùng cùng harness T00, bỏ workspace dotenv, không có DSN/API keys trong process, chặn DNS/socket ra ngoài và bỏ qua live tests. |
| Test Results | Focused **96 passed**, exit 0. Offline regression **822 passed, 13 deselected, 1 warning**, exit 0. External connection attempts **0**. JUnit: `.deps/phase18-t07-focused.xml` và `.deps/phase18-t07-regression.xml`. Warning AsyncMock ở `test_api_orchestrator.py::test_deterministic_fallback_flow` trùng cảnh báo baseline. `git diff --check` **PASS**. |
| Compatibility Impact | Chưa có execution engine trong T07; policy cung cấp API nội bộ cho Gateway T10, không sửa adapter/business flow hoặc public contracts. Routes hiện tại vẫn disabled/pending; không gọi provider. |
| Known Issues | Admission/health/quota reservation và attempt finalization thuộc T09/T10; T07 chỉ chặn attempt count/deadline theo policy. Live provider behavior chưa kiểm chứng và tiếp tục bị khóa tới T17. |
| Next Task Allowed | **T08** ở lượt riêng. |

## 2026-11-20 (Asia/Saigon) — T00 Repository Audit & Preflight

| Mục | Kết quả |
| --- | --- |
| Task ID | T00 |
| Status | **FAIL** trong lượt audit ban đầu, được xử lý ở T00-FIX bên dưới. |
| Source Files Reviewed | README, development status, kế hoạch V1 đính kèm, `.env.example`, `pyproject.toml`, Phase 8/Gemini, Phase 12/OpenRouter/Groq, các script và judge liên quan, FastAPI lifecycle/orchestrator/health, Telegram client, DB masking và test gates. [Inventory](phase18_preimplementation_audit.md) |
| Files Changed | [Preimplementation audit](phase18_preimplementation_audit.md) và execution log này. |
| Implementation Summary | Audit `main` tại `c740d50de1976e8aafa371000644ae227f453cf0`, lập inventory, mô tả retry/error handling và xác minh legacy config bằng fixture giả. Dùng bản kế hoạch đính kèm vì đường dẫn plan chưa có trong repo. |
| Tests Executed | Hai lượt regression offline cùng selection và một smoke test dotenv. Chạy đối chứng regression với DSN giả sau khi baseline tái hiện lỗi. JUnit lưu ở `.deps/phase18-t00-regression.xml` và `.deps/phase18-t00-configured-regression.xml`. |
| Test Results | Baseline không DSN **672 passed, 1 failed, 13 deselected, 1 warning**. Đối chứng DSN giả **673 passed, 13 deselected, 1 warning**. Smoke dotenv **PASS**. API/Telegram **157 passed**. Harness ghi **0 lần thử kết nối bên ngoài** ở hai lượt regression. Provider-backed và Supabase live **NOT RUN**. |
| Compatibility Impact | Thay đổi trong workspace chỉ thuộc tài liệu audit và execution log. Đã kiểm tra legacy dotenv; Gateway loader và rollback chờ các task tương ứng. |
| Known Issues | `test_check_connection_failure_handling` lộ project ref giả trong lỗi/log khi thiếu DSN. Cảnh báo `AsyncMock` đã biết. `pip check` báo 5 xung đột sẵn có. [Chi tiết](phase18_preimplementation_audit.md) |
| Next Task Allowed | T00-FIX để xử lý lỗi baseline và chạy lại regression. |

## 2026-11-20 (Asia/Saigon) — T00-FIX

| Mục | Kết quả |
| --- | --- |
| Task ID | T00-FIX |
| Status | **PASS**. T00 đạt acceptance gate. |
| Source Files Reviewed | DB connection/engine factory, DSN settings, provisioning tests và callers của engine factory. |
| Files Changed | [DB connection](../src/shopassist/db/connection.py), [provisioning tests](../tests/test_database_provisioning.py), [preimplementation audit](phase18_preimplementation_audit.md) và execution log này. |
| Implementation Summary | Dùng thông báo an toàn cố định khi tạo engine, thực hiện connection check hoặc đóng engine tạm thất bại. Bổ sung coverage cho thiếu DSN, có DSN, port sai, password/project ref trong driver exception và captured logs. |
| Tests Executed | Focused provisioning tests, sau đó regression với cùng selection và network guard T00. Tiến trình pytest chạy thiếu DSN. Các unit test có cấu hình DSN tự cung cấp fixture với engine được mock. |
| Test Results | Focused **19 passed, 1 deselected**, exit 0. Regression **679 passed, 13 deselected, 1 warning**, exit 0. API/Telegram **157 passed**. **0 lần thử kết nối bên ngoài** ở cả hai lượt. JUnit ở `.deps/phase18-t00-fix-focused.xml` và `.deps/phase18-t00-fix-regression.xml`. |
| Compatibility Impact | Giữ `ValueError` khi thiếu DSN, `RuntimeError` cho connection check thất bại và các tham số tạo engine. Lỗi khởi tạo từ driver được quy về `RuntimeError` với nội dung an toàn. |
| Known Issues | Cảnh báo `AsyncMock` đã có trong baseline. Live database và provider validation ở trạng thái **NOT RUN**. |
| Next Task Allowed | **T01** ở lượt riêng. |

## 2026-11-20 (Asia/Saigon) — T01 Gateway Architecture & Contracts

| Mục | Kết quả |
| --- | --- |
| Task ID | T01 |
| Status | **PASS** cho đặc tả. T00 và T00-FIX đạt điều kiện đầu vào. |
| Source Files Reviewed | T00 audit và log, kế hoạch V1 đính kèm, cấu hình ENV được kiểm với danh sách field an toàn, GeminiClient, query engine, Phase 12 providers/service/validator, orchestrator, FastAPI routes/lifespan, Telegram Top-K và Phase 14 judge/CLI. Canonical plan path và YAML runtime chưa có trong checkout. |
| Files Changed | [Architecture](phase18_architecture.md), [Gateway contract](phase18_gateway_contract.md) và execution log này. |
| Implementation Summary | Khóa dependency boundaries, task/adapter/request/response/error contracts, routing YAML, retry/cooldown/quota/deadline/cancellation, per-attempt telemetry, migration/rollback và acceptance cho T02–T18. |
| Tests Executed | Kiểm tra Markdown links, headings, tables và checklist nội dung. Regression pytest với selection và network guard T00, workspace dotenv được bỏ qua và không cấu hình DSN cho tiến trình. |
| Test Results | Kiểm tra tài liệu **PASS**. Regression **679 passed, 13 deselected, 1 warning**, exit 0, 23.09s. API/Telegram **157 passed**. **0 lần thử kết nối bên ngoài**. JUnit ở `.deps/phase18-t01-regression.xml`. Các test Gateway cụ thể là acceptance cho các task triển khai. |
| Compatibility Impact | Public API giữ schema default Top-K=5 khi client bỏ field. Baseline Phase 18 dùng `top_k=3` rõ ràng, bot và Phase 12 standalone theo ENV. Phase 14 có task riêng và giữ model mặc định hiện tại. Phase 8 fail closed và Phase 12 deterministic fallback thuộc business services. |
| Known Issues | Cảnh báo `AsyncMock` hiện có. YAML runtime cần tạo ở T02. Provider/route live compatibility, account entitlement và cost evidence hiện là **NOT RUN**, với activation gates ở T17. Groq backup được thiết kế disabled/pending. |
| Next Task Allowed | **T02** ở lượt riêng. T02–T18 hiện **NOT RUN**. |

## 2026-11-20 (Asia/Saigon) — T02 preflight

Đã đọc yêu cầu và các tài liệu cấu hình liên quan. Loader và YAML chưa được tạo. Configuration tests và offline regression cho T02 **NOT RUN**. T02 chưa đạt acceptance và T03 **NOT ALLOWED**.

## 2026-11-20 (Asia/Saigon) — T02 implementation

| Mục | Kết quả |
| --- | --- |
| Status | **FAIL**. Loader và YAML đã được triển khai, còn thiếu kiểm chứng ràng buộc evidence với provider, endpoint, model, schema và task theo T01. |
| Files Changed | `src/shopassist/llm_gateway/__init__.py`, `src/shopassist/llm_gateway/config.py`, `config/llm_gateway.yaml`, `tests/test_llm_gateway_config.py`, `pyproject.toml`, execution log. |
| Implementation Summary | Pydantic settings, YAML safe loader, kiểm duplicate keys, provider, endpoint, route, schema và references. Các route thiếu evidence đều disabled/pending. PyYAML được khai báo trực tiếp. |
| Tests Executed | Focused configuration và legacy tests. Offline regression với network guard T00 và không có DSN trong tiến trình. |
| Test Results | Focused **64 passed**. Regression cuối **693 passed, 13 deselected, 1 warning**, exit 0, **0 external connection attempts**. JUnit `.deps/phase18-t02-final.xml`. Cảnh báo AsyncMock đã có tại baseline. |
| Compatibility Impact | Legacy runtime chưa được tích hợp với loader trong T02. Flag disabled trả về None và không đọc YAML. Các route primary và Groq đều pending. |
| Known Issues | Validation hiện chỉ kiểm tra evidence ref có mặt, chưa xác thực nội dung evidence có khớp route. Acceptance contract T01 chưa đạt. |
| Next Task Allowed | **NOT ALLOWED**. Hoàn tất validation evidence và kiểm thử lại trước T03. |

## 2026-11-20 (Asia/Saigon) — T02-FIX Route Evidence Validation

| Mục | Kết quả |
| --- | --- |
| Status | **PASS** cho validation cấu hình và synthetic fixtures. |
| Files Changed | `src/shopassist/llm_gateway/config.py`, `tests/test_llm_gateway_config.py`, execution log này. Các thay đổi T02 trước đó vẫn thuộc worktree. |
| Evidence Validation | Approved route yêu cầu evidence record cục bộ cho approval và cost. Record phải khớp route, task, provider, endpoint, model, schema, structured mode, cost/pricing, trạng thái approved/valid và thời hạn UTC. Artifact phải tồn tại trong cùng thư mục cấu hình hoặc thư mục con và khớp SHA-256. Không có automatic approval. |
| Test Results | Focused Gateway và legacy **83 passed** trước thay đổi hỗ trợ evidence refs riêng. Lượt regression sau thay đổi cuối **712 passed, 13 deselected, 1 warning**, exit 0, **0 external connection attempts**. JUnit ở `.deps/phase18-t02fix-acceptance.xml`. Warning AsyncMock đã có từ baseline. |
| Compatibility Impact | YAML hiện tại vẫn load với tất cả route disabled/pending. Evidence records của test là synthetic, chỉ dùng kiểm logic. Một operator chịu trách nhiệm nội dung và phê duyệt evidence, hash xác nhận tính toàn vẹn của artifact. |
| Remaining Unverified Routes | Gemini Phase 8, OpenRouter, Groq và Gemini judge đều pending. Live compatibility, entitlement và cost vẫn cần xác minh tại T17 theo authorization. |
| Next Task Allowed | **T03** ở lượt riêng. |

## 2026-11-25 (Asia/Saigon) — T03 Unified Gateway Schemas & Errors

| Mục | Kết quả |
| --- | --- |
| Task ID | T03 |
| Status | **PASS** |
| Source Files Reviewed | Contract T01, execution log, configuration loader, Phase 8/12 output và usage schemas, task T03 trong implementation plan đính kèm. |
| Files Changed | `src/shopassist/llm_gateway/schemas.py`, `src/shopassist/llm_gateway/errors.py`, `tests/test_llm_gateway_schemas.py`, execution log. |
| Implementation Summary | Generic GatewayRequest/Response, immutable attempt history, GatewayUsage giữ null khi unknown, ErrorCategory/ReasonCode allowlists và structured GatewayError/ProviderAttemptError. Kiểm correlation IDs, attempt order và route uniqueness, winning provider/model/usage, deadline scope, UTC timestamp và context counts. Prompt, raw response và payload bị loại khỏi repr/dump mặc định. |
| Tests Executed | Focused Gateway configuration và schemas, sau đó full offline selection theo T00 với network guard và thiếu DSN. |
| Test Results | Focused **63 passed**, exit 0. Regression **742 passed, 13 deselected, 1 warning**, exit 0, 88.87s. **0 external connection attempts** ở cả hai lượt. JUnit `.deps/phase18-t03-focused-final.xml` và `.deps/phase18-t03-regression.xml`. |
| Compatibility Impact | Các contracts mới là internal. Exact response class/schema binding của composition root tiếp tục thuộc T04. Các schema hiện tại của business services tiếp tục được sử dụng ở integrations sau. |
| Implementation Choices | ID giới hạn 128 ký tự allowlisted, mỗi prompt và raw response giới hạn 1.000.000 ký tự. Giữ nguyên whitespace của prompt hợp lệ. Payload cũng bị loại khỏi serialization mặc định vì có thể chứa thông tin nhạy cảm. |
| Known Issues | Warning AsyncMock đã có từ baseline. Các route live vẫn pending và cần xác minh ở T17. |
| Next Task Allowed | **T04** ở lượt riêng. T04 chưa được thực hiện. |

## 2026-11-25 (Asia/Saigon) — T04 Provider Registry & Capability Management

| Mục | Kết quả |
| --- | --- |
| Task ID | T04 |
| Status | **PASS** |
| Source Files Reviewed | Task T04 trong kế hoạch V1, architecture và gateway contract T01, configuration/evidence loader, schemas T03 và configuration tests. |
| Files Changed | `src/shopassist/llm_gateway/registry.py`, `src/shopassist/llm_gateway/adapters/__init__.py`, `src/shopassist/llm_gateway/adapters/base.py`, `src/shopassist/llm_gateway/config.py`, `tests/test_llm_gateway_registry.py`, execution log. |
| Implementation Summary | ProviderRegistry tạo snapshot bất biến qua loader xác thực evidence. Resolve route và liệt kê routes theo thứ tự profile, kiểm exact output schema class từ trusted bindings. Khai báo structured mode capabilities, kiểm enabled/approved/evidence expiry và quyền dùng paid ở Gateway/task. Loader giữ thời hạn evidence nhỏ nhất để registry kiểm lại khi xét eligibility. Adapter protocol gồm prepare, single-dispatch complete_once và aclose cùng PreparedRequest/AdapterResult. |
| Tests Executed | Focused Gateway registry/configuration/schemas, sau đó full offline selection T00 với network guard và thiếu DSN. Evidence trong tests chỉ là synthetic fixtures. |
| Test Results | Focused **77 passed**, exit 0. Regression **756 passed, 13 deselected, 1 warning**, exit 0, 24.06s. **0 external connection attempts** ở cả hai lượt. JUnit `.deps/phase18-t04-focused-final.xml` và `.deps/phase18-t04-regression.xml`. |
| Compatibility Impact | Business services chưa sử dụng registry ở T04. Tất cả ordered route metadata được trả để các task sau ghi skip reasons. Caller phải kiểm `ineligibility` trước admission/dispatch. Credential, health, quota và budget admission thuộc các task triển khai tương ứng. |
| Known Issues | Warning AsyncMock hiện có. Model/wire compatibility live và entitlement vẫn pending T17. Production YAML giữ nguyên disabled/pending cho cả primary và backup. |
| Next Task Allowed | **T05** ở lượt riêng. T05 chưa được thực hiện. |

## 2026-11-25 (Asia/Saigon) — T05 Gemini Adapter

| Mục | Kết quả |
| --- | --- |
| Task ID | T05 |
| Status | **PASS** |
| Source Files Reviewed | GeminiClient, LLMSettings, Phase 8 reliability tests, adapter/registry/error contracts, T05 trong implementation plan và SDK transport selection/cleanup cài tại máy. |
| Files Changed | `src/shopassist/llm/gemini_client.py`, `src/shopassist/llm_gateway/adapters/gemini.py`, `tests/test_llm_gateway_gemini.py`, execution log. |
| Implementation Summary | Thêm raw single-call method và optional HttpOptions vào GeminiClient. GeminiAdapter dùng prepare/complete_once/aclose, lazy credential resolution, schema v1, usage unknown giữ null, timeout/cancellation và normalized ProviderAttemptError theo T01. Usage được lấy trước đọc text. HTTPX transports có retry=0, redirects và trust_env tắt, SDK attempts=1. |
| Tests Executed | Focused Gemini adapter và Phase 8 reliability tests. Kiểm SDK thật bằng mock transport trả HTTP 429, xác nhận một request. Full offline selection với network guard T00 và thiếu DSN. |
| Test Results | Focused **36 passed**, exit 0. Regression **770 passed, 13 deselected, 1 warning**, exit 0, 24.15s. **0 external connection attempts**. JUnit `.deps/phase18-t05-focused-acceptance.xml` và `.deps/phase18-t05-acceptance.xml`. |
| Compatibility Impact | Legacy structured-generation loop tiếp tục dùng đường hiện tại. Adapter trả raw output và normalized usage để Gateway validate output ở bước triển khai tương ứng. Mapping lỗi không nhận raw provider message. HTTP 400 chưa nhận dạng được nguyên nhân được phân loại PROVIDER_REJECTED. |
| Known Issues | Warning AsyncMock đã có từ baseline. Gemini model/entitlement/structured output live vẫn pending T17. Runtime Phase 8 integration thuộc T12. |
| Next Task Allowed | **T06** ở lượt riêng. T06 chưa được thực hiện. |

## 2026-11-25 (Asia/Saigon) — T06 OpenRouter & Groq Adapters

| Mục | Kết quả |
| --- | --- |
| Task ID | T06 |
| Status | **PASS** |
| Source Files Reviewed | Phase 12 providers, strict recommendation JSON schema/parser, Gateway adapter contracts, Gemini adapter và task T06 trong implementation plan. |
| Files Changed | `src/shopassist/llm_gateway/adapters/chat_completion.py`, `src/shopassist/llm_gateway/adapters/openrouter.py`, `src/shopassist/llm_gateway/adapters/groq.py`, `tests/test_llm_gateway_chat_adapters.py`, execution log. |
| Implementation Summary | Shared single-dispatch HTTPX transport cho hai OpenAI-compatible REST endpoints, retry=0, trust_env=false, follow_redirects=false. Strict JSON schema projection từ schema caller, model-specific token/reasoning options, normalized nullable usage, safe errors, Retry-After delta/HTTP-date, cancellation và idempotent async cleanup. OpenRouter tắt provider-side fallback. HTTP 400 kết thúc attempt mà không gửi request sửa format. |
| Tests Executed | Mock transport conformance cho cả hai adapters và legacy recommendation tests. Kiểm json_schema/json_object, usage thiếu/zero, output/envelope lỗi, refusal, status 400/401/403/429/503/302, timeout/network, dispatch denial/cancellation và closure. Full offline selection theo T00 với thiếu DSN và network guard. |
| Test Results | Focused **55 passed**, exit 0. Regression **802 passed, 13 deselected, 1 warning**, exit 0, 31.25s. **0 external connection attempts**. JUnit `.deps/phase18-t06-focused-final.xml` và `.deps/phase18-t06-regression.xml`. |
| Compatibility Impact | Groq Gateway adapter chọn REST qua HTTPX để dùng chung single-request transport với OpenRouter. Payload vẫn giữ max_completion_tokens và reasoning_effort theo route. Raw generated content trả cho Gateway validation ở task sau. Các legacy providers tiếp tục dùng implementation hiện tại. |
| Known Issues | Warning AsyncMock đã có từ baseline. Production routes tiếp tục disabled/pending và cần validation/entitlement tại T17. Phase 12 runtime integration thuộc T11. |
| Next Task Allowed | **T07** ở lượt riêng. T07 chưa được thực hiện. |

## 2026-11-25 (Asia/Saigon) - T17 Evidence Update and OpenRouter Controlled Attempt

| Item | Result |
| --- | --- |
| Task ID | T17 provider-specific preflight and one controlled OpenRouter validation attempt |
| Status | **T17 remains BLOCKED / FAIL for acceptance.** OpenRouter account Free Tier evidence was verified, but the isolated inference attempt was rejected before producing a valid model response. Gemini and Groq were not dispatched. T18 is not allowed. |
| Budget Authorization | Existing authorization remains in force: Gemini 2/10,000 tokens, OpenRouter 3/20,000, Groq 3/20,000; global 8/50,000; USD $0 maximum. No new approval requested. Harness was run only for OpenRouter with exact route `recommendation_openrouter`, zero-cost ceiling, 25s attempt timeout and 120s total deadline. |
| OpenRouter Account Evidence | One authenticated, read-only `GET https://openrouter.ai/api/v1/key` using the local OpenRouter credential returned HTTP 200, `is_free_tier=true`, key limit USD $0, remaining USD $0, usage USD $0, and free-model daily allowance 50/50 remaining. Only allowlisted fields were retained; credential value and account identifiers were not logged. Verification time: 2026-11-25 07:34:54 UTC. User screenshot independently showed a `shopassist` key with $0.000 credits/total/key limit. |
| Model/Request Policy Evidence | OpenRouter's current exact model page identifies `baidu/ernie-5.5-flash-preview:free` as Free ($0 input/output), supports JSON Schema structured outputs, and says it is served by Baidu Qianfan. The ShopAssist OpenRouter adapter pins the exact model and sends `provider.allow_fallbacks=false`; paid models remain disallowed. Sources: https://openrouter.ai/baidu/ernie-5.5-flash-preview%3Afree and https://openrouter.ai/api/v1/key. |
| Evidence Artifacts | Added `data/interim/phase18_t17/openrouter_free_tier_preflight.json` with sanitized metadata and source references; SHA-256 `38e9a1f7d2e29982c009a8c1d7350b4f37cbc371f3e7053f9897a552d7724840`. Added `data/interim/phase18_t17/free_tier_entitlements_openrouter.json` bound to the exact provider/model and a one-hour evidence validity window. No production evidence/approval state was changed. |
| OpenRouter Attempt | Harness passed route identity and evidence preflight, then dispatched exactly one inference request. Result **FAILED / PROVIDER_REJECTED**; no reported model identity, valid structured output, token usage or actual cost was returned. Latency 13,453 ms. Harness conservatively reserved 5,731 tokens because provider usage was unavailable. The attempt is not retried. |
| Gemini Screenshot Review | Google AI Studio screenshot shows two API keys marked Free tier. A local check compared `GEMINI_API_KEY` against the two visible masked suffixes without printing the credential; neither matched. Therefore the screenshot does not bind to the credential in `.env`. No Gemini request was sent. Official general pricing is not substituted for credential-specific entitlement. |
| Groq | No account-specific Free Tier proof was supplied or verified. No request was sent; route remains BLOCKED. |
| Counters | Persistent inference ledger: Gemini 0 requests / 0 tokens; OpenRouter 1 request / 5,731 conservatively reserved tokens; Groq 0 / 0. Global 1 inference request / 5,731 tokens; pending reservations 0; configured cost ceiling USD $0. Actual cost/usage for the rejected OpenRouter response remain unknown. In addition, exactly one non-inference OpenRouter metadata GET was made for account verification. |
| Compatibility/Route State | All production routes remain `enabled=false`, `approval=pending`, cost class `unknown`; `LLM_GATEWAY_ALLOW_PAID_MODELS=false`. The OpenRouter route is not approved despite account/model pricing evidence because live structured output was not validated. No Gemini/Groq live attempt and no automatic approval. |
| Next Step | T17 remains incomplete. Diagnose the OpenRouter rejection from a safe provider response/status or offline payload conformance before any further request; any additional inference must remain inside the existing OpenRouter cap of 3 and zero-cost policy. Obtain account-specific proof bound to the local Gemini credential and Groq credential before dispatch. No T18. |

## 2026-11-25 (Asia/Saigon) - T17 Groq Credential Match and Controlled Validation

| Item | Result |
| --- | --- |
| Task ID | T17 Groq provider-specific validation |
| Status | **Groq isolated validation PASS (one provider only); overall T17 remains BLOCKED.** OpenRouter validation failed and Gemini remains blocked. No T18. |
| Operator Evidence | Operator stated the replacement Groq key is the Free Tier key. User-provided Groq console screenshot shows a new `shopAssist` key with 0 API calls. A local comparison confirmed the configured `GROQ_API_KEY` matches the screenshot's visible suffix; the secret itself was never printed. The screenshot does not display the billing tier, so the Free Tier status is recorded as operator-attested, not as a tier field returned by the API. Groq's official billing documentation says Free-tier accounts have Free-tier restrictions and usage-based charges stop when downgraded; the model documentation lists Developer-tier prices, which are not authorized here. |
| Read-only Preflight | Authenticated `GET https://api.groq.com/openai/v1/models` returned HTTP 200 and listed `openai/gpt-oss-20b`. This confirmed credential validity and model availability only; no inference was sent by this GET. No rate-limit headers identifying account tier were returned. |
| Controlled Inference | The existing isolated harness passed exact route/evidence admission and sent exactly one request. Result: **PASS**. Reported model matched `openai/gpt-oss-20b`; Phase 12 Pydantic/schema validation passed; catalog product ID and evidence citation checks passed. Usage: 806 input, 386 output, 35 reasoning, 1,192 total tokens. Latency 4,172 ms. Actual/estimated cost was not reported (`null`); the request was run under the operator-attested Free Tier and zero-paid policy. Semantic groundedness remains flagged for human review. |
| Evidence Artifacts | Added `data/interim/phase18_t17/groq_free_tier_preflight.json` and `data/interim/phase18_t17/free_tier_entitlements_groq.json`, bound to the exact credential fingerprint/provider/model and one-hour evidence window. Provenance clearly distinguishes user attestation from authenticated model-list evidence. The route remains unapproved. |
| Persistent Counters | Updated the ledger to include both account metadata GETs as provider requests: OpenRouter 2/3 total provider API requests (1 metadata + 1 inference); Groq 2/3 (1 metadata + 1 inference); Gemini 0/2. Global total is 4/8 requests. Inference token accounting is OpenRouter 5,731 conservatively reserved (provider usage unavailable) and Groq 1,192 reported; total 6,923/50,000. Pending reservations 0. Cost remains USD $0 ceiling; actual cost is unknown where providers did not return it. |
| Failover/Approval | Automatic failover validation was not run because Phase 12 routes have not both passed and been approved. No route was automatically approved or enabled. `LLM_GATEWAY_ALLOW_PAID_MODELS=false`; all production routes remain disabled/pending. |
| Next Step | Overall T17 remains blocked on Gemini credential-bound Free Tier evidence and successful Gemini validation, plus diagnosis/revalidation of OpenRouter's rejected structured-output request. Groq semantic groundedness requires human review. Do not start T18. |

## 2026-11-25 (Asia/Saigon) - T17 Gemini API Key Metadata Check

| Item | Result |
| --- | --- |
| Task ID | T17 Gemini credential metadata check |
| Status | **Credential authenticated and exact model listed; no inference run. Gemini route remains BLOCKED for live validation because this does not establish the local key's Free Tier billing entitlement.** |
| Request | One read-only `GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000` using the local key in the `x-goog-api-key` header. No prompt/generation endpoint was called. |
| Result | HTTP 200. `models/gemini-3.5-flash-lite` appeared in the catalog and listed `generateContent` support. Credential value was not printed. The check cannot confirm project billing tier or guarantee a generation request is permitted under Free Tier. |
| Artifact | `data/interim/phase18_t17/gemini_key_metadata_check.json` contains only the sanitized status, model capability, hashed credential reference and explicit scope limitation. No production route state changed. |
| Counters | Account metadata GETs: Gemini 1, OpenRouter 1, Groq 1. Inference requests: Gemini 0, OpenRouter 1, Groq 1. Total provider API requests: 5/8. Inference token budget: 6,923/50,000 (OpenRouter 5,731 reserved; Groq 1,192 reported). Pending reservations 0. |
| Next Step | For Gemini, a Free Tier account artifact bound to this exact local credential is still needed before a generation request. T17 and T18 status unchanged. |

## 2026-11-25 (Asia/Saigon) - T17 Gemini Controlled Live Validation

| Item | Result |
| --- | --- |
| Task ID | T17 Gemini selected-route validation |
| Status | **Gemini validation PASS. Overall T17 remains BLOCKED** because OpenRouter failed structured-output validation and Phase 12 failover acceptance requires both recommendation routes validated/approved. No T18. |
| Authorization / Entitlement Basis | Operator explicitly confirmed the current Gemini key is Free Tier and requested the controlled test. The claim is recorded as operator attestation, bound to the local credential fingerprint; it is not mislabeled as a billing-tier field returned by Google. The model metadata GET had authenticated successfully and the exact model appeared with `generateContent`. Official Gemini pricing lists a Free Tier with no charge for this model; paid-model policy remained false and no grounding/search tools were used. Source: https://ai.google.dev/gemini-api/docs/pricing. |
| Controlled Inference | Isolated harness dispatched exactly one synthetic query-understanding request to `gemini-3.5-flash-lite`. Provider-reported identity matched exactly; `phase8.query.v1` validation passed. Latency 4,469 ms; usage 31 input + 124 output = 155 tokens. Provider did not return actual/estimated cost (`null`); no paid route was requested and `LLM_GATEWAY_ALLOW_PAID_MODELS=false`. |
| Evidence | Added `data/interim/phase18_t17/gemini_free_tier_operator_attestation.json` and `data/interim/phase18_t17/free_tier_entitlements_gemini.json`, with one-hour validity and a digest binding. The artifact preserves that account tier came from the operator's attestation; metadata endpoint alone cannot prove billing tier. |
| Aggregated Validation Artifact | `data/interim/phase18_t17/validation.json` now retains all three provider outcomes: Gemini **passed**, Groq **passed** (human groundedness review remains), OpenRouter **failed / PROVIDER_REJECTED**. No route was approved or enabled. |
| Persistent Counters | All provider API calls are counted, including read-only metadata GETs: Gemini 2/2 (1 metadata + 1 inference), Groq 2/3 (1 + 1), OpenRouter 2/3 (1 + 1), global 6/8. Inference tokens: Gemini 155 reported, Groq 1,192 reported, OpenRouter 5,731 conservatively reserved due missing usage; total 7,078/50,000. Pending reservations 0. Actual cost is null where providers did not report it. |
| Tests / Compatibility | No source code changed and no new unit test suite was run in this turn. The live harness validated the exact Gemini output schema; prior offline harness test results remain 26 focused and 928 full regression passed. Production routes remain disabled/pending; no prompt, dataset, retrieval or public API contract changed. |
| Remaining Gate | Diagnose and rerun OpenRouter within its remaining provider request allowance; complete Phase 12 groundedness human review; then perform only the failover cases permitted by T17. No automatic route approval. T18 remains disallowed. |

## 2026-11-25 (Asia/Saigon) - T17 OpenRouter Retest After Zero-Cost Dashboard Evidence

| Item | Result |
| --- | --- |
| Task ID | T17 OpenRouter retest |
| Status | **OpenRouter validation still FAIL/BLOCKED.** The retest used the final available OpenRouter request under the provider cap and ended with a network error. No further OpenRouter request is allowed within the approved three-request cap. |
| Operator Evidence | User supplied a dashboard screenshot for `ERNIE-5.5-Flash-Preview (free)` showing min/max/average/total all `$0.00`. This complements the earlier authenticated key metadata response showing `is_free_tier=true`, key limit `$0`, and usage `$0`. The refreshed sanitized record is `data/interim/phase18_t17/openrouter_zero_cost_dashboard_recheck.json`. The exact model is documented as zero-priced and supporting JSON Schema: https://openrouter.ai/baidu/ernie-5.5-flash-preview%3Afree. |
| Retest | Refreshed the local evidence digest from the new dashboard observation and re-ran only `recommendation_openrouter` through the isolated harness, with paid models disabled, exact `:free` model pinned and provider fallbacks off. Exactly one inference request was dispatched. Result: **NETWORK_ERROR**, 23,218 ms; no model identity, schema output, provider usage or actual cost returned. No retry. |
| Prior OpenRouter Attempt | Preserved: earlier attempt was `PROVIDER_REJECTED`, 13,453 ms, with no usage/model/cost returned. Both attempts conservatively reserve 5,731 tokens each; request details/raw errors are not persisted. |
| Aggregated Artifact | `data/interim/phase18_t17/validation.json` now retains Gemini PASS, Groq PASS (human groundedness review required), and latest OpenRouter failure plus both OpenRouter attempts in history. No production route state changed. |
| Counters | Provider requests including metadata GETs: Gemini 2/2 (1 metadata + 1 inference), Groq 2/3 (1 + 1), OpenRouter 3/3 (1 metadata + 2 inference), global **7/8**. Token budget: Gemini 155 reported, Groq 1,192 reported, OpenRouter 11,462 reserved for two failed requests; total **12,809/50,000**. Pending reservations 0. The screenshot showed `$0.00` before this latest attempt; actual cost for the failed attempt is unavailable from the response and is not asserted as confirmed. |
| Gate / Next Step | T17 remains incomplete because OpenRouter has not validated output, Phase 12 groundedness needs human review, and automatic failover criteria are unmet. No OpenRouter retries remain under the approved cap. Gemini/Groq production routes remain disabled/pending. T18 is not allowed. |

## 2026-11-25 (Asia/Saigon) - T17 OpenRouter Credential Change Check (No Dispatch)

| Item | Result |
| --- | --- |
| Task ID | T17 OpenRouter retry preflight |
| Status | **NOT DISPATCHED.** The current environment still contains an OpenRouter-format `OPENROUTER_API_KEY` and a different Google/Gemini-format `GEMINI_API_KEY_2`; only credential types and equality were checked locally, no secret values were printed. |
| Compatibility | OpenRouter's API requires an OpenRouter-issued credential. A Google Gemini API key cannot authenticate to the OpenRouter API; no request was sent with it. |
| Budget Gate | OpenRouter has already reached its approved cap of 3 provider API requests (one metadata GET plus two inference attempts). No further OpenRouter request is permitted within the existing authorization, even after a key change. |
| Counters | No counters changed in this preflight. Global remains 7/8 provider API requests and 12,809/50,000 inference tokens; OpenRouter remains 3/3 requests. |
| Next Step | The operator must provide an OpenRouter-issued key in `OPENROUTER_API_KEY` and renew/raise the OpenRouter request ceiling before another live attempt. T18 remains disallowed. |

## 2026-11-25 (Asia/Saigon) - Operator-Requested Phase 12 Gemini Route Change

| Item | Result |
| --- | --- |
| Task | Replace the Phase 12 production profile's OpenRouter primary with Gemini using `GEMINI_API_KEY_2`; preserve Groq as the second candidate. |
| Implementation | Added provider profile `gemini_recommendation` and route `recommendation_gemini` (`gemini-3.5-flash-lite`, Google Generative Language endpoint, `gemini_schema`, `phase12.recommendation.v1`). Phase 12 default order is now Gemini then Groq. The OpenRouter route remains defined for audit/rollback but is no longer in the default profile. API and CLI Gateway composition roots bind the new profile to `GEMINI_API_KEY_2`; profile-specific adapter lookup takes precedence over provider-kind lookup. |
| Safety / compatibility | All candidate routes remain `enabled=false`, `approval=pending`, cost `unknown`; `LLM_GATEWAY_ALLOW_PAID_MODELS=false`. No prompts, business schemas, public API contracts, dataset, retrieval, reranking or recommendation behavior changed. No provider credentials were modified and no LLM request was sent for this change. |
| Focused tests | Gateway configuration, registry, runtime, validation harness, lifecycle and experiment integration: **103 passed**. |
| Offline regression | Network-safe broad selection: **910 passed, 7 skipped, 26 deselected, 1 pre-existing AsyncMock warning**, 52.84s; excludes live/database-marked tests, the known stale `test_api_settings_defaults` expectation, and `tests/test_semantic_retrieval.py` because its local embedding checkpoint is unavailable. JUnit: `.deps/phase18-route-change-offline.xml`. |
| Regression limitation | The attempted unfiltered offline selection was not a valid offline run: it exposed unmarked live Supabase tests and attempted database connections; embedding tests also attempted to fetch `BAAI/bge-small-en-v1.5` from Hugging Face and received HTTP 401. No test established a successful database connection, and no provider LLM API was called by this route-change work. The first unrelated assertion failure was `test_api_settings_defaults` (`api_default_top_k` expected 5, actual 3). Do not count that run as acceptance evidence. |
| T17 budget / acceptance | Existing T17 counters remain at Gemini 2/2, OpenRouter 3/3, Groq 2/3, global 7/8 requests and 12,809/50,000 tokens; maximum paid spend remains USD $0. Those ceilings do not authorize live validation of the new Phase 12 Gemini route. A new provider-specific budget and entitlement evidence for the `GEMINI_API_KEY_2` account are required before dispatch. |
| Status | **Route configuration and wiring implemented; production route acceptance remains BLOCKED/PENDING T17.** No route was approved or enabled. T18 is not allowed. |

## 2026-11-25 (Asia/Saigon) - Operator Correction: Remove OpenRouter from Phase 18 Gateway

| Item | Result |
| --- | --- |
| Task | Remove OpenRouter entirely from the Phase 18 Gateway Phase 12 route and replace it with Gemini using `GEMINI_API_KEY_2`. |
| Changes | Removed the OpenRouter provider and `recommendation_openrouter` route from `config/llm_gateway.yaml`; removed OpenRouter adapter construction from FastAPI and CLI Gateway composition roots; removed OpenRouter from the live T17 route allowlist and adapter factory. The Phase 12 route order is Gemini (`recommendation_gemini`) then Groq (`recommendation_groq`). Legacy OpenRouter code/settings remain available only with Gateway disabled, preserving the legacy-mode invariant. Historical T17 ledger keys and logs remain readable and are not active dispatch candidates. |
| Tests | After this correction: focused Gateway/config/registry/harness/lifecycle/experiment/CLI suite **109 passed** in 20.27s. No provider, database, or model-download calls were part of this test run. The earlier broad safe selection (910 passed) preceded this final removal and is not claimed as a post-correction full regression. |
| Acceptance | Phase 12 Gateway route remains disabled/pending with unknown cost until new T17 budget and exact Gemini account entitlement/evidence are approved and validated. No credentials were changed; no live request was sent. T18 remains disallowed. |

## 2026-11-26 (Asia/Saigon) - Operator Free Tier Attestation and T17 Re-preflight

| Item | Result |
| --- | --- |
| Operator Attestation | Operator confirmed all selected provider keys/accounts are Free Tier, paid billing is disabled, and asked to complete T17. This is recorded as operator attestation, not provider-returned billing metadata. |
| Local Credential Readiness | `GEMINI_API_KEY_2` and `GROQ_API_KEY` are present in the local dotenv file. `GEMINI_API_KEY_2` is different from the Gemini key used for the earlier Phase 8 query test. No key or fingerprint was printed. |
| Evidence | Added `data/interim/phase18_t17/gemini_recommendation_key2_operator_attestation.json` and `groq_current_free_tier_operator_attestation.json`; current, one-hour entitlement index is `free_tier_entitlements_phase12_current.json`. Records bind provider/model/task/schema and credential fingerprints, distinguish operator attestation from provider metadata, and enforce zero paid spend. The evidence loader validated both entries. |
| Offline Preflight | Dry-run selected only `recommendation_gemini` and `recommendation_groq`; exact endpoints/models and credentials were present, both routes remain disabled/pending with unknown cost, paid models are false, and no provider request was sent. |
| Budget Gate | Persistent T17 ledger remains Gemini 2/2, Groq 2/3, OpenRouter historical 3/3, global 7/8 requests; total tokens 12,809/50,000, maximum cost USD $0. Gemini's per-provider request ceiling is exhausted, so the new Phase 12 Gemini recommendation request is blocked even though one global request slot remains. Free Tier confirmation does not increase the approved request ceiling. |
| Remaining Work | Requires explicit T17 budget amendment for at least one additional Gemini request (Gemini cap 2 → 3; global cap may remain 8, token ceiling 50,000 and cost ceiling USD $0). Then run Gemini Phase 12 structured-output/catalog validation. Groq groundedness still needs human review; prior result artifact records IDs/citations but not raw response text. Automatic failover cases and route approval remain outstanding. No T18. |

## 2026-11-26 (Asia/Saigon) - T17 Gemini Phase 12 Controlled Validation

| Item | Result |
| --- | --- |
| Authorization | Operator approved exactly one additional Gemini request: Gemini cap 3, global cap 8, 50,000 tokens, maximum paid spend USD $0. `LLM_GATEWAY_ALLOW_PAID_MODELS=false`. |
| Preflight | Confirmed `GEMINI_API_KEY_2` is present and its local fingerprint matches the current operator-attestation artifact; exact route/model/task/schema/endpoint matched YAML. Current Gemini and Groq Free Tier attestations passed the harness evidence loader. No credential value or fingerprint was printed. |
| Dispatch | Isolated T17 harness dispatched exactly one request for `recommendation_gemini` using `gemini-3.5-flash-lite` at `https://generativelanguage.googleapis.com`. No retry or additional request. |
| Result | **Individual Gemini Phase 12 validation PASS.** Reported model matched; `phase12.recommendation.v1` parsed; catalog product ID and evidence citations matched the frozen catalog fixture. Usage: 303 input + 361 output = 664 tokens. Latency 4,640 ms. Actual cost was not reported (`null`); Free Tier operator attestation and USD $0 ceiling applied. The harness flags groundedness for human review; raw generated text is not retained in the sanitized result artifact, so that review is still outstanding. |
| Artifact | `data/interim/phase18_t17/validation_gemini_recommendation.json`; SHA-256 `B6117294E79DEB1B9B58DA2658CFE891D5E2E2AFB526A0D1A4E9E5D25B9E6F32`. No production route approval/enable state changed. |
| Counters | Gemini 3/3 requests, 819/10,000 tokens; Groq 2/3 requests, 1,192/20,000 tokens; historical OpenRouter 3/3, 11,462 tokens; global **8/8 requests**, 13,473/50,000 tokens; pending reservations 0; maximum paid spend USD $0. No further T17 dispatch fits the approved request ceiling. |
| Status / Remaining Gates | **T17 remains BLOCKED.** Gemini and Groq each have schema/identity/catalog-ID/citation validation results, but human groundedness review remains outstanding and response text is not retained for that review. Per T17 sequence, automatic failover cases wait until both routes are individually reviewed/approved; route approval is never automatic. Any additional live call requires a new budget because global request cap 8/8 is exhausted. T18 is not allowed. |

## 2026-11-26 (Asia/Saigon) - T17 Approved Groundedness Review Requests

| Item | Result |
| --- | --- |
| Authorization | Operator approved two additional inference requests: one Gemini and one Groq. Updated ceiling: 10 total requests, 50,000 tokens, USD $0 maximum; per-provider caps Gemini 4/10,000 and Groq 3/20,000. |
| Harness / Tests | Added a separate groundedness-review artifact containing only the parsed Phase 12 payload and the exact frozen catalog fixture; prompts and credentials are excluded from the review file and raw payload is excluded from the validation summary. Focused Gateway/config/registry/harness/lifecycle/experiment/CLI tests: **110 passed**, 25.85s. |
| Gemini Attempt | `recommendation_gemini`, `gemini-3.5-flash-lite`: exactly one request; result **PROVIDER_UNAVAILABLE**, attempt count 1, latency 6,266 ms, no reported model/usage/cost, no retry. The harness conservatively charged its reservation (5,731 tokens). The prior Gemini Phase 12 request still has schema/catalog-ID/citation PASS, but no captured text for human groundedness review. |
| Groq Attempt | `recommendation_groq`, `openai/gpt-oss-20b`: exactly one request; result **PASS** for model identity, Phase 12 schema, catalog product ID and evidence citations. Usage: 806 input + 306 output = 1,112 tokens, 13 reasoning tokens; latency 6,328 ms. Actual cost was not reported (`null`), under Free Tier operator attestation and USD $0 policy. Parsed output and fixture are in `validation_groq_groundedness_review_recommendation_groq_groundedness_review.json`; manual groundedness review is still required. |
| Aggregated Evidence | `data/interim/phase18_t17/validation_current_routes.json`; SHA-256 `5A2ABDB411637CA6F536E021BF9CAFF99E2D84F3D01CB6A847E1E4A2AF7CBDEB`. It retains the prior Gemini pass, the single Gemini unavailable result, and Groq pass, with current counters. |
| Counters | Gemini **4/4 requests**, 6,550/10,000 tokens; Groq **3/3**, 2,304/20,000; historical OpenRouter 3/3, 11,462 tokens; global **10/10 requests**, 20,316/50,000 tokens; pending reservations 0; paid spend ceiling USD $0. No more dispatches fit this authorization. |
| Status / Remaining Gates | **T17 remains BLOCKED.** Gemini recommendation groundedness lacks a reviewable successful output; its one approved follow-up was unavailable. Groq's review artifact awaits human decision. Do not approve/enable either route automatically. Automatic failover validation stays behind the individual review/approval gate. Further live calls require another budget; T18 is not allowed. |
