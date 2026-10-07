# ShopAssist — Conversational Product Recommendation System

## 1. Project Overview

ShopAssist là một hệ thống AI hỗ trợ tư vấn và đề xuất sản phẩm thương mại điện tử (E-commerce Consumer Products) thông qua hội thoại ngôn ngữ tự nhiên.

Người dùng tương tác với hệ thống thông qua giao diện **Telegram Bot**.

Ví dụ:

> “Tôi cần một chiếc laptop mỏng nhẹ dưới $800, pin tốt và khởi động nhanh để làm việc văn phòng.”

Hệ thống phân tích và bóc tách câu hỏi thành hai nhóm thông tin:

```text
Hard Constraints (Điều kiện ràng buộc rõ ràng)
- category = laptop
- max_price = 800
```

và:

```text
Soft Preferences (Sở thích, nhu cầu ngữ nghĩa)
- lightweight / mỏng nhẹ
- good battery life / pin tốt
- fast boot / khởi động nhanh
- suitable for office work / làm việc văn phòng
```

Sau đó hệ thống áp dụng kỹ thuật tìm kiếm kết hợp (Hybrid Retrieval) cùng bước tái xếp hạng (Reranking) để truy xuất các sản phẩm phù hợp nhất từ Product Knowledge Base, trước khi sinh câu trả lời tư vấn có căn cứ (grounded recommendation) trả về cho người dùng.

Kiến trúc luồng xử lý tổng quát:

```text
User
 ↓
Telegram Bot
 ↓
FastAPI
 ↓
LLM Query Understanding
 ↓
Hard Constraints + Soft Preferences
 ↓
Hybrid Product Retrieval (SQL Filtering + Vector Search)
 ↓
Ranking / Reranking
 ↓
Top-K Products
 ↓
LLM Recommendation Generation
 ↓
Telegram Response
```

---

# 2. Problem Statement

Các nền tảng thương mại điện tử cung cấp hàng chục nghìn đến hàng triệu sản phẩm đa dạng. Khi tìm kiếm sản phẩm phù hợp, người dùng thường gặp phải các rào cản:

- Phải tìm kiếm bằng từ khóa cứng nhắc (keyword matching);
- Phải áp dụng thủ công nhiều bộ lọc thông số kỹ thuật phức tạp;
- Phải tự đọc và phân tích nhiều trang mô tả sản phẩm dài;
- Phải tự so sánh thông số giữa các lựa chọn;
- Khó diễn đạt các nhu cầu mang tính ngữ nghĩa và ngữ cảnh sử dụng thực tế.

Trong thực tế, nhu cầu mua sắm của người dùng thường được diễn đạt tự nhiên qua ngôn cảnh và mục đích sử dụng.

Ví dụ:

> “Tôi là sinh viên cần tìm một tai nghe chụp tai chống ồn tốt, êm tai khi đeo lâu, giá dưới $100.”

Một search engine truyền thống dựa trên từ khóa hoặc lọc thuộc tính (faceted search) có thể dễ dàng lọc:

```text
category = headphones
price <= 100
```

nhưng gặp khó khăn lớn khi phải định lượng và đối khớp các đặc tính ngữ nghĩa:

```text
noise cancellation
comfortable for long wear
good for students
```

Nếu chỉ sử dụng Pure Vector Search (tìm kiếm ngữ nghĩa thuần túy), hệ thống lại thường vi phạm các ràng buộc cứng (như vượt mức giá tối đa hoặc sai ngành hàng). Ngược lại, nếu chỉ dùng bộ lọc truyền thống, hệ thống sẽ bỏ lỡ hoàn toàn chiều sâu ngữ nghĩa trong nhu cầu người dùng.

Bài toán trọng tâm của project:

> Làm thế nào để xây dựng một hệ thống có khả năng hiểu toàn diện cả các điều kiện rõ ràng (hard constraints) lẫn các sở thích ngữ nghĩa (soft preferences) của người dùng từ ngôn ngữ tự nhiên, kết hợp lọc cấu trúc và tìm kiếm vector để đề xuất sản phẩm chính xác và đáng tin cậy?

---

# 3. Domain & Product Scope

Domain chính thức của hệ thống:

> **E-commerce Consumer Products**

Thay vì giới hạn cố định ở một nhóm sản phẩm hẹp ngay từ đầu, ShopAssist định vị là hệ thống đề xuất cho các danh mục sản phẩm tiêu dùng phổ biến. Danh mục ngành hàng chính thức của hệ thống sẽ được quyết định sau khi tiến hành **Khám phá và phân tích phân phối dữ liệu (Exploratory Data Analysis - EDA)** trên dataset catalog.

Quy trình xác định phạm vi ngành hàng:

```text
Flipkart Products 20K
        ↓
Dataset Profiling / EDA
        ↓
Category Distribution Analysis
        ↓
Select Suitable Product Categories
        ↓
Basic Data Cleaning
        ↓
Final Product Dataset
```

### Tiêu chí lựa chọn category:

1. **Sufficient Number of Products**: Danh mục phải có lượng sản phẩm đủ lớn để tạo không gian truy vấn và đề xuất có ý nghĩa (tránh danh mục quá thưa thớt).
2. **Usable Descriptions**: Phần lớn sản phẩm phải có văn bản mô tả rõ ràng, giàu thông tin ngữ nghĩa phục vụ embedding.
3. **Usable Price Information**: Có thông tin giá (retail price / discounted price) rõ ràng để hỗ trợ lọc điều kiện tài chính.
4. **Usable Specifications**: Có thông số kỹ thuật (product specifications) để bóc tách thuộc tính chi tiết.
5. **Reasonable Category Quality**: Cấu trúc danh mục phân tầng mạch lạc, dữ liệu ít nhiễu hoặc sai lệch.
6. **Suitability for Natural-Language Queries**: Phù hợp với các truy vấn mua sắm giàu ngữ nghĩa (người dùng thường có nhiều tiêu chí so sánh, nhu cầu sử dụng, tính năng).

### Quy mô sản phẩm mục tiêu (Target Dataset Size):

> **5,000 – 15,000 clean products**

*Lưu ý*: Con số 5,000 – 15,000 là khoảng mục tiêu dự kiến nhằm đảm bảo hiệu năng và chất lượng thử nghiệm, phạm vi chính thức sẽ được chốt sau khi hoàn thành EDA và lựa chọn danh mục.

---

# 4. Primary Dataset — Flipkart Products 20K

Dataset chính thức được sử dụng làm Product Knowledge Base ban đầu của ShopAssist là:

> **Flipkart Products 20K**

Đây là bộ dữ liệu catalog sản phẩm thương mại điện tử với quy mô khoảng 20,000 bản ghi sản phẩm.

Các trường dữ liệu dự kiến khai thác:

```text
uniq_id / pid            - Định danh duy nhất của sản phẩm
product_name             - Tên tiêu đề sản phẩm
product_category_tree    - Chuỗi cây phân cấp danh mục
retail_price             - Giá niêm yết bán lẻ
discounted_price         - Giá sau khuyến mãi / giá bán thực tế
description              - Văn bản mô tả chi tiết sản phẩm
product_rating           - Điểm đánh giá sản phẩm
overall_rating           - Điểm đánh giá tổng quan (nếu có)
brand                    - Thương hiệu sản phẩm
product_specifications   - Thông số kỹ thuật chi tiết của sản phẩm
product_url              - Đường dẫn gốc đến sản phẩm
```

### Yêu cầu khảo sát và kiểm định qua EDA:

Không giả định mọi trường dữ liệu đều có sẵn và đầy đủ giá trị ở tất cả bản ghi. Sau khi thu thập dữ liệu, hệ thống bắt buộc phải thực hiện bước **Dataset Profiling / EDA** chi tiết để kiểm tra:

- **Column availability**: Xác nhận chính xác tên cột và cấu trúc dữ liệu thực tế của file;
- **Missing values**: Đo lường tỷ lệ khuyết thiếu trên từng trường (đặc biệt là giá, mô tả, rating, brand);
- **Duplicates**: Phát hiện và xử lý các bản ghi trùng lặp mã sản phẩm, trùng lặp tiêu đề hoặc nội dung;
- **Category distribution**: Phân tích tần suất xuất hiện và độ sâu phân cấp của các danh mục trong `product_category_tree`;
- **Price coverage**: Kiểm tra tỷ lệ sản phẩm có giá hợp lệ, định dạng số, phân bố mức giá;
- **Rating coverage**: Kiểm tra mật độ sản phẩm có điểm đánh giá rating sẵn có;
- **Description coverage**: Đánh giá độ dài và độ phong phú của văn bản mô tả;
- **Specification coverage**: Đánh giá cấu trúc trường thông số kỹ thuật (dạng chuỗi, JSON, hay key-value);
- **Brand coverage**: Tỷ lệ bản ghi có nhãn thương hiệu rõ ràng.

Schema vật lý thực tế của cơ sở dữ liệu chỉ được hoàn thiện sau khi có báo cáo EDA cụ thể.

---

# 5. Data Pipeline & Processing Strategy

Khác với các pipeline phức tạp nhiều tầng cồng kềnh, ShopAssist tinh giản tối đa quy trình xử lý dữ liệu để tập trung nguồn lực vào bài toán cốt lõi: **AI Engineering, Hybrid Retrieval và LLM Recommendation**.

Quy trình xử lý dữ liệu tổng thể:

```text
Flipkart Products 20K
        ↓
Dataset Download
        ↓
Dataset Profiling / EDA
        ↓
Category Selection
        ↓
Basic Data Cleaning
        ↓
Deduplication
        ↓
Normalize Structured Fields
        ↓
Build retrieval_text
        ↓
Final Product Dataset
        ↓
PostgreSQL + pgvector
```

### Các bước xử lý cơ bản trong Data Cleaning:

1. **Missing ID & Title**: Loại bỏ các bản ghi thiếu định danh duy nhất (`uniq_id`/`pid`) hoặc thiếu tên sản phẩm (`product_name`).
2. **Deduplication**: Khử trùng lặp dựa trên product ID và tên sản phẩm tương đồng.
3. **Price Normalization**: Chuẩn hóa trường giá (`retail_price`, `discounted_price`) về định dạng số thực (float/numeric), loại bỏ ký tự tiền tệ hoặc giá trị âm/không hợp lệ.
4. **Rating Normalization**: Chuyển đổi trường rating về thang điểm chuẩn (ví dụ 1.0 – 5.0), xử lý giá trị NaN hoặc chuỗi không xác định.
5. **Brand & Category Normalization**: Chuẩn hóa chuỗi thương hiệu (viết hoa/viết thường, khoảng trắng) và phân tách cây danh mục (`product_category_tree`) thành cấp danh mục rõ ràng (`main_category`, `sub_category`).
6. **Malformed & Empty Text Handling**: Xử lý các ký tự điều khiển lỗi, định dạng mã HTML còn sót trong mô tả, và lọc các bản ghi có nội dung văn bản quá ngắn hoặc rỗng.

Quy trình này không áp dụng các rule engine phức tạp giả định trước mà chỉ xử lý những vấn đề dữ liệu thực sự phát hiện được trong quá trình EDA.

---

# 6. Exclusion of Reviews in V1 Scope

Trong phiên bản Version 1 (V1), ShopAssist xác định phạm vi rõ ràng:

> **Không sử dụng raw reviews và không thực hiện bất kỳ bước tổng hợp review (review aggregation) nào trong V1.**

Hệ thống loại bỏ hoàn toàn các cấu phần xử lý review phức tạp:

- Không thu thập dữ liệu raw user reviews;
- Không thực hiện review filtering;
- Không thực hiện tóm tắt review bằng LLM (LLM review summarization);
- Không tự trích xuất danh sách ưu điểm (pros) và nhược điểm (cons) từ reviews;
- Không tính toán các chỉ số phái sinh từ review cá nhân (như review count derived, common positive points, common negative points).

### Tận dụng điểm đánh giá có sẵn:

Nếu dataset Flipkart có sẵn trường đánh giá (ví dụ `product_rating` hoặc `overall_rating`), trường này sẽ được sử dụng trực tiếp như một thuộc tính cấu trúc (numerical metadata) phục vụ cho:

- Lọc điều kiện tối thiểu (ví dụ `rating >= 4.0`);
- Trọng số phụ trợ trong quá trình Ranking / Reranking.

Hệ thống tuyệt đối không tự bịa đặt hoặc suy diễn các bản tóm tắt đánh giá khi không có dữ liệu thực tế.

---

# 7. Final Product Schema

Sau khi hoàn tất quá trình làm sạch và chuẩn hóa, schema logic của bảng dữ liệu sản phẩm trong Product Knowledge Base được định hình như sau:

| Trường dữ liệu | Kiểu dữ liệu | Vai trò chính | Mô tả |
|---|---|---|---|
| `product_id` | String | Khóa chính (Primary Key) | Mã định danh duy nhất của sản phẩm (lấy từ `uniq_id` hoặc `pid`) |
| `product_name` | String | Hiển thị, TF-IDF, Semantic | Tên đầy đủ của sản phẩm |
| `category` | String | SQL Filter, Phân loại | Ngành hàng chuẩn hóa sau khi phân tách danh mục |
| `brand` | String | SQL Filter, Ranking | Thương hiệu chuẩn hóa của sản phẩm |
| `retail_price` | Float / Numeric | Thông tin tham chiếu | Giá bán lẻ niêm yết ban đầu |
| `discounted_price`| Float / Numeric | SQL Filter, Ranking | Giá bán thực tế / giá ưu đãi sử dụng cho ràng buộc ngân sách |
| `rating` | Float | SQL Filter, Ranking | Điểm đánh giá trung bình có sẵn từ dataset |
| `description` | Text | Semantic Search | Văn bản mô tả tính năng và chi tiết sản phẩm |
| `product_specifications` | Text / JSON | Semantic, Detail Display | Thông số kỹ thuật chi tiết của sản phẩm |
| `product_url` | String | Hiển thị | Đường dẫn tham chiếu đến sản phẩm gốc |
| `retrieval_text` | Text | TF-IDF, Vector Embedding | Văn bản tổng hợp đại diện ngữ nghĩa cho sản phẩm |

