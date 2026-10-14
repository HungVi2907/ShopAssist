# Bài 05 — Retrieval & Reranking: So Sánh Lexical, Dense, Hybrid RRF & Cross-Encoder

---

## 1. Khái Niệm Cốt Lõi: Kiến Trúc Tìm Kiếm Hai Giai Đoạn (Two-Stage Search)

Trong các hệ thống thông tin quy mô lớn (Google, Amazon, Shopee), một bài toán nan giải luôn tồn tại:
- Nếu dùng mô hình nơ-ron cực kỳ thông minh để so sánh câu truy vấn với hàng triệu sản phẩm trong kho $\rightarrow$ **Hệ thống sẽ bị quá tải, độ trễ lên tới vài giây hoặc vài phút!**
- Nếu chỉ dùng thuật toán tìm kiếm đơn giản, nhanh gọn $\rightarrow$ **Tốc độ dưới 10 mili-giây, nhưng kết quả xếp hạng chưa thực sự tối ưu.**

Để cân bằng hoàn hảo giữa **Tốc độ (Speed)** và **Chất lượng (Accuracy)**, ngành AI Information Retrieval áp dụng mô hình **Hai Giai Đoạn (Two-Stage Architecture)**:

```
[Kho 8,405 Sản phẩm] 
         |
         v   GIAI ĐOẠN 1: RETRIEVAL (Thu hồi ứng viên — First Stage)
         |   - Mục tiêu: Recall cao, tốc độ cực nhanh (< 20ms).
         |   - Thu hẹp từ 8,405 sản phẩm xuống còn Top-10 ứng viên tiềm năng.
         |   - Công nghệ: TF-IDF, pgvector HNSW, Hybrid RRF.
         v
[Top-10 Ứng viên]
         |
         v   GIAI ĐOẠN 2: RERANKING (Tái xếp hạng tinh vi — Second Stage)
         |   - Mục tiêu: Precision cao, tối ưu hóa thứ tự 1, 2, 3...
         |   - Xếp hạng lại danh sách 10 sản phẩm dựa trên tương tác chuyên sâu.
         |   - Công nghệ: Multi-Signal Scoring, Transformer Cross-Encoder.
         v
[Top-5 Đề xuất tinh hoa gửi tới LLM sinh phản hồi]
```

---

## 2. Bốn Phương Pháp Retrieval & Reranking Trong ShopAssist

### 2.1. Baseline 1 — TF-IDF (Tìm Kiếm Từ Khóa Truyền Thống)
- **Cơ chế:** Dựa trên tần suất từ (Term Frequency) và nghịch đảo tần suất xuất hiện trong tập văn bản (Inverse Document Frequency). So sánh vector thưa (Sparse Vector) qua Cosine Similarity.
- **Ưu điểm:** Cực kỳ chính xác khi người dùng tìm tên riêng, thương hiệu ("Puma", "Nike", "Casio"), mã hiệu sản phẩm ("Carson 2"). Tốc độ dưới 1 mili-giây.
- **Nhược điểm:** Hoàn toàn mù tịt trước các từ đồng nghĩa hoặc câu hỏi mô tả cảm xúc ("giày êm chân đi làm hàng ngày").

### 2.2. Baseline 2 — Dense Retrieval (Tìm Kiếm Ngữ Nghĩa Vector)
- **Cơ chế:** Dùng mô hình Bi-Encoder (`BAAI/bge-small-en-v1.5`) nhúng câu hỏi và sản phẩm thành vector dày (Dense Vector 384D) độc lập nhau, sau đó đo khoảng cách góc Cosine trên database pgvector.
- **Ưu điểm:** Hiểu được từ đồng nghĩa, ngữ cảnh rộng, xử lý mượt mà câu hỏi dài.
- **Nhược điểm:** Có thể bỏ qua những từ khóa định danh cụ thể (ví dụ: tìm "iPhone 13", vector search có thể trả về "iPhone 12" vì ngữ nghĩa của chúng rất gần nhau!).

