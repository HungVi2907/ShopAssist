# Phase 18 V1 — LLM Gateway Contract

**T01 · 2026-11-20 (Asia/Saigon) · Internal contract v1**

Contract dùng trong process Python 3.10+ trên một event loop. `async complete(request: GatewayRequest[T]) -> GatewayResponse[T]` trả payload đã qua schema validation hoặc raise `GatewayError`. External cancellation propagate bằng `asyncio.CancelledError`. Caller task sở hữu business validation và fallback. [Kiến trúc và các integration points](phase18_architecture.md)

## Task và schema

| `TaskType` | `schema_id` mặc định / output model | Route production dự kiến, theo thứ tự | Khi hết route |
| --- | --- | --- | --- |
| `query_understanding` | `phase8.query.v1` / `QueryUnderstandingOutput` | Gemini `gemini-3.5-flash-lite` | Fail closed, Phase 8 invalid result, không chuyển tới retrieval. |
| `recommendation_generation` | `phase12.recommendation.v1` / `LLMRecommendationPayload` | OpenRouter `baidu/ernie-5.5-flash-preview:free`, sau đó Groq `openai/gpt-oss-20b` khi đủ điều kiện | Deterministic catalog fallback do Phase 12 thực hiện. |
| `llm_judge` | `phase14.judge.v1` / `LLMJudgeResponseSchema` | Gemini `gemini-3.1-flash-lite` để giữ model mặc định của Phase 14 hiện tại. | Live skip trước dispatch hoặc failure sau dispatch theo chính sách CLI đã mô tả. |

Model IDs là định tuyến thiết kế. T17 kiểm chứng model availability, structured output, compatibility và giá/quyền dùng trong môi trường được phép. T02 có thể khai báo primary dự kiến từ bảng này. Route thiếu evidence hợp lệ bắt đầu với `enabled=false` và approval `pending`. Groq backup giữ các trạng thái đó tới khi đạt validation và usage/cost approval. Phase 8 và Phase 14 khởi đầu với một route. V1 bật automatic failover theo cấu hình local cho các route đủ điều kiện. Task/schema/profile khác phải được khai báo và kiểm tra qua registry.

## Unified request, response và error

| `GatewayRequest[T]` | Kiểu và ràng buộc |
| --- | --- |
| `task`, `profile` | `TaskType` và ID profile có trong registry. Mặc định profile `default`, do caller tin cậy chọn. |
| `request_id`, `task_id` | Hai internal correlation IDs. Cùng `request_id` cho Phase 8/12 trong một API request, `task_id` riêng cho từng invocation. CLI cấp ID nếu không có. Hai trường có giới hạn độ dài, được chuẩn hóa trước telemetry. |
| `system_prompt`, `user_prompt` | `str` do service dựng, giữ nguyên bytes biểu diễn UTF-8 khi chuyển nội dung hợp lệ. Validate input kích thước hữu hạn, không được rỗng sau trim. Dùng nội dung bản gốc sau validation. Đánh dấu sensitive, loại khỏi repr/dump thường. |
| `schema_id`, `response_schema` | Stable ID theo bảng và lớp Pydantic `type[T]` do caller cung cấp. Schema registry kiểm cặp ID/class trong trusted composition root. Dùng wire projection có kiểm chứng theo adapter, giữ nguyên lớp validate cuối. Từ chối schema/task/profile mismatch trước dispatch. |
| `parent_deadline_mono` | `float \| None`, timestamp tuyệt đối cùng monotonic clock trong process. Caller API lấy từ deadline request, CLI có thể bỏ trống. |

Request không có field provider/model/URL/credential, wire params, Top-K hay retry override. Route config sở hữu wire options như temperature, max output tokens, reasoning_effort, structured mode và model-specific flags. Provider error khi request vượt giới hạn context của route được phân loại `INCOMPATIBLE_ROUTE`. Trường hợp phát hiện từ metadata đã biết trước dispatch thì skip route sớm. Không truncate prompt để cố dùng route.

