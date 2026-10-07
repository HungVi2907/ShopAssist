# Phase 2: Exploratory Data Analysis & Dataset Profiling Report

> **Project**: ShopAssist — Conversational Product Recommendation System
> **Dataset**: Flipkart Products 20K (`data/raw/flipkart_products.csv`)
> **Scope**: Strictly analytical (read-only, no data cleaning or filtering applied).

---

## 1. Dataset Overview

- **Total Rows**: 20,000
- **Total Columns**: 15
- **Memory Usage**: 47.6 MB
- **Duplicate Columns**: []

### Column Summary Table

| Column Name | Inferred Dtype | Non-Null Count | Null Count | Null % | Unique Count | Unique % |
|---|---|---:|---:|---:|---:|---:|
| `uniq_id` | `object` | 20,000 | 0 | 0.0% | 20,000 | 100.0% |
| `crawl_timestamp` | `object` | 20,000 | 0 | 0.0% | 371 | 1.85% |
| `product_url` | `object` | 20,000 | 0 | 0.0% | 20,000 | 100.0% |
| `product_name` | `object` | 20,000 | 0 | 0.0% | 12,676 | 63.38% |
| `product_category_tree` | `object` | 20,000 | 0 | 0.0% | 6,466 | 32.33% |
| `pid` | `object` | 20,000 | 0 | 0.0% | 19,998 | 99.99% |
| `retail_price` | `float64` | 19,922 | 78 | 0.39% | 2,247 | 11.24% |
| `discounted_price` | `float64` | 19,922 | 78 | 0.39% | 2,448 | 12.24% |
| `image` | `object` | 19,997 | 3 | 0.01% | 18,589 | 92.94% |
| `is_FK_Advantage_product` | `bool` | 20,000 | 0 | 0.0% | 2 | 0.01% |
| `description` | `object` | 19,998 | 2 | 0.01% | 17,539 | 87.7% |
| `product_rating` | `object` | 20,000 | 0 | 0.0% | 36 | 0.18% |
| `overall_rating` | `object` | 20,000 | 0 | 0.0% | 36 | 0.18% |
| `brand` | `object` | 14,136 | 5,864 | 29.32% | 3,499 | 17.5% |
| `product_specifications` | `object` | 19,986 | 14 | 0.07% | 18,825 | 94.12% |

---

## 2. Missing Values Analysis

Phân tích tỷ lệ khuyết thiếu thực tế (kết hợp NaN, chuỗi rỗng, khoảng trắng, và chuỗi semantic missing như `"No rating available"`):

| Column | Actual NaN | Empty / WS | Semantic Missing | Effective Missing | Effective Missing % |
|---|---:|---:|---:|---:|---:|
| `uniq_id` | 0 | 0 | 0 | 0 | **0.0%** |
| `crawl_timestamp` | 0 | 0 | 0 | 0 | **0.0%** |
| `product_url` | 0 | 0 | 0 | 0 | **0.0%** |
| `product_name` | 0 | 0 | 0 | 0 | **0.0%** |
| `product_category_tree` | 0 | 0 | 0 | 0 | **0.0%** |
| `pid` | 0 | 0 | 0 | 0 | **0.0%** |
| `retail_price` | 78 | 0 | 0 | 78 | **0.39%** |
| `discounted_price` | 78 | 0 | 0 | 78 | **0.39%** |
| `image` | 3 | 0 | 0 | 3 | **0.01%** |
| `is_FK_Advantage_product` | 0 | 0 | 0 | 0 | **0.0%** |
| `description` | 2 | 0 | 0 | 2 | **0.01%** |
| `product_rating` | 0 | 0 | 18,151 | 18,151 | **90.75%** |
| `overall_rating` | 0 | 0 | 18,151 | 18,151 | **90.75%** |
| `brand` | 5,864 | 0 | 0 | 5,864 | **29.32%** |
| `product_specifications` | 14 | 0 | 0 | 14 | **0.07%** |

> [!NOTE]
> `product_rating` và `overall_rating` có tới hơn 90% bản ghi mang chuỗi `"No rating available"`, dẫn tới tỷ lệ khuyết thiếu hiệu dụng thực tế lên tới ~91%.

---

## 3. Duplicate Analysis

