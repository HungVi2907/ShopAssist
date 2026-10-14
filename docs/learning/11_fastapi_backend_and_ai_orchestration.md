# Bài 11: FastAPI Backend & Điều Phối AI Pipeline Thực Chiến

> **Mục tiêu bài học:**  
> Hiểu rõ tại sao một hệ thống AI thực tế không thể chỉ là các script rời rạc chạy trên Jupyter Notebook, mà cần một Backend kiến trúc chuẩn mực để quản lý tài nguyên, điều phối các pha xử lý AI (Phases 8–12), bảo vệ thông tin bí mật (API Keys, Database Credentials) và phục vụ người dùng thông qua giao diện REST API hiệu năng cao.

---

## 1. Tại Sao Ứng Dụng AI Cần Một Backend Chuyên Dụng?

Rất nhiều người khi mới học AI thường dừng lại ở mức: viết một file Python, gọi hàm `predict()` hoặc `client.generate_content()`, và in kết quả ra màn hình terminal. Tuy nhiên, khi đưa vào sản phẩm thực tế (ví dụ: kết nối với ứng dụng Mobile, Web hoặc Telegram Bot), bạn gặp ngay các rào cản chí mạng:

1. **Bảo mật bí mật (Secret Protection):**  
   Bạn **không bao giờ** được để API Key (Gemini, OpenRouter) hay Database Connection String ở phía Client (Frontend hoặc Telegram Client). Nếu Client gọi trực tiếp LLM, toàn bộ API Key và Database của bạn sẽ bị đánh cắp trong tích tắc. Backend đóng vai trò là bức tường lửa bảo vệ toàn bộ thông tin nhạy cảm.
2. **Chi phí khởi tạo tài nguyên (Resource Initialization Overhead):**  
   Mô hình embedding (như BGE-small-en-v1.5) nặng hàng trăm Megabytes; chỉ mục TF-IDF chứa 8,405 tài liệu sản phẩm; cơ sở dữ liệu pgvector yêu cầu thiết lập connection pool có kiểm tra SSL. Nếu mỗi khi người dùng hỏi một câu mà hệ thống lại load lại mô hình từ đĩa thì thời gian phản hồi sẽ mất hơn 20 giây! Backend cho phép tải mô hình một lần duy nhất vào bộ nhớ RAM khi khởi động và tái sử dụng cho hàng nghìn lượt truy vấn tiếp theo.
3. **Điều phối chuỗi AI phức tạp (AI Pipeline Orchestration):**  
   Một hệ thống RAG thực tế không chỉ có một cuộc gọi LLM đơn lẻ. Nó gồm một chuỗi các mắt xích:
   - **Phase 8:** Phân tích câu hỏi và bóc tách ràng buộc (LLM Query Understanding).
   - **Phase 9:** Mã hóa sở thích người dùng thành vector 384 chiều (Dense Embedding).
   - **Phase 10:** Tìm kiếm kết hợp (pgvector + TF-IDF lexical search).
   - **Phase 11:** Tái xếp hạng (Reranking) và đối khớp văn bản sản phẩm chuẩn mực.
   - **Phase 12:** Sinh lời tư vấn có căn cứ và kiểm chứng trích dẫn (Grounded Recommendation).  
   Backend chính là "nhạc trưởng" (Orchestrator) đảm bảo các bước diễn ra đúng thứ tự, dữ liệu truyền qua các pha đúng chuẩn và tự động ngắt sớm (short-circuit) khi gặp lỗi.

---

## 2. Kiến Trúc FastAPI & Mô Hình Bất Đồng Bộ (Asynchronous I/O)

FastAPI là framework web hiện đại bậc nhất trong hệ sinh thái Python nhờ hỗ trợ chuẩn `async`/`await` nguyên bản, tích hợp chặt chẽ với Pydantic v2 và tự động sinh tài liệu Swagger/OpenAPI.

### Sự khác biệt cốt lõi: Async I/O vs Synchronous
- **Synchronous (Đồng bộ truyền thống):** Khi gửi một request tới LLM (mất khoảng 1–2 giây để sinh văn bản) hoặc query PostgreSQL, thread xử lý sẽ bị "treo" (block). Nếu có 10 người dùng đồng thời, server cần 10 threads riêng biệt; nếu có 100 người dùng, server sẽ cạn kiệt tài nguyên.
- **Asynchronous (Bất đồng bộ với `async`/`await`):** Khi server gửi request tới Gemini hoặc Supabase, nó lập tức "nhường" quyền xử lý (yield event loop) để phục vụ request của người dùng khác trong lúc chờ kết quả từ mạng. Nhờ vậy, một tiến trình đơn (single process) có thể xử lý hàng trăm kết nối đồng thời với mức tiêu hao RAM cực thấp.