| `GatewayResponse[T]` | Kiểu và nghĩa |
| --- | --- |
| `request_id`, `task_id`, `task`, `schema_id` | IDs và loại từ request. |
| `payload`, `raw_text` | `T` đã validate và `str \| None` giới hạn kích thước dành cho mapping nội bộ của Phase 8. Raw data chỉ tồn tại trong process và bị loại khỏi repr/serialization mặc định. |
| `route_id`, `provider`, `model`, `reported_model` | Route thắng, provider/model đã dispatch. `reported_model: str \| None` là upstream identity/version nếu có và an toàn để lưu. Canonical route model và revision là hai trường riêng. Route dùng model ID cố định, tắt provider-side model fallback nếu khả dụng. Nếu response xác nhận model family ngoài alias/version được duyệt, đánh dấu `INCOMPATIBLE_ROUTE` và bỏ payload. Thiếu reported model được lưu null. |
| `usage`, `attempts` | Usage của attempt thành công và ordered immutable sequence `AttemptRecord` của mọi dispatch. |
| `latency_ms`, `failover_used` | Elapsed task monotonic và bool true nếu route thắng có vị trí sau primary trong YAML, kể cả primary bị skip. |

`GatewayError` mang `category`, allowlisted `reason_code`, thông báo chung an toàn, IDs, immutable attempts và `elapsed_ms`. `source` có các giá trị `request`, `admission`, `provider`, `gateway`, `deadline`. Với deadline dùng `deadline_scope=task|parent`. Không kèm raw exception, auth, headers, provider body, prompt hoặc schema error values. Trả `NO_ELIGIBLE_ROUTE` nếu 0 dispatch và hết route, với route skip reasons trong task summary. Sau ít nhất một dispatch dùng lỗi attempt cuối khi hết eligible routes. Deadline và lỗi request/cấu hình có ưu tiên cao hơn khi phát hiện trước dispatch. Startup config error là `CONFIGURATION_ERROR` an toàn, có field path allowlisted và không chứa raw input.

### Adapter interface, router và registry

`ProviderAdapter.complete_once(prepared: PreparedRequest, *, timeout_s: float, on_dispatch: Callable[[], None]) -> AdapterResult` là coroutine một attempt. `ProviderAdapter.aclose() -> None` đóng client sở hữu. `prepare(request, route) -> PreparedRequest` chỉ chuyển wire format và validate local, không I/O. `PreparedRequest` chứa route resolved và request body nhạy cảm. `AdapterResult` chứa raw output giới hạn, provider usage normalized, status và reported model nếu có. Adapter có thể raise `ProviderAttemptError` normalized với `category`, `reason_code`, `http_status: int | None`, `retry_after_s: float | None` và usage nếu đã nhận response. Gateway lưu chính lỗi đó vào attempt. Sau khi đọc response envelope, adapter lấy usage trước khi decode và validate generated output. Usage vẫn được giữ khi output lỗi.

Adapter gọi `on_dispatch` đúng một lần ở ranh giới transport trước khi bắt đầu request, gồm connect và DNS phục vụ dispatch đó. Hook kiểm deadline và commit admission/attempt. Hook fail thì transport không chạy. Retry hooks ở SDK/HTTP/adapter bị tắt. Mock transport đếm thật mọi request. Unit tests đối chiếu count với records. Local prepare failure không tạo attempt. Adapter chỉ cho phép wire variants đã khai báo, không đổi body rồi gửi lại. Gateway dùng parser chung để kiểm JSON và model validation. Các normalization cấu trúc tương thích legacy như bỏ Markdown fences/wrapper list của Phase 12 được gắn với decoder đã đăng ký theo schema, giữ hành vi parser hiện có. Business normalization và groundedness chạy phía caller.

