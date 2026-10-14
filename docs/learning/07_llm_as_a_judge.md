# Bài 07 — Phương Pháp LLM-as-a-Judge: Đánh Giá Đề Xuất Bằng AI

---

## 1. Khái Niệm Cốt Lõi: Tại Sao Phải Dùng LLM Để Chấm Điểm LLM?

Trong các tác vụ truyền thống (như phân loại ảnh, dịch máy BLEU/ROUGE), chúng ta có thể so sánh chuỗi ký tự bằng các thuật toán đo trùng lặp $N$-gram. Nhưng trong hệ thống RAG:
- LLM sinh ra một đoạn văn đề xuất mua sắm: nó có thể viết bằng tiếng Anh, tiếng Việt, văn phong thân thiện, diễn giải lý do mua hàng sinh động.
- Điểm ROUGE/BLEU hoàn toàn vô dụng: Hai câu có ý nghĩa giống hệt nhau nhưng dùng từ ngữ khác nhau sẽ bị ROUGE chấm điểm rất thấp.
- Thuê con người đọc và chấm điểm hàng nghìn câu trả lời hàng ngày là quá chậm và tốn kém, không thể áp dụng cho chu trình CI/CD phần mềm tự động.

**Giải pháp hiện đại:** **LLM-as-a-Judge** — Sử dụng một mô hình ngôn ngữ lớn (thường là mô hình mạnh, hoạt động ở nhiệt độ thấp) đóng vai trò là một "Giám khảo chất lượng", đọc câu trả lời của hệ sinh và chấm điểm dựa trên một **Bản tiêu chí rõ ràng (Rubric)**.

---

## 2. Thiết Kế Bộ Tiêu Chí Chấm Điểm (Judging Rubric) Chuẩn Mực

Một sai lầm kinh điển của người mới làm LLM-as-a-Judge là đưa ra câu hỏi chung chung: *"Hãy chấm điểm câu trả lời này từ 1 đến 10"*. Kết quả là LLM sẽ chấm điểm tùy tiện theo cảm xúc và thiên kiến!

Trong ShopAssist, chúng ta thiết kế Rubric phiên bản `phase14-rubric-v1.0` gồm **5 tiêu chí độc lập** (thang điểm 1 đến 5 cho mỗi tiêu chí):

| Tiêu chí | Trọng tâm thẩm định | Điểm 5 (Xuất sắc) | Điểm 1 (Thất bại) |
|---|---|---|---|
| **1. Groundedness (Tính Căn Cứ)** | Mọi câu khẳng định có dựa vào văn bản sản phẩm được cung cấp hay không? | 100% chi tiết kỹ thuật đều có dẫn chứng trong evidence. | Bịa đặt tính năng không hề có trong bài đăng sản phẩm. |
| **2. Factual Correctness (Độ Chính Xác Thực Tế)** | Giá tiền, thương hiệu, danh mục có khớp chính xác với database? | Giá tiền, tên hãng, số sao khớp từng con số. | Sai giá, lộn tên thương hiệu, nhầm lẫn đơn vị tiền tệ. |
| **3. Query Relevance (Độ Phù Hợp Nhu Cầu)** | Đề xuất có giải quyết đúng mong muốn và sở thích của người mua? | Giải quyết trọn vẹn cả nhu cầu chính và các sở thích phụ. | Đề xuất lạc đề hoặc không đúng đối tượng sử dụng. |
| **4. Citation Support (Chất Lượng Dẫn Chứng)** | Các trích dẫn nguồn có tuân thủ định dạng `[PID-E#]` và chỉ đúng dòng? | Đúng định dạng `[PID-E#]`, dẫn chứng trực tiếp vào thông số. | Không có trích dẫn hoặc tự bịa mã trích dẫn giả mạo. |
| **5. Missing Info Handling (Xử Lý Thông Tin Thiếu)** | Khi catalog thiếu thông tin người dùng hỏi, mô hình ứng xử ra sao? | Thành thật thừa nhận thông tin thiếu, không phỏng đoán. | Bịa đặt thông số để làm hài lòng người mua. |

---

## 3. Cấu Trúc Hóa Đầu Ra Của Giám Khảo Bằng Pydantic

Để tích hợp vào pipeline kiểm thử tự động, kết quả chấm điểm của Giám khảo không thể là một bài văn bình phẩm. Nó bắt buộc phải là một đối tượng JSON có cấu trúc chặt chẽ:

```python
# Trích đoạn từ src/shopassist/evaluation/phase14_judge.py
class LLMJudgeResponseSchema(BaseModel):
    groundedness_score: int = Field(..., ge=1, le=5)
    factual_correctness_score: int = Field(..., ge=1, le=5)
    query_relevance_score: int = Field(..., ge=1, le=5)
    citation_support_score: int = Field(..., ge=1, le=5)
    missing_info_handling_score: int = Field(..., ge=1, le=5)
    overall_decision: str = Field(..., description="PASS, MARGINAL, hoặc FAIL")
    evidence_supported: bool = Field(...)
    unsupported_claims: list[str] = Field(default_factory=list)
    critique: str = Field(..., description="Lời giải thích ngắn gọn của giám khảo")
```

---

## 4. Các Thiên Kiến Phổ Biến Của LLM Judge & Cách Phòng Ngừa

Mô hình LLM không phải là con người khách quan tuyệt đối; nó có các thiên kiến tâm lý học nơ-ron (Cognitive Biases):

1. **Verbosity Bias (Thiên vị câu trả lời dài dòng):** LLM có xu hướng chấm điểm cao hơn cho những câu trả lời dài, nhiều từ ngữ hoa mỹ, dù nội dung có thể sáo rỗng hoặc thừa thãi.
   - *Cách phòng ngừa:* Trong rubric, nhấn mạnh: *"Độ dài không đồng nghĩa với chất lượng; câu trả lời ngắn gọn nhưng chính xác tuyệt đối được ưu tiên điểm cao nhất"*.
