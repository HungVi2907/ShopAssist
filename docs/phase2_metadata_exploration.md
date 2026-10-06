# Phase 2 — Khảo sát metadata Appliances

Chạy lại từ thư mục gốc của ShopAssist:

```powershell
python scripts/explore_metadata.py
```

Script đọc tuần tự `data/raw/meta_Appliances.jsonl` và tạo:

- `data/interim/category_analysis.csv`: tần suất từng nút taxonomy, đường dẫn taxonomy và `main_category`.
- `data/interim/metadata_profile.json`: độ đầy đủ trường, kiểu dữ liệu, thống kê số và các tín hiệu sơ bộ cho 5 nhóm sản phẩm.

## Quy mô và độ đầy đủ

| Chỉ số | Kết quả |
| --- | ---: |
| Bản ghi | 94.327 |
| `parent_asin` duy nhất | 94.327 |
| Nút taxonomy duy nhất | 102 |
| Đường dẫn taxonomy duy nhất | 95 |
| Có `title` | 94.318 (99,99%) |
| Có `categories` | 91.042 (96,52%) |
| Có `features` | 77.784 (82,46%) |
| Có `description` | 62.155 (65,89%) |
| Có `details` | 92.317 (97,87%) |
| Có `price` | 46.726 (49,54%) |
| Có `average_rating` / `rating_number` | 94.327 (100%) |
| `rating_number >= 5` / `>= 10` | 65.743 / 52.267 |

Giá có median $26,99 và p90 $142,24 **trên toàn bộ Appliances**, phần lớn là linh kiện; đây không phải phân bố giá của 5 nhóm mục tiêu. 3.285 bản ghi không có đường dẫn `categories`. `main_category` không đồng nghĩa với taxonomy `categories`: hai giá trị phổ biến nhất là `Tools & Home Improvement` (42.694) và `Appliances` (25.572).

## Taxonomy thực tế

| Nút `categories` | Số bản ghi |
| --- | ---: |
| `Appliances` | 85.384 |
| `Parts & Accessories` | 71.321 |
| `Dryer Parts & Accessories` | 15.354 |
| `Refrigerator Parts & Accessories` | 14.246 |
| `Replacement Parts` | 13.785 |
| `Small Appliance Parts & Accessories` | 5.275 |
| `Coffee & Espresso Machine Parts & Accessories` | 5.275 |

Đường dẫn nhiều bản ghi nhất là `Appliances > Parts & Accessories` (17.628), tiếp theo là `Appliances > Parts & Accessories > Dryer Parts & Accessories > Replacement Parts` (13.785). Nhánh liên quan cà phê trong tệp này là **phụ kiện máy pha cà phê**, chủ yếu là bộ lọc, chứ không phải taxonomy của máy pha hoàn chỉnh.

## Tín hiệu cho 5 nhóm mục tiêu

Đếm sơ bộ khi tên nhóm xuất hiện trong `title` **hoặc** đường dẫn `categories`. Với ấm điện, dùng từ rộng `kettle` để không bỏ sót ứng viên; bước này chưa khẳng định sản phẩm dùng điện. Các nhóm có thể trùng nhau. Cột cuối loại các bản ghi có từ gợi ý phụ kiện trong title hoặc taxonomy, nhưng vẫn **chưa xác nhận** là sản phẩm hoàn chỉnh.

| Nhóm | Có tín hiệu | Tín hiệu trong taxonomy | Tín hiệu trong title | Không có tín hiệu phụ kiện |
| --- | ---: | ---: | ---: | ---: |
| Coffee maker | 5.295 | 5.275 | 1.126 | 1 |
| Blender | 14 | 0 | 14 | 3 |
| Air fryer | 12 | 0 | 12 | 5 |
| Electric kettle (từ `kettle`) | 13 | 0 | 13 | 5 |
| Rice cooker | 1 | 0 | 1 | 0 |

Ví dụ sai lệch: nhánh coffee gồm giấy lọc và filter tái sử dụng; title có `air fryer` có thể là bộ phụ kiện hoặc áo phủ nồi; title có `blender` có thể là nắp hoặc khớp thay thế. Ngược lại, một sản phẩm hoàn chỉnh có thể nằm trong taxonomy sai hoặc có title không chứa mẫu từ khóa trên. Vì vậy các con số chỉ dùng để **đánh giá độ phủ nguồn**, không phải số sản phẩm sạch của Phase 3.

## Kết luận cho bước tiếp theo

`Appliances` cho thấy độ phủ rất thấp đối với 5 nhóm sản phẩm; các tín hiệu hiện có không hỗ trợ mục tiêu 5.000–15.000 sản phẩm hoàn chỉnh nếu chỉ dùng nguồn này. Cần kiểm tra `Home_and_Kitchen` theo checkpoint trong proposal trước khi chốt nguồn dữ liệu và quy tắc lọc. Đồng thời, thiếu giá ở khoảng một nửa bản ghi sẽ ảnh hưởng đến các truy vấn có ràng buộc giá; cần đo lại tỷ lệ này trên tập sản phẩm đã chọn.

Đã thực hiện kiểm tra mẫu nguồn thay thế; xem [báo cáo Home_and_Kitchen](home_and_kitchen_probe.md).