*Lưu ý*: Schema chi tiết có thể được tinh chỉnh mở rộng sau khi EDA xác nhận cấu trúc thực tế của dataset Flipkart.

---

# 8. Construction of `retrieval_text`

Để phục vụ cho cả mô hình tìm kiếm từ khóa truyền thống (TF-IDF) và tìm kiếm ngữ nghĩa đa chiều (Dense Vector Search), mỗi sản phẩm được xây dựng một trường văn bản đại diện duy nhất gọi là `retrieval_text`.

Cấu trúc xây dựng:

```text
retrieval_text = 
    product_name
    + " | Category: " + category
    + " | Brand: " + brand
    + " | Description: " + description
    + " | Specifications: " + product_specifications
```

### Nguyên tắc tạo `retrieval_text`:

- **Bỏ qua trường rỗng**: Nếu một trường thông tin (ví dụ `brand` hoặc `product_specifications`) không có dữ liệu ở một sản phẩm nhất định, hệ thống sẽ bỏ qua trường đó một cách an toàn mà không đưa vào các giá trị rác như `"None"`, `"NaN"`, hoặc `"null"`.
- **Làm sạch văn bản**: Loại bỏ khoảng trắng thừa, thẻ HTML sót lại, và chuẩn hóa dấu phân tách để giữ độ liền mạch ngữ nghĩa.
- **Ứng dụng thống nhất**: `retrieval_text` là nguồn đầu vào trực tiếp cho:
  - Vectorizer TF-IDF (cho baseline lexical search);
  - Mô hình Sentence Transformers / Embedding Model (để sinh dense vector embedding lưu trữ vào pgvector);
  - Ngữ cảnh tham chiếu cho mô hình Reranker.

---

# 9. Structured vs. Unstructured Information Architecture

Kiến trúc dữ liệu của ShopAssist phân định rõ ràng vai trò của hai nhóm thông tin:

```text
Product Data
 ├── Structured Information
 │    ├── category
 │    ├── brand
 │    ├── retail_price
 │    ├── discounted_price
 │    └── rating
 │    └───► Sử dụng cho: SQL Hard Filtering & Ranking Signals
 │
 └── Unstructured / Semantic Information
      ├── product_name
      ├── description
      └── product_specifications
      └───► Tổng hợp thành retrieval_text
      └───► Sử dụng cho: TF-IDF, Dense Embedding & Semantic Search
```

### Structured Information:

- Được lưu trữ dưới dạng các cột có kiểu dữ liệu chuẩn (TEXT, NUMERIC, FLOAT) trong PostgreSQL;
- Được đánh index phù hợp (B-Tree) để tối ưu hóa truy vấn lọc điều kiện cứng;
- Đảm bảo tính toán chính xác 100% đối với các yêu cầu về ngân sách, thương hiệu và ngành hàng.

### Unstructured Information:

- Chứa đựng các chi tiết mô tả tính năng, công năng sử dụng, chất liệu, kích thước, thiết kế;
- Được ánh xạ thành vector không gian nhiều chiều (ví dụ 384, 768 hoặc 1536 chiều) lưu trong cột kiểu `vector` của extension **pgvector**;
- Đảm bảo khả năng hiểu các nhu cầu ngữ nghĩa phức tạp mà SQL không thể so khớp chính xác.

---

# 10. Data Organization

Cấu trúc thư mục dữ liệu trong project được tổ chức rõ ràng theo các tầng xử lý:

```text
data/
├── raw/
│   └── flipkart_products.csv                  # File dataset gốc tải về
│
├── interim/
│   ├── eda_profiling_report.json             # Báo cáo tổng hợp số liệu EDA
│   ├── category_distribution.json            # Thống kê phân bố ngành hàng
│   └── cleaned_candidates.parquet            # Dữ liệu sau bước làm sạch sơ bộ
│
└── processed/
    └── products.parquet                      # File dữ liệu chuẩn hóa cuối cùng
                                              # sẵn sàng nạp vào PostgreSQL/pgvector
```

File `products.parquet` là nguồn chân lý (Single Source of Truth) đại diện cho toàn bộ Product Knowledge Base dùng cho ứng dụng và các kịch bản thử nghiệm đánh giá.

---

# 11. Query Understanding

Cơ chế hiểu câu hỏi người dùng là mắt xích AI đầu tiên và quan trọng nhất trong hệ thống:

> **LLM-based Structured Query Extraction + Semantic Representation of Soft Preferences**

### Ví dụ quy trình trích xuất:

Người dùng nhập câu hỏi tự nhiên:

> *"I need a lightweight laptop under $800 with good battery life."*

LLM phân tích ngữ cảnh và trích xuất thành đối tượng JSON có cấu trúc:

```json
{
  "category": "laptop",
  "brand": null,
  "min_price": null,
  "max_price": 800,
  "min_rating": null,
  "preferences": [
    "lightweight",
    "good battery life"
  ]
}
```

### Nguyên tắc kiến trúc tại tầng Query Understanding:

- **Chuyên biệt hóa nhiệm vụ**: Tại bước này, LLM **tuyệt đối không gợi ý hoặc tự chọn sản phẩm**. Nhiệm vụ duy nhất của mô hình là bóc tách ngữ nghĩa từ ngôn ngữ tự nhiên sang cấu trúc dữ liệu máy có thể xử lý.
- **Tách bạch Hard vs Soft**:
  - Các thông số đo đếm được hoặc phạm vi cụ thể (`category`, `brand`, `min_price`, `max_price`, `min_rating`) được xếp vào nhóm điều kiện cứng.
  - Các mong muốn định tính (`lightweight`, `compact`, `durable`, `good battery life`) được đưa vào mảng `preferences`.
- **Dynamic Schema**: Danh mục chuẩn (`category`) được định hình theo danh sách categories đã chốt sau EDA, giúp mô hình prompt chuẩn hóa danh mục chính xác.

---

# 12. Hard Constraints Handling

Hard Constraints là các ràng buộc bắt buộc mà một sản phẩm hợp lệ phải thỏa mãn đầy đủ.

Các trường điều kiện cứng điển hình:

```text
- category   : Khớp chính xác ngành hàng (hoặc ánh xạ enum ngành hàng)
- brand      : Khớp thương hiệu chỉ định (nếu người dùng yêu cầu)
- min_price  : Giá sàn (sản phẩm không được thấp hơn)
- max_price  : Giá trần (sản phẩm không được vượt quá ngân sách)
- min_rating : Ngưỡng đánh giá tối thiểu (ví dụ rating >= 4.0)
```