`TaskRouter.routes_for(task, profile, schema_id) -> tuple[ResolvedRoute, ...]` dùng snapshot registry đã validate. `ProviderRegistry.resolve(route_id) -> ResolvedRoute` trả provider profile, exact model ID, role/order, schema/version và structured mode, giới hạn context/output, approved aliases, parameters, `enabled`, approval và cost policy. Registry build từ cấu hình một lần và trả mọi ordered route kèm metadata để Gateway ghi reason nếu bị skip. Health/quota state riêng với config static. Không nhận arbitrary model from user prompt hoặc provider response.

## Cấu hình và validation

T02 tạo `GatewaySettings` và YAML theo structure sau. Các nhóm và field dưới đây thuộc phiên bản `version: 1`.

| YAML field | Shape |
| --- | --- |
| `providers` | Map `provider_profile_id -> {kind, credential_env, endpoint, limits}`. `kind` thuộc `gemini\|openrouter\|groq`. `credential_env` là tên credential trong ENV, map theo kind, ví dụ `GEMINI_API_KEY`. `endpoint` là HTTPS base có hostname/path allowlist theo adapter. Limits hỗ trợ `requests_per_minute`, `tokens_per_day`, `max_in_flight`, `cost_per_day_usd`. Giới hạn có giá trị phải dương/hữu hạn. |
| `routes` | Map `route_id -> {provider, model, structured_mode, schema_ids, enabled, approval, cost, options}`. `approval={status, evidence_ref}`, status `pending\|approved`. `evidence_ref` có thông tin xác minh endpoint/model/schema và quyền dùng. `structured_mode` enum `gemini_schema\|json_schema\|json_object`. `json_object` chỉ dùng khi route/schema combo được kiểm chứng và vẫn validate locally. `cost={class, evidence_ref, input_per_million_usd, output_per_million_usd}`, class `unknown\|free\|paid`. Options typed theo kind, gồm `max_output_tokens`, `context_limit_tokens`, temperature/reasoning settings và optional `reported_model_aliases`. |
| `tasks` | Map từ ba `TaskType` đến `profiles`. Từng profile có `schema_id`, `route_ids` (ordered, index 0 primary), `allow_paid` (mặc định false). Mỗi default profile có primary. Profile thử nghiệm do T14 thêm với schema đã đăng ký. Route có thể xuất hiện ở nhiều task nếu phù hợp schema/approval, nhưng trong một profile không lặp `route_id` hoặc cùng bộ provider profile/endpoint/model. |

Registry validation kiểm task/schema allowlist, ID và reference hợp lệ, order và uniqueness, route capability theo adapter/schema, model wire params, endpoint allowlist và pricing/approval. Chỉ route bật và approved mới eligible. Enabled route pending là lỗi cấu hình. Route draft/pending được phiên bản thiết kế biểu diễn bằng disabled. Evidence ref phải khớp provider profile/endpoint/model/structured mode/schema/task và phạm vi cost. Model/endpoint/schema thay đổi làm evidence cũ mất hiệu lực. Endpoint chỉ chấp nhận HTTPS allowlist theo provider, path đúng API base và cấm userinfo/query/fragment/redirect. Transport không lấy proxy/base URL ngầm từ ENV. Limits/timeout không nhận NaN, infinity, số âm hoặc kiểu dữ liệu mơ hồ. Reject duplicate YAML keys, unknown fields, broken references, numeric/boolean không hợp lệ và YAML custom tags. Dùng safe loader, dependency YAML trực tiếp trong T02. Khi file valid nhưng credential tương ứng trống hoặc thiếu, route `UNCONFIGURED` và bị skip. Health được phép hiển thị cấu hình thiếu mà không tạo network.

