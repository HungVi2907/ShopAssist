
# ShopAssist — Conversational Product Recommendation System

## 1. Project Overview

ShopAssist là một hệ thống AI hỗ trợ tư vấn và đề xuất các thiết bị điện gia dụng nhà bếp thông qua hội thoại tự nhiên.

Người dùng tương tác với hệ thống thông qua Discord Bot.

Ví dụ:

> “Tôi cần một máy pha cà phê dưới $100, nhỏ gọn và dễ vệ sinh.”

Hệ thống cần hiểu được:

```text
Hard Constraints
- category = coffee maker
- price <= 100
```

và:

```text
Soft Preferences
- compact
- easy to clean
```

Sau đó hệ thống tìm kiếm, xếp hạng và đề xuất các sản phẩm phù hợp nhất từ Product Knowledge Base.

Kiến trúc tổng quát:

```text
User
↓
Discord Bot
↓
FastAPI
↓
LLM Query Understanding
↓
Hard Constraints + Soft Preferences
↓
Hybrid Product Retrieval
↓
Ranking / Reranking
↓
Top-K Products
↓
LLM Recommendation
↓
Discord Response
```

---

# 2. Problem Statement

Các nền tảng thương mại điện tử cung cấp hàng nghìn hoặc hàng triệu sản phẩm.

Người dùng thường phải:

- tìm kiếm bằng keyword;
- sử dụng nhiều bộ lọc;
- đọc nhiều mô tả sản phẩm;
- tự so sánh thông số;
- đọc reviews;
- tự xác định sản phẩm nào phù hợp với nhu cầu thực tế.

Trong khi đó, nhu cầu mua hàng thường được diễn đạt bằng ngôn ngữ tự nhiên.

Ví dụ:

> “Tôi sống một mình, muốn một air fryer không quá đắt, nhỏ gọn và dễ vệ sinh.”

Một search engine truyền thống có thể xử lý:

```text
category = air fryer
price <= X
```

nhưng khó xử lý:

```text
good for one person
compact
easy to clean
```

Project đặt ra bài toán:

> Làm thế nào để xây dựng một hệ thống có khả năng hiểu cả các điều kiện rõ ràng và các preference mang tính ngữ nghĩa của người dùng để đề xuất sản phẩm phù hợp?

---

# 3. Domain

Domain chính thức:

> **Small Kitchen Appliances**

Phiên bản V1 tập trung vào 5 product families:

```text
1. Coffee Makers
2. Blenders
3. Air Fryers
4. Electric Kettles
5. Rice Cookers
```

Không bao gồm:

```text
spare parts
replacement filters
replacement blades
accessories
installation components
attachments
covers
lids
adapters
```

Mục tiêu là chỉ giữ lại các sản phẩm hoàn chỉnh mà người dùng thực sự có thể cân nhắc mua.

---

# 4. Dataset

## 4.1 Data Source

Nguồn dữ liệu:

> **Amazon Reviews 2023**

Giả định trong đề xuất ban đầu là top-level category:

```text
Appliances
```

Sau Phase 2, `Appliances` không có độ phủ phù hợp cho cả năm family. Nguồn metadata **đang được sử dụng** để xây dựng candidate là `Home_and_Kitchen` của Amazon Reviews 2023. Phase 3B đã quét hết file metadata 11,788,767,944 byte bằng HTTP byte ranges, không tải toàn bộ file về máy.

Sử dụng hai nguồn dữ liệu:

```text
Product Metadata
+
Product Reviews
```

---

# 5. Dataset Acquisition Strategy

Amazon Reviews 2023 không cung cấp trực tiếp một dataset tên:

```text
Small Kitchen Appliances
```

Ban đầu dự kiến xây dựng dataset từ category:

```text
Appliances
```

rồi lọc xuống 5 product families đã chọn. Kết quả khám phá cho thấy cần chuyển nguồn chính sang `Home_and_Kitchen`.

Quy trình:

```text
Amazon Reviews 2023
        ↓
Home_and_Kitchen Metadata
        ↓
Candidate Discovery (Phase 3/3B)
        ↓
Stratified Manual Audit (Phase 4A)
        ↓
Cleaning Rule Design (Phase 4B)
        ↓
Final Product Selection (Phase 4C)
        ↓
Collect parent_asin
        ↓
Acquire Reviews for Selected parent_asin
        ↓
Aggregate Reviews
        ↓
Final Product Knowledge Base
```

