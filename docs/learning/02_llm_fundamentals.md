# Bài 02 — Nền Tảng LLM Trong Thực Chiến ShopAssist

---

## 1. Khái Niệm Cốt Lõi Về Large Language Models (LLMs)

Một **Mô hình Ngôn ngữ Lớn (LLM)** về bản chất là một mạng nơ-ron Transformer khổng lồ được huấn luyện để dự đoán từ tiếp theo (Next Token Prediction) dựa trên ngữ cảnh văn bản trước đó. Khi được mở rộng lên hàng tỷ tham số (Parameters) và hàng nghìn tỷ từ (Tokens), mô hình bộc lộ khả năng suy luận ngữ nghĩa (In-context Reasoning), hiểu ngữ pháp và tuân theo chỉ dẫn (Instruction Following).

Tuy nhiên, trong kỹ thuật phần mềm, chúng ta cần nắm vững các khái niệm vận hành sau:

### 1.1. Tokens & Tokenization
- Máy tính không đọc trực tiếp từng chữ cái hay từ ngữ của con người, mà chia nhỏ văn bản thành các mẩu gọi là **Tokens** (1 token xấp xỉ 3/4 từ tiếng Anh, hoặc 1 chữ cái/ký tự tiếng Việt có dấu).
- **Ý nghĩa kỹ thuật:** Mọi nhà cung cấp API (OpenAI, Google Gemini, Groq) đều tính tiền và giới hạn tốc độ (Rate Limit) dựa trên số lượng token xử lý:
  $$\text{Tổng Token} = \text{Input/Prompt Tokens} + \text{Output/Completion Tokens}$$

### 1.2. Context Window (Cửa sổ ngữ cảnh)
- Là giới hạn số lượng token tối đa mà một mô hình có thể "nhìn thấy" trong một lần gọi (bao gồm System Prompt + User Message + Model Response).
- Ví dụ: `gemini-3.1-flash-lite` hỗ trợ context window lớn, nhưng đưa quá nhiều thông tin rác vào ngữ cảnh sẽ gây ra hiện tượng *"Lost in the Middle"* — mô hình bị phân tâm và bỏ sót thông tin quan trọng.

### 1.3. Temperature (Nhiệt độ ngẫu nhiên)
- **Temperature = 0.0:** Mô hình luôn chọn token có xác suất cao nhất (Greedy Decoding / Deterministic). Câu trả lời có tính lặp lại cao, ổn định nhất.
- **Temperature > 0.7:** Mô hình lấy mẫu ngẫu nhiên từ các token có xác suất thấp hơn, tạo ra câu trả lời phong phú, sáng tạo hơn nhưng dễ gây ảo giác.
- **Quy tắc vàng trong ShopAssist:** Với các tác vụ trích xuất dữ liệu có cấu trúc (Phase 8), **bắt buộc đặt `temperature = 0.0`** để đảm bảo tính ổn định và kiểm thử được.

---

## 2. Structured Outputs & Tại Sao Cần Pydantic?

Khi viết phần mềm truyền thống, nếu một hàm trả về chuỗi văn bản tự do, backend sẽ không thể xử lý tiếp. Chúng ta cần dữ liệu có kiểu rõ ràng (Typed Objects).

Trước đây, lập trình viên thường dùng prompt: *"Hãy trả về JSON, không nói gì thêm"*. Nhưng cách này thường xuyên bị lỗi:
- Mô hình thêm lời mở đầu: *"Here is your JSON:"* làm lỗi hàm `json.loads()`.
- Thiếu các trường bắt buộc, hoặc sai kiểu dữ liệu (trả về chuỗi `"2000"` thay vì số thực `2000.0`).

### Giải pháp của ShopAssist: Schema-Constrained Generation
Trong Phase 8 và Phase 12, ShopAssist sử dụng cơ chế **Structured Outputs** dựa trên Pydantic v2:
1. Định nghĩa schema bằng class Python kế thừa `pydantic.BaseModel`.
2. Truyền JSON Schema trực tiếp vào API của nhà cung cấp LLM (Google Gen AI SDK hoặc OpenAI JSON Schema Strict Mode).
3. Engine của LLM sẽ áp dụng ngữ pháp kiểm soát (Grammar Constrained Decoding / Constrained Sampling) ở tầng sinh token, đảm bảo 100% token sinh ra khớp hoàn toàn với schema quy định.

```python
# Trích đoạn từ src/shopassist/llm/schemas.py
class HardConstraints(BaseModel):
    category: str | None = None
    brand: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_rating: float | None = None
    currency: str | None = "INR"

class QueryUnderstandingOutput(BaseModel):
    semantic_query: str
    hard_constraints: HardConstraints
    soft_preferences: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_reason: str | None = None
```

---

## 3. Phân Vai Hai Điểm Chạm LLM: Phase 8 vs. Phase 12

Trong ShopAssist, LLM chỉ xuất hiện ở đúng 2 điểm trong pipeline, nhưng đảm nhận 2 nhiệm vụ hoàn toàn khác biệt:

```
[User Input] ---> [Phase 8: LLM NLU] ---> [Search & Database] ---> [Phase 12: LLM NLG] ---> [Response]
                  (Trích xuất cấu trúc)                            (Sinh đề xuất có dẫn chứng)
```