- **Exact Duplicate Rows**: 0 bản ghi (không có dòng trùng lặp 100%).
- **Duplicate `uniq_id`**: 0 bản ghi (toàn bộ 20,000 ID đều duy nhất 100%).
- **Duplicate `pid`**: 2 bản ghi (19,998 unique pids, có 2 trường hợp pid bị trùng lặp).
- **Duplicate `product_name`**: 7324 bản ghi có tên sản phẩm trùng lặp.
- **Potential Duplicate Products**: 4453 bản ghi (trùng normalized name + brand + discounted_price).

---

## 4. Identifier Quality

- **`uniq_id`**: 20,000/20,000 unique (100% uniqueness, 0 nulls). Đạt chuẩn làm **Primary Key** kỹ thuật.
- **`pid`**: 19,998 unique (99.99% uniqueness, 0 nulls). Có 2 pid ánh xạ tới nhiều hơn 1 `uniq_id`.
- **One `uniq_id` to multiple `pid`**: 0
- **One `pid` to multiple `uniq_id`**: 2

---

## 5. Price Analysis

### Thống kê phân bố giá

| Metric | `retail_price` | `discounted_price` |
|---|---:|---:|
| Count | 19,922 | 19,922 |
| Missing | 78 (0.39%) | 78 (0.39%) |
| Min | 35.0 | 35.0 |
| P1 | 199.0 | 120.0 |
| P25 (Q1) | 666.0 | 350.0 |
| Median (P50) | 1040.0 | 550.0 |
| Mean | 2979.21 | 1973.4 |
| P75 (Q3) | 1999.0 | 999.0 |
| P95 | 8090.15 | 5999.0 |
| P99 | 42446.66 | 31920.74 |
| Max | 571230.0 | 571230.0 |

### Kiểm tra bất thường về giá (Anomalies)

- `discounted_price > retail_price`: 0 (không có trường hợp giá bán cao hơn giá niêm yết).
- Giá <= 0: 0 bản ghi.
- Cả hai giá đều khuyết thiếu: 78 bản ghi (chiếm 0.39%).
- Mức giảm giá trung bình: 45.0% (Mean: 40.52%).

---

## 6. Rating Analysis

- **`product_rating` Numeric Count**: 1,849 (9.25%)
- **`overall_rating` Numeric Count**: 1,849 (9.25%)
- **`"No rating available"` Count**: 18,151 (~90.76%)
- **Rating Value Range**: Min = 1.0, Max = 5.0, Mean = 3.81, Median = 4.0
- **Out of range (<0 hoặc >5)**: 0 thấp hơn 0, 0 cao hơn 5.
- **Mối quan hệ giữa `product_rating` và `overall_rating`**: Khớp nhau hoàn toàn 100% (20,000 dòng trùng khớp tuyệt đối). Cả hai trường đều có thể dùng thay thế cho nhau.

---

## 7. Brand Analysis

- **Số lượng bản ghi thiếu Brand**: 5,864 (29.32%)
- **Số lượng Brand duy nhất**: 3,499 brands thô (3,369 normalized brands)
- **Trường hợp thừa khoảng trắng đầu/cuối**: 1 bản ghi
- **Redundancy do khác biệt chữ hoa/thường**: 130 brands

### Top 10 Thương hiệu phổ biến nhất:

| Rank | Brand | Product Count | Percentage |
|---|---|---:|---:|
| 1 | `Allure Auto` | 469 | 2.34% |
| 2 | `Regular` | 313 | 1.57% |
| 3 | `Voylla` | 299 | 1.49% |
| 4 | `Slim` | 288 | 1.44% |
| 5 | `TheLostPuppy` | 229 | 1.15% |
| 6 | `Karatcraft` | 211 | 1.05% |
| 7 | `Black` | 167 | 0.83% |
| 8 | `White` | 155 | 0.78% |
| 9 | `DailyObjects` | 144 | 0.72% |
| 10 | `Speedwav` | 141 | 0.7% |

---

## 8. Description Quality

- **Số bản ghi có mô tả**: 19,998 (99.99%)
- **Độ dài ký tự (Character Length)**: Median = 229.0 chars, Mean = 430.88 chars, P95 = 1313.15 chars
- **Số lượng từ (Word Count)**: Median = 37.0 words, Mean = 68.7 words
- **Mô tả rất ngắn**: <20 chars: 0, <50 chars: 0, <100 chars: 21
- **Chứa mã HTML**: 0 bản ghi
- **Chứa URL**: 2 bản ghi

---

## 9. Product Specifications Quality

