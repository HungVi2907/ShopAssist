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

**Current status** | T00-T14 **PASS**; T15 **FAIL / incomplete**. T16 is not allowed yet.

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