YAML là nguồn routing khi Gateway enabled. `LLM_GATEWAY_CONFIG_PATH` chọn một file (mặc định `config/llm_gateway.yaml`, relative theo project root), process ENV ưu tiên dotenv. Đọc `LLM_GATEWAY_ENABLED` trước, chỉ load YAML khi enabled. Legacy ENV và CLI overrides không tham gia chọn route hoặc wire options ở mode này. Thông báo xung đột chỉ nêu tên biến. Legacy settings lấy giá trị business như `PHASE12_TOP_K`/language qua phần settings độc lập, tránh import-time validation các trường routing legacy trong Gateway path. Flag false chọn legacy toàn phiên và không đọc registry. Credentials lấy từ `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY` theo profile, loại khỏi dump và startup errors.

| ENV control | Default và validation |
| --- | --- |
| `LLM_GATEWAY_ENABLED`, `LLM_GATEWAY_AUTO_FAILOVER`, `LLM_GATEWAY_ALLOW_PAID_MODELS` | Mặc định false, true, false. Failover false chỉ xét primary. Paid true chỉ mở điều kiện đầu tiên, route vẫn cần approval, task allow_paid, pricing và quota/cost binding phù hợp. |
| `LLM_GATEWAY_MAX_ATTEMPTS_PER_TASK`, `LLM_GATEWAY_MAX_ATTEMPTS_PER_ROUTE` | Tương ứng 2 (chấp nhận 1–2) và 1 (chỉ chấp nhận 1). Không tăng được quá giới hạn thiết kế. |
| `LLM_GATEWAY_ATTEMPT_TIMEOUT_SECONDS`, `LLM_GATEWAY_QUERY_DEADLINE_SECONDS`, `LLM_GATEWAY_RECOMMENDATION_DEADLINE_SECONDS`, `LLM_GATEWAY_JUDGE_DEADLINE_SECONDS` | 25, 30, 45, 30 giây. Judge 30 là default của thiết kế. Các giá trị còn lại khớp cấu hình workspace. Các giá trị dương, hữu hạn. Effective timeout chịu remaining deadline. |
| `LLM_GATEWAY_DEFAULT_COOLDOWN_SECONDS` | 60 giây mặc định, giới hạn recovery backoff mặc định từ 60 đến 900 giây khi cấu hình mặc định. Cấu hình hữu hạn trong khoảng (0, 900]. `Retry-After` lớn hơn 900 vẫn giữ deadline do provider yêu cầu nếu parse được an toàn. |
| `LLM_GATEWAY_TELEMETRY_ENABLED`, `LLM_GATEWAY_TELEMETRY_DIR`, `LLM_GATEWAY_LOG_PROMPTS`, `LLM_GATEWAY_LOG_RESPONSES` | Metadata telemetry mặc định bật, thư mục local mặc định `data/interim/llm_gateway`. Prompt/response logging mặc định false. V1 từ chối true để giữ audit artifact metadata-only. |

Giá `unknown` bị deny trước dispatch. Route free cần evidence theo deployment về điều khoản và entitlement account, hậu tố `:free` chỉ là model ID. Route paid cần giá đáng tin cậy cho mọi thành phần có thể tính phí, ước lượng chi phí tối đa có upper bound và quota cost hữu hạn. Registry không lookup giá, model hoặc quyền bằng network. Snapshot sót evidence phải fail closed qua disable hoặc admission deny. T17 có thể dùng harness validation tách runtime để kiểm candidate chưa approved. Harness chỉ dispatch sau khi operator cấp quyền cho exact route, credential scope, deadline và trần số request/token/cost, với guard tính phí riêng. Không mở runtime eligibility cho candidate qua flag validation.

## Routing, deadline và failover