### Cơ chế thực thi qua SQL:

Các điều kiện này được chuyển trực tiếp thành câu truy vấn SQL có tham số trên PostgreSQL:

```sql
SELECT product_id, product_name, brand, discounted_price, rating, retrieval_text
FROM products
WHERE 
    (:category IS NULL OR category ILIKE :category)
    AND (:brand IS NULL OR brand ILIKE :brand)
    AND (:max_price IS NULL OR discounted_price <= :max_price)
    AND (:min_price IS NULL OR discounted_price >= :min_price)
    AND (:min_rating IS NULL OR rating >= :min_rating);
```

### Lợi ích:

- **100% Deterministic**: Đảm bảo không xảy ra hiện tượng sản phẩm vượt ngân sách người dùng xuất hiện trong tập ứng viên.
- **Tối ưu hóa không gian tìm kiếm**: Giảm bớt số lượng vector cần so sánh tương đồng trong bước tìm kiếm ngữ nghĩa tiếp theo.

---

# 13. Soft Preferences Handling

Soft Preferences là các sở thích, kỳ vọng mang tính mô tả định tính, công năng sử dụng hoặc phong cách mà người dùng mong muốn nhưng không thể diễn đạt bằng phép so sánh toán học hoặc SQL thông thường.

Ví dụ các soft preferences phổ biến:

```text
lightweight           - mỏng nhẹ, dễ mang theo
good battery life     - thời lượng pin dài
easy to use           - dễ thao tác, thân thiện người dùng
durable               - bền bỉ, chịu va đập tốt
compact               - nhỏ gọn, tiết kiệm không gian
portable              - tính di động cao
good for beginners    - phù hợp cho người mới bắt đầu
comfortable           - êm ái, thoải mái khi dùng lâu
```

Hệ thống **không hard-code** danh sách cố định các sở thích này. Thay vào đó, kiến trúc xử lý động hoàn toàn:

```text
preferences: ["lightweight", "good battery life"]
        ↓
Gộp thành Semantic Preference Query
(Ví dụ: "lightweight laptop with good battery life for portable use")
        ↓
Embedding Model
        ↓
Query Embedding Vector
        ↓
Cosine Similarity / Vector Search trên retrieval_text
```

Sản phẩm nào có phần mô tả (`description`) và thông số (`specifications`) đề cập rõ nét và phù hợp với các đặc tính này sẽ đạt điểm tương đồng ngữ nghĩa (semantic similarity score) cao hơn.

---

# 14. Product Knowledge Base

Toàn bộ tri thức sản phẩm được lưu trữ tập trung trên cơ sở dữ liệu quan hệ mạnh mẽ hỗ trợ vector:

> **PostgreSQL + pgvector**

### Cấu trúc bảng lưu trữ:

```sql
CREATE TABLE products (
    product_id VARCHAR(64) PRIMARY KEY,
    product_name TEXT NOT NULL,
    category VARCHAR(128) NOT NULL,
    brand VARCHAR(128),
    retail_price NUMERIC(12, 2),
    discounted_price NUMERIC(12, 2),
    rating REAL,
    description TEXT,
    product_specifications TEXT,
    product_url TEXT,
    retrieval_text TEXT,
    embedding vector(384) -- Kích thước phụ thuộc vào mô hình embedding được chọn
);

-- Index cho tìm kiếm thuộc tính cấu trúc
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_products_brand ON products(brand);
CREATE INDEX idx_products_price ON products(discounted_price);
CREATE INDEX idx_products_rating ON products(rating);

-- Index cho tìm kiếm vector nhanh chóng
CREATE INDEX idx_products_embedding ON products 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

Sự kết hợp giữa relational index và HNSW vector index trong cùng một database cho phép thực thi truy vấn kết hợp (filtered vector search) với độ trễ thấp và độ chính xác cao.

---

# 15. Main AI Recommendation Workflow

Phương pháp AI chủ đạo của ShopAssist kết hợp sức mạnh của mô hình ngôn ngữ lớn, công cụ truy xuất dữ liệu lai và mô hình tái xếp hạng:

> **LLM Query Understanding + Structured Filtering + Semantic Search + Reranking + Grounded Recommendation**

Sơ đồ quy trình chi tiết:

```text
                        ┌────────────────────────────────┐
                        │      User Natural Query        │
                        └────────────────┬───────────────┘
                                         │
                                         ▼
                        ┌────────────────────────────────┐
                        │    LLM Query Understanding     │
                        └───────┬────────────────┬───────┘
                                │                │
            ┌───────────────────┴──┐          ┌──┴───────────────────┐
            │   Hard Constraints   │          │   Soft Preferences   │
            │  category, brand,    │          │  semantic attributes │
            │  price, rating       │          │  use-case context    │
            └───────────┬──────────┘          └──────────┬───────────┘
                        │                                │
                        │  SQL Filter                    │  Vector Embedding
                        ▼                                ▼
            ┌────────────────────────────────────────────────────────┐
            │                   Hybrid Retrieval                     │
            │          (Filtered Semantic Vector Search)             │
            └───────────────────────────┬────────────────────────────┘
                                        │
                                        ▼ Top-N Candidates (e.g. 20)
            ┌────────────────────────────────────────────────────────┐
            │                  Ranking / Reranking                   │
            │     (Cross-Encoder / Weighted Multi-Signal Score)      │
            └───────────────────────────┬────────────────────────────┘
                                        │
                                        ▼ Top-K Products (e.g. 3 - 5)
            ┌────────────────────────────────────────────────────────┐
            │           Grounded LLM Recommendation Engine           │
            │   (Generates reasoning, comparisons, and trade-offs)   │
            └───────────────────────────┬────────────────────────────┘
                                        │
                                        ▼
                        ┌────────────────────────────────┐
                        │     Telegram User Response     │
                        └────────────────────────────────┘
