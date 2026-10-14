# Bài 03 — Embeddings & Vector Search: BGE, Cosine Similarity & pgvector

---

## 1. Khái Niệm Cốt Lõi: Tại Sao Văn Bản Lại Biến Thành Vector?

Máy tính không hiểu được ý nghĩa trừu tượng của từ ngữ; nó chỉ hiểu các phép toán số học. Trong nhiều thập kỷ, tìm kiếm văn bản dựa vào **từ khóa (Lexical Matching)**: đếm số lần xuất hiện của từ (TF-IDF, BM25).

Tuy nhiên, tìm kiếm từ khóa gặp phải vấn đề nan giải: **Khoảng cách từ vựng (Vocabulary Mismatch)**:
- Người dùng tìm: *"sneakers"*
- Catalog ghi: *"casual walking athletic shoes"*
- Tìm kiếm từ khóa trả về: **0 kết quả** vì không có chữ "sneakers" nào trong bài đăng!

### 1.1. Embedding Là Gì?
**Text Embedding** là quá trình chuyển đổi một đoạn văn bản thành một chuỗi số thực cố định (Vector) trong không gian nhiều chiều:
$$\text{Text} \xrightarrow{\text{Embedding Model}} \vec{v} = [x_1, x_2, \dots, x_D] \in \mathbb{R}^D$$

Điểm kỳ diệu của mạng nơ-ron Embedding (Transformer encoder) là: **Những đoạn văn bản có ý nghĩa ngữ nghĩa tương tự nhau sẽ được đặt ở các vị trí gần nhau trong không gian vector**, bất kể chúng dùng các từ ngữ hoàn toàn khác nhau.

### 1.2. Kích Thước Vector (Embedding Dimensions)
- Mô hình nhỏ (Small): 384 chiều (ví dụ: `bge-small-en-v1.5`, `all-MiniLM-L6-v2`).
- Mô hình trung bình: 768 chiều (ví dụ: `bge-base-en-v1.5`, BERT base).
- Mô hình lớn: 1536 chiều hoặc 3072 chiều (ví dụ: OpenAI `text-embedding-3-small/large`).
- **Lựa chọn của ShopAssist:** Chúng ta chọn mô hình **`BAAI/bge-small-en-v1.5`** với $D = 384$ chiều. Vector 384D chiếm ít dung lượng RAM và bộ nhớ đĩa, tốc độ tính toán cực nhanh trên CPU mà vẫn đạt chất lượng ngữ nghĩa hàng đầu trên bảng xếp hạng MTEB.

---

## 2. Đo Lường Khoảng Cách: Cosine Similarity vs. Cosine Distance

Làm sao để biết 2 vector $\vec{u}$ và $\vec{v}$ có "gần nhau" hay không? Chúng ta đo góc giữa 2 vector qua **Cosine Similarity**:

$$\text{Cosine Similarity}(\vec{u}, \vec{v}) = \frac{\vec{u} \cdot \vec{v}}{\|\vec{u}\| \|\vec{v}\|} = \frac{\sum_{i=1}^D u_i v_i}{\sqrt{\sum_{i=1}^D u_i^2} \sqrt{\sum_{i=1}^D v_i^2}}$$

- Nếu 2 vector cùng hướng hoàn toàn: $\text{Cosine Similarity} = 1.0$.
- Nếu 2 vector trực giao (không liên quan): $\text{Cosine Similarity} = 0.0$.
- Nếu 2 vector ngược hướng: $\text{Cosine Similarity} = -1.0$.

### Chuẩn Hóa L2 (L2-Normalization) & Bí Quyết Tốc Độ
Nếu mọi vector đều được chuẩn hóa về độ dài bằng 1 ($\|\vec{u}\| = 1$), công thức tính Cosine Similarity rút gọn thành một phép **nhân vô hướng (Dot Product)** đơn giản:
$$\text{Cosine Similarity}(\vec{u}, \vec{v}) = \vec{u} \cdot \vec{v}$$
Trong ShopAssist, hàm `EmbeddingModel.encode(..., normalize_embeddings=True)` luôn chuẩn hóa vector đầu ra, giúp cơ sở dữ liệu tính toán cực nhanh mà không cần chia cho độ dài vector.

---

## 3. Cách pgvector & Chỉ Mục HNSW Hoạt Động Trong PostgreSQL

Nếu catalog có 100,000 sản phẩm, việc so sánh vector truy vấn với từng sản phẩm một (Linear Scan / Exact Search) sẽ rất chậm ($O(N)$). Chúng ta cần thuật toán **Tìm kiếm láng giềng gần đúng (Approximate Nearest Neighbors - ANN)**.

ShopAssist sử dụng extension **`pgvector`** trên PostgreSQL với chỉ mục **HNSW (Hierarchical Navigable Small World)**:
- **Nguyên lý HNSW:** Xây dựng một đồ thị đa tầng (tương tự skip-list). Tầng trên cùng có ít nút để nhảy bước lớn, càng xuống tầng dưới số lượng liên kết càng dày đặc để tìm kiếm tinh vi. Độ phức tạp giảm từ $O(N)$ xuống $O(\log N)$.
- **Toán tử `<=>` trong pgvector:** Đại diện cho **Cosine Distance**:
  $$\text{Cosine Distance} = 1.0 - \text{Cosine Similarity}$$
  Do đó, khoảng cách càng nhỏ thì sản phẩm càng tương đồng!