1. Validate request, đặt `task_deadline = started_mono + task_budget_s`, `effective_deadline = min(task_deadline, parent_deadline_mono nếu có)`. Đo trên cùng monotonic clock được inject khi test. Kiểm deadline trước và sau prepare/response validation và ngay sát dispatch. Timeout toàn attempt gồm I/O, bounded decode và schema validation, lấy `min(attempt_timeout, effective_deadline - now)`. Đặt transport timeout và outer async timeout. Giới hạn payload và kiểm elapsed sau xử lý đồng bộ để output quá hạn không thành success.
2. Duyệt ordered routes. Với mỗi route, kiểm enabled/approval/capability, credential, cost permission, health, quota và concurrency. Prepare local dựa vào exact prompt/schema. Allocate reservation atomic khi ready. Recheck admission và thời gian ở dispatch. Nếu route bị skip, ghi reason nhưng không tiêu attempt. Khi failover false, bỏ qua mọi route sau primary kể cả primary bị skip. Khi failover true, xét route tiếp theo khi primary bị skip hoặc attempt có category cho phép. Luồng tuần tự, mỗi route chỉ được dispatch một lần và tối đa hai dispatch trong một task.
3. Khi provider trả output hợp lệ trong hạn, chọn route đó, finalize đúng một record cho dispatch và return. Nếu lỗi, settle usage và health trước khi xét route tiếp theo. Khi hết tuyến hợp lệ hoặc hết attempt budget, trả về lỗi theo contract. Không sleep/wait cho cooldown trong request. Nếu hết task budget, raise `DEADLINE_EXCEEDED` scope task. Caller áp dụng contract fallback nếu API còn thời gian. Nếu hết parent budget, propagate scope parent xuyên qua Phase 8/12 để API dùng mapping HTTP 504 hiện tại. Outer API timeout vẫn là giới hạn cuối.
4. Nếu task bị caller cancel, finalize `CANCELLED` cho attempt đã dispatch, settle reservation/release slot trong cleanup, rồi re-raise `CancelledError`. Không chọn backup hay dựng business fallback khi cancel. Timeout/cancel có thể xảy ra sau khi provider bắt đầu tính phí. Không suy diễn rằng upstream đã dừng.

### Error taxonomy

| Category | Ví dụ | Backup và health |
| --- | --- | --- |
| `INVALID_REQUEST`, `CONFIGURATION_ERROR` | Schema binding sai, prompt contract sai, YAML/capability declaration sai | Dừng task hoặc startup. Không provider call. |
| `NO_ELIGIBLE_ROUTE` | `DISABLED`, `UNAPPROVED`, `UNCONFIGURED`, `COST_DENIED`, `COOLDOWN`, `QUOTA_EXHAUSTED`, `CAPACITY_EXHAUSTED` | Skip route hiện tại, xét route khác theo policy. Nếu 0 dispatch và hết routes, kết thúc với category này. Skip reason chi tiết ở task summary. |
| `AUTHENTICATION`, `PERMISSION_DENIED` | 401 hoặc credential 403. 403 model-scope nếu biết chính xác | Chặn profile/route theo scope cho snapshot hoặc tới restart/credential rotation. Chỉ xét backup đủ điều kiện. Không gửi lại vào profile đã bị chặn. |
| `RATE_LIMITED` | 429 hoặc provider quota signal được nhận dạng | Cooldown provider profile/shared account budget, xét backup eligible. |
| `PROVIDER_UNAVAILABLE`, `NETWORK_ERROR`, `ATTEMPT_TIMEOUT` | 408, 5xx. Transport/connection error. Timeout một attempt | Cooldown theo policy. Xét backup nếu còn deadline và budget. |
| `INCOMPATIBLE_ROUTE` | 400/404/422 được nhận dạng rõ là unsupported model/schema/params/context hoặc sai model identity | Mark unavailable theo route/schema nếu cấu hình route gây lỗi. Vượt context riêng request chỉ skip request đó. Có thể sang backup phù hợp. Không đổi JSON mode rồi gửi lại. |
| `INVALID_OUTPUT` | Empty/truncated output, JSON malformed hoặc Pydantic validation lỗi | Xét backup phù hợp nếu còn budget. Chuỗi lỗi schema/encoding tính vào health route. Usage đã nhận vẫn được lưu. |
| `PROVIDER_REJECTED`, `INTERNAL_ERROR` | Policy refusal có tín hiệu rõ, 4xx còn lại, lỗi provider request không phân loại, lỗi invariant/code Gateway | Dừng. Ghi lý do đã sanitize. Policy refusal không phạt health. |
| `DEADLINE_EXCEEDED`, `CANCELLED` | Hết task/parent deadline hoặc caller cancel | Dừng, không backup. Cancellation là category telemetry. Caller nhận `CancelledError`. |