```

---

# 16. Hybrid Retrieval

Hybrid Retrieval đóng vai trò kết nối giữa bộ lọc chính xác (Deterministic Filtering) và không gian ngữ nghĩa (Semantic Space).

### Cơ chế hoạt động:

1. **Bước 1 - Structured Filtering**: Dựa trên các thuộc tính trong `Hard Constraints`, SQL engine lọc nhanh trên bảng sản phẩm để loại bỏ tất cả các sản phẩm vi phạm điều kiện (sai ngành hàng, vượt ngân sách, điểm rating quá thấp).
2. **Bước 2 - Semantic Scoring**: Trên tập sản phẩm ứng viên đã vượt qua bộ lọc cứng, hệ thống tính toán khoảng cách cosine giữa vector truy vấn (tổng hợp từ `soft preferences` hoặc toàn bộ câu hỏi) và vector `embedding` của từng sản phẩm.
3. **Bước 3 - Candidate Selection**: Lấy ra danh sách ứng viên tiềm năng hàng đầu (`Top-N Candidates`, ví dụ N = 20) để chuyển tiếp sang giai đoạn Reranking.

Cơ chế này ngăn chặn hoàn toàn nhược điểm "ảo giác điều kiện" của mô hình ngôn ngữ thuần túy và hiện tượng vector search trả về sản phẩm không đúng mức giá mong muốn.

---

# 17. Retrieval Methods for Experimentation

Để trả lời câu hỏi nghiên cứu kỹ thuật và chứng minh tính hiệu quả của phương pháp đề xuất, ShopAssist thiết kế 4 cấu hình truy xuất phục vụ đánh giá thực nghiệm:

### Baseline 1 — TF-IDF + Cosine Similarity
- Phương pháp tìm kiếm từ khóa truyền thống (Lexical Search).
- Ánh xạ câu hỏi người dùng và `retrieval_text` thành ma trận thưa TF-IDF.
- Xếp hạng theo độ tương đồng Cosine.
- *Điểm yếu dự kiến*: Không hiểu từ đồng nghĩa, không xử lý được các ràng buộc số học về giá và rating.

### Baseline 2 — Dense Embedding + Vector Search
- Tìm kiếm ngữ nghĩa thuần túy (Pure Vector Search).
- Nhúng toàn bộ câu hỏi người dùng thành dense vector và tìm k-láng giềng gần nhất (k-NN) trong `pgvector`.
- *Điểm yếu dự kiến*: Có thể trả về sản phẩm phù hợp về mô tả ngữ nghĩa nhưng vi phạm mức giá tối đa hoặc sai lệch thương hiệu cụ thể.

### Method 3 — Structured Filtering + Embedding Search
- Kết hợp lọc điều kiện cứng trước (Hard Filtering qua SQL), sau đó tìm kiếm vector trên tập sản phẩm còn lại.
- Chưa áp dụng bước phân tích sâu soft preferences và chưa có tầng Reranking.

### Proposed Method — LLM Query Understanding + Structured Filtering + Semantic Search + Reranking
- Phương pháp toàn diện của ShopAssist:
  - LLM trích xuất rõ ràng Hard Constraints và Soft Preferences;
  - SQL Filtering đảm bảo ràng buộc 100%;
  - Vector Search trên Soft Preferences tìm kiếm ứng viên;
  - Cross-Encoder Reranker chấm điểm và xếp hạng lại Top-K sản phẩm tối ưu.

---

# 18. Ranking and Reranking

Sau khi bước Hybrid Retrieval trả về tập ứng viên ban đầu (Top-N, thông thường N = 15 – 25 sản phẩm), hệ thống áp dụng bước tái xếp hạng (Reranking) để chọn ra Top-K (3 – 5 sản phẩm) xuất sắc nhất gửi tới tầng sinh gợi ý.

### Yếu tố cấu thành điểm số xếp hạng:

```text
Final Score = 
    w1 * Cross_Encoder_Score (hoặc Semantic Similarity)
  + w2 * Constraint_Match_Score
  + w3 * Normalized_Product_Rating
```

1. **Reranker Score (Cross-Encoder)**: Sử dụng một mô hình cross-encoder gọn nhẹ để đánh giá trực tiếp cặp `(Query + Preferences, Product Retrieval Text)`. Cross-encoder có khả năng so khớp tương tác giữa từng từ tốt hơn so với bi-encoder embedding.
2. **Constraint Satisfaction**: Điểm thưởng nếu sản phẩm đáp ứng hoàn hảo các thuộc tính ưa thích.
3. **Product Rating**: Điểm đánh giá thực tế của sản phẩm được chuẩn hóa đưa vào như một tín hiệu phụ trợ, ưu tiên sản phẩm có chất lượng được cộng đồng kiểm chứng cao hơn khi các yếu tố ngữ nghĩa tương đương.

*Lưu ý*: Trong V1, không sử dụng bất kỳ đặc trưng phái sinh nào từ reviews trong công thức xếp hạng.

---

# 19. Grounded LLM Recommendation Generation

Mô hình LLM ở tầng cuối cùng nhận ngữ cảnh gồm:

```text
Input Context:
1. Original User Query (Câu hỏi gốc của người dùng)
2. Parsed Requirements (Các ràng buộc và sở thích đã bóc tách)
3. Top-K Product Metadata (Thông tin đầy đủ của các sản phẩm ứng viên được chọn)
```

### Nhiệm vụ của LLM:

- **Giải thích lý do gợi ý (Reasoning)**: Trình bày rõ ràng tại sao từng sản phẩm lại đáp ứng đúng nhu cầu cụ thể của người dùng.
- **So sánh đối chiếu (Comparison)**: So sánh sự khác biệt then chốt giữa các lựa chọn đề xuất (ví dụ: sản phẩm A ưu tiên tính gọn nhẹ, sản phẩm B có cấu hình mạnh hơn nhưng giá cao hơn một chút).
- **Phân tích đánh đổi (Trade-offs)**: Giúp người dùng nhìn thấy điểm mạnh và điểm giới hạn của từng sản phẩm để đưa ra quyết định mua sắm sáng suốt.

### Nguyên tắc Groundedness (Chống ảo giác thông tin):

- LLM **tuyệt đối không được tự bịa đặt** giá cả, thông số kỹ thuật, thương hiệu, hoặc điểm đánh giá không có thật trong Product Knowledge Base.
- Mọi nhận định về sản phẩm phải có căn cứ trực tiếp từ `description` và `product_specifications` được cung cấp trong prompt context.

---

# 20. Telegram Bot Integration

Telegram Bot đóng vai trò là giao diện tương tác người dùng chính của ShopAssist.

Kiến trúc tích hợp:

```text
Telegram User
     │ (Natural language messages)
     ▼
Telegram Bot Service (Python)
     │ (HTTP POST /recommend)
     ▼
FastAPI Application
     │ (Dependency Injection)
     ▼
AI Recommendation Engine
  (Query Understanding → Hybrid Search → Reranking → Grounded LLM)
     │ (Structured JSON Response + Formatted Text)
     ▼
FastAPI Application
     │
     ▼
Telegram Bot Service
     │ (Markdown formatted response + Product Cards / Links)
     ▼