---

# 6. Metadata Download

Bước đầu đã tải và phân tích:

```text
meta_Appliances.jsonl
```

Sau EDA, Phase 3B đã quét toàn bộ metadata `meta_Home_and_Kitchen.jsonl` qua HTTP byte ranges và chỉ lưu các candidate. Xem [báo cáo Phase 3B](phase3b_full_scan.md).

Không tải reviews ngay.

Mục tiêu đầu tiên là kiểm tra taxonomy thực tế của Amazon.

Các field quan trọng gồm:

```text
main_category
title
average_rating
rating_number
features
description
price
store
categories
details
parent_asin
```

---

# 7. Taxonomy Exploration

Trong Phase 2, sau khi tải metadata `Appliances`:

```text
Appliances
```

thực hiện EDA để xác định Amazon đang biểu diễn 5 product families như thế nào.

Ví dụ có thể gặp:

```text
Coffee Makers
Drip Coffee Makers
Countertop Blenders
Air Fryers
Electric Kettles
Rice Cookers
```

Không hard-code taxonomy trước khi kiểm tra dữ liệu thực tế.

Mục tiêu của bước này:

```text
Coffee Maker        → count
Blender             → count
Air Fryer           → count
Electric Kettle     → count
Rice Cooker         → count
```

---

# 8. Product Family Detection

Xây dựng mapping riêng:

```text
coffee_maker
blender
air_fryer
electric_kettle
rice_cooker
```

Detection dựa trên:

```text
categories
+
title
```

thay vì chỉ dựa vào keyword trong title.

Ví dụ:

```text
Coffee Maker:
- coffee maker
- coffee machine
- drip coffee

Blender:
- blender
- countertop blender

Air Fryer:
- air fryer

Electric Kettle:
- electric kettle

Rice Cooker:
- rice cooker
```

---

# 9. Accessory Filtering

Keyword matching đơn giản có thể gặp sản phẩm như:

```text
Replacement Blade for Blender
```

và nhầm thành blender hoàn chỉnh.

Do đó cần kiểm toán mẫu trước khi thiết kế exclusion filtering. Các từ khóa dưới đây chỉ là ví dụ tín hiệu; không được tự động xóa toàn bộ sản phẩm có từ `filter`, `basket` hoặc cờ phụ kiện.

Ví dụ:

```text
replacement
spare
accessory
filter
blade replacement
lid
cover
adapter
attachment
part
parts
```

Pipeline:

```text
Product
↓
Product Family Detection
↓
Accessory Signal
↓
Manual Audit → Rule Validation → Keep / Remove (Phase 4B/4C)
```

---

# 10. Dataset Validation

Sau cleaning, thống kê lại số lượng.

Target dataset:

> **5,000 – 15,000 clean products**

Phase 3B có 55,064 candidate với `parent_asin` duy nhất; đây **chưa phải** 55,064 sản phẩm sạch. Phase 4 xác định tập cuối cùng. Không nới lỏng quy tắc chất lượng chỉ để đạt target.

V1 hướng tới thiết bị nhà bếp nhỏ chạy điện. Dụng cụ pha cà phê thủ công và ấm đun trên bếp dự kiến nằm ngoài phạm vi cuối cùng, nhưng Phase 4A chỉ ghi nhãn mẫu; Phase 4B mới thiết kế và xác thực quy tắc. Giá thiếu không loại candidate ở Phase 4A; SQL price constraints chỉ áp dụng trên sản phẩm có giá, còn chính sách cho giá thiếu sẽ được quyết định sau.

Không cần cố lấy càng nhiều càng tốt.

Ưu tiên:

```text
quality
>
quantity
```

Sản phẩm tối thiểu phải có:

```text
parent_asin
title
product_family
```

và nên có ít nhất một trong:

```text
description
features
details
```

Có thể ưu tiên những sản phẩm có:

```text
rating_number >= 5
```

hoặc:

```text
rating_number >= 10
```