- **Độ phủ thông số kỹ thuật**: 99.93% (19,986 bản ghi có dữ liệu)
- **Độ dài trung bình**: Median = 523.0 chars, Mean = 600.98 chars
- **Cấu trúc dữ liệu**: Có 19,986 bản ghi sử dụng cú pháp hash Ruby (`=>`).
- **Tỷ lệ trích xuất thành công trong mẫu kiểm tra**: 99.4%

### Các khóa thuộc tính (Specification Keys) phổ biến nhất:

| Thuộc tính (Key) | Số lần xuất hiện trong mẫu |
|---|---:|
| `Type` | 332 |
| `Ideal For` | 327 |
| `Occasion` | 243 |
| `Color` | 234 |
| `Brand` | 213 |
| `Number of Contents in Sales Package` | 199 |
| `Fabric` | 168 |
| `Pattern` | 166 |
| `Sales Package` | 159 |
| `Model Number` | 148 |

---

## 10. Category Tree Distribution

- **Số lượng bản ghi cây danh mục hợp lệ**: 20,000 (100.00%)
- **Độ sâu phân cấp (Category Depth)**: Min = 1, Max = 8, Median = 4.0, Mean = 4.35
- **Số danh mục Level 1 duy nhất**: 265
- **Số danh mục Level 2 duy nhất**: 217

### Phân bố độ sâu danh mục (Depth Distribution):

| Depth (Số tầng) | Số lượng sản phẩm |
|---|---:|
| Level 1 | 328 |
| Level 2 | 1,129 |
| Level 3 | 4,419 |
| Level 4 | 4,765 |
| Level 5 | 4,911 |
| Level 6 | 3,640 |
| Level 7 | 778 |
| Level 8 | 30 |

### Top 15 Danh mục Level 1 lớn nhất:

| Rank | Level 1 Category | Product Count | % of Dataset |
|---|---|---:|---:|
| 1 | `Clothing` | 6,198 | 30.99% |
| 2 | `Jewellery` | 3,531 | 17.66% |
| 3 | `Footwear` | 1,227 | 6.13% |
| 4 | `Mobiles & Accessories` | 1,099 | 5.5% |
| 5 | `Automotive` | 1,012 | 5.06% |
| 6 | `Home Decor & Festive Needs` | 929 | 4.64% |
| 7 | `Beauty and Personal Care` | 710 | 3.55% |
| 8 | `Home Furnishing` | 700 | 3.5% |
| 9 | `Kitchen & Dining` | 647 | 3.23% |
| 10 | `Computers` | 578 | 2.89% |
| 11 | `Watches` | 530 | 2.65% |
| 12 | `Baby Care` | 483 | 2.42% |
| 13 | `Tools & Hardware` | 391 | 1.96% |
| 14 | `Toys & School Supplies` | 330 | 1.65% |
| 15 | `Pens & Stationery` | 313 | 1.57% |

---

## 11. Category Suitability Table (Inputs for Phase 3)

Bảng tổng hợp chất lượng dữ liệu theo từng ngành hàng Level 1 (các ngành hàng có >= 50 sản phẩm):