Telegram User
```

### Tính độc lập và khả năng mở rộng của kiến trúc:

- **Decoupled Architecture**: Giao diện Telegram Bot hoàn toàn tách rời khỏi Core AI Recommendation Engine.
- Tầng Core AI được đóng gói sau dịch vụ RESTful API chuẩn mực xây dựng bằng **FastAPI**.
- Nhờ thiết kế này, trong tương lai hệ thống có thể dễ dàng mở rộng để tích hợp thêm các nền tảng khác như:
  - Web Application (React / Next.js / Vue);
  - Mobile App;
  - Zalo Mini App / Chatbot;
  - Các hệ thống CSKH doanh nghiệp,
  mà không cần phải sửa đổi hay viết lại bất kỳ dòng code nào trong recommendation engine.

---

# 21. Evaluation Dataset

Để đánh giá một cách khoa học và định lượng hiệu năng của toàn bộ hệ thống, project xây dựng một bộ dữ liệu đánh giá chuẩn (Evaluation Benchmark Dataset).

### Quy mô mục tiêu:

> **200 – 500 test queries**

### Cấu trúc từng mẫu đánh giá:

```json
{
  "query_id": "test_042",
  "raw_query": "I need a lightweight laptop under $800 with good battery life.",
  "expected_structured_query": {
    "category": "laptop",
    "brand": null,
    "min_price": null,
    "max_price": 800,
    "min_rating": null,
    "preferences": [
      "lightweight",
      "good battery life"
    ]
  },
  "ground_truth_relevant_product_ids": [
    "PROD_00123",
    "PROD_00456",
    "PROD_00789"
  ]
}
```

### Phân loại các nhóm query kiểm thử:

1. **Simple Constraint Queries**: Chỉ chứa 1 ràng buộc cứng (ví dụ: *"Show me laptops under $600"*).
2. **Multi-Constraint Queries**: Kết hợp nhiều điều kiện cứng (ví dụ: *"Samsung smartphone with at least 4.0 rating between $200 and $400"*).
3. **Soft Preference Queries**: Chỉ chứa nhu cầu cảm tính/ngữ nghĩa (ví dụ: *"Ergonomic office chair for long working hours with good lumbar support"*).
4. **Use-case Queries**: Diễn đạt theo ngữ cảnh người dùng (ví dụ: *"Best gifts for college students who study computer science"*).
5. **Mixed Hard + Soft Requirements**: Kết hợp cả điều kiện cứng và ngữ nghĩa (ví dụ mẫu ở trên).

---

# 22. Query Understanding Evaluation

Đo lường năng lực của LLM trong việc chuyển đổi từ ngôn ngữ tự nhiên sang cấu trúc dữ liệu chính xác.

### Các chỉ số đánh giá:

1. **Category Accuracy**: Tỷ lệ phần trăm dự đoán đúng danh mục sản phẩm so với nhãn chuẩn.
2. **Brand Accuracy**: Tỷ lệ phần trăm bóc tách chính xác thương hiệu người dùng yêu cầu.
3. **Price Constraint Accuracy**: Độ chính xác trong việc xác định đúng ngưỡng giá (`min_price`, `max_price`).
4. **Rating Constraint Accuracy**: Độ chính xác khi nhận diện yêu cầu điểm đánh giá tối thiểu.
5. **Preference Extraction Metrics**:
   - **Precision**: Tỷ lệ sở thích bóc tách được thực sự có trong câu hỏi;
   - **Recall**: Tỷ lệ sở thích người dùng đề cập được LLM nhận diện đầy đủ;
   - **F1-Score**: Trung bình điều hòa giữa Precision và Recall của trích xuất sở thích.

---

# 23. Retrieval Quality Evaluation

Đo lường chất lượng truy xuất sản phẩm của các thuật toán tìm kiếm trên tập Ground Truth.

### Các chỉ số đánh giá:

1. **Precision@K (K = 3, 5)**: Tỷ lệ sản phẩm thực sự phù hợp trong top K sản phẩm được truy xuất.
2. **Recall@K (K = 3, 5)**: Tỷ lệ sản phẩm phù hợp được tìm thấy so với toàn bộ các sản phẩm liên quan có trong database.
3. **MRR (Mean Reciprocal Rank)**: Đánh giá vị trí xuất hiện của sản phẩm liên quan đầu tiên trong danh sách xếp hạng.
4. **nDCG@K (Normalized Discounted Cumulative Gain)**: Đánh giá chất lượng thứ tự xếp hạng của danh sách sản phẩm, ưu tiên các sản phẩm có độ liên quan cao xuất hiện ở các vị trí đầu tiên.

---

# 24. Constraint Satisfaction Evaluation

Đánh giá mức độ tuân thủ các điều kiện bắt buộc mà người dùng đã chỉ định rõ trong truy vấn.

### Chỉ số cốt lõi:

> **Constraint Satisfaction Rate (%)**

Được định nghĩa là tỷ lệ phần trăm các sản phẩm được đề xuất thỏa mãn 100% các điều kiện ràng buộc cứng (ngân sách, ngành hàng, thương hiệu, điểm đánh giá tối thiểu).

Ví dụ: Nếu người dùng đặt điều kiện `price <= 800`, bất kỳ sản phẩm nào có giá $805 xuất hiện trong danh sách đề xuất đều bị tính là vi phạm điều kiện (constraint violation). Phương pháp đạt chuẩn phải hướng tới tỷ lệ thỏa mãn tiệm cận 100%.

---

# 25. Generation Quality Evaluation

Đánh giá chất lượng của văn bản câu trả lời do LLM sinh ra trước khi gửi về cho người dùng.

### Tiêu chí đánh giá:

1. **Groundedness / Hallucination Rate**: Kiểm tra xem tất cả các thông số, tính năng, và mức giá được nhắc đến trong câu trả lời có bằng chứng xác thực trong Product Knowledge Base hay không.
2. **Factual Correctness**: Tính chính xác tuyệt đối của các thông tin kỹ thuật được trình bày.
3. **Recommendation Relevance**: Độ phù hợp của lý lẽ tư vấn so với câu hỏi và mục đích sử dụng ban đầu của người dùng.

---

# 26. System & Engineering Evaluation

Đánh giá hệ thống dưới góc độ kỹ thuật phần mềm và AI Engineering khi triển khai thực tế:

```text
- Average Latency (Độ trễ trung bình của một lượt tương tác end-to-end)
- P95 Latency (Độ trễ phân vị thứ 95)
- Retrieval Latency (Thời gian thực thi tìm kiếm database & vector)
- LLM Latency (Thời gian xử lý của các lệnh gọi mô hình ngôn ngữ)
- Token Usage per Request (Số lượng token tiêu thụ trung bình cho mỗi truy vấn)
- Cost per Request (Chi phí tài nguyên ước tính trên mỗi lượt người dùng)
- API Error Rate (Tỷ lệ lỗi của hệ thống backend)
```

---

# 27. Experimental Benchmarking

Bảng so sánh thực nghiệm tổng hợp giữa các phương pháp trên cùng một tập Evaluation Dataset:

| Phương pháp (Method) | Recall@5 | MRR | nDCG@5 | Constraint Satisfaction Rate | Groundedness | Latency (ms) |
|---|---:|---:|---:|---:|---:|---:|
| **Baseline 1: TF-IDF + Cosine** | - | - | - | Thấp (< 60%) | N/A | Rất thấp |
| **Baseline 2: Pure Embedding Search** | - | - | - | Trung bình (~70%) | N/A | Thấp |
| **Method 3: Structured Filter + Embedding** | - | - | - | Cao (> 95%) | N/A | Trung bình |
| **Proposed: LLM Understanding + Hybrid + Rerank** | **Cao nhất** | **Cao nhất** | **Cao nhất** | **Tiệm cận 100%** | **> 98%** | Chấp nhận được |

Mục tiêu thử nghiệm là chứng minh một cách định lượng sự vượt trội của phương pháp Proposed so với các baseline truyền thống.

---

# 28. Main Research / Engineering Question

Câu hỏi nghiên cứu và thực nghiệm kỹ thuật xuyên suốt của project ShopAssist:

> **Can LLM-based query understanding combined with structured filtering and semantic retrieval improve product recommendation quality compared with traditional TF-IDF and pure embedding-based retrieval?**

*(Liệu việc kết hợp cơ chế hiểu truy vấn dựa trên LLM cùng bộ lọc dữ liệu cấu trúc và tìm kiếm ngữ nghĩa có cải thiện chất lượng đề xuất sản phẩm một cách rõ rệt so với các phương pháp TF-IDF truyền thống và tìm kiếm vector thuần túy hay không?)*

---

# 29. Technology Stack

Kiến trúc công nghệ được lựa chọn theo tiêu chuẩn hiện đại, ổn định và tối ưu cho AI Engineering:

```text
Python 3.10+
│
├── Data Acquisition & Processing
│   ├── Pandas / NumPy
│   └── PyArrow (Parquet handling)
│
├── Baseline Retrieval
│   └── Scikit-learn (TF-IDF vectorizer, Cosine Similarity)
│
├── Embeddings & Vector Search
│   ├── Sentence Transformers (Hugging Face)
│   └── PostgreSQL + pgvector (Vector storage, HNSW indexing)
│
├── Query Understanding & Generation
│   └── LLM APIs (Structured Output via Pydantic / Function Calling)
│
├── Ranking / Reranking
│   └── Cross-Encoder (Sentence Transformers / FlashRank / Cohere)
│
├── Backend Application
│   ├── FastAPI (RESTful API, Async request handling)
│   └── Pydantic v2 (Data validation & schemas)
│
├── Conversational Interface
│   └── Telegram Bot API (thông qua thư viện python-telegram-bot hoặc tương đương)
│
├── Quality Assurance & Evaluation
│   ├── Pytest (Unit testing, integration testing)
│   └── Evaluation scripts (Custom metrics calculation)
│
└── Containerization & Deployment
    └── Docker & Docker Compose