### 2.3. Hybrid Retrieval & Reciprocal Rank Fusion (RRF)
- **Cơ chế:** Chạy song song cả Dense Search và TF-IDF Search trên tập sản phẩm đã được lọc qua SQL (Structured Filter). Sau đó, hợp nhất 2 danh sách kết quả bằng thuật toán **RRF (Reciprocal Rank Fusion)**:
  $$\text{RRF Score}(p) = \sum_{m \in \{\text{dense, lexical}\}} \frac{1}{60 + \text{rank}_m(p)}$$
  Hằng số $k = 60$ là tham số chuẩn trong giới nghiên cứu IR giúp làm mượt điểm số, tránh việc một phương pháp có rank 1 lấn át hoàn toàn phương pháp còn lại.
- **Ưu điểm:** Lấy được ưu điểm của cả hai thế giới: vừa giữ được sự chính xác về từ khóa của TF-IDF, vừa có sự bao quát ngữ nghĩa của Dense Vector.

### 2.4. Cross-Encoder Reranking
- **Sự khác biệt mấu chốt giữa Bi-Encoder và Cross-Encoder:**
  - *Bi-Encoder (Retrieval):* Encode Query riêng, Document riêng. Chúng không hề "nhìn thấy" nhau trước khi nhân tích vô hướng.
  - *Cross-Encoder (Reranking):* Ghép trực tiếp chuỗi `[CLS] Query [SEP] Product Text [SEP]` đưa vào toàn bộ các lớp Self-Attention của Transformer. Mọi từ trong Query được tương tác chéo (Cross-Attention) với từng từ trong Document.
- **Ưu điểm:** Khả năng đánh giá mối quan hệ tương quan ngữ nghĩa sâu sắc nhất.
- **Nhược điểm:** Rất tốn kém tài nguyên tính toán; không thể tính trước (pre-compute) vector lưu vào database.

---

## 3. Kết Quả Thực Nghiệm Thực Tế Tại Phase 14

Dưới đây là các số liệu đo lường thực tế từ bài chạy thực nghiệm trên toàn bộ 174 candidate pool và tập ca thử nghiệm của ShopAssist:

### 3.1. So sánh Retrieval (Toàn bộ 174 Pool, Cutoff K=5)

| Phương pháp | nDCG@5 (Chất lượng tổng thể) | MRR (Đưa đúng vào top 1) | Precision@5 (Tỷ lệ sản phẩm đúng) | Judgment Coverage |
|---|---|---|---|---|
| **TF-IDF (Lexical)** | 0.8324 | **0.6050** | **0.5054** | 100% |
| **Dense (pgvector BGE)** | 0.7625 | 0.5651 | 0.4785 | 100% |
| **Hybrid RRF** | **0.9067** | 0.5322 | 0.4275 | 100% |

> **Phân tích AI Engineering:**  
> - **Hybrid RRF đạt nDCG@5 cao nhất vượt trội (0.9067):** Việc kết hợp cả từ khóa và vector giúp đẩy các sản phẩm thực sự phù hợp lên các vị trí cao nhất.
> - **TF-IDF có MRR cao nhất (0.6050):** Trong tập truy vấn e-commerce, rất nhiều câu hỏi chứa tên thương hiệu chính xác. Khi từ khóa khớp chính xác, TF-IDF đưa ngay sản phẩm đó lên rank 1.

---

### 3.2. So sánh Tái Xếp Hạng (Phase 11 Reranking Benchmark)

| Phương pháp Tái Xếp Hạng | Thuật toán | nDCG@5 | MRR | Độ trễ trung vị (Latency) | Số bước dịch chuyển thứ hạng |
|---|---|---|---|---|---|
| **RRF Pass-Through** | Giữ nguyên thứ tự RRF | 0.9155 | 0.8750 | **0.26 ms** | 0.00 |
| **Multi-Signal** | Trọng số: Lexical + Dense + Price + Rating | **0.9342** | **1.0000** | **0.16 ms** | 3.00 |
| **Cross-Encoder** | `ms-marco-MiniLM-L2-v2` (CPU) | 0.8624 | 0.8333 | **545.66 ms** | 12.00 |

---

## 4. Phân Tích Bài Học Kỹ Thuật Đắt Giá (Engineering Trade-Offs)

Nhìn vào bảng số liệu trên, có 2 hiện tượng cực kỳ thú vị và thực tế:

### Hiện tượng 1: Tại sao Cross-Encoder (mô hình AI phức tạp) lại có nDCG thấp hơn Multi-Signal (thuật toán số học đơn giản)?
1. **Lệch miền dữ liệu (Domain Mismatch):** Mô hình `cross-encoder/ms-marco-MiniLM-L2-v2` được huấn luyện trên dữ liệu web hỏi đáp (MS MARCO passage ranking). Văn bản trong catalog e-commerce chứa đầy thông số kỹ thuật dạng bảng, kích thước, tên hãng viết tắt. Mô hình không được fine-tune trên dữ liệu mua sắm nên dễ bị đánh lừa bởi những câu quảng cáo hoa mỹ thay vì các thông số kỹ thuật cốt lõi.
2. **Multi-Signal tích hợp tín hiệu nghiệp vụ (Domain Signals):** Thuật toán Multi-Signal trong ShopAssist không chỉ nhìn vào độ tương đồng câu chữ mà còn kết hợp điểm đánh giá sao (`rating`) và độ ưu đãi về giá (`discounted_price`). Đây chính là những yếu tố mà người mua sắm thực tế quan tâm nhất!

### Hiện tượng 2: Sự đánh đổi khổng lồ về độ trễ (Latency Trade-Off)
- **Multi-Signal:** Chạy mất **0.16 mili-giây** trên CPU (hầu như tức thì).
- **Cross-Encoder:** Chạy mất **545.66 mili-giây** trên CPU (hơn nửa giây, **chậm hơn 3,400 lần**!).
- **Quyết định của AI Engineer:** Trong môi trường sản phẩm thực tế cần phản hồi nhanh cho chatbot (SLA < 1 giây), việc hy sinh 545ms quý giá cho một mô hình Cross-Encoder chưa fine-tune là một quyết định tồi. **Lựa chọn Hybrid RRF kết hợp Multi-Signal là quyết định kiến trúc chiến thắng tuyệt đối!**

---

## 5. Mã Nguồn Tham Chiếu Trong Repository

- **Triển khai TF-IDF Index:** [src/shopassist/retrieval/tfidf.py](file:///d:/Project/ShopAssist/src/shopassist/retrieval/tfidf.py). Tải chỉ mục từ vựng đã fit từ Phase 6.
- **Triển khai Hybrid Retrieval & RRF:** [src/shopassist/retrieval/hybrid.py](file:///d:/Project/ShopAssist/src/shopassist/retrieval/hybrid.py#L427).
- **Triển khai Reranking Service:** [src/shopassist/reranking/core.py](file:///d:/Project/ShopAssist/src/shopassist/reranking/core.py). Chứa các class `RerankingService`, `load_local_cross_encoder` và thuật toán tính điểm đa tín hiệu.

---

## 6. Cạm Bẫy Thường Gặp (Common Mistakes)

1. **Nhầm lẫn giữa Bi-Encoder và Cross-Encoder:** Dùng Cross-Encoder để tìm kiếm trên toàn bộ database 100,000 sản phẩm. Điều này là bất khả thi về mặt tính toán! Cross-Encoder sinh ra chỉ để chấm điểm lại một tập nhỏ (Top 10–50) sau khi giai đoạn Retrieval đã hoàn thành.
2. **Cộng điểm số trực tiếp thay vì xếp hạng (Rank):** Điểm Cosine của Dense nằm trong khoảng $[0, 1]$, điểm TF-IDF có thể nằm trong khoảng $[0, 25]$. Nếu cộng trực tiếp 2 điểm số này với nhau, điểm TF-IDF sẽ nuốt chửng điểm Cosine. Đó là lý do tại sao thuật toán **Reciprocal Rank Fusion (RRF)** chuẩn hóa theo **thứ hạng (Rank)** chứ không dùng điểm số thô!

---

## 7. Bài Học Cốt Lõi (Key Takeaways)
1. **Kiến trúc hai giai đoạn là chuẩn mực:** Dùng thuật toán nhanh và nhẹ ở tầng Retrieval để gom ứng viên; dùng thuật toán tinh vi ở tầng Reranking để tối ưu vị trí.
2. **Không phải mô hình AI phức tạp lúc nào cũng thắng:** Thuật toán heuristic tận dụng tốt tri thức miền nghiệp vụ (như Multi-Signal) hoàn toàn có thể đánh bại mô hình nơ-ron nặng nề cả về độ chính xác lẫn tốc độ.
3. **RRF là giải pháp hợp nhất không cần tinh chỉnh (Zero-tuning):** RRF cho phép kết hợp các công cụ tìm kiếm khác nhau một cách kỳ diệu mà không cần phải huấn luyện thêm mô hình học máy nào.