nhưng chỉ áp dụng sau khi kiểm tra phân phối dữ liệu.

---

# 11. Category Validation Checkpoint — Completed

Trước khi chốt dataset cuối cùng, cần kiểm tra:

> 5 product families có xuất hiện đủ trong `Appliances` hay không?

Nếu:

```text
Appliances
```

đã cung cấp đủ 5 category và đạt target dataset:

```text
5K–15K products
```

thì giữ nguyên nguồn duy nhất là `Appliances`.

Nếu một số family có quá ít dữ liệu, mới xem xét bổ sung subset từ:

```text
Home_and_Kitchen
```

Kết quả: `Appliances` thiếu độ phủ cân bằng cho năm family; mẫu `Home_and_Kitchen` cho thấy độ phủ tốt hơn. Phase 3B đã quét toàn bộ metadata của nguồn này và thu 55,064 candidate từ 3,735,584 bản ghi. Đây là kết quả khám phá candidate, chưa phải tập sản phẩm cuối. Xem [kiểm tra nguồn](home_and_kitchen_probe.md) và [Phase 3B](phase3b_full_scan.md).

---

# 12. Reviews Acquisition

Chỉ sau Phase 4C, khi tập `parent_asin` sạch cuối cùng đã được chốt, mới tải reviews liên quan từ Amazon Reviews 2023 (bao gồm nguồn `Home_and_Kitchen` phù hợp với sản phẩm được chọn):

```text
Reviews for selected products
```

Sau đó lấy danh sách:

```text
selected parent_asin
```

và chỉ giữ reviews thuộc những sản phẩm đã chọn.

Flow:

```text
Selected Products
↓
parent_asin list
↓
Relevant Reviews
↓
Filter Reviews
↓
Selected Reviews
```

Không giữ toàn bộ review dataset.

---

# 13. Aggregated Reviews

Không đưa hàng trăm review raw của từng sản phẩm trực tiếp vào Vector Database.

Thay vào đó tạo:

```text
Aggregated Review Information
```

Ví dụ:

```text
review_count
average_review_rating
common positive points
common negative points
review summary
```

Ví dụ:

```json
{
  "review_summary": {
    "pros": [
      "easy to clean",
      "compact",
      "fast cooking"
    ],
    "cons": [
      "small capacity",
      "fan can be noisy"
    ]
  }
}
```

Điều này đặc biệt hữu ích cho các soft preferences như:

```text
easy to clean
quiet
compact
good for one person
```

---

# 14. Final Product Dataset

Dataset cuối cùng dự kiến có schema:

```text
parent_asin

product_family

title

brand

price

average_rating

rating_number

categories

description

features

details

review_count

review_rating

review_summary

retrieval_text
```

Trong đó:

```text
retrieval_text
=
title
+
features
+
description
+
technical details
+
review summary
```

`retrieval_text` được sử dụng để tạo embedding.

---

# 15. Data Organization

Cấu trúc dữ liệu hiện có và dự kiến (các file review và sản phẩm sạch chỉ xuất hiện ở phase sau):

```text
data/

├── raw/
│   ├── meta_Appliances.jsonl
│   └── reviews_source.jsonl                 # Phase 5, dự kiến
│
├── interim/
│   ├── category_analysis.csv
│   ├── home_kitchen_candidates.jsonl         # Phase 3B
│   ├── phase4a_audit_sample.csv              # Phase 4A
│   ├── selected_products.jsonl
│   └── selected_reviews.jsonl
│
└── processed/
    └── products.parquet
```

`products.parquet` sẽ là dataset chính của AI system sau Phase 5/6. Không tạo file `meta_Home_and_Kitchen.jsonl` local trong Phase 3B.

---

# 16. Query Understanding

Phương pháp chính thức:

> **LLM-based Structured Query Extraction + Semantic Representation of Soft Preferences**

Ví dụ user hỏi:

> “Tôi muốn một máy pha cà phê Philips dưới $150, nhỏ gọn và dễ dùng.”

LLM parse thành:

```json
{
  "category": "coffee_maker",
  "brand": "Philips",
  "min_price": null,
  "max_price": 150,
  "min_rating": null,
  "preferences": [
    "compact",
    "easy to use"
  ]
}
```

