# Kiểm tra nguồn Home_and_Kitchen

Nguồn: [Amazon Reviews 2023 / meta_Home_and_Kitchen.jsonl](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/blob/main/raw/meta_categories/meta_Home_and_Kitchen.jsonl). File metadata có kích thước 11.788.767.944 byte. Để kiểm tra độ phủ trước khi quyết định tải toàn bộ, chạy:

```powershell
python scripts/sample_home_metadata.py
```

Script lấy 24 đoạn, mỗi đoạn 4 MiB, tại trung điểm của 24 phần đều nhau của file. Tổng dữ liệu tải là 96 MiB (khoảng 0,85% file). Mỗi response phải có HTTP 206 và `Content-Range` đúng; các dòng JSONL bị cắt ở mép đoạn không được tính. Kết quả chi tiết ở `data/interim/home_sample_profile.json`. Đây là **mẫu trải đều theo byte**, không phải thống kê toàn bộ hay tập sản phẩm đã làm sạch.

## Kết quả mẫu

31.873 bản ghi JSONL hợp lệ được phân tích. Taxonomy thực sự có `Home & Kitchen > Kitchen & Dining > Small Appliances` cùng các nhánh `Blenders`, `Fryers > Air Fryers`, `Rice Cookers`; nhóm cà phê và ấm điện nằm dưới `Coffee, Tea & Espresso`.

| Nhóm | Có tín hiệu trong title hoặc taxonomy | Không có tín hiệu phụ kiện |
| --- | ---: | ---: |
| Coffee maker | 173 | 83 |
| Blender | 104 | 56 |
| Air fryer | 90 | 39 |
| Kettle (bao gồm ấm không dùng điện) | 70 | 60 |
| Rice cooker | 23 | 23 |

Các con số trên là **ứng viên**, không phải sản phẩm sạch. Trong mẫu có giấy lót nồi chiên nằm trong `Air Fryers`, bình đun trên bếp nằm trong `Tea Kettles`, và cả title không liên quan nằm sai taxonomy. Một số máy pha cà phê là dụng cụ thủ công như French press hoặc Moka pot. Phase 3 cần xác định rõ có bao gồm chúng hay không, rồi kiểm tra cả title lẫn taxonomy và loại phụ kiện bằng quy tắc cụ thể.

| Trường có dữ liệu | Home_and_Kitchen (mẫu) | Appliances (toàn bộ) |
| --- | ---: | ---: |
| `categories` | 89,42% | 96,52% |
| `features` | 75,44% | 82,46% |
| `description` | 56,25% | 65,89% |
| `details` | 98,91% | 97,87% |
| `price` | 34,44% | 49,54% |

**Đánh giá:** `Home_and_Kitchen` phù hợp hơn rõ rệt về **độ phủ của cả 5 nhóm sản phẩm hoàn chỉnh**. Điểm yếu là giá chỉ có trong 34,44% bản ghi mẫu; cần đo lại trên tập ứng viên đã lọc vì tỷ lệ toàn category chịu ảnh hưởng của đồ trang trí, nội thất và nhiều loại hàng khác. Mẫu 96 MiB chưa đủ để chốt số sản phẩm sạch hay độ tin cậy của phép ngoại suy. Nguồn này là ứng viên chính cho Phase 3; `Appliances` có thể dùng bổ sung sau khi khử trùng lặp `parent_asin` nếu cần.
