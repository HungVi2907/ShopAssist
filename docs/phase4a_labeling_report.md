# Phase 4A — Báo cáo gán nhãn mẫu kiểm toán

## Phạm vi và trạng thái

Mẫu Phase 4A gồm **380 `parent_asin` duy nhất**, lấy từ 55.064 candidate `Home_and_Kitchen` của Phase 3B với seed `20261006`: 20 dòng cho mỗi tổ hợp của 5 family × 3 nguồn khớp (300 dòng), cộng 80 dòng chọn bổ sung cho nhóm rủi ro. Đây là mẫu cân bằng có chủ đích và tăng tỷ lệ các ca khó, **không phải mẫu ngẫu nhiên phản ánh tỷ lệ toàn bộ candidate**.

Trợ lý đã đọc title, taxonomy, features, description và details của các bản ghi được chọn; 45 ca khó được đối chiếu thêm với bản ghi JSONL đầy đủ. Hiện **380/380 dòng có nhãn**, **45/45 ca khó đã được xét lần hai**, và `review_required = NO` trong [CSV đã hoàn tất](../data/interim/phase4a_audit_sample_labeled.csv). Sáu ca mang nhãn `AMBIGUOUS` là **kết luận kiểm toán rằng metadata không đủ hoặc tự mâu thuẫn**, chứ không phải ô nhãn còn bỏ trống. Chúng cần xác minh nguồn ngoài nếu muốn quyết định loại sản phẩm chắc chắn ở phase sau.

Các nhãn này là đánh giá từ metadata lưu trong dự án; chưa đối chiếu trang bán hàng trực tiếp, chưa được kiểm tra độc lập bởi người thứ hai, và **chưa phải bộ quy tắc làm sạch Phase 4B**.

## Artifact và dấu vết

| Tệp | Vai trò |
| --- | --- |
| `data/interim/phase4a_audit_sample.csv` | Mẫu gốc chưa gán nhãn, giữ nguyên |
| `data/interim/phase4a_audit_sample_prelabelled.csv` | Nhãn lượt đầu và 45 cờ cần xét sâu |
| `data/interim/phase4a_review_queue.csv` | Bản chụp 45 ca khó trước khi xét sâu |
| `data/interim/phase4a_audit_sample_labeled.csv` | **Bản dùng để đọc kết quả gán nhãn hiện tại** |
| `data/interim/phase4a_review_queue_resolved.csv` | Đủ 45 quyết định cuối của lượt xét sâu, mỗi dòng có lý do riêng |
| `scripts/prelabel_phase4a_audit.py`, `scripts/finalize_phase4a_labels.py` | Dấu vết quyết định, kiểm tra hash đầu vào, không sửa mẫu gốc |

`audit_status = ADJUDICATED` chỉ 45 ca được xét sâu lần hai; `PRELABEL` chỉ 335 ca còn lại đã gán nhãn ở lượt đầu. Mọi dòng đều có `audit_label`, `audit_family` và `audit_reason`. `audit_family` dùng một trong năm family chuẩn cho `VALID_PRODUCT`, và `NONE` khi không có family phù hợp. Việc gán family cho sản phẩm đa chức năng là lựa chọn kiểm toán theo chức năng được bán chính, không tự động trở thành chính sách dataset.

## Kết quả toàn mẫu

| Nhãn | Số dòng | Ý nghĩa trong mẫu |
| --- | ---: | --- |
| `VALID_PRODUCT` | 142 | Thiết bị hoàn chỉnh, chạy điện, có chức năng thuộc family mục tiêu |
| `ACCESSORY` | 89 | Bộ phận, đồ thay thế hoặc phụ kiện đi kèm; không phải máy hoàn chỉnh |
| `MANUAL_DEVICE` | 35 | Dụng cụ pha cà phê thủ công hoặc dùng nguồn nhiệt ngoài |
| `STOVETOP` | 38 | Ấm không có bộ gia nhiệt điện tích hợp, dùng bếp hoặc nguồn nhiệt ngoài |
| `OTHER_NOISE` | 70 | Hàng ngoài năm family: thực phẩm, dụng cụ, chai lắc, máy khác, v.v. |
| `AMBIGUOUS` | 6 | Metadata thiếu hoặc mâu thuẫn nên chưa xác định chắc loại sản phẩm |
| `WRONG_FAMILY` | 0 | Không gặp ca rõ ràng thuộc một family mục tiêu khác trong mẫu này |
| **Tổng** | **380** | 380 ASIN duy nhất |

