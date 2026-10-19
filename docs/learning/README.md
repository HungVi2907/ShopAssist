# Sổ Tay Học Tập AI Engineering Thực Chiến — Dự Án ShopAssist

Chào mừng bạn đến với bộ tài liệu học tập toàn diện về **AI Engineering** được đúc kết từ dự án thực tế **ShopAssist**.

ShopAssist là một hệ thống trợ lý mua sắm AI (Conversational AI Shopping Assistant) ứng dụng kiến trúc **Hybrid RAG (Retrieval-Augmented Generation)**, kết hợp giữa mô hình ngôn ngữ lớn (LLM), truy vấn ngữ nghĩa vector (Dense Embeddings + pgvector), tìm kiếm từ khóa truyền thống (TF-IDF), và các lớp xác thực quy chuẩn (Deterministic Guardrails).

Mục tiêu lớn nhất của dự án này **không phải là tối ưu điểm số học thuật hay chạy đua mô hình mới nhất**, mà là giúp bạn hiểu sâu sắc:
- Cách một ứng dụng AI hoàn chỉnh được thiết kế và vận hành trong thực tế.
- Các quyết định kỹ thuật (Engineering Trade-offs) giữa độ trễ, chi phí, độ tin cậy và chất lượng.
- Cách đánh giá (Evaluation) hệ thống AI bằng chỉ số định lượng, AI-Silver Benchmark và LLM-as-a-Judge mà không bị phụ thuộc vào nhãn người (Human Gold).

---

## 🗺️ Lộ Trình Học Tập (Curriculum Index)

Bộ tài liệu được sắp xếp theo trình tự từ tổng quan đến chi tiết kỹ thuật, từ lý thuyết cốt lõi đến thực nghiệm đo lường:

| Bài học | Tiêu đề | Nội dung trọng tâm |
|---|---|---|
| [**Bài 00**](00_ai_engineering_roadmap.md) | **Lộ Trình AI Engineering & Vị Trí Của ShopAssist** | AI Engineer làm gì? Khác biệt giữa AI Engineer, Data Scientist và Software Engineer. Toàn cảnh 17 Phase của ShopAssist. |
| [**Bài 01**](01_shopassist_architecture.md) | **Kiến Trúc Tổng Thể ShopAssist** | Luồng dữ liệu End-to-End, sơ đồ Mermaid, vai trò từng module (Phase 8 -> 9 -> 10 -> 11 -> 12). |
| [**Bài 02**](02_llm_fundamentals.md) | **Nền Tảng LLM Trong Thực Chiến** | Prompt Engineering, Temperature, Tokens, Context Window, Structured Outputs (Pydantic). Phân vai LLM Phase 8 (Query Understanding) vs Phase 12 (Recommendation). |
| [**Bài 03**](03_embeddings_vector_search.md) | **Embeddings & Vector Search** | Bản chất toán học của Vector, Cosine Similarity, mô hình BAAI/bge-small-en-v1.5, chỉ mục HNSW trong pgvector và tại sao cần kết hợp SQL filters. |
| [**Bài 04**](04_rag_architecture.md) | **Kiến Trúc RAG & Grounded Generation** | RAG là gì? Khác gì Fine-tuning? Cách xây dựng Evidence Context (`[PID-E#]`) để triệt tiêu Hallucination. Trace chi tiết 1 truy vấn. |
| [**Bài 05**](05_retrieval_and_reranking.md) | **Retrieval & Reranking Chuyên Sâu** | So sánh Lexical (TF-IDF), Dense (Vector), Hybrid (RRF) và Cross-Encoder. Đánh đổi thời gian chạy 0.16ms vs 545ms. |
| [**Bài 06**](06_ai_evaluation_metrics.md) | **Các Chỉ Số Đánh Giá Hệ Thống AI** | Precision@K, MRR, nDCG@K, Pool-conditional Recall, Coverage. Công thức toán, ví dụ tính tay, cạm bẫy bảo toàn thứ hạng (Rank Preservation). |
| [**Bài 07**](07_llm_as_a_judge.md) | **Phương Pháp LLM-as-a-Judge** | Cách dùng LLM chấm điểm LLM, thiết kế Rubric 5 tiêu chí, phân định rõ ràng giữa Deterministic Code và LLM Judgment. |
| [**Bài 08**](08_ai_engineering_reliability.md) | **Độ Tin Cậy, An Toàn & Chi Phí** | Xử lý Hallucination, Prompt Injection, Bounded Retries, Timeout, Fallback deterministic, quản lý Token và tối ưu chi phí API. |
| [**Bài 09**](09_reproducing_phase14.md) | **Hướng Dẫn Tái Hiện Thực Nghiệm Phase 14** | Hướng dẫn từng bước chạy evaluation runner, đọc báo cáo, kiểm thử unit test và xem kết quả thực tế. |
| [**Bài 10**](10_what_we_learned.md) | **Tổng Kết Bài Học AI Engineering Thực Chiến** | Những bài học xương máu về thiết kế hệ thống AI, các trade-offs cốt lõi và tư duy kỹ thuật cần mang theo vào các dự án tương lai. |
| [**Bài 11**](11_fastapi_backend_and_ai_orchestration.md) | **FastAPI Backend & Điều Phối AI Pipeline Thực Chiến** | Tại sao ứng dụng AI cần backend? Kiến trúc FastAPI, Async/Sync, Lifespan, Orchestration Phase 8–12, Short-circuiting, Guardrails và chuẩn bị cho Telegram Bot. |
| [**Bài 12**](12_telegram_bot_integration.md) | **Tích Hợp Telegram Bot & Thiết Kế Giao Diện Hội Thoại** | Ranh giới giữa AI Backend và Presentation, Long Polling vs Webhook, httpx AsyncClient, HTML escaping, typing indicators, session nonces và per-chat concurrency locking. |

---

## 🎯 Cấu Trúc Mỗi Bài Học

Để đảm bảo tính trực quan và dễ tiếp thu, mỗi tài liệu đều tuân thủ cấu trúc chuẩn:
1. **Khái niệm cốt lõi (Core Concept):** Giải thích bản chất bằng ngôn ngữ trực quan, không dùng thuật ngữ trừu tượng khó hiểu.
2. **Ví dụ thực tế trong ShopAssist (Real Example):** Minh họa bằng chính dữ liệu sản phẩm, truy vấn tìm kiếm hoặc phản hồi của hệ thống.
3. **Mã nguồn tương ứng (Source Code):** Đường dẫn clickable trực tiếp đến code triển khai trong repository (`src/shopassist/...`).
4. **Quan sát thực nghiệm (Empirical Observations):** Kết quả đo lường thực tế từ Phase 14.
5. **Cạm bẫy thường gặp (Common Mistakes):** Những sai lầm phổ biến mà người mới bắt đầu làm AI thường mắc phải.
6. **Bài học cốt lõi (Key Takeaways):** Tóm tắt 2-3 gạch đầu dòng cô đọng nhất.

---

> [!TIP]
> **Cách học hiệu quả:** Bạn nên đọc từ Bài 00 để có bức tranh toàn cảnh, sau đó đọc tuần tự từng bài kết hợp mở trực tiếp mã nguồn và chạy các script thực nghiệm trong terminal để đối chiếu!