```

---

# 30. Development Plan

Quy trình phát triển được thiết kế tuần tự, mạch lạc qua 17 giai đoạn rõ ràng:

### Phase 1 — Acquire Flipkart Dataset
- Tải về bộ dữ liệu Flipkart Products 20K;
- Kiểm tra tính toàn vẹn của tệp (file integrity, format parsing);
- Khảo sát sơ bộ cấu trúc các cột và kiểu dữ liệu ban đầu.

### Phase 2 — Dataset Profiling / EDA
- Phân tích chi tiết mức độ khuyết thiếu (missing values) trên từng trường;
- Kiểm tra và đo lường tỷ lệ dữ liệu trùng lặp (duplicates);
- Thống kê phân bố độ phủ của giá tiền (`retail_price`, `discounted_price`), đánh giá (`rating`), thương hiệu (`brand`), mô tả (`description`) và thông số (`product_specifications`);
- Lập báo cáo EDA tổng quan làm căn cứ ra quyết định kỹ thuật.

### Phase 3 — Category Selection
- Phân tích cây phân cấp danh mục (`product_category_tree`);
- Chọn lọc các nhóm ngành hàng phù hợp đáp ứng đầy đủ các tiêu chí về số lượng, chất lượng văn bản và tính ứng dụng cho mua sắm đàm thoại;
- Xác lập phạm vi ngành hàng chính thức cho hệ thống (đạt quy mô dự kiến khoảng 5,000 – 15,000 sản phẩm sạch).

### Phase 4 — Dataset Cleaning
- Loại bỏ các bản ghi thiếu thông tin định danh hoặc thiếu tiêu đề;
- Khử trùng lặp sản phẩm;
- Chuẩn hóa định dạng số cho giá và điểm rating;
- Chuẩn hóa tên thương hiệu và phân cấp danh mục;
- Làm sạch các chuỗi văn bản lỗi, ký tự HTML còn sót lại.

### Phase 5 — Build Product Knowledge Base
- Xây dựng trường đại diện ngữ nghĩa tổng hợp `retrieval_text` cho từng sản phẩm;
- Xuất dữ liệu sạch ra tệp chuẩn `products.parquet`;
- Thiết kế schema database trên PostgreSQL, cài đặt extension `pgvector`;
- Nạp toàn bộ dữ liệu cấu trúc và vector nhúng vào cơ sở dữ liệu, thiết lập index B-Tree và HNSW.

### Phase 6 — TF-IDF Baseline
- Xây dựng pipeline trích xuất đặc trưng văn bản bằng TF-IDF trên `retrieval_text`;
- Cài đặt hàm tìm kiếm theo độ tương đồng Cosine phục vụ đối chuẩn (Baseline 1).

### Phase 7 — Semantic Search
- Tích hợp mô hình Sentence Transformers sinh dense embedding cho câu hỏi và tài liệu;
- Cài đặt truy vấn tìm kiếm k-NN vector trong `pgvector` phục vụ đối chuẩn (Baseline 2).

### Phase 8 — LLM Query Understanding
- Thiết kế prompt và JSON schema chuẩn tắc cho LLM;
- Cài đặt module phân tích câu hỏi người dùng, bóc tách chính xác Hard Constraints và Soft Preferences.

### Phase 9 — Soft Preference Representation
- Xây dựng cơ chế chuyển đổi mảng sở thích người dùng thành câu truy vấn ngữ nghĩa cô đọng;
- Tạo vector nhúng đại diện cho các sở thích mềm để đối khớp vào không gian vector.

### Phase 10 — Hybrid Retrieval
- Tích hợp điều kiện lọc SQL và tìm kiếm vector tương đồng trong một câu truy vấn thống nhất;
- Kiểm tra độ chính xác và hiệu năng truy xuất tập ứng viên Top-N ban đầu.

### Phase 11 — Reranking
- Tích hợp mô hình Cross-Encoder hoặc thuật toán chấm điểm đa tín hiệu (Multi-signal scoring);
- Tái xếp hạng danh sách ứng viên Top-N để chọn lọc ra Top-K sản phẩm tối ưu nhất.

### Phase 12 — LLM Recommendation
- Thiết kế prompt sinh phản hồi tư vấn có căn cứ (grounded prompt);
- Cung cấp ngữ cảnh Top-K sản phẩm cho LLM sinh phân tích, so sánh ưu nhược điểm và đưa ra lý lẽ đề xuất thuyết phục.

### Phase 13 — Evaluation Dataset
- Xây dựng bộ dữ liệu đánh giá gồm 200 – 500 truy vấn đa dạng tình huống;
- Gán nhãn chuẩn cho structured query mong đợi và danh sách sản phẩm liên quan (ground truth).

### Phase 14 — Experimental Evaluation
- Chạy thử nghiệm tự động trên toàn bộ các phương pháp (Baseline 1, Baseline 2, Method 3, Proposed Method);
- Tính toán đầy đủ các chỉ số: Precision@K, Recall@K, MRR, nDCG@K, Constraint Satisfaction Rate, Groundedness, Latency;
- Lập bảng kết quả so sánh và viết báo cáo phân tích thực nghiệm.

### Phase 15 — FastAPI Backend
- Xây dựng backend RESTful API bằng FastAPI;
- Thiết lập endpoint chính `POST /recommend`;
- Tích hợp xử lý bất đồng bộ (async), cấu hình middleware, validation schemas và xử lý lỗi chuẩn mực.

### Phase 16 — Telegram Bot
- Phát triển Telegram Bot độc lập kết nối tới FastAPI backend;
- Xử lý tin nhắn người dùng, định dạng kết quả hiển thị trực quan (Markdown, hình ảnh sản phẩm, liên kết tham khảo);
- Xử lý các tình huống ngoại lệ, phản hồi chờ và hỗ trợ trải nghiệm người dùng mượt mà.

### Phase 17 — Deployment
- Đóng gói toàn bộ hệ thống bằng Docker và Docker Compose (FastAPI app, Telegram Bot, PostgreSQL + pgvector);
- Cấu hình logging tập trung, quản lý biến môi trường (.env);
- Giám sát độ trễ, mức độ tiêu thụ token và tính sẵn sàng của hệ thống.

---

# 31. MVP Scope & Boundaries

Phạm vi phiên bản sản phẩm khả thi tối thiểu (MVP - Version 1) bao gồm đầy đủ các thành phần cốt lõi:

```text
[x] Dataset Flipkart Products 20K
[x] Dataset Profiling & Báo cáo EDA
[x] Lựa chọn danh mục sản phẩm (Category Selection)
[x] Quy trình làm sạch dữ liệu cơ bản (Basic Cleaning)
[x] Xây dựng Product Knowledge Base (PostgreSQL + pgvector)
[x] Baseline 1: TF-IDF Retrieval
[x] Baseline 2: Dense Embedding Retrieval
[x] LLM Query Understanding (Trích xuất JSON cấu trúc)
[x] Hard Constraint Filtering qua SQL
[x] Soft Preference Embedding Representation
[x] Hybrid Retrieval kết hợp lọc và tìm kiếm vector
[x] Ranking / Reranking ứng viên Top-K
[x] Grounded LLM Recommendation Generation
[x] Bộ dữ liệu đánh giá và pipeline thực nghiệm định lượng
[x] Backend RESTful API với FastAPI
[x] Conversational Interface qua Telegram Bot
[x] Đóng gói và triển khai qua Docker
```

---

# 32. Out of Scope for V1

Các tính năng và hướng phát triển sau đây nằm ngoài phạm vi của phiên bản V1 và có thể được xem xét ở các phiên bản tiếp theo:

```text
[-] Không sử dụng dữ liệu đánh giá chi tiết của người dùng (Raw User Reviews)
[-] Không thực hiện tổng hợp review (Review Aggregation) hoặc trích xuất pros/cons từ review
[-] Không xây dựng hệ thống gợi ý cá nhân hóa dựa trên lịch sử mua hàng (Personalized Recommendation)
[-] Không áp dụng lọc cộng tác (Collaborative Filtering) hoặc phân tích giỏ hàng
[-] Không fine-tuning mô hình ngôn ngữ lớn (LLM Fine-tuning)
[-] Không xây dựng hệ thống đa tác tử phức tạp (Multi-agent Systems)
[-] Không phát triển giao diện người dùng web đa trang phức tạp (Complex Web UI)
```

---

# 33. Key Highlights of the Project

ShopAssist không đơn thuần là một ứng dụng bọc LLM đơn giản ("wrapper") hay một hệ thống RAG cơ bản dạng:

```text
Product Description ──► Vector Database ──► LLM
```

Điểm khác biệt cốt lõi của ShopAssist nằm ở kiến trúc kỹ thuật AI Engineering bài bản và toàn diện:

```text
Data Engineering (EDA, Cleaning, Knowledge Base Construction)
        ↓