---

## 4. Tại Sao Cần Kết Hợp SQL Filters & Vector Search (Filtered Search)?

Đây là bài học kiến trúc sống còn mà nhiều dự án AI mắc sai lầm:

### Kịch bản thất bại của "Pure Vector Search":
Giả sử người dùng tìm: *"Giày thể thao Nike dưới 1 triệu"*.
Nếu bạn chỉ chuyển câu trên thành vector và bắn vào Vector Database:
- Vector search sẽ trả về các đôi giày Nike rất đẹp, rất đúng ngữ nghĩa... nhưng giá **3 triệu hoặc 5 triệu**!
- Vì không gian vector chỉ hiểu "sự tương đồng về mặt ngữ nghĩa", vector search không thể ép buộc điều kiện số học cứng (`price <= 1,000,000`).

### Giải pháp của ShopAssist: Pre-filtering trực tiếp trong SQL
Chúng ta kết hợp mệnh đề `WHERE` của SQL với toán tử khoảng cách vector của pgvector trong cùng một câu lệnh truy vấn duy nhất:

```sql
SELECT product_id, product_name, category, brand, discounted_price,
       embedding <=> CAST(:query_vector AS vector) AS cosine_distance
FROM public.products
WHERE embedding_model = 'BAAI/bge-small-en-v1.5'
  AND category ILIKE '%Footwear%'
  AND brand ILIKE 'Nike'
  AND discounted_price <= 1000.0
ORDER BY embedding <=> CAST(:query_vector AS vector), product_id ASC
LIMIT 10;
```

**Lợi ích kép:**
1. **Chính xác tuyệt đối 100%:** Những sản phẩm sai danh mục hoặc vượt ngân sách bị loại bỏ ngay từ đầu.
2. **Tốc độ vượt trội:** Giảm không gian tìm kiếm từ 8,405 sản phẩm xuống chỉ còn vài chục sản phẩm thỏa mãn điều kiện trước khi tính toán khoảng cách vector.

---

## 5. Mã Nguồn Tham Chiếu Trong Repository

- **Mô hình Embedding BGE:** Xem [src/shopassist/embeddings/model.py](file:///d:/Project/ShopAssist/src/shopassist/embeddings/model.py). Tự động nhận diện thiết bị (`cuda` nếu có GPU NVIDIA, fallback về `cpu`), sử dụng instruction bất đối xứng đặc thù của BGE:
  `"Represent this sentence for searching relevant passages: "`
- **Triển khai truy vấn pgvector:** Xem [src/shopassist/retrieval/semantic.py](file:///d:/Project/ShopAssist/src/shopassist/retrieval/semantic.py#L420) và [src/shopassist/retrieval/hybrid.py](file:///d:/Project/ShopAssist/src/shopassist/retrieval/hybrid.py#L427).
- **Định dạng Vector Literal cho SQL:** Xem [src/shopassist/db/ingestion.py](file:///d:/Project/ShopAssist/src/shopassist/db/ingestion.py). Hàm `format_vector_literal(vec)` chuyển đổi mảng numpy float thành chuỗi định dạng PostgreSQL `[0.0123,-0.0456,...]`.

---

## 6. Cạm Bẫy Thường Gặp (Common Mistakes)

1. **Quên BGE Query Instruction:** Các mô hình embedding hiện đại (BGE, E5, Instructor) được huấn luyện bất đối xứng. Văn bản sản phẩm (Document/Passage) được encode trực tiếp, nhưng câu hỏi của người dùng (Query) bắt buộc phải có tiền tố chỉ dẫn. Nếu quên tiền tố này, điểm tương đồng Cosine sẽ bị tụt giảm nghiêm trọng.
2. **Lỗi Null Rating:** Khi người dùng yêu cầu "đánh giá từ 4 sao trở lên" (`min_rating = 4.0`), nhiều sản phẩm mới chưa có đánh giá sẽ có giá trị `rating = NULL`. Nếu câu SQL viết `rating >= 4.0`, trong chuẩn SQL giá trị `NULL >= 4.0` sẽ trả về `UNKNOWN` (False). Trong ShopAssist, quy tắc này được kiểm soát chặt chẽ: sản phẩm có rating NULL không bao giờ được coi là thỏa mãn ngưỡng đánh giá.
3. **Post-filtering thay vì Pre-filtering:** Nhiều hệ thống lấy top-100 vector gần nhất rồi mới dùng Python code để lọc giá. Hậu quả là nếu trong top-100 không có sản phẩm nào dưới 1 triệu, kết quả trả về sẽ bị rỗng (Zero Results), dù trong database vẫn còn sản phẩm thỏa mãn!

---

## 7. Bài Học Cốt Lõi (Key Takeaways)
1. **Vector Search là phép toán đo góc:** Nó giải quyết bài toán đồng nghĩa và ngữ cảnh mà từ khóa không làm được.
2. **Đừng bao giờ dùng Vector Search đơn độc trong E-commerce:** Luôn kết hợp Vector Search với các bộ lọc thuộc tính SQL có cấu trúc (Category, Brand, Price, Rating).
3. **Chuẩn hóa vector L2:** Luôn chuẩn hóa vector để biến phép tính khoảng cách thành tích vô hướng nhanh gọn.