Trong ShopAssist:
```python
# Ví dụ route bất đồng bộ trong src/shopassist/api/routes/recommendations.py
@router.post("/recommend", response_model=RecommendationResponse)
async def generate_recommendations(
    payload: RecommendationRequest,
    orchestrator: RecommendationOrchestrator = Depends(get_orchestrator),
) -> RecommendationResponse:
    # Non-blocking await cho phép xử lý nhiều request song song
    response = await orchestrator.orchestrate(request=payload, request_id=request_id)
    return response
```

---

## 3. Cạm Bẫy Lớn: Phân Định Async I/O và Sync CPU-Bound Trong AI

Đây là lỗi phổ biến nhất của các kỹ sư chuyển từ lập trình Web thông thường sang làm AI Backend: **đưa các phép tính toán ma trận nặng của AI trực tiếp vào hàm async!**

### Vấn đề:
Khi bạn chạy `encoder.encode(query)` bằng PyTorch hoặc tính tích vô hướng ma trận thưa trong TF-IDF (`matrix.dot(vector)`), đây là các tác vụ **CPU-bound** (ngốn 100% CPU để tính toán). Nếu bạn gọi một hàm đồng bộ CPU-bound bên trong hàm `async def`, toàn bộ Event Loop của FastAPI sẽ bị "đóng băng", khiến tất cả các người dùng khác không thể gửi nhận request!

### Giải pháp kỹ thuật trong ShopAssist:
Chúng ta sử dụng `asyncio.to_thread()` để đẩy các tác vụ CPU-bound ra worker threadpool riêng, giữ cho event loop luôn thông suốt:

```python
# Trích đoạn từ src/shopassist/api/services/orchestrator.py

# 1. Tác vụ I/O mạng gọi LLM: Dùng await trực tiếp
query_result = await self.query_engine.parse_query_async(query_text)

# 2. Tác vụ CPU-bound (BGE embedding tính toán tensor): Đẩy sang threadpool!
preference_result = await asyncio.to_thread(
    self.preference_service.represent, query_result
)

# 3. Tác vụ I/O cơ sở dữ liệu pgvector: Dùng await trực tiếp
retrieval_result = await self.hybrid_service.retrieve(...)

# 4. Tác vụ CPU-bound (Reranking & sắp xếp danh sách ứng viên): Đẩy sang threadpool!
reranking_result = await asyncio.to_thread(
    self.reranking_service.rerank, ...
)
```

---

## 4. Quản Lý Vòng Đời Tài Nguyên Thông Minh Với FastAPI Lifespan

Trước FastAPI 0.93, người ta thường dùng các sự kiện `@app.on_event("startup")` và `@app.on_event("shutdown")`. Hiện nay, chuẩn mực hiện đại là **Lifespan Context Manager** (`@asynccontextmanager`).

Lifespan cho phép gom toàn bộ logic khởi tạo và dọn dẹp tài nguyên vào một khối code duy nhất:

```python
# Trích đoạn từ src/shopassist/api/main.py
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # =========================================================================
    # GIAI ĐOẠN KHỞI ĐỘNG (STARTUP): Tải tài nguyên một lần duy nhất vào RAM
    # =========================================================================
    logger.info("Initializing ShopAssist backend services and model assets...")
    
    # 1. Cấu hình event loop cho Windows
    ensure_windows_event_loop_policy()

    # 2. Khởi tạo connection pool SQLAlchemy
    engine = get_async_engine(pool_size=5, max_overflow=2, pool_pre_ping=True)
    app.state.engine = engine

    # 3. Nạp chỉ mục TF-IDF (8,405 sản phẩm)
    tfidf_index = TFIDFIndex.load(DEFAULT_TFIDF_ARTIFACT_DIR)
    app.state.tfidf_index = tfidf_index

    # 4. Tải mô hình BGE Embedding (384D) một lần và dùng chung cho cả Phase 9 & 10
    dense_query_encoder = DenseQueryEncoder()
    app.state.query_encoder = dense_query_encoder

    # 5. Khởi tạo Orchestrator điều phối
    orchestrator = RecommendationOrchestrator(...)
    app.state.orchestrator = orchestrator

    yield  # Ứng dụng chạy và phục vụ các HTTP requests ở đây

    # =========================================================================
    # GIAI ĐOẠN DỌN DẸP (SHUTDOWN): Đóng kết nối an toàn khi tắt server
    # =========================================================================
    logger.info("Shutting down ShopAssist backend...")
    await query_engine.client.aclose()      # Đóng HTTP session của Gemini
    await provider._http_client.aclose()    # Đóng HTTP session của OpenRouter
    await engine.dispose()                  # Giải phóng Connection Pool Database
```

