# ShopAssist Phase 18 V1 — T00 Repository Audit & Preflight

**Ngày 2026-11-20 (Asia/Saigon). Trạng thái T00 — PASS sau T00-FIX.** Regression offline thiếu DSN có 679 test đậu và 0 lần thử kết nối bên ngoài. T01 được phép bắt đầu trong lượt riêng.

## Repository và phạm vi

- Audit trên branch `main`, commit `c740d50de1976e8aafa371000644ae227f453cf0`, đồng bộ với ref `origin/main` hiện có tại máy (0 ahead, 0 behind). Worktree đã có thay đổi ở `data/interim/phase5_8_knowledge_base_validation_report.json` và 28 tệp untracked trong `data/interim/runtime_baseline/` trước T00.
- Đọc README, development status và kế hoạch Phase 18 V1 đính kèm. Tại commit được audit, `docs/phase18_implementation_plan.md`, `config/llm_gateway.yaml` và package `shopassist.llm_gateway` đều chưa có. T02 của kế hoạch là bước tạo loader và YAML. Các model mục tiêu bên dưới lấy từ bản đính kèm. [README](../README.md), [Development status](development_status.md)
- T00 ghi audit và [execution log](phase18_execution_log.md). T00-FIX sửa xử lý lỗi kết nối Supabase và bổ sung test. Regression dùng dữ liệu, fixture và checkpoint có sẵn, với kết quả JUnit lưu trong thư mục `.deps/` đã được Git ignore.

## Call-site inventory và retry

| Luồng | Nơi gọi và dependency | Retry / lifecycle hiện tại |
| --- | --- | --- |
| Phase 8 runtime | `RecommendationOrchestrator.orchestrate` → `QueryUnderstandingEngine.parse_query_async` → `GeminiClient.generate_structured_async` → `google.genai.Client.aio.models.generate_content`. Client lazy, yêu cầu JSON theo Pydantic `QueryUnderstandingOutput` schema v1. [Orchestrator](../src/shopassist/api/services/orchestrator.py), [Query engine](../src/shopassist/llm/query_understanding.py), [GeminiClient](../src/shopassist/llm/gemini_client.py) | Client đặt SDK `attempts=1`. Wrapper thử tối đa 4 lần theo mặc định (1 + 3 retry) cho 429, 500, 502, 503, 504, timeout và `ConnectionError`. Mỗi lần có timeout 30 giây. Backoff có jitter và đọc gợi ý `retryDelay` từ nội dung lỗi. Lỗi JSON/schema đi thẳng về engine. |
| Phase 12 OpenRouter | `RecommendationService.generate` → factory chọn `OpenRouterProvider` → `httpx.AsyncClient.post` tới `/chat/completions`. Gửi `json_schema`, xác thực nội dung bằng parser chung. [RecommendationService](../src/shopassist/recommendation/core.py), [Providers](../src/shopassist/recommendation/provider.py) | Wrapper có 3 retry mặc định cho 429, 500/502/503/504, timeout và network error. 429 dùng `Retry-After` dạng số nguyên giây cùng backoff. HTTP 400 ở mode `json_schema` gửi thêm một request bằng `json_object` ngoài bộ đếm retry. Có thể gửi 5 request với cấu hình mặc định, hoặc 2 request khi đặt retry bằng 0. |
| Phase 12 Groq | Cùng service/factory → `GroqProvider` → `groq.AsyncGroq.chat.completions.create`. Yêu cầu strict JSON Schema, truyền `reasoning_effort` và `max_completion_tokens`. [Providers](../src/shopassist/recommendation/provider.py) | Wrapper có 3 retry mặc định cho rate limit, kết nối/timeout và các 5xx kể trên. Constructor chưa đặt `max_retries` cho SDK. `groq 1.7.0` cài trên máy mặc định 2 SDK retry, nên chuỗi lỗi mà cả hai tầng cùng retry có thể tạo tối đa 12 request. |
| Phase 8 CLI và experiments | `parse_user_query.py` và `evaluate_query_understanding.py` gọi query engine. `run_phase8_experiments.py` và `run_phase8_2_experiments.py` gọi Gemini qua các experiment runner với override theo kịch bản. `test_gemini_connection.py` gọi SDK model listing và structured generation qua wrapper. [CLI](../scripts/parse_user_query.py), [Evaluation](../scripts/evaluate_query_understanding.py), [Experiment runner](../src/shopassist/llm/experiments/runner.py), [Phase 8.2 runner](../src/shopassist/llm/experiments/phase82/runner.py), [Diagnostics CLI](../scripts/test_gemini_connection.py) | Gemini giữ retry. Phase 8.2 dùng hook `on_attempt`/`on_response` để giữ và ghi ngân sách theo attempt, có cache thành công opt-in và mặc định dry-run. Model listing là đường gọi riêng của diagnostics. |
| Phase 12 evaluation | `scripts/evaluate_phase12.py` dựng `RecommendationService` cho evaluation và so sánh context, hỗ trợ `--provider`/`--model`. [Evaluation CLI](../scripts/evaluate_phase12.py) | Thừa hưởng retry của provider. CLI hiện đặt `--live` mặc định `True`, nên gọi script thông thường có thể phát sinh inference. |
| Phase 14 judge | `scripts/run_phase14_evaluation.py --run-live-judge` → `run_llm_judge` → `GeminiClient.generate_structured` với schema riêng của judge. Có mock mode. [Evaluation CLI](../scripts/run_phase14_evaluation.py), [Judge](../src/shopassist/evaluation/phase14_judge.py) | Thừa hưởng retry Gemini. Wrapper sync dùng `asyncio.run` và đóng client trong `finally`. |
| Phase 13 AI-Silver | `scripts/run_phase13_ai_silver.py` có adapter `OpenAICompatibleJudgeProvider` dùng `httpx` với endpoint/model từ `SHOPASSIST_SILVER_{slot}_*` cho `A`, `B`, `ADJUDICATOR`. Endpoint có thể trỏ tới provider tương thích. Đây là luồng benchmark độc lập cần được nhận diện khi audit migration script ở T14. [CLI](../scripts/run_phase13_ai_silver.py), [Judge provider](../src/shopassist/evaluation/silver.py) | Adapter sở hữu 2 retry mặc định và dùng context manager để đóng HTTP client mỗi lần. |
| FastAPI / Telegram | FastAPI lifespan tạo Phase 8 và Phase 12 service. `/api/v1/health` kiểm tra cấu hình LLM và probe DB bằng `SELECT 1` với giới hạn 5 giây. Telegram gọi REST backend qua `FastAPIRecommendationClient`. [Lifespan](../src/shopassist/api/main.py), [Health route](../src/shopassist/api/routes/health.py), [Bot client](../src/shopassist/bot/clients/recommendation.py) | API bao cả pipeline bằng `asyncio.wait_for` 90 giây (HTTP 504 khi hết hạn), bot timeout 95 giây. Lifespan đóng Gemini và OpenRouter qua thuộc tính private. Groq giữ SDK client ở `_client` và thiếu đường đóng tương ứng trong lifespan hiện tại. |