### Health/cooldown và quota

- **Scope.** Mỗi worker có health state theo provider profile và route/schema. Provider profiles dùng chung cùng credential/endpoint có rate/cost limits dùng chung trong worker. Key nội bộ không chứa credential raw. Route-specific compatibility giữ tách. Không dùng distributed coordination trong V1. T17/T18 phải dùng một worker hoặc cấu hình quota từng worker sao cho tổng giới hạn nằm trong quota đã duyệt.
- **Cooldown.** Active → cooldown sau 429 hoặc lỗi transient như timeout/network/5xx. Exponential backoff theo consecutive count từ default tới cap. 429 dùng `Retry-After` delta-seconds hoặc HTTP-date, hay structured retry delay Gemini nếu có. Convert một lần từ wall clock UTC sang monotonic và lấy max với backoff. Fallback default khi header thiếu/sai. Khi hết cooldown, chỉ giữ một admission thử (half-open) bằng atomic reservation trong worker. Thành công reset streak. Thất bại transient đặt cooldown lại. Skip/pre-dispatch cancel trả probe slot, post-dispatch cancel release nhưng không tính success. Auth/permission hoặc route compatibility permanent bị block theo snapshot. Corrected config/credential và restart reset. Health đọc snapshot, không probe.
- **Cập nhật concurrent.** 429, network error, attempt timeout và 5xx cập nhật profile health. Lỗi encoding/schema cập nhật cooldown của route/schema. Lease half-open gắn với health generation để response thành công từ attempt cũ không xoá cooldown mới do attempt khác vừa đặt. Trạng thái deny hoặc cooldown của bất kỳ scope áp dụng nào đều chặn route.
- **Admission.** Reserve request count (rolling 60s), concurrent slot, token ceiling (UTC day) và estimated maximum cost (UTC day nếu áp dụng) atomically trước dispatch. Chỉ gauge theo configured limits, không coi counter là quota vendor. Nếu quota token/cost cần upper bound đáng tin cậy mà không có, deny. Token upper bound dùng tokenizer đã xác minh hoặc documented conservative bound đủ bao cả prompt overhead/reasoning. Không dựa vào ước lượng tuỳ ý theo ký tự cho cost hard cap. Route free với budget token không giới hạn vẫn chịu request/concurrency policy nếu được cấu hình.
- **Settlement.** Commit một request tại dispatch kể cả HTTP lỗi/timeout. Release reservation khi chưa dispatch. Khi đã dispatch, reconcile actual usage/statements nếu biết. Nếu unknown giữ reservation đến khi window reset. Reject lượt sau nếu actual usage vượt cap dù do provider báo khác estimate. In-flight slot luôn release, kể cả cancellation. Không giữ lock trong network I/O. Worker restart reset counters, không dùng reset để khẳng định còn upstream quota.
- **CLI budget.** CLI factory có thể inject một run budget guard ở composition root. Guard nhận metadata safe của route và estimated bound, reserve cùng admission, commit tại dispatch và settle theo `AttemptRecord` đúng một lần. Việc reject guard khiến route không dispatch. Guard không được mở rộng registry, deadline hoặc policy. Pacing của experiment vẫn thuộc runner và phải nằm trong run budget.

## Telemetry và tính usage