LLM ở bước này:

```text
không recommend sản phẩm
```

mà chỉ làm nhiệm vụ:

```text
Natural Language
↓
Structured Representation
```

---

# 17. Hard Constraints

Hard constraints là các điều kiện có thể filter chính xác.

Ví dụ:

```text
category
brand
min_price
max_price
min_rating
```

Ví dụ:

```text
category = coffee_maker
brand = Philips
price <= 150
```

được xử lý bằng:

```text
SQL Filtering
```

---

# 18. Soft Preferences

Soft preferences là các yêu cầu khó biểu diễn bằng SQL.

Ví dụ:

```text
quiet
compact
easy to clean
easy to use
good for one person
good for family
good for beginner
powerful
energy efficient
```

Các preference được chuyển thành semantic representation.

Ví dụ:

```text
["compact", "easy to clean", "good for one person"]
```

↓

```text
Semantic Query
```

↓

```text
Embedding Model
```

↓

```text
Query Embedding
```

---

# 19. Product Knowledge Base

Dữ liệu được chia thành hai nhóm.

## Structured Information

Ví dụ:

```text
product_family
brand
price
rating
```

dùng cho:

```text
SQL Filtering
```

## Unstructured Information

Ví dụ:

```text
description
features
details
review_summary
```

dùng cho:

```text
Embedding
+
Semantic Search
```

Database:

```text
PostgreSQL
+
pgvector
```

---

# 20. Main AI Method

Phương pháp chính:

> **LLM Query Understanding + Hybrid Retrieval + Reranking + LLM Recommendation**

Flow:

```text
User Query
        ↓
LLM Structured Query Extraction
        ↓
┌──────────────────────┐
│ Hard Constraints     │
│ category             │
│ brand                │
│ price                │
│ rating               │
└──────────────────────┘
          +
┌──────────────────────┐
│ Soft Preferences     │
│ compact              │
│ quiet                │
│ easy to clean        │
│ good for family      │
└──────────────────────┘
          ↓
Structured Filtering
+
Semantic Search
          ↓
Candidate Products
          ↓
Ranking / Reranking
          ↓
Top-K
          ↓
LLM Recommendation
```

---

# 21. Hybrid Retrieval

Ví dụ:

> “Tôi cần air fryer dưới $120, nhỏ và dễ vệ sinh.”

LLM extract:

```text
Hard:
category = air_fryer
price <= 120
```

và:

```text
Soft:
compact
easy to clean
```

SQL:

```text
category = air_fryer
AND
price <= 120
```

tạo ra candidate set.

Sau đó semantic search sử dụng:

```text
compact
easy to clean
```

để ranking các candidate.

---

# 22. Retrieval Methods for Experiment

Project sẽ benchmark nhiều phương pháp.

## Baseline 1

```text
TF-IDF
+
Cosine Similarity
```

## Baseline 2

```text
Embedding
+
Vector Search
```

## Method 3

```text
Structured Filtering
+
Embedding Search
```

## Proposed Method

```text
LLM Query Understanding
+
Structured Filtering
+
Semantic Search
+
Reranking
```

---

# 23. Ranking / Reranking

Hybrid Retrieval có thể trả:

```text
Top 20 Candidates
```

Sau đó reranking chọn:

```text
Top 3–5 Products
```

Ranking có thể kết hợp:

```text
semantic similarity

constraint satisfaction

product rating

reranker score
```

---

# 24. LLM Recommendation

LLM nhận:

```text
Original User Query

+

Top-K Product Metadata
```

LLM có nhiệm vụ:

- giải thích sản phẩm nào phù hợp;
- so sánh các lựa chọn;
- chỉ ra trade-off;
- hỗ trợ người dùng đưa ra quyết định.

Ví dụ:

> Product A phù hợp nhất nếu bạn ưu tiên kích thước nhỏ và dễ vệ sinh. Product B có dung tích lớn hơn nhưng giá cao hơn. Product C phù hợp hơn nếu bạn thường nấu cho nhiều người.

LLM:

```text
không được tự tạo thông số sản phẩm
```

mà phải dựa trên Product Knowledge Base.

---

# 25. Discord Integration