`price` có dữ liệu ở **124/380** dòng (32,6%); giá thiếu không ảnh hưởng đến nhãn. Số `VALID_PRODUCT` là **kết quả trong mẫu**, không phải ước lượng số sản phẩm sạch trong 55.064 candidate. Không được nhân tỷ lệ này lên toàn tập vì mẫu đã cân bằng strata và chọn bổ sung ca rủi ro.

### Theo family được phát hiện ở Phase 3B

| Candidate family | Tổng | Valid | Accessory | Manual | Stovetop | Other noise | Ambiguous |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `coffee_maker` | 88 | 30 | 19 | 31 | 0 | 7 | 1 |
| `blender` | 67 | 27 | 26 | 0 | 0 | 12 | 2 |
| `air_fryer` | 65 | 35 | 24 | 0 | 0 | 6 | 0 |
| `electric_kettle` | 80 | 17 | 0 | 2 | 37 | 23 | 1 |
| `rice_cooker` | 60 | 31 | 6 | 0 | 0 | 21 | 2 |
| Nhiều family | 20 | 2 | 14 | 2 | 1 | 1 | 0 |
| **Tổng** | **380** | **142** | **89** | **35** | **38** | **70** | **6** |

Theo **family đã gán nhãn** cho 142 sản phẩm valid: `coffee_maker` 31, `blender` 27, `air_fryer` 35, `electric_kettle` 18, `rice_cooker` 31. Hai dòng nhiều family được gán family chính dựa trên chức năng thực tế: ấm điện Kenmore là `electric_kettle`; máy pha cà phê kiêm xay Mr. Coffee là `coffee_maker`.

### Theo nguồn khớp

| `match_source` | Tổng | Valid | Accessory | Manual | Stovetop | Other noise | Ambiguous |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `title_only` | 122 | 21 | 46 | 11 | 7 | 35 | 2 |
| `taxonomy_only` | 107 | 36 | 24 | 6 | 7 | 31 | 3 |
| `both` | 151 | 85 | 19 | 18 | 24 | 4 | 1 |

Trong mẫu này, `both` có nhiều sản phẩm valid hơn, nhưng vẫn chứa phụ kiện, thiết bị thủ công và ấm bếp. `taxonomy_only` có các trường hợp taxonomy sai rõ rệt (máy làm đá nằm trong `Air Fryers`, thực phẩm/dictaphone nằm trong `Rice Cookers`). `title_only` dễ bắt nhầm đồ chỉ nhắc đến máy trong ngữ cảnh sử dụng, như dầu xịt, dụng cụ cắt khoai và cốc/đồ thay thế. Các số trong bảng **không thể dùng trực tiếp làm precision của toàn bộ nguồn**.

## Quan sát về các cờ Phase 3B

Các cờ là tín hiệu lấy mẫu, không phải nhãn thật:

| Cờ trong mẫu | Số dòng mang cờ | Nhãn trùng loại cờ | Phản ví dụ đáng chú ý |
| --- | ---: | ---: | --- |
| `accessory_flag` | 224 | 85 `ACCESSORY` | **76** máy valid vẫn mang cờ, thường do `filter`, `basket`, `cup` trong bộ máy hoàn chỉnh |
| `manual_flag` | 35 | 25 `MANUAL_DEVICE` | **2** máy valid: espresso pump có chữ “manual”, Moka có đế điện |
| `stovetop_flag` | 42 | 34 `STOVETOP` | Teapot/trang trí hoặc sản phẩm không phải ấm đun nước cũng có cờ |
| `ambiguous_family` | 20 | Không phải nhãn loại bỏ | Có **2** thiết bị valid đa chức năng hoặc sai taxonomy |

Ngược lại, trong mẫu có dụng cụ thủ công hoặc ấm bếp **không được cờ tương ứng**. Vì vậy Phase 4B cần kiểm tra cả false positive lẫn false negative của từng cờ và xác nhận bằng ngữ cảnh sản phẩm.

## Xét sâu 45 ca khó