| Record | Fields và invariants |
| --- | --- |
| `GatewayUsage` | `input_tokens`, `output_tokens`, `total_tokens`, `reasoning_tokens` là `int \| None` không âm, `estimated_cost_usd` là decimal không âm hoặc null, kèm `pricing_ref: str \| None`. Missing/partial giữ null cho field chưa biết. Giữ số 0 đã được provider xác nhận. Chỉ derive total khi input/output đều biết và semantics provider đồng nhất, không cộng reasoning hai lần. Tính estimate khi giá đáng tin và sufficient usage, hoặc 0 với route đã xác minh free. |
| `AttemptRecord` | `request_id`, `task_id`, `task`, `profile`, `schema_id`, `attempt_number` (1-based), `route_index` (0-based), `route_id`, `provider`, `model`, optional `reported_model`, `started_at_utc`, `latency_ms`, optional `http_status`, `outcome=success\|error\|cancelled`, `error_category`/safe `reason_code`, `usage`, `system_chars`, `user_chars`, `context_chars`, `is_failover_route`. `context_chars` là tổng số ký tự của system và user prompt theo Python `len`, báo riêng từng phần và cố định qua các attempts. |
| Task summary | Kết quả và elapsed, actual winning route/provider/model hoặc null, ordered skip reasons, attempt count, failover flag và tổng observed per-attempt usage. Field tổng authoritative là null nếu có attempt thiếu field. Có thể ghi thêm known subtotal và missing-attempt count riêng. 0 attempts có tổng 0. |

Task summary và từng attempt dùng unique key `(task_id, attempt_number)` cho attempt, tránh cộng từ cả summary lẫn records. Runtime record tạo đúng một lần khi dispatch, finalize một lần cả timeout/cancel/error, sink không yêu cầu network. Bounded queue và rotating local JSONL với giới hạn kích thước/file count do T08 đặt và test. Telemetry I/O failure/drop tăng counter an toàn và không đổi business outcome. Metadata telemetry không dùng request/task IDs làm labels metrics. Normalized timestamps dùng UTC, latency monotonic. Correlation ID do server cấp hoặc HMAC qua incoming client ID để tránh ghi nội dung tùy ý. Giữ cùng giá trị nội bộ giữa hai task. Allowlist fields và deny config/SDK dumps, headers/query, exception causes, prompt/response text và arbitrary provider strings. Raw payload xác thực để dùng nghiệp vụ chỉ đi qua process memory. Actual provider/model từ route thắng được ghi riêng với catalog fallback hoặc judge skip, không thêm field vào public schema.

## Các tình huống kiểm contract bằng mock

| Tình huống | Kỳ vọng tại ranh giới transport và caller |
| --- | --- |
| Primary hợp lệ, backup approved | 1 dispatch tới primary, 1 attempt record, `failover_used=false`. |
| Primary 429 hoặc 503, backup đủ điều kiện | 2 dispatch theo thứ tự YAML. 429 cập nhật profile cooldown. Response dùng provider/model và usage của attempt 2, task summary giữ usage hai attempts. |
| Primary cooldown, backup hợp lệ | 1 dispatch với `attempt_number=1`, `route_index=1`, `failover_used=true` và primary có skip reason. Nếu failover tắt thì 0 dispatch. |
| Primary timeout sau 25s, task budget 30s | Backup có tối đa 5s trừ thời gian đã dùng cho bookkeeping và chịu parent deadline ngắn hơn nếu có. Hết hạn trước dispatch thì không gọi backup. |
| Primary error, backup pending hoặc policy cấm paid | 1 dispatch. Phase 12 giữ catalog fallback. Phase 8 invalid result thì retrieval không chạy. |
| Output sai schema, response có usage | Attempt record lưu usage dù error. Backup hợp lệ được xét nếu còn thời gian. Khi response không có usage, field tương ứng là null. |
| Caller cancel trước hoặc sau dispatch | 0 hoặc 1 dispatch và đồng số attempt records. Reserved slots được release. Caller nhận `CancelledError` và không chạy backup hoặc business fallback. |
| Judge không có eligible route trước dispatch hoặc live thất bại sau dispatch | Skip/demo được đánh dấu khi 0 dispatch vì thiếu route. Failure sau dispatch không có rubric score do live. |