| Tiêu chí | Phase 8: Query Understanding | Phase 12: Grounded Recommendation |
|---|---|---|
| **Mục đích** | **NLU (Natural Language Understanding):** Phân tích ngữ pháp, bóc tách thực thể và ý định. | **NLG (Natural Language Generation):** Tổng hợp thông tin, so sánh và thuyết phục người mua. |
| **Mô hình triển khai** | Google Gemini `gemini-3.1-flash-lite`. | Groq `openai/gpt-oss-20b` hoặc OpenRouter `gemma-4-26b`. |
| **Đầu vào** | Câu chat thô của người dùng (chỉ 5–20 từ). | Câu hỏi + Dữ liệu sản phẩm ứng viên đã được lọc từ database kèm ID bằng chứng (`[PID-E#]`). |
| **Đầu ra** | Đối tượng `QueryUnderstandingOutput` thuần JSON. | Đối tượng `LLMRecommendationPayload` chứa câu chào, ưu nhược điểm và mã trích dẫn. |
| **Quy tắc an toàn** | Nếu phát hiện câu hỏi tối nghĩa hoặc có phủ định nguy hiểm ("không phải giày da"), phải bật cờ `needs_clarification = True`. | **Tuyệt đối không bịa thông số.** Mọi câu khẳng định phải gắn kèm mã trích dẫn `[PID-E#]`. |

---

## 4. Mã Nguồn Tham Chiếu Trong Repository

- **Cấu hình tham số LLM:** Xem [src/shopassist/llm/config.py](file:///d:/Project/ShopAssist/src/shopassist/llm/config.py). Đọc biến môi trường `GEMINI_TEMPERATURE=0.0`, `GEMINI_MAX_OUTPUT_TOKENS=2048`, `GEMINI_TIMEOUT_SECONDS=30`.
- **Triển khai Gemini Client:** Xem [src/shopassist/llm/gemini_client.py](file:///d:/Project/ShopAssist/src/shopassist/llm/gemini_client.py). Chứa cơ chế gọi API với `types.GenerateContentConfig`, cơ chế retry tự động với exponential backoff khi gặp lỗi mạng hoặc rate limit (HTTP 429).
- **Prompt hệ thống của Phase 8:** Xem [src/shopassist/llm/prompts.py](file:///d:/Project/ShopAssist/src/shopassist/llm/prompts.py). Hướng dẫn mô hình cách nhận diện danh mục trong catalog 12 ngành hàng Flipkart và quy tắc nhận diện đơn vị tiền tệ INR.
- **Evidence Context Builder của Phase 12:** Xem [src/shopassist/recommendation/context.py](file:///d:/Project/ShopAssist/src/shopassist/recommendation/context.py). Chuyển đổi dữ liệu bảng sản phẩm thành các thẻ chứng cứ `[PID-E1]`, `[PID-E2]`.

---

## 5. Quan Sát Thực Nghiệm Tại Phase 14

Khi thực thi `scripts/run_phase14_evaluation.py --run-live-judge`, mô hình `gemini-3.1-flash-lite` đã chạy thẩm định trực tiếp một đoạn đề xuất:
- **Thời gian phản hồi:** 1,496.34 ms (xấp xỉ 1.5 giây).
- **Kiểm soát định dạng:** 100% phản hồi trả về tuân thủ cấu trúc Pydantic `LLMJudgeResponseSchema`, không gặp bất kỳ lỗi parse JSON nào.
- **Độ nhạy ngữ nghĩa:** Mô hình phát hiện được sự chênh lệch nhỏ giữa *"designed specifically for jogging"* (câu LLM đề xuất) và *"lightweight EVA midsole for running"* (bằng chứng thực tế trong catalog).

---

## 6. Cạm Bẫy Thường Gặp (Common Mistakes)

1. **Đặt Temperature cao cho tác vụ trích xuất:** Đặt `temperature = 0.7` cho Phase 8 sẽ dẫn đến việc cùng một câu truy vấn của người dùng, mỗi lần chạy lại trích xuất ra một JSON khác nhau, khiến hệ thống không thể kiểm thử hồi quy (Regression Testing).
2. **Quên xử lý Timeout và Retry:** Mạng Internet và các nhà cung cấp cloud LLM thường xuyên bị nghẽn (Spike latency hoặc Rate limit 429). Nếu không bọc trong vòng lặp thử lại có giới hạn (Bounded Retry) như trong [gemini_client.py:L247](file:///d:/Project/ShopAssist/src/shopassist/llm/gemini_client.py#L247), toàn bộ ứng dụng sẽ bị sập.
3. **Prompt quá dài và thừa thãi:** Nhồi nhét hàng nghìn từ vào System Prompt khiến chi phí token tăng vọt và mô hình dễ bị lẫn lộn giữa các quy tắc. Hãy giữ prompt ngắn gọn, ví dụ cụ thể (Few-shot) và dùng JSON Schema để định hình cấu trúc.

---

## 7. Bài Học Cốt Lõi (Key Takeaways)
1. **Pydantic là người bạn thân thiết nhất của AI Engineer:** Luôn định nghĩa hợp đồng dữ liệu rõ ràng bằng Pydantic trước khi kết nối với LLM.
2. **Nhiệt độ 0.0 cho tính toán, sáng tạo cho đối thoại:** Luôn dùng `temperature = 0.0` khi cần độ chính xác cao và cấu trúc dữ liệu ổn định.
3. **Phân tách nhiệm vụ:** Không bao giờ bắt một lần gọi LLM làm tất cả mọi thứ; hãy chia nhỏ thành pipeline gồm các bước đơn giản, kiểm soát được.