Ở lượt đầu: 15 `AMBIGUOUS` và 30 ca có dấu hiệu mâu thuẫn hoặc ranh giới sản phẩm cần kiểm tra. Sau lượt hai, **9 ca đổi nhãn** và 36 ca giữ nhãn nhưng có lý do cụ thể hơn. Các thay đổi:

| `parent_asin` | Nhãn lượt đầu → kết luận | Chứng cứ quyết định |
| --- | --- | --- |
| `B0BK876P3S` | Ambiguous → Other noise | Chai lắc điện trộn bột protein, không có chức năng xay thực phẩm |
| `B07L965DPC` | Ambiguous → Other noise | Bình/ấm camping dùng năng lượng mặt trời, không thấy bộ gia nhiệt điện tích hợp |
| `B071HC5PYT` | Ambiguous → Manual device | Bộ Hario gồm bình rót, phễu và giấy lọc pour-over |
| `B000AXQAEW` | Ambiguous → Stovetop | Mô tả đầy đủ nói rõ ấm gang đun nước bằng nhiệt ngoài |
| `B089FLQZ3R` | Ambiguous → Other noise | Features/description là chảo điện/hot pot, không xác nhận chế độ nấu cơm |
| `B07SZ6W7NN` | Ambiguous → Stovetop | Features ghi dùng trên bếp gas, điện và cảm ứng |
| `B09JZR6XWC` | Ambiguous → Valid coffee maker | Máy hoàn chỉnh pha cà phê và có bộ xay tích hợp; chức năng chính là pha cà phê |
| `B09NY9W21B` | Ambiguous → Stovetop | Title ghi ấm gang dùng trên bếp, không có bộ gia nhiệt tích hợp |
| `B00938S1V0` | Ambiguous → Other noise | Sản phẩm chính là máy trộn bột, blender chỉ là phụ kiện kèm theo |

Sáu dòng còn nhãn `AMBIGUOUS` là `B0837266L8` (title máy cà phê nhưng mô tả bộ điều tốc xe RC), `B0B1MB61HL` (title chỉ có dấu sao), `B071VJGDLF` (title đậu đen nhưng mô tả cốc thay thế), `B07G8Y42B5` (chỉ có tên ấm chung và taxonomy), `B09H5FYLWK` (hộp cơm điện nhưng không xác nhận nấu cơm), `B01DJDE9PQ` (one-touch cooker trong taxonomy nồi cơm nhưng thiếu mô tả chức năng). Đây là sáu **nhãn AMBIGUOUS đã hoàn tất**, không được tự suy ra là valid hay loại bỏ trong Phase 4A.

Những ca giữ nhãn nhưng quan trọng: máy espresso 220–240 V vẫn là máy pha cà phê chạy điện; máy air-fry oven và pressure/rice multicooker được tính valid khi chức năng mục tiêu được nói rõ; samovar điện được gán kettle vì có bộ gia nhiệt 2200 W; máy giữ nóng cơm không được xem là nồi **nấu** cơm; ấm súp điện không phải ấm đun nước. [CSV 45 quyết định](../data/interim/phase4a_review_queue_resolved.csv) ghi lý do riêng và các trường gốc cho từng ASIN.

## Quy ước gán nhãn và giới hạn

- `VALID_PRODUCT` yêu cầu máy hoàn chỉnh chạy điện và có chức năng mục tiêu được mô tả. Trong **mẫu kiểm toán**, máy đa chức năng được gán family nếu chức năng đó rõ ràng; Phase 4B sẽ quyết định có áp dụng cùng ranh giới cho toàn dataset hay không.
- `ACCESSORY` dựa vào sản phẩm được bán là phần/phụ kiện, không dựa máy móc vào một từ như `filter` hoặc cờ Phase 3B. Máy hoàn chỉnh có filter, basket, cup đi kèm vẫn có thể valid.
- `MANUAL_DEVICE` áp dụng cho dụng cụ pha cà phê thủ công; `STOVETOP` cho ấm đun bằng bếp/nhiệt ngoài. Các đồ dùng bếp không thuộc hai loại này được xếp `OTHER_NOISE` khi rõ ràng ngoài năm family.
- `AMBIGUOUS` giữ nguyên khi metadata mâu thuẫn hoặc thiếu căn cứ. Không dùng giá, rating hay số review để thay thế thông tin loại sản phẩm.
- Có thể có sai sót vì Amazon metadata thiếu, sai taxonomy, mô tả lẫn sản phẩm khác hoặc chỉ có bản ghi cũ. Không có xác minh hình ảnh/trang bán hàng; tập 335 nhãn lượt đầu chưa được một người thứ hai kiểm tra.