| Category | Products | % Dataset | Desc Cov % | Desc Med Len | Price Cov % | Brand Cov % | Specs Cov % | Rating Cov % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `Clothing` | 6,198 | 30.99% | 99.98% | 223.0 | 99.56% | 50.87% | 99.92% | 10.13% |
| `Jewellery` | 3,531 | 17.66% | 100.0% | 219.0 | 99.75% | 100.0% | 99.97% | 4.02% |
| `Footwear` | 1,227 | 6.13% | 100.0% | 190.0 | 99.84% | 30.73% | 99.84% | 13.12% |
| `Mobiles & Accessories` | 1,099 | 5.5% | 100.0% | 639.0 | 99.82% | 100.0% | 99.91% | 3.73% |
| `Automotive` | 1,012 | 5.06% | 100.0% | 222.0 | 99.8% | 100.0% | 100.0% | 2.37% |
| `Home Decor & Festive Needs` | 929 | 4.64% | 100.0% | 300.0 | 99.78% | 92.9% | 99.78% | 3.66% |
| `Beauty and Personal Care` | 710 | 3.55% | 100.0% | 197.5 | 99.86% | 21.97% | 99.86% | 15.35% |
| `Home Furnishing` | 700 | 3.5% | 99.86% | 150.0 | 100.0% | 100.0% | 99.86% | 5.14% |
| `Kitchen & Dining` | 647 | 3.23% | 100.0% | 482.0 | 99.69% | 56.41% | 100.0% | 9.74% |
| `Computers` | 578 | 2.89% | 100.0% | 215.0 | 99.13% | 99.83% | 100.0% | 30.45% |
| `Watches` | 530 | 2.65% | 100.0% | 305.0 | 99.62% | 9.06% | 100.0% | 36.42% |
| `Baby Care` | 483 | 2.42% | 100.0% | 222.0 | 99.59% | 94.62% | 100.0% | 2.9% |
| `Tools & Hardware` | 391 | 1.96% | 100.0% | 218.0 | 98.98% | 100.0% | 100.0% | 14.07% |
| `Toys & School Supplies` | 330 | 1.65% | 100.0% | 199.0 | 99.7% | 31.21% | 100.0% | 11.21% |
| `Pens & Stationery` | 313 | 1.57% | 100.0% | 217.0 | 100.0% | 55.59% | 100.0% | 4.79% |
| `Bags, Wallets & Belts` | 265 | 1.32% | 100.0% | 361.0 | 99.62% | 56.98% | 100.0% | 11.7% |
| `Furniture` | 180 | 0.9% | 100.0% | 213.0 | 100.0% | 100.0% | 100.0% | 3.33% |
| `Sports & Fitness` | 166 | 0.83% | 100.0% | 291.0 | 100.0% | 65.06% | 100.0% | 19.28% |
| `Cameras & Accessories` | 82 | 0.41% | 100.0% | 150.0 | 87.8% | 100.0% | 100.0% | 19.51% |
| `Home Improvement` | 81 | 0.4% | 100.0% | 259.0 | 97.53% | 100.0% | 100.0% | 4.94% |

---

## 12. Text Retrieval Readiness

Đánh giá độ sẵn sàng của các trường văn bản phục vụ Dense Vector Search và TF-IDF:

- **Sản phẩm có Title (`product_name`)**: 20,000 (100.0%)
- **Sản phẩm có Description**: 19,998 (99.99%)
- **Sản phẩm có Specifications**: 19,986 (99.93%)
- **Sản phẩm có cả Title + Description**: 19,998 (99.99%)
- **Sản phẩm có đầy đủ Title + Description + Specifications**: 19,984 (99.92%)
- **Tổng độ dài văn bản kết hợp (Title + Desc + Specs)**: Median = 884.0 chars (P25: 700.0, P75: 1246.25 chars)

> [!TIP]
> 99.92% sản phẩm có đầy đủ cả 3 thành phần văn bản (Title, Description, Specifications), với độ dài trung vị hơn 884 ký tự. Đây là cơ sở dữ liệu rất lý tưởng cho mô hình Sentence Transformers embedding.

---

## 13. Important Data Quality Risks & Recommendations for Phase 3

### Rủi ro chất lượng dữ liệu chính:
1. **Tỷ lệ thiếu Rating rất cao (~90.76%)**: Tuyệt đối không thể dùng Rating làm hard filter bắt buộc (sẽ làm mất 90% sản phẩm). Rating chỉ nên là soft ranking signal phụ trợ khi có sẵn.
2. **Định dạng Specifications không phải JSON chuẩn**: Lưu dạng Ruby hash với ký tự `=>`. Cần parser chuyên dụng ở Phase 4 khi làm sạch.
3. **Tỷ lệ thiếu Brand (~29.3%)**: Một số ngành hàng thời trang hoặc trang sức không có nhãn hiệu rõ ràng. Cần lưu ý khi lọc thương hiệu.
4. **Giá niêm yết bị khuyết thiếu 78 bản ghi (0.39%)**: Cần loại bỏ các sản phẩm không có giá ở Phase 4.

### Khuyến nghị cho Phase 3 (Category Selection):
- Các danh mục có độ phủ thông số kỹ thuật, mô tả và giá rất cao, phù hợp hoàn hảo cho truy vấn mua sắm đàm thoại: `Clothing`, `Jewellery`, `Footwear`, `Mobiles & Accessories`, `Automotive`, `Computers`, `Home Décor & Festive Needs`.
- Danh mục tiêu chuẩn của dự án có thể dễ dàng đạt mốc mục tiêu **5,000 – 15,000 sản phẩm sạch** từ các nhóm ngành hàng có chất lượng cao nhất.