> **Lợi ích:** Không tải lại mô hình khi có request mới; giải phóng 100% kết nối cơ sở dữ liệu và socket mạng khi tắt app, tránh hiện tượng connection leak và cạn kiệt bộ nhớ.

---

## 5. Chuẩn Hóa Hợp Đồng Dữ Liệu (Data Contract) Với Pydantic v2

Trong kiến trúc phần mềm chuyên nghiệp, **Data Contract** là bản giao kèo bất biến giữa Frontend (hoặc Telegram Bot) và Backend. Nếu dữ liệu đầu vào không hợp lệ, hệ thống phải từ chối ngay lập tức trước khi gọi các dịch vụ AI tốn tiền.

Trong `src/shopassist/api/schemas.py`:
- `RecommendationRequest`:
  - `query`: chuỗi bắt buộc, từ 1 đến 500 ký tự (chống spam chuỗi quá dài gây tràn context LLM).
  - `top_k`: số nguyên từ 1 đến 20 (chống client yêu cầu lấy 10,000 sản phẩm gây sập RAM).
  - `language`: kiểm tra thuộc tập `{"auto", "en", "vi"}`.
  - `model_config = ConfigDict(extra="forbid")`: **Nghiêm cấm các trường lạ** trong JSON body để phát hiện sớm các lỗi sai chính tả từ phía client.

---

## 6. Bộ Chuyển Đổi Ngữ Nghĩa Giá Tiền (PriceBoundaryAdapter)

Một ví dụ điển hình của việc xử lý xung đột hợp đồng giữa các pha trong AI:

### Bối cảnh:
- **Phase 8 Schema v1** chỉ trích xuất giá trị số: `min_price: 3000.0`, `max_price: 3000.0`. Nó **không** có cờ cho biết đây là điều kiện ngặt (`<`) hay bao gồm (`<=`).
- **Phase 10** có cơ chế bảo vệ nghiêm ngặt: Nếu truy vấn có điều kiện giá mà không rõ toán tử là `<` hay `<=`, nó sẽ từ chối xử lý (`UNSUPPORTED_INTENT`) để tránh lọc sai sản phẩm.

### Giải pháp kỹ thuật:
Thay vì sửa Phase 8 (đã bị đóng băng nghiệm thu) hoặc đoán mò rằng mọi mức giá đều là `<=`, chúng ta xây dựng `PriceBoundaryAdapter` tại tầng API (`src/shopassist/api/price_adapter.py`):
- Phân tích cú pháp văn bản gốc:
  - "under 3000", "below 2000", "dưới 2000" -> xác định chắc chắn là `<` (`max_inclusive = False`).
  - "up to 3000", "maximum 3000", "tối đa 3000", "3000 đổ lại" -> xác định là `<=` (`max_inclusive = True`).
  - "between 1000 and 3000", "từ 1000 đến 3000" -> xác định khoảng bao gồm hai đầu.
  - "around 2000", "khoảng 2000" -> là mức giá ước lượng, không có toán tử biên an toàn -> trả về `is_resolved = False`, kích hoạt trạng thái `CLARIFICATION_REQUIRED` để người dùng xác nhận lại!

---

## 7. Short-Circuiting & Xử Lý Lỗi An Toàn (Fail-Closed & Fallback)

Trong quy trình AI Pipeline nhiều bước, **Short-Circuiting (Ngắt sớm)** là nguyên tắc sống còn: khi một bước phía trước phát hiện lỗi hoặc yêu cầu người dùng làm rõ, hệ thống phải **dừng lại ngay lập tức**, không được gọi các bước phía sau để tránh lãng phí chi phí LLM và tài nguyên database.

Bảng điều hướng trạng thái trong `RecommendationOrchestrator`:

```text
Truy vấn chứa từ phủ định ("no leather")
   │
   ├─► DỪNG NGAY: Trả về UNSUPPORTED_INTENT (Không gọi Phase 8)
   ▼
Phase 8: Câu hỏi mơ hồ ("recommend something nice")
   │
   ├─► DỪNG NGAY: Trả về CLARIFICATION_REQUIRED (Không gọi Phase 9, 10, 11, 12)
   ▼
Phase 8: Đơn vị tiền tệ lạ ("500 USD")
   │
   ├─► DỪNG NGAY: Trả về UNSUPPORTED_INTENT (Catalog dùng INR)
   ▼
Phase 10: Không có sản phẩm nào thỏa mãn bộ lọc
   │
   ├─► DỪNG NGAY: Trả về NO_RESULTS (Không gọi Phase 11, 12)
   ▼
Phase 12: LLM OpenRouter bị Rate Limit (HTTP 429)
   │
   └─► CỨU CÁNH: Chuyển sang DETERMINISTIC_FALLBACK (Dùng rule sinh văn bản từ catalog)
```

> [!IMPORTANT]
> **Deterministic Fallback:** Khi nhà cung cấp LLM bên ngoài bị quá tải hoặc sập mạng, hệ thống ShopAssist không trả về lỗi HTTP 500 cho người dùng. Thay vào đó, nó sử dụng thông tin sản phẩm có sẵn từ Phase 11 để tạo câu trả lời mẫu có căn cứ, đồng thời đánh dấu `fallback_used: true` trong metadata. Khách hàng vẫn nhận được danh sách sản phẩm gợi ý chuẩn xác!

---

## 8. Giám Sát, Tracing & Đo Lường (Observability)

Một Backend AI đạt chuẩn production phải cho phép kỹ sư biết chính xác mỗi request tiêu tốn bao nhiêu thời gian và tiền bạc:

1. **Request Tracing:** Mỗi request được middleware tự động gắn một `request_id` dạng UUID4. Mã này được trả về trong header `X-Request-ID` và nằm trong toàn bộ log ghi vết.
2. **Đo độ trễ theo từng chặng (Stage Latency Breakdown):** Response trả về chi tiết số mili-giây tiêu tốn cho từng pha:
   ```json
   "stage_latencies_ms": {
     "phase8_query_understanding": 450.2,
     "phase9_preferences": 25.1,
     "phase10_hybrid_retrieval": 110.8,
     "phase11_reranking": 1.9,
     "phase12_recommendation": 680.4
   }
   ```
3. **Theo dõi Token & Chi phí:** Tính tổng số prompt tokens và completion tokens giữa các LLMs, ước lượng chi phí USD chính xác.

---

## 9. Chiến Lược Kiểm Thử Backend (Testing Strategy)

Trong Phase 15, chúng ta áp dụng mô hình kim tự tháp kiểm thử gồm 3 tầng:

1. **Unit Testing (Tầng đơn vị):** Kiểm tra độc lập logic của Pydantic schemas, `PriceBoundaryAdapter`, `InMemorySessionStore` và các kịch bản ngắt sớm của `RecommendationOrchestrator`. (Chạy cực nhanh: 74 tests trong ~9 giây).
2. **Mocked API Integration Testing (Tầng tích hợp mô phỏng):** Sử dụng `httpx.AsyncClient` gửi request HTTP ảo qua toàn bộ pipeline FastAPI, kiểm tra các mã lỗi HTTP 422, 503, 504, 500, header tracing và khả năng xử lý đồng thời (16 tests trong ~10 giây). Không tiêu tốn bất kỳ chi phí API nào.
3. **Live Smoke Testing (Tầng kiểm thử thực tế):** Gửi request thật tới PostgreSQL Supabase, mô hình BGE thật, TF-IDF thật và các dịch vụ LLM bên ngoài để nghiệm thu hệ thống trong môi trường thực.

---

## 10. Tổng Kết Bài Học (Key Takeaways)

1. **Không bao giờ gọi LLM trực tiếp từ Client:** Luôn đặt một Backend có xác thực, rate limit và quản lý vòng đời tài nguyên ở giữa.
2. **Không block Event Loop:** Tác vụ I/O mạng dùng `async`/`await`; tác vụ tính toán tensor/ma trận CPU-bound bắt buộc phải bọc qua `asyncio.to_thread()`.
3. **Khởi tạo tài nguyên với Lifespan:** Tải mô hình và connection pool một lần duy nhất lúc khởi động server, chia sẻ tài nguyên giữa các request.
4. **Short-circuiting cứu nguy chi phí:** Dừng quy trình ngay khi phát hiện câu hỏi không hợp lệ, không để request lỗi tiếp tục gọi LLM.
5. **Deterministic Fallback là cứu cánh:** Đảm bảo hệ thống vẫn trả về sản phẩm thật ngay cả khi API LLM bên thứ ba bị quá tải.
