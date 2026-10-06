# Phase 4B — Cleaning Rule Design and Validation

## Mục tiêu và đầu vào

Phase 4B xây quy tắc **xác định có giải thích** từ mẫu đã gán nhãn Phase 4A. Đầu vào là `data/interim/phase4a_audit_sample_labeled.csv` (380 nhãn đã hoàn tất) và bản ghi metadata đầy đủ tương ứng trong `data/interim/home_kitchen_candidates.jsonl`. Script chỉ nối đúng các ASIN thuộc mẫu để phân tích/kiểm định; **không chạy lọc 55.064 candidate** và không tạo tập `selected_products`.

Quy tắc ở `scripts/cleaning_rules.py` trả về `predicted_label`, `decision` (`KEEP`, `REMOVE`, `REVIEW`), `predicted_family` khi giữ, `rule_id`, `matched_signals`, và `reason`. Cờ `possible_accessory`, `possible_manual_product`, `possible_stovetop_kettle` từ Phase 3B **không được dùng làm ground truth hoặc điều kiện loại trực tiếp**.

## Phân tích pattern

`scripts/analyze_phase4b_patterns.py` chuẩn hóa Unicode bằng NFKC, casefold, tách dấu câu và khoảng trắng. Với mỗi sản phẩm, script đếm **document frequency** của unigram/bigram trên title, taxonomy, features, description và các trường details dạng đơn giản. Tỷ lệ giữa một nhãn và `VALID_PRODUCT` dùng làm trơn add-0.5; riêng `VALID_PRODUCT` được so với bốn nhãn invalid gộp. Một số từ metadata chung và số được bỏ khỏi bảng xếp hạng. [Bảng JSON](../data/interim/phase4b_pattern_analysis.json) và [báo cáo pattern](../data/interim/phase4b_pattern_analysis.md) ghi số đếm, n-gram và ví dụ đối chứng.

Tín hiệu hữu ích trong **mẫu này**: `replacement`, `compatible with`, taxonomy `Parts & Accessories`, `liner`, `cord organizer` cho phụ kiện; `french press` và `pour over` cho pha cà phê thủ công; `whistling`, `stovetop`, `Cookware > Tea Kettles` cho ấm bếp; `wattage`, `automatic`, `shut off`, `programmable` hỗ trợ máy chạy điện. Đây chỉ là **ứng viên tín hiệu**: `filter`, `basket`, `cup`, `manual`, `induction`, thậm chí `replacement` xuất hiện ở các sản phẩm valid. Chẳng hạn máy pha cà phê hoàn chỉnh có filter/carafe, nồi chiên hoàn chỉnh có basket/giấy lót đi kèm, và máy espresso chạy điện có "manual" trong phần điều khiển. Không loại chỉ bằng một từ.

## Kiến trúc và thứ tự quyết định

1. **Thiếu danh tính:** title trống/vô nghĩa và thiếu mô tả đủ tin cậy → `REVIEW`.
2. **Phụ kiện có chứng cứ mạnh:** tên bộ phận/thay thế, quan hệ tương thích, taxonomy bộ phận được xác nhận bởi mô tả, hoặc sản phẩm bán chính là liner, blade, basket, cover, cord organizer → `ACCESSORY`. Phân biệt phụ kiện **được bán riêng** với phụ kiện **đi kèm một máy hoàn chỉnh**. Wattage của máy tương thích không biến lưỡi dao thành blender hoàn chỉnh.
3. **Pha cà phê thủ công:** French press, pour-over, Moka dùng bếp, percolator không điện, hand lever → `MANUAL_DEVICE`. Đế điện, bơm điện và cấu trúc máy thực sự bảo vệ Moka/espresso chạy điện; chữ "electric" trong "electric stovetop" mô tả **bếp bên ngoài**, không phải điện của bình cà phê.
4. **Ấm dùng nhiệt ngoài:** `stovetop`, `whistling`, gas stove hoặc taxonomy cookware + không có bằng chứng bộ gia nhiệt tích hợp → `STOVETOP`. Tên ấm điện và dữ liệu heater/base được ưu tiên hơn phép so sánh như "faster than stovetop" trong mô tả.
5. **Hàng ngoài phạm vi:** title nhận diện dụng cụ khác, thực phẩm, chai lắc, nồi microwave không điện, máy giữ nóng cơm, hot plate, soup kettle, v.v. → `OTHER_NOISE`.
6. **Bằng chứng máy hoàn chỉnh:** logic riêng theo family. Coffee cần máy pha và bằng chứng power/brewing/taxonomy; blender cần động cơ/chức năng xay; air fryer cần air-fry thực sự; electric kettle cần bộ gia nhiệt hoặc điện được chứng thực; rice cooker cần **chức năng nấu cơm** chứ không chỉ giữ nóng. Máy đa chức năng vẫn có thể `KEEP` nếu chức năng mục tiêu được mô tả rõ.
7. **Chứng cứ chưa đủ hoặc mâu thuẫn:** → `REVIEW`. Đây là abstention có chủ đích; không tự động giữ hay loại.