**Bước tiếp theo:** dùng bộ nhãn như bằng chứng để thiết kế và kiểm định quy tắc trong Phase 4B, đồng thời xử lý riêng sáu ASIN thiếu chứng cứ nếu cần. Chưa áp dụng quy tắc lên 55.064 candidate, chưa chọn tập sản phẩm cuối và chưa tải review.

## Phụ lục — đủ 45 quyết định xét sâu

Bảng dưới đây ghi quyết định theo từng ASIN. Trường hợp nhãn `AMBIGUOUS` đã được xét sâu và có lý do; không có dòng nào còn chờ gán nhãn.

| parent_asin | Nhãn đã chốt | Family | Lý do ngắn |
| --- | --- | --- | --- |
| `B0837266L8` | `AMBIGUOUS` | `NONE` | Coffee-machine title conflicts with RC-car speed-controller features and description; listing identity is unreliable. |
| `B001RL5P9W` | `MANUAL_DEVICE` | `NONE` | Granite steel percolator pot has an insulating handle and no integrated electrical heater. |
| `B00EZBTTV6` | `VALID_PRODUCT` | `coffee_maker` | 15-bar powered espresso machine; 220–240 V plug compatibility is a later availability issue, not product type. |
| `B00N2XQ8Q2` | `VALID_PRODUCT` | `coffee_maker` | Features state that the machine grinds beans and automatically brews up to 12 cups. |
| `B0BK876P3S` | `OTHER_NOISE` | `NONE` | USB shaker bottle mixes protein powder; no food-blending blades or target blender function are described. |
| `B0B1MB61HL` | `AMBIGUOUS` | `NONE` | Title is only asterisks; blender taxonomy and electric specifications cannot establish product identity. |
| `B071VJGDLF` | `AMBIGUOUS` | `NONE` | Black-beans title conflicts with replacement blender-cup description; neither product identity is reliable. |
| `B0BCHJ7F8G` | `VALID_PRODUCT` | `blender` | Powered nut-milk machine explicitly heats and blends, and offers a smoothie mode. |
| `B0055ZHAV2` | `ACCESSORY` | `NONE` | Thermostat title conflicts with blender-container description, but both describe parts rather than a complete blender. |
| `B091RM7GCK` | `VALID_PRODUCT` | `air_fryer` | Complete countertop oven explicitly marketed with an air-fry function; hybrid appliance counted for this audit. |
| `B08VDLK32T` | `VALID_PRODUCT` | `air_fryer` | 1400 W air fryer, basket and air-circulation features outweigh incorrect knife-sharpener taxonomy. |
| `B07HRMQJCF` | `VALID_PRODUCT` | `air_fryer` | Brand-only title is supported by air-fryer features, capacity, wattage and controls. |
| `B0C8F19BQY` | `VALID_PRODUCT` | `air_fryer` | Powered countertop oven has an explicit Air Fry cooking mode; hybrid appliance counted for this audit. |
| `B089B63Z8R` | `VALID_PRODUCT` | `air_fryer` | Complete 2-in-1 machine explicitly provides rapid-hot-air frying as well as deep frying. |
| `B00AQ7YA26` | `STOVETOP` | `NONE` | Outdoor kettle boils using natural fuel rather than an integrated electrical heater; grouped with externally heated kettles. |
| `B07L965DPC` | `OTHER_NOISE` | `NONE` | Camping solar/thermos vessel has no evidence of an integrated powered kettle heater. |
| `B0160JG29C` | `OTHER_NOISE` | `NONE` | Glass teapot with a matching warmer is described without an integrated electric boiling element. |
| `B01LYOAYPE` | `VALID_PRODUCT` | `electric_kettle` | Electric samovar has a 2200 W heating element, boils water and shuts off automatically. |
| `B071HC5PYT` | `MANUAL_DEVICE` | `NONE` | Hario kit contains a glass pouring vessel, porcelain dripper and paper filters; operation is manual. |
| `B000AXQAEW` | `STOVETOP` | `NONE` | Full description says cast-iron teapot brings water to a boil at medium external heat. |
| `B002WBV1L2` | `STOVETOP` | `NONE` | Copper water-boiling kettle is listed as cookware and has no integrated electrical components. |
| `B096TB5NLT` | `OTHER_NOISE` | `NONE` | 1500 W chai brewer prepares milk tea; it is not an electric water kettle or another target family. |
| `B0007CXQM0` | `STOVETOP` | `NONE` | Traditional teakettle under cookware has no powered element; classified as externally heated. |
| `B07G8Y42B5` | `AMBIGUOUS` | `NONE` | Only a generic kettle title and electric taxonomy exist; no features establish its heat source. |
| `B09H5FYLWK` | `AMBIGUOUS` | `NONE` | Electric lunch-box heater calls itself a rice cooker, but no features show that it cooks raw rice. |
| `B001JO40X4` | `VALID_PRODUCT` | `rice_cooker` | Electric pressure/slow cooker explicitly includes a rice-cooking program; hybrid counted for this audit. |
| `B07HB139GC` | `VALID_PRODUCT` | `rice_cooker` | Electric multicooker explicitly rice-cooks in addition to pressure-cooking and steaming. |
| `B089FLQZ3R` | `OTHER_NOISE` | `NONE` | Features and description identify an electric skillet/hot pot with no supported rice program despite the title. |
| `B01DJDE9PQ` | `AMBIGUOUS` | `NONE` | One-touch cooker has rice-cooker taxonomy but no feature or description confirming rice cooking. |
| `B00GRTW524` | `OTHER_NOISE` | `NONE` | Electric multi-cooker/steamer description covers stews, roasts and steaming but no rice function. |
| `B0C1RBRQ7L` | `OTHER_NOISE` | `NONE` | Commercial electric rice warmer holds already-cooked rice; no raw-rice cooking function is described. |
| `B07MCW97CF` | `VALID_PRODUCT` | `rice_cooker` | Electric pressure multicooker lists a dedicated Rice program. |
| `B081V7RG9M` | `VALID_PRODUCT` | `rice_cooker` | Electric pressure multicooker lists Rice/Risotto and Multigrain presets. |
| `B098G2G6SG` | `VALID_PRODUCT` | `rice_cooker` | Electric hot pot explicitly advertises a de-sugar rice-cooking function. |
| `B00004SC50` | `VALID_PRODUCT` | `rice_cooker` | Powered steamer includes a rice bowl and description explicitly says it cooks rice. |
| `B07SZ6W7NN` | `STOVETOP` | `NONE` | Teapot feature says it is safe on gas, induction and electric stovetops for boiling water. |
| `B0757Y4S84` | `VALID_PRODUCT` | `electric_kettle` | Complete kettle has digital temperature control, concealed electric heater and keep-warm mode; coffee taxonomy is wrong. |
| `B077TVSJ7Q` | `MANUAL_DEVICE` | `NONE` | Pour-over kit includes manual coffee brewer and pouring kettle, with no integrated powered brewer. |
| `B09JZR6XWC` | `VALID_PRODUCT` | `coffee_maker` | Complete powered machine brews coffee and has a built-in blender; coffee maker is the primary marketed function. |
| `B07H28TCLC` | `VALID_PRODUCT` | `coffee_maker` | 1050 W, 15-bar pump proves powered espresso machine; manual flag refers to wording, not manual brewing. |
| `B01E5KME6S` | `VALID_PRODUCT` | `coffee_maker` | Moka brewer has a described electric base and adjustable heat control; manual keyword is misleading. |
| `B003XW7XMK` | `OTHER_NOISE` | `NONE` | 1000 W soup kettle is a commercial soup warmer, not a water kettle. |
| `B09NY9W21B` | `STOVETOP` | `NONE` | Title explicitly states cast-iron tea kettle is stove-top safe; no electric heater is described. |
| `B08LDFMWKW` | `OTHER_NOISE` | `NONE` | Hand-operated french-fry cutter only mentions an air fryer as a possible use context. |
| `B00938S1V0` | `OTHER_NOISE` | `NONE` | Product is primarily a stand mixer; included blender attachment does not make it a standalone blender. |