## Error handling và contract tại ranh giới migration

- **Phase 8.** Thiếu key, lỗi upstream sau retry, lỗi JSON/schema hoặc lỗi normalization đều rơi vào nhánh `is_valid=False` với hard constraints trống. Engine đặt `needs_clarification=True` trong payload nội bộ ngay cả khi provider lỗi. Orchestrator kiểm `is_valid` trước, trả `INVALID_INPUT` và dừng trước retrieval. `CLARIFICATION_REQUIRED` là nhánh riêng của kết quả hợp lệ cần người dùng làm rõ. T12 cần giữ phân biệt này khi bổ sung fail-closed. [Query engine](../src/shopassist/llm/query_understanding.py), [Orchestrator](../src/shopassist/api/services/orchestrator.py)
- **Phase 12.** Provider/parse failure dẫn đến `DETERMINISTIC_FALLBACK` từ candidate metadata và evidence hiện có. `GroundednessValidator` kiểm product IDs, citations và có thể kích hoạt fallback khi payload thiếu sản phẩm hợp lệ. Service dùng model trong settings làm provenance; dữ liệu hiện tại chưa ghi actual route hay usage theo attempt. [RecommendationService](../src/shopassist/recommendation/core.py), [GroundednessValidator](../src/shopassist/recommendation/validation.py)
- **Public API.** Contract gồm `POST /api/v1/recommend` và alias `/recommend`, readiness/liveness, response `status`, `products`, `metadata`, `usage`, cùng các status/HTTP mappings hiện tại. `top_k` nhận 1–20, mặc định API, Phase 12 và bot đều là 5. Orchestrator truyền giá trị request qua reranking và generation. Kế hoạch đặt mục tiêu Top-K=3 cho Phase 18, nên cần xác định cách áp dụng ở T01 để giữ được contract public hiện có. [API schemas](../src/shopassist/api/schemas.py), [Bot settings](../src/shopassist/bot/config.py)

## Cấu hình và dependencies