Mỗi bước tạo `rule_id` ổn định. Thứ tự này được điều chỉnh theo lỗi thật: phần thay thế có thông số của máy tương thích cần được chặn trước rule valid; máy hoàn chỉnh có filter/basket đi kèm cần được bảo vệ; cụm "manual"/"electric stove" không thể quyết định độc lập. Không có bảng tra `parent_asin → label` trong engine.

## Kiểm định trên mẫu đã gán nhãn

`scripts/validate_phase4b_rules.py` kiểm định 374 dòng có nhãn xác định. Sáu nhãn `AMBIGUOUS` được trình bày riêng, **không đưa vào** mẫu số precision/recall. `REVIEW` không tính là giữ nhầm hay loại nhầm, nhưng làm giảm recall. Các tỷ lệ sau là **trên chính mẫu dùng thiết kế và tinh chỉnh rule**, chưa phải ước lượng trên dữ liệu mới.

| Quyết định | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| `KEEP` cho `VALID_PRODUCT` | 1.0000 | 0.8873 | 0.9403 |
| `REMOVE` cho bốn nhãn invalid | 1.0000 | 0.8836 | 0.9382 |

- **0/142** `VALID_PRODUCT` bị `REMOVE` nhầm; **16/142** được đưa sang `REVIEW`.
- **0/232** sản phẩm invalid bị `KEEP` nhầm; **27/232** được đưa sang `REVIEW`.
- 331/374 dòng nhãn xác định nhận quyết định `KEEP` hoặc `REMOVE` (coverage **88,50%**); 43/374 được `REVIEW`.
- Trong sáu dòng nhãn thật `AMBIGUOUS`, rule trả `REVIEW` cho bốn; một được dự đoán `VALID_PRODUCT` và một `OTHER_NOISE`. Hai ca này cho thấy metadata tự mâu thuẫn vẫn có thể vượt qua rule. Không dùng sáu ca mơ hồ làm ví dụ keep/remove để tính các chỉ số trên.

| Nhãn | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| `VALID_PRODUCT` | 1.0000 | 0.8873 | 0.9403 |
| `ACCESSORY` | 0.9205 | 0.9101 | 0.9153 |
| `MANUAL_DEVICE` | 0.8421 | 0.9143 | 0.8767 |
| `STOVETOP` | 0.8889 | 0.8421 | 0.8649 |
| `OTHER_NOISE` | 0.9767 | 0.6000 | 0.7434 |

`OTHER_NOISE` có recall thấp vì rule ưu tiên `REVIEW` khi chỉ thấy taxonomy nhiễu hoặc title quá chung. Có nhầm lẫn **giữa các loại invalid** (ví dụ một dụng cụ nấu không điện được gọi `ACCESSORY` thay vì `OTHER_NOISE`); quyết định `REMOVE` vẫn đúng theo nhãn nhị phân, nhưng phải xem confusion matrix khi thiết kế bộ quy tắc cuối.

Lượt kiểm định ban đầu có **7** false rejections và **15** false acceptances. Sau các chỉnh sửa theo nhóm lỗi, các vòng tiếp theo là **2/8**, **1/1**, rồi **0/0** trên mẫu phát triển. Các chỉnh sửa có lý do tổng quát: nhận diện sản phẩm chính trong title, tách công suất máy tương thích khỏi phụ kiện, và xử lý ngữ cảnh nhiệt ngoài. Kết quả 0/0 **không chứng minh rule tổng quát hóa**; Phase 4C cần một mẫu mới độc lập trước khi tin kết quả trên toàn tập.

Xem [validation JSON](../data/interim/phase4b_rule_validation.json), [báo cáo validation](../data/interim/phase4b_rule_validation.md), [dự đoán từng dòng](../data/interim/phase4b_predictions.csv), [false rejections](../data/interim/phase4b_false_rejections.csv) và [false acceptances](../data/interim/phase4b_false_acceptances.csv). Hai file lỗi hiện có header và 0 dòng; chúng vẫn được sinh mỗi lần kiểm định.

## Chạy lại và kiểm thử

Từ thư mục gốc `ShopAssist`:

```powershell
python scripts/analyze_phase4b_patterns.py
python scripts/validate_phase4b_rules.py
python -m unittest discover -s tests -v
```

Các script không gọi mạng, tải review, tạo embedding, gọi LLM, hoặc ghi `selected_products`. Quy tắc vẫn có thể sai với dữ liệu chưa thấy, đặc biệt là metadata mâu thuẫn, taxonomy đặt nhầm, máy đa chức năng và các tên chỉ nêu brand. `REVIEW` cần quy trình xử lý trong Phase 4C; không được ngầm coi là `KEEP` hoặc `REMOVE`.

**Bước tiếp theo:** Phase 4C chạy rule trên toàn bộ candidate, kiểm tra phân phối và một mẫu kiểm định mới, xử lý chính sách cho hàng chờ `REVIEW`, rồi mới đóng băng tập `parent_asin` được chọn. Phase 4C chưa được thực hiện ở đây.