Discord chỉ đóng vai trò interface.

Architecture:

```text
Discord User
↓
Discord Bot
↓
FastAPI
↓
AI Recommendation Engine
↓
FastAPI
↓
Discord Bot
↓
User
```

Core AI system được tách riêng khỏi Discord.

Nhờ đó sau này có thể tích hợp:

```text
Zalo
Telegram
Web Application
Mobile Application
```

mà không phải xây lại recommendation engine.

---

# 26. Evaluation Dataset

Ngoài Amazon Product Dataset, project xây dựng một evaluation dataset riêng.

Cấu trúc:

```text
User Query

Expected Structured Query

Relevant Products
```

Target:

```text
200–500 queries
```

Các query gồm:

```text
Simple Constraints

Multi-Constraints

Soft Preferences

Use-case Queries

Mixed Hard + Soft Requirements
```

Ví dụ:

```text
"I need a quiet blender under $100."
```

Ground truth:

```json
{
  "category": "blender",
  "max_price": 100,
  "preferences": [
    "quiet"
  ]
}
```

---

# 27. Query Understanding Evaluation

Đánh giá khả năng LLM hiểu user query.

Metrics:

```text
Category Accuracy

Brand Accuracy

Price Constraint Accuracy

Rating Constraint Accuracy

Preference Extraction Precision

Preference Extraction Recall

Preference Extraction F1
```

Ví dụ:

```text
Category Accuracy = 96%

Price Constraint Accuracy = 95%

Preference Extraction F1 = 0.88
```

---

# 28. Retrieval Evaluation

Metrics:

```text
Precision@K

Recall@K

MRR

nDCG@K
```

Mục tiêu:

> Relevant products có xuất hiện ở vị trí cao trong ranking hay không?

---

# 29. Constraint Satisfaction Evaluation

Đánh giá recommendation có thỏa hard constraints hay không.

Metric:

> **Constraint Satisfaction Rate**

Ví dụ:

```text
User:
price <= $100
```

Nếu hệ thống recommend sản phẩm:

```text
$150
```

thì tính là violation.

---

# 30. Generation Evaluation

Đánh giá câu trả lời cuối của LLM.

Metrics / criteria:

```text
Groundedness

Factual Correctness

Recommendation Relevance
```

Kiểm tra xem LLM có:

```text
sai giá

sai brand

sai feature

sai capacity

tạo thông tin không có trong KB
```

hay không.

---

# 31. System Evaluation

Đánh giá dưới góc độ AI Engineering:

```text
Average Latency

P95 Latency

Retrieval Latency

LLM Latency

Token Usage / Request

Cost / Request

API Error Rate
```

---

# 32. Main Experiment

Benchmark:

| Method | Recall@5 | MRR | nDCG@5 | Constraint Satisfaction |
|---|---:|---:|---:|---:|
| TF-IDF | | | | |
| Embedding Search | | | | |
| Hybrid Retrieval | | | | |
| LLM Query Understanding + Hybrid | | | | |
| Hybrid + Reranking | | | | |

Mục tiêu experiment:

> Kiểm tra việc kết hợp LLM-based query understanding, structured filtering và semantic retrieval có cải thiện chất lượng product recommendation so với traditional search hay không.

---

# 33. Research / Engineering Question

Câu hỏi kỹ thuật chính:

> **Can LLM-based query understanding combined with structured filtering and semantic retrieval improve product recommendation quality compared with traditional TF-IDF and pure embedding-based retrieval?**

Đây sẽ là câu hỏi xuyên suốt phần experiment và evaluation.

---

# 34. Technology Stack

```text
Python
│
├── Data Processing
│   └── Pandas
│
├── Baseline Retrieval
│   └── Scikit-learn / TF-IDF
│
├── Embedding
│   └── Sentence Transformers
│
├── Database
│   └── PostgreSQL
│       └── pgvector
│
├── Query Understanding
│   └── LLM Structured Output
│
├── Ranking / Reranking
│
├── Recommendation Generation
│   └── LLM
│
├── Backend
│   └── FastAPI
│
├── Discord
│   └── discord.py
│
├── Testing
│   └── pytest
│
└── Deployment
    └── Docker
```

---

# 35. Development Plan