| Phạm vi | Cấu hình legacy tại HEAD | Cấu hình mục tiêu trong kế hoạch |
| --- | --- | --- |
| Phase 8 | `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL` mặc định `gemini-3.1-flash-lite`, `GEMINI_TEMPERATURE`, `GEMINI_MAX_OUTPUT_TOKENS`, `GEMINI_TIMEOUT_SECONDS`, `GEMINI_MAX_RETRIES`. Runtime gọi Gemini trực tiếp. | `gemini-3.5-flash-lite` qua YAML, fail closed khi primary không khả dụng. |
| Phase 12 | `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `PHASE12_LLM_PROVIDER` (mặc định `openrouter`), `PHASE12_LLM_MODEL` (mặc định `google/gemma-4-26b-a4b-it:free`), `OPENROUTER_BASE_URL`/referer/title, `PHASE12_LLM_*` cho timeout/tokens/reasoning/retries, cùng top-k, language và cost. `DEFAULT_GROQ_MODEL` có trong source nhưng chỉ đổi provider sẽ vẫn lấy default model của OpenRouter. | YAML định tuyến OpenRouter `baidu/ernie-5.5-flash-preview:free` → Groq `openai/gpt-oss-20b` khi đạt compatibility và cost/usage approval. Giới hạn 2 outbound requests/task, 1/route. |
| Gateway / rollback | `.env.example` có các biến legacy. Hai settings class dùng `extra="ignore"` và tạo singleton khi import. | `config/llm_gateway.yaml` là nguồn routing khi bật Gateway. ENV giữ credentials và runtime controls. `LLM_GATEWAY_ENABLED=false` là rollback theo kế hoạch T14. |

Đã kiểm tra [template](../.env.example), [LLMSettings](../src/shopassist/llm/config.py) và [RecommendationSettings](../src/shopassist/recommendation/config.py). Phép thử với dotenv tạm và giá trị giả xác nhận alias legacy, ưu tiên process ENV, chọn đúng provider qua factory và loại trường API key khỏi `model_dump()`. Việc hiện tại chấp nhận biến lạ `LLM_GATEWAY_ENABLED` chỉ cho thấy legacy reader bỏ qua biến này. Gateway loader, rollback và model compatibility chưa thể kiểm tra ở T00. Nội dung `.env` của workspace được bỏ qua ở lớp đọc dotenv trong tiến trình kiểm thử.

- **Runtime.** [pyproject.toml](../pyproject.toml) đã khai báo `google-genai`, `groq`, `httpx`, `pydantic`, `pydantic-settings` và `python-dotenv`. Môi trường chạy có Python 3.10.11, `google-genai 2.29.0`, `groq 1.7.0`, `httpx 0.28.1`, `pydantic 2.12.5`, `pydantic-settings 2.14.2`, `python-dotenv 1.2.2` và `fastapi 0.138.0`.
- **YAML và tests.** `PyYAML 6.0.3` có sẵn và xuất hiện trong [requirements Phase 13 Windows](../requirements-phase13-windows.txt), chưa là dependency trực tiếp của package. Nếu T02 dùng PyYAML, package cần khai báo để clean install có parser. Runner dùng `pytest 8.4.2` và `pytest-asyncio 0.26.0`. API/bot tests dùng mocked DB, ASGI và HTTP transports. Các test embedding/reranking dùng checkpoint đã cache khi được chọn.
- **Môi trường.** `.venv` dùng `include-system-site-packages=true`. `pip check` báo 5 xung đột sẵn có, gồm ShopAssist yêu cầu `pyarrow>=15,<20` trong khi đang cài 23.0.1, hai constraint của `uni2ts` với `python-dotenv`/Torch, OpenCV với NumPy và GluonTS với pandas. Số liệu regression dưới đây phản ánh môi trường đã kiểm tra.

## Offline regression

Chạy hai lượt bằng `.venv\Scripts\python.exe`, gọi `pytest.main` với bộ chọn dưới đây. Harness bỏ qua dotenv workspace, loại biến môi trường provider và live opt-in có sẵn, đặt Hugging Face/Transformers ở chế độ offline và chặn DNS/kết nối socket Python ra ngoài loopback. Lượt đối chứng thêm một DSN giả trỏ tới host `offline.invalid`. Không dùng Supabase, Gemini, OpenRouter, Groq hay Telegram thật.

```text
tests -q -ra -k "not test_live_" -m "not live_api"
--ignore=tests/test_gemini_integration.py
--ignore=tests/test_api_real_smoke.py
--ignore=tests/test_recommendation_real_openrouter.py
--ignore=tests/test_recommendation_real_groq.py
--ignore=tests/test_phase10_to_phase11_integration.py
```

| Lượt chạy | Kết quả | Bằng chứng cục bộ |
| --- | --- | --- |
| Baseline không cấu hình DSN | **672 passed, 1 failed, 13 deselected, 1 warning** trong 32.02s, exit 1. | `.deps/phase18-t00-regression.xml` |
| Đối chứng cùng selection, DSN giả | **673 passed, 13 deselected, 1 warning** trong 24.33s, exit 0. | `.deps/phase18-t00-configured-regression.xml` |
| Smoke test dotenv legacy với fixture giả | **PASS**, exit 0. | Alias, ENV precedence, factory và loại trường key khỏi model dump. |

Harness ghi nhận **0 lần thử kết nối bên ngoài** ở cả hai lượt regression. Trong lượt baseline, API có 99 test đậu và Telegram có 58. Phase 8 có 127, Phase 12 có 23, Phase 14 có 11. Embedding, preference, retrieval và reranking có 127 test đậu, gồm BGE và cross-encoder cached. Các số theo nhóm lấy từ JUnit XML. Cả hai lượt có cảnh báo `AsyncMock` coroutine chưa await trong `test_deterministic_fallback_flow`, đã được ghi trong development status ngày 2026-10-23.

**Lỗi baseline tại commit được audit.** `test_database_provisioning.py::test_check_connection_failure_handling` dùng mock tạo thông báo lỗi chứa project ref giả. Trước bản sửa, `check_connection()` chỉ che thông tin khi `settings.supabase_db_url` chứa `@`. Khi thiếu DSN, raw exception xuất hiện trong log và `RuntimeError`. Lượt đối chứng dùng DSN giả ban đầu xác nhận điều kiện này.

### Xác nhận sau T00-FIX

Lỗi tạo engine, kiểm tra kết nối và cleanup engine tạm dùng thông báo cố định trong log và `RuntimeError`. Traceback hiển thị cho caller bỏ qua raw driver exception. Lỗi thiếu DSN và lỗi port không hợp lệ vẫn trả `ValueError`. Unit tests dùng mock để kiểm tra cả DSN thiếu và DSN đã cấu hình, kiểm tra password/project ref trong traceback và captured logs. [DB connection](../src/shopassist/db/connection.py), [Regression tests](../tests/test_database_provisioning.py)

| Lượt chạy sau sửa | Kết quả | Bằng chứng cục bộ |
| --- | --- | --- |
| Focused `tests/test_database_provisioning.py` | **19 passed, 1 deselected**, exit 0, 8.22s. | `.deps/phase18-t00-fix-focused.xml` |
| Regression offline thiếu DSN, cùng bộ lọc T00 | **679 passed, 13 deselected, 1 warning**, exit 0, 23.94s. API/Telegram **157 passed**. | `.deps/phase18-t00-fix-regression.xml` |

Cả hai lượt ghi **0 lần thử kết nối bên ngoài**. Harness bỏ qua `.env` của workspace và gỡ `SUPABASE_DB_URL` khỏi môi trường tiến trình pytest. Chuỗi DSN mẫu chỉ nằm trong fixture unit test dùng mock. Cảnh báo `AsyncMock` trong `test_deterministic_fallback_flow` đã có ở baseline.

## Rủi ro cho các task tiếp theo

| Mức ưu tiên | Phát hiện và tác động |
| --- | --- |
| Cao | Retry lồng của Groq và JSON mode resend của OpenRouter vượt ngân sách Phase 18. Attempt count cần đối chiếu ở transport, gồm request đầu tiên và mọi lần gửi lại, trong phạm vi deadline của task và deadline HTTP. |
| Cao | Các route/model mới và quyền sử dụng hoặc chi phí của backup chưa được xác minh. Cấu hình strict JSON cho Groq và `json_schema` của OpenRouter hiện có gắn với đường gọi/model khác. Phase 8 thiếu backup đã được phê duyệt, Phase 12 có fallback metadata khi hết route hợp lệ. |
| Cao | Phase 12 hiện parse nội dung trước khi lấy usage và mặc định token thiếu thành 0. Gemini có diagnostics `usage_known`, nhưng kiểu legacy trả số 0 khi thiếu. Retry và payload lỗi có thể làm thiếu attempt telemetry. Cần thể hiện unknown trong Gateway mà vẫn giữ giá trị và kiểu trong public response. |
| Cao | Raw provider errors/body có thể đi vào log/diagnostics Phase 12, và `OPENROUTER_BASE_URL` được ghép với path mang bearer credential. Endpoint validation, redaction và ownership của các async client cần kiểm thử cùng cancellation. |
| Trung bình | Các CLI có override ENV/model, các experiment runner có cache/budget riêng và Phase 14 judge có schema riêng. Scope migration cần nhận diện từng caller để YAML có quyền quyết định routing khi bật Gateway và rollback dùng được các biến legacy. |