Natural Language Understanding
        ↓
LLM Structured Query Extraction (Tách biệt Hard Constraints và Soft Preferences)
        ↓
Deterministic Hard Constraint Filtering (Đảm bảo 100% không vi phạm điều kiện)
        ↓
Semantic Preference Understanding (Nắm bắt nhu cầu cảm tính người dùng)
        ↓
Hybrid Retrieval (Thu hẹp không gian tìm kiếm kết hợp vector search)
        ↓
Ranking / Reranking (Cross-Encoder tinh chỉnh thứ tự ưu tiên)
        ↓
Grounded LLM Recommendation (Sinh lời giải thích minh bạch, không ảo giác)
        ↓
Empirical Evaluation (Đo lường định lượng từng thành phần AI độc lập)
        ↓
Production-ready Architecture (FastAPI Backend + Telegram Bot + Docker)
```

Mỗi thành phần trong chuỗi xử lý đều có giao diện định nghĩa rõ ràng, có khả năng đo lường độc lập và có thể thay thế hoặc nâng cấp linh hoạt, thể hiện rõ tư duy kỹ thuật kết hợp giữa **Khoa học Dữ liệu, Xử lý Ngôn ngữ Tự nhiên và Kỹ thuật Phần mềm Hiện đại**.

---

# 34. Final Project Definition

Tóm tắt định nghĩa kỹ thuật chính thức của dự án:

- **Project Name**: ShopAssist
- **Technical Name**: Conversational Product Recommendation System using LLM-based Query Understanding and Hybrid Retrieval
- **Domain**: E-commerce Consumer Products
- **Primary Dataset**: Flipkart Products 20K
- **Product Scope**: Được xác định chính thức sau quá trình dataset profiling và phân tích phân bố ngành hàng
- **Product Data**: Structured Product Metadata + Product Descriptions + Product Specifications
- **Query Understanding**: LLM-based Structured Query Extraction + Semantic Representation of Soft Preferences
- **Retrieval**: Structured Filtering + Semantic Search
- **Recommendation**: Ranking / Reranking + Grounded LLM Explanation
- **Database**: PostgreSQL + pgvector
- **Backend**: FastAPI
- **Interface**: Telegram Bot
- **Evaluation**: Query Understanding, Retrieval Quality, Constraint Satisfaction, Generation Quality, System Performance
- **Main Objective**: Build and evaluate an end-to-end conversational product recommendation system capable of understanding natural-language purchasing requirements and recommending relevant products based on both explicit constraints and semantic user preferences.