## Phase 1 — Metadata Acquisition (completed)

Download:

```text
meta_Appliances.jsonl
```

Chưa tải reviews.

---

## Phase 2 — Dataset Exploration (completed)

Phân tích:

```text
categories
title
features
details
description
price
rating
parent_asin
```

Thống kê 5 product families.

---

## Phase 3 — Candidate Dataset Construction (completed)

Phát hiện candidate có độ phủ cao cho:

```text
Coffee Makers
Blenders
Air Fryers
Electric Kettles
Rice Cookers
```

Gắn cờ để kiểm toán, chưa loại tự động:

```text
Accessories
Replacement Parts
Spare Parts
```

Target sau Phase 4C:

```text
5K–15K clean products
```

## Phase 3B — Full Home_and_Kitchen Metadata Scan (completed)

Đã quét 3,735,584 metadata records qua HTTP byte ranges; giữ 55,064 candidate, 55,064 `parent_asin` duy nhất. Tập này còn phụ kiện, sản phẩm thủ công và các bản ghi mơ hồ, nên chưa phải clean dataset.

## Phase 4A — Stratified Candidate Audit (metadata-based labels completed)

Đã lấy mẫu theo năm family × `title_only`/`taxonomy_only`/`both`, bổ sung nhóm cờ rủi ro và gán nhãn 380 dòng từ metadata; 45 ca khó được xét sâu, 6 dòng có nhãn `AMBIGUOUS`. Đây là bằng chứng kiểm toán, chưa phải quy tắc lọc cuối. Xem [hướng dẫn Phase 4A](phase4a_stratified_audit.md) và [báo cáo gán nhãn](phase4a_labeling_report.md).

## Phase 4B — Cleaning Rule Design and Validation (implemented on Phase 4A sample)

Đã phân tích nhãn audit và kiểm chứng quy tắc xác định cho phụ kiện, dụng cụ thủ công, ấm dùng trên bếp, hàng ngoài phạm vi và bảo vệ máy hợp lệ. Quy tắc có kết quả `KEEP`/`REMOVE`/`REVIEW`, lý do và `rule_id`; đã đo precision, recall, lỗi loại nhầm và ca chưa đủ chứng cứ trên 380 dòng mẫu. Xem [Phase 4B](phase4b_cleaning_rules.md). Chưa chạy làm sạch toàn bộ 55.064 candidate.

## Phase 4C — Final Product Cleaning and Selection

Áp dụng quy tắc đã kiểm chứng và chốt tập `parent_asin` sạch. Mục tiêu 5,000–15,000 sản phẩm là định hướng, ưu tiên chất lượng hơn số lượng. Quyết định chính sách giá thiếu tại đây.

---

## Phase 5 — Review Acquisition and Aggregation

Chỉ lấy review của:

```text
selected parent_asin
```

Tạo:

```text
review_count
review rating
review summary
pros
cons
```

---

## Phase 6 — Build Product Knowledge Base

Tạo:

```text
products.parquet
```

Sau đó import vào:

```text
PostgreSQL
+
pgvector
```

---

## Phase 7 — TF-IDF Baseline

Implement:

```text
User Query
↓
TF-IDF
↓
Cosine Similarity
↓
Top-K Products
```

---

## Phase 8 — Embedding / Semantic Search

Implement:

```text
Product Text
↓
Embedding
↓
pgvector
```

So sánh:

```text
TF-IDF
vs
Embedding Search
```

---

## Phase 9 — LLM Query Understanding

Implement:

```text
User Query
↓
LLM
↓
Structured JSON
```

Schema:

```json
{
  "category": null,
  "brand": null,
  "min_price": null,
  "max_price": null,
  "min_rating": null,
  "preferences": []
}
```

---

## Phase 10 — Soft Preference Representation

```text
preferences
↓
Semantic Query
↓
Embedding
```

---

## Phase 11 — Hybrid Retrieval

```text
Hard Constraints
↓
SQL Filtering
```

+

```text
Soft Preferences
↓
Semantic Retrieval
```

↓

```text
Candidate Products
```

---

## Phase 12 — Reranking

```text
Top 20
↓
Reranker
↓
Top 3–5
```

---