2. **Position Bias (Thiên vị vị trí):** Khi so sánh 2 câu trả lời A và B, mô hình thường có xu hướng thiên vị câu xuất hiện ở vị trí đầu tiên (hoặc cuối cùng).
   - *Cách phòng ngừa:* Đảo vị trí (Swap order) và chạy 2 lần độc lập để kiểm tra tính nhất quán.
3. **Self-Enhancement Bias (Thiên vị chính mình):** Một mô hình của Google (Gemini) thường chấm điểm cao hơn cho văn phong do chính Gemini sinh ra; tương tự với OpenAI GPT-4.
   - *Cách phòng ngừa:* Dùng mô hình giám khảo độc lập từ nhà cung cấp khác (ví dụ: dùng Gemini đi chấm điểm sản phẩm sinh ra bởi LLaMA hoặc Gemma).

---

## 5. Tại Sao Hai Giám Khảo AI Cùng Đồng Ý Vẫn Có Thể Sai? (Correlated Errors)

Trong Phase 13, ShopAssist sử dụng 2 giám khảo độc lập (Judge A và Judge B) và đạt tỷ lệ đồng thuận rất cao:
- Exact Agreement: **85.21%**
- Quadratic Weighted Kappa $\kappa = \mathbf{0.8336}$ (Mức độ đồng thuận thống kê rất mạnh).

Tuy nhiên, trong AI Engineering, **sự đồng thuận của 2 AI không đồng nghĩa với Sự thật tuyệt đối (Ground Truth)**:
- Nếu cả Judge A và Judge B đều sử dụng các mô hình họ Transformer chia sẻ chung dữ liệu tiền huấn luyện web, chúng có thể cùng mắc một **Lỗi tương quan (Correlated Error)**.
- Ví dụ: Một câu truy vấn có lỗi ngữ pháp tiếng lóng đặc thù của Việt Nam có thể bị cả 2 giám khảo hiểu sai theo cùng một cách!

---

## 6. Sự Kết Hợp Hoàn Hảo: Deterministic Check + LLM Judge

Vì LLM Judge vẫn có xác suất mắc lỗi, hệ thống của ShopAssist áp dụng mô hình **Kiểm Định Lai (Hybrid Validation)**:

```
[Generated Recommendation Payload]
          |
          +---> 1. DETERMINISTIC CHECKS (Code Python thuần - Nhanh, Không Tốn Tiền, 100% Chuẩn)
          |     - Check product_id có nằm trong database không?
          |     - Check cú pháp tag [PID-E#] có đúng regex không?
          |     - Check giá bán có đúng từng chữ số với catalog không?
          |     - Check có vi phạm bộ lọc Category / Brand / Price không?
          |
          +---> 2. SEMANTIC LLM JUDGE (Chỉ chạy khi bước 1 đã PASS)
                - Đánh giá khả năng diễn đạt, lập luận logic.
                - Đánh giá xem câu giải thích có thực sự liên quan đến sở thích người mua không.
```

Nhờ tầng lọc tất định số 1, hơn 90% các lỗi nghiêm trọng (ảo giác ID, sai giá, vi phạm ràng buộc) đều bị phát hiện ngay lập tức mà không cần tốn một token API nào cho LLM Judge!

---

## 7. Mã Nguồn Tham Chiếu Trong Repository

- **Triển khai LLM-as-a-Judge:** [src/shopassist/evaluation/phase14_judge.py](file:///d:/Project/ShopAssist/src/shopassist/evaluation/phase14_judge.py). Chứa toàn bộ System Prompt, Rubric và schema kiểm soát.
- **Thẩm định tất định:** [src/shopassist/evaluation/phase14_evaluator.py:L480](file:///d:/Project/ShopAssist/src/shopassist/evaluation/phase14_evaluator.py#L480). Hàm `evaluate_deterministic_grounding` kiểm tra ID sản phẩm và tiền tố trích dẫn.
- **Unit test LLM Judge:** [tests/test_phase14_evaluation.py:L260](file:///d:/Project/ShopAssist/tests/test_phase14_evaluation.py#L260).

---

## 8. Cạm Bẫy Thường Gặp (Common Mistakes)

1. **Gán nhãn LLM Judge thành "Human Ground Truth":** Đây là lỗi vi phạm đạo đức nghiên cứu khoa học nghiêm trọng nhất. Nhãn sinh ra bởi AI Judge chỉ được phép gọi là **AI-Silver (hoặc Synthetic Labels)**, không bao giờ được phép mạo nhận là Human Gold.
2. **Không trích xuất danh sách khẳng định sai (Unsupported Claims):** Nếu giám khảo chỉ chấm điểm 3/5 mà không chỉ ra cụ thể câu chữ nào bị sai trong mảng `unsupported_claims`, lập trình viên sẽ không thể debug và cải thiện prompt.

---

## 9. Bài Học Cốt Lõi (Key Takeaways)
1. **Rubric chi tiết là chìa khóa:** Không hỏi LLM điểm số chung chung; hãy chia nhỏ thành các tiêu chí cụ thể với mô tả rõ ràng cho mức điểm 1, 3, 5.
2. **Structured Output là bắt buộc:** Ép LLM Judge trả về Pydantic schema để dễ dàng tích hợp vào hệ thống kiểm thử tự động.
3. **Deterministic đi trước, LLM đi sau:** Luôn dùng code Python để kiểm tra các thuộc tính cứng trước khi tốn chi phí gọi LLM đánh giá ngữ nghĩa.