## Phase 13 — LLM Recommendation

Input:

```text
User Query
+
Top Products
+
Product Metadata
```

Output:

```text
Recommendation

Reason

Comparison

Trade-offs
```

---

## Phase 14 — Evaluation Dataset

Tạo:

```text
200–500 queries
```

với:

```text
Expected Structured Query
+
Relevant Products
```

---

## Phase 15 — Experimental Evaluation

Benchmark:

```text
TF-IDF

Embedding

Hybrid

LLM + Hybrid

Hybrid + Reranking
```

Metrics:

```text
Query Parsing Accuracy

Precision@K

Recall@K

MRR

nDCG@K

Constraint Satisfaction Rate

Groundedness
```

---

## Phase 16 — FastAPI

API chính:

```text
POST /recommend
```

Input:

```json
{
  "query": "I need a compact air fryer under $100"
}
```

Output:

```json
{
  "parsed_query": {},
  "products": [],
  "answer": ""
}
```

---

## Phase 17 — Discord Bot

```text
Discord
↓
FastAPI
↓
Recommendation Engine
↓
FastAPI
↓
Discord
```

---

## Phase 18 — Deployment

- Dockerize backend.
- Deploy FastAPI.
- Deploy Discord Bot.
- Logging.
- Error handling.
- LLM usage tracking.
- Latency monitoring.

---

# 36. MVP Scope

Version 1 bắt buộc có:

```text
Amazon Home_and_Kitchen Metadata

5 Product Families

Dataset Cleaning

Aggregated Reviews

TF-IDF Baseline

Embedding Retrieval

LLM Query Understanding

Hard Constraint Filtering

Soft Preference Embedding

Hybrid Retrieval

Ranking / Reranking

LLM Recommendation

Evaluation

FastAPI

Discord Bot

Docker Deployment
```

---

# 37. Out of Scope for V1

Chưa thực hiện:

```text
Personalized Recommendation

User Purchase History

Collaborative Filtering

User Profile Learning

Fine-tuning LLM

Multi-agent Systems

Complex Agent Framework

Complex Web UI
```

Có thể phát triển trong Version 2.

---

# 38. Điểm nổi bật của project

Project không chỉ là:

```text
Product Description
↓
Vector Database
↓
LLM
```

mà là:

```text
Data Engineering
        ↓
Natural Language Understanding
        ↓
LLM Structured Extraction
        ↓
Hard Constraint Filtering
        ↓
Semantic Preference Understanding
        ↓
Hybrid Retrieval
        ↓
Ranking / Reranking
        ↓
Grounded LLM Recommendation
        ↓
Evaluation
        ↓
API
        ↓
Discord
        ↓
Deployment
```

Điểm quan trọng nhất là mỗi AI component có thể được đánh giá riêng.

Điều này giúp project thể hiện cả:

```text
AI / NLP

AI Engineering

Software Engineering

Experimental Evaluation
```

---

# 39. Final Project Definition

**Project Name**

> ShopAssist

**Technical Name**

> Conversational Product Recommendation System using LLM-based Query Understanding and Hybrid Retrieval

**Domain**

> Small Kitchen Appliances

**Source**

> Amazon Reviews 2023

**Primary Source Category**

> Home_and_Kitchen (metadata chính sau EDA; `Appliances` là giả định ban đầu)

**Product Families**

```text
Coffee Makers
Blenders
Air Fryers
Electric Kettles
Rice Cookers
```

**Product Data**

```text
Metadata
+
Aggregated Reviews
```

**Target Dataset**

```text
5,000 – 15,000 clean products
```

**Query Understanding**

> LLM-based Structured Query Extraction + Semantic Representation of Soft Preferences

**Retrieval**

> Structured Filtering + Semantic Search

**Recommendation**

> Ranking / Reranking + Grounded LLM Explanation

**Interface**

> Discord Bot

**Evaluation**

```text
Query Understanding

Retrieval Quality

Constraint Satisfaction

Generation Quality

System Performance
```

**Main Objective**

> Build and evaluate an end-to-end conversational product recommendation system capable of understanding natural-language purchasing requirements and recommending relevant small kitchen appliances based on both explicit constraints and semantic user preferences.
