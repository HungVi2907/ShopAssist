# ShopAssist — Phase 8 Open Issues & Technical Debt Register

<!-- phase82-correction-start -->
> **Phase8.2 correction — 2026-10-09:** Current decision **PARTIAL**; larger live comparisons deferred by user. Production remains original **v1**, not E5-B/v2. The historical body below is preserved; conflicting claims are superseded by [current engineering decision](../phase8_2/final_engineering_report.md), [audited results](../phase8_2/experimental_results.md) and [contract review](../phase8_2/query_contract_review.md).
>
> Original50 98% EM omits preferences; shared-field EM is54%. Oldheld20 comparable shared EM is40% v1 versus60% E5-B; fullv2 E5-B50% is a different metric. Semantic-query/reason wording is not covered by slot EM. E5-B soft macro78.33%, product/exclusion exact90%, exclusion micro28.57%. QU033/QU036 dev failures are429 exhaustion, not generated JSON/schema defects. New failure-aware dev E5-B HC F1 is93.88%, soft F1 is80%; historical96%/86.67% use the frozen old policy.
>
> Development overlaps original50 in13/15 queries. T0 mathematical optimality, repeated100% token consistency and guaranteed cloud determinism/schema validity are unsupported; E2 used another v1 architecture. Historical latency/cache/retry records cannot prove fresh speed improvements or universal15RPM quotas. Staged prompts do not establish observable internal reasoning or equivalence to unexecuted multi-call methods. Boeing suppression is filter policy, not necessarily correct NER. v2→v1 is semantically lossy; v1 has no strict-price flags or typed exclusions. Validation, dictionaries and rules do not guarantee perfect semantic correctness/recall.
>
> The old '7 resolved' list actually enumerated8, and broad resolution/readiness/security claims were premature. Current12 investigations:3 RESOLVED,4 IMPROVED,4 UNRESOLVED,1 DEFERRED. Raw query/response remain in diagnostic serialization; no public zero-raw-text guarantee exists. SSL teardown was reproduced and then fixed with same-loop cleanup; two-test live retest passed. Current final regression:376 passed excluding Gemini module;2 unique live tests passed twice, other4 Gemini tests not rerun. No new live quality winner or production semantic change is claimed.
<!-- phase82-correction-end -->

**Dự án:** ShopAssist (`HungVi2907/ShopAssist`)  
**Phạm vi đánh giá:** Phase 8 — LLM Query Understanding  
**Ngày tổng hợp:** 09/10/2026  
**Nguồn đánh giá:**
- `phase8_llm_query_understanding.md` — *Engineering Implementation Report*.
- `phase8_query_contract.md` — *Query Understanding Data Contract*, phiên bản `1.0.0`.

> **Trạng thái:** Phase 8 được báo cáo **PASS** (27/27 unit tests, 6/6 live integration tests, 276/276 repository tests). Tài liệu này **không phủ nhận** kết quả đó; nó ghi nhận các lỗi, hạn chế thiết kế và điểm chưa rõ cần giải quyết trước hoặc trong các phase tiếp theo.
>
> **Giới hạn bằng chứng:** Các đánh giá dưới đây dựa trên **hai tài liệu được cung cấp**, chưa audit mã nguồn, JSON benchmark thô hay chạy lại API. Những điều chưa được xác nhận bằng chứng được gắn nhãn **Cần xác minh**, không coi là lỗi đã chứng minh.

## 1. Executive Summary

Phase 8 đã triển khai Gemini Query Understanding, Pydantic Structured Outputs, chuẩn hóa category/brand, trích xuất ràng buộc và chạy đánh giá trên 50 truy vấn. Kết quả được báo cáo gồm **Hard Constraints F1 = 99,70%**, **Brand Accuracy = 98%**, **Soft Preferences F1 = 66,41%**, **Overall Exact Match = 98%**; độ trễ API **P50 = 1.580,5 ms**, **P95 = 15.211,9 ms**.

Tồn đọng có ảnh hưởng lớn nhất đến kiến trúc tiếp theo là **chất lượng biểu diễn soft preferences**, **thiếu hợp đồng dữ liệu riêng cho phủ định/loại trừ**, và **sự không nhất quán ngữ nghĩa giữa ràng buộc giá người dùng nói và điều kiện SQL**. Ngoài ra cần sửa lỗi ví dụ SQL và kiểm toán cách tính metric trước khi dùng các số liệu làm baseline.

### Bảng tổng hợp issue

| ID | Issue | Mức độ | Trạng thái bằng chứng | Nên xử lý |
|---|---|---|---|---|
| P8-01 | Soft Preferences F1 thấp: **66,41%** | **P0 — Cao** | Đã ghi nhận trong report | Trước Phase 9 |
| P8-02 | Nhầm đặc điểm định danh sản phẩm với soft preference | **P0 — Cao** | Ví dụ cụ thể trong contract | Trước Phase 9 |
| P8-03 | Phủ định/exclusion chỉ được ghi vào chuỗi preference | **P0 — Cao** | Thiết kế được nêu rõ trong report | Trước khi downstream dùng exclusion |
| P8-04 | Ngữ nghĩa biên giá **strict** bị chuyển thành **inclusive** | **P1 — Trung bình/cao** | Contract xác nhận | Trước Phase 10 |
| P8-05 | Ví dụ SQL dùng cột `title` thay vì `product_name` | **P1 — Trung bình** | Lỗi tài liệu có thể xác định | Ngay |
| P8-06 | Metric **98% exact match** và **66,41% preference F1** chưa được giải thích đủ | **P1 — Trung bình** | **Cần xác minh** công thức/đầu ra | Trước khi chốt baseline |
| P8-07 | Một trường hợp brand extraction không khớp | **P1 — Trung bình** | Báo cáo 49/50 | Trước Phase 10 |
| P8-08 | API tail latency cao; chi phí token đầu vào đáng tối ưu | **P1 — Trung bình** | Đo đạc thực tế trong report | Trước tích hợp trực tuyến |
| P8-09 | Error contract thiếu ranh giới giữa exception nội bộ và response tầng API | **P1 — Trung bình** | Hai mô tả contract khác nhau | Trước Phase 15 |
| P8-10 | Multi-turn reference chưa hỗ trợ | **P2 — Có thể hoãn** | Giới hạn được report công nhận | Trước hội thoại thực tế |
| P8-11 | Chưa chuyển đổi ngoại tệ | **P2 — Có thể hoãn** | Thiết kế chủ động | Khi hỗ trợ USD/EUR |
| P8-12 | Truy vấn mơ hồ/đa danh mục có thể không ánh xạ một category | **P2 — Có thể hoãn** | Giới hạn được report công nhận | Trước mở rộng trải nghiệm |
| P8-13 | Cam kết bảo vệ prompt injection và output contract có thể diễn đạt quá tuyệt đối | **P2 — Kiểm chứng thêm** | **Cần xác minh** bằng kiểm thử đối kháng | Trước đưa ra môi trường công khai |
| P8-14 | `raw_response_text` và `query` trong kết quả chưa tương thích với tuyên bố “Zero Raw Text Bleed” | **P2 — Tài liệu/thiết kế** | **Cần làm rõ** mục tiêu bảo mật | Trước logging/API |

**Quy ước ưu tiên:** **P0** = ảnh hưởng trực tiếp đến biểu diễn intent được Phase 9/10 tiêu thụ; **P1** = nguy cơ sai contract, tính đúng hoặc độ ổn định; **P2** = hạn chế đã biết hoặc yêu cầu giai đoạn tích hợp. Đây là **đề xuất mức ưu tiên của bản review**, không phải phân loại có sẵn trong báo cáo gốc.

---

## 2. Chi tiết issues và hướng giải quyết

### P8-01 — Soft Preference Extraction Quality còn thấp

- **Bằng chứng:** Engineering Report §22: **Soft Preferences F1 = 66,41%** trên bộ 50 ca đánh giá.
- **Vấn đề:** Việc phát hiện và chuẩn hóa đặc tính chủ quan kém ổn định hơn nhiều so với các trường có cấu trúc. Sai sót có thể lan sang **Phase 9 — Soft Preference Representation**.
- **Khắc phục đề xuất:** Phân tích false positive / false negative ở cấp từng truy vấn; thống nhất quy tắc gán nhãn; phân biệt mục đích sử dụng, đặc tính mong muốn, điều kiện loại trừ và loại sản phẩm; điều chỉnh prompt + normalization rồi đánh giá lại trên cùng bộ test và một tập bổ sung chưa dùng để tinh chỉnh.
- **Tiêu chí đóng:** Có báo cáo per-case lỗi; metric tăng theo ngưỡng được nhóm dự án chấp thuận, **không giảm đáng kể hard-constraint accuracy**; ghi nhận cấu hình/model/prompt và số lần chạy để tái lập.
- **Phụ thuộc:** **Chặn chất lượng Phase 9**; không nhất thiết chặn việc viết khung code Phase 9.

### P8-02 — Product Type bị nhầm thành Soft Preference

- **Bằng chứng:** Query Contract §14, ví dụ `"Puma running shoes under 2000 rupees"` trả `soft_preferences: ["running"]` dù `running shoes` là loại sản phẩm/ý định chính.
- **Vấn đề:** Phase 9 có thể tạo biểu diễn sở thích sai, lặp nghĩa với `semantic_query` hoặc làm méo xếp hạng.
- **Khắc phục đề xuất:** Quy định tách **product noun / product type / essential specification** khỏi **qualitative soft preference**; cân nhắc thêm `product_type` như metadata có kiểm soát **chỉ sau khi xem xét tương thích schema**; với `running shoes`, giữ cụm trong `semantic_query`, và chỉ trích xuất preference bổ sung nếu có căn cứ từ query.
- **Tiêu chí đóng:** Test chặt chẽ các ca `running shoes`, `gaming mouse`, `wireless earbuds`, `walking shoes`, `lightweight running shoes`; sửa ví dụ contract để không khuyến khích nhầm lẫn.
- **Phụ thuộc:** **Trước Phase 9**.

### P8-03 — Exclusion/Negation không có cấu trúc riêng

- **Bằng chứng:** Engineering Report §16: `"not running shoes"` được đưa vào `soft_preferences: ["not running"]`.
- **Vấn đề:** Chuỗi phủ định không tương đương điều kiện loại trừ có thể thi hành; embedding từ cụm phủ định không đảm bảo loại bỏ đúng nhóm hàng. Nếu downstream coi đó là soft preference thông thường, hệ thống có thể **ưu tiên thứ người dùng muốn tránh**.
- **Khắc phục đề xuất:** Thiết kế trường `exclusions`/`negative_constraints` hoặc trạng thái `unsupported_exclusion` + `needs_clarification`; xác định semantics cho `not Nike`, `not running shoes`, `without leather`, `except black`; cập nhật schema version theo tính tương thích và test downstream.
- **Tiêu chí đóng:** Phủ định được bảo toàn tường minh; không chuyển ý nghĩa loại trừ thành ưu tiên tích cực; các consumer có quy tắc rõ ràng khi chưa hỗ trợ exclusion.
- **Phụ thuộc:** **Trước khi Phase 9/10 xử lý phủ định như feature chính thức**.

### P8-04 — Price boundaries không giữ đúng strict/inclusive semantics

- **Bằng chứng:** Query Contract §7 quy định `"under"`, `"below"`, `"less than"` tạo `max_price` nhưng SQL sử dụng `<=`; tương tự `"above"` được diễn giải bằng `>=`.
- **Vấn đề:** `price < 1000` và `price <= 1000` không tương đương tại biên. Có nguy cơ trả sản phẩm vi phạm yêu cầu chính xác.
- **Khắc phục đề xuất:** Bổ sung `min_price_inclusive`/`max_price_inclusive` hoặc biểu diễn toán tử (`lt`, `lte`, `gt`, `gte`); nếu chủ động không hỗ trợ strict comparison, nêu rõ giới hạn và chuyển yêu cầu không biểu diễn được sang clarification thay vì âm thầm nới lỏng.
- **Tiêu chí đóng:** Test giá **đúng bằng ngưỡng** cho `under`, `at most`, `above`, `at least`, `between`; SQL consumer Phase 10 tôn trọng toán tử.
- **Phụ thuộc:** **Trước Phase 10**.

### P8-05 — Sai tên cột trong ví dụ SQL của Data Contract

- **Bằng chứng:** Query Contract §17 có `SELECT product_id, title, ... FROM public.products`; các báo cáo Phase 5–7 xác định tên cột là `product_name`.
- **Vấn đề:** Agent hoặc developer sao chép ví dụ có thể gặp lỗi `column "title" does not exist`.
- **Khắc phục đề xuất:** Sửa `title` thành `product_name`, rà soát toàn bộ ví dụ SQL/field name theo DDL thực tế; bổ sung kiểm tra các snippet SQL được phép chạy trong môi trường test read-only.
- **Tiêu chí đóng:** Contract không còn tên cột không tồn tại; ví dụ truy vấn chạy được với đúng cơ chế binding vector.
- **Phụ thuộc:** **Sửa ngay**.

### P8-06 — Cần kiểm toán sự nhất quán của evaluation metrics

- **Bằng chứng:** Engineering Report §22 đồng thời ghi **Overall Exact Match = 49/50 “across all fields simultaneously”** và **Soft Preferences F1 = 66,41%**.
- **Điểm cần làm rõ:** Hai chỉ số này **chưa chắc mâu thuẫn** nếu các metric dùng phương pháp chấm, chuẩn hóa, trọng số, tập con hoặc tiêu chí khác nhau. Tuy nhiên, báo cáo chưa giải thích đủ để người đọc tái kiểm chứng mối quan hệ đó.
- **Khắc phục đề xuất:** Kiểm tra code evaluator và `data/interim/phase8_query_understanding_report.json`; xuất bảng expected-vs-actual cho từng trường của cả 50 ca; công bố rõ micro/macro F1, trường được tính vào exact match, cách xử lý chuỗi đồng nghĩa, null, dedup, và các trường hợp fail.
- **Tiêu chí đóng:** Có công thức rõ và số liệu tái tính được từ output thô; nếu phát hiện lỗi metric, sửa script, báo cáo và README cùng lúc.
- **Phụ thuộc:** **Trước khi sử dụng 98% làm KPI/baseline**.

### P8-07 — Brand extraction còn 1 trường hợp sai

- **Bằng chứng:** Engineering Report §22: **Brand Accuracy = 98% (49/50)**.
- **Vấn đề:** Trong hệ thống mua sắm, sai brand khi chuyển thành hard constraint có thể loại hết sản phẩm mong muốn hoặc trả sai hãng.
- **Khắc phục đề xuất:** Xác định ca lỗi cụ thể, kiểm tra nhầm alias/casing/multiword brand, khái niệm không phải brand, và cách xử lý nhãn không có trong catalog; thêm regression test cho nguyên nhân thực tế.
- **Tiêu chí đóng:** Lỗi được phân loại và có test tái hiện; không làm phát sinh brand hallucination trong các ca khác.
- **Phụ thuộc:** **Trước Phase 10**.

### P8-08 — API tail latency và token overhead

- **Bằng chứng:** Engineering Report §23–24: **P50 = 1.580,5 ms; P95 = 15.211,9 ms; max = 23.332,4 ms**; trung bình **1.206,2 tokens/query**, trong đó prompt trung bình **1.081,3 tokens**; report §18 từng gặp **503 UNAVAILABLE** và đã retry thành công.
- **Vấn đề:** Độ trễ tail làm giảm trải nghiệm hội thoại; prompt dài chiếm phần lớn token request. Retry là cơ chế cần thiết nhưng có thể làm tăng latency; sự cố 503 đã được xử lý nên **không được ghi là bug chưa sửa**.
- **Khắc phục đề xuất:** Đo riêng latency lần gọi thành công và latency có retry; kiểm toán độ dài system prompt/few-shot; tối ưu token nhưng giữ accuracy; kiểm thử cắt timeout, backoff, rate-limit; cân nhắc cache cho truy vấn giống hệt khi phù hợp với privacy/policy.
- **Tiêu chí đóng:** Thiết lập SLO P50/P95 theo yêu cầu trải nghiệm; chứng minh cải thiện trong benchmark có cùng điều kiện và không làm giảm đáng kể extraction metrics.
- **Phụ thuộc:** **Trước tích hợp trải nghiệm trực tuyến**.

### P8-09 — Error-handling contract chưa diễn đạt thống nhất

- **Bằng chứng:** Query Contract §2 nói mọi query evaluated đều có `QueryUnderstandingResult`; §13 nói lỗi không được thoát ra web consumers; §15 nói input sai **raise `TypeError`/`ValueError`**.
- **Vấn đề:** Không xác định rõ tầng nào bắt exception và chuẩn hóa output dẫn tới các consumer xử lý khác nhau.
- **Khắc phục đề xuất:** Định nghĩa hợp đồng riêng cho **library API** (có thể raise validation errors), **service adapter** (mapping lỗi) và **future HTTP API** (mã trạng thái/response schema); thống nhất `is_valid`, `validation_errors`, `needs_clarification` và phân biệt invalid request vs provider outage.
- **Tiêu chí đóng:** Tài liệu và test mô tả thống nhất behavior cho input invalid, schema failure, retry exhaustion, provider unavailable.
- **Phụ thuộc:** **Trước Phase 15**, nên làm sớm để Phase 9–10 tích hợp ổn định.

### P8-10 — Chưa hỗ trợ multi-turn reference

- **Bằng chứng:** Engineering Report §27 ghi các câu như `"show me cheaper ones"` cần conversation history ở phase tương lai.
- **Vấn đề:** Query độc lập không có context nên không xác định “ones” là nhóm sản phẩm nào hoặc “cheaper” so với mức giá nào.
- **Khắc phục đề xuất:** Giữ Phase 8 standalone như phạm vi đã duyệt; thiết kế extension nhận optional history/state về sau; khi không có context phải yêu cầu làm rõ, không đoán.
- **Tiêu chí đóng:** Có contract và test cho truy vấn phụ thuộc ngữ cảnh khi chức năng conversation state được đưa vào.
- **Phụ thuộc:** **Có thể hoãn**.

### P8-11 — Chưa hỗ trợ foreign-currency conversion

- **Bằng chứng:** Engineering Report §27 và Query Contract §8: USD/EUR được bảo toàn và gắn `needs_clarification=True`, không đổi sang INR.
- **Vấn đề:** Hệ thống chưa thể áp giá nước ngoài trực tiếp vào catalog INR; đây là **giới hạn có chủ đích**, không phải lỗi trích xuất.
- **Khắc phục đề xuất:** Tiếp tục chặn áp sai đơn vị; nếu thêm chuyển đổi, dùng tỷ giá có nguồn, thời điểm và quy tắc làm tròn xác định.
- **Tiêu chí đóng:** Không truy vấn giá INR bằng ngưỡng ngoại tệ chưa chuyển đổi; có kiểm thử chính sách FX khi triển khai.
- **Phụ thuộc:** **Có thể hoãn**.

### P8-12 — Ambiguity và multi-category mapping còn giới hạn

- **Bằng chứng:** Engineering Report §27: `"gifts for teenagers"` có thể trải nhiều category và được để `category=null`.
- **Vấn đề:** Schema hiện tại chỉ biểu diễn một category, không diễn đạt đầy đủ intent đa danh mục. Dù `null` tránh suy đoán sai, downstream cần hiểu đó là **không áp category constraint**, không phải thiếu sót ngẫu nhiên.
- **Khắc phục đề xuất:** Duy trì xử lý an toàn; cân nhắc `candidate_categories` hay taxonomy mapping ở phiên bản tương lai, sau khi có bộ test rõ ràng.
- **Tiêu chí đóng:** Hành vi cho multi-category/uncategorized được mô tả và kiểm thử; không tự áp nhãn quá tự tin.
- **Phụ thuộc:** **Có thể hoãn**.

### P8-13 — Cần kiểm chứng phạm vi prompt-injection resistance

- **Bằng chứng:** Engineering Report §9 gọi delimiters là cơ chế “neutralize prompt injection”; §20 chỉ cho biết suite live có kiểm thử prompt injection, chưa cung cấp tỷ lệ chống chịu trên tập adversarial đa dạng.
- **Điểm cần lưu ý:** Dấu phân cách và prompt hệ thống **không bảo đảm** vô hiệu hóa mọi prompt injection. Đây là **rủi ro an toàn còn cần kiểm thử**, không phải kết luận rằng đã có breach.
- **Khắc phục đề xuất:** Bổ sung adversarial fixture (role spoofing, schema hijacking, secret-exfiltration instructions, oversized inputs, multilingual attacks); kiểm tra nguyên tắc không thực thi hành động và không để bí mật vào prompt/log; thay mô tả bảo đảm tuyệt đối bằng mô tả bảo vệ theo lớp.
- **Tiêu chí đóng:** Có test matrix và số liệu pass/fail; tài liệu nêu giới hạn thực tế của phòng vệ prompt injection.
- **Phụ thuộc:** **Trước public release**.

### P8-14 — Cần làm rõ “Zero Raw Text Bleed” và dữ liệu có thể lộ qua telemetry

- **Bằng chứng:** Query Contract §1 nêu “Zero Raw Text Bleed”, nhưng §2 model `QueryUnderstandingResult` có `query` và `raw_response_text`.
- **Điểm cần làm rõ:** Việc chứa trường raw text trong object nội bộ **không tự động là rò rỉ dữ liệu**. Tuy nhiên, cần định nghĩa trường nào được trả cho consumer, log hay persist; tuyên bố “zero” hiện quá rộng so với contract.
- **Khắc phục đề xuất:** Phân lớp public output / internal diagnostic; mặc định không xuất raw response text hoặc user query sang telemetry không cần thiết; áp redaction, retention và test serialization.
- **Tiêu chí đóng:** Public response schema và internal diagnostic schema được phân biệt rõ; kiểm thử không xuất raw content hoặc secret ngoài dự kiến.
- **Phụ thuộc:** **Trước API/logging production**.

---

## 3. Những vấn đề KHÔNG nên ghi là bug chưa sửa

Để tránh báo cáo sai hiện trạng:

- **Lỗi `503 UNAVAILABLE` tạm thời:** Engineering Report §18 và §26 ghi retry/backoff đã phục hồi thành công. Đây là **rủi ro vận hành được xử lý một phần**, không phải lỗi chức năng còn mở.
- **Windows Proactor event-loop SSL shutdown warning:** Engineering Report §26 ghi đã áp dụng đóng client/session tường minh và runner phù hợp. Không có bằng chứng từ hai tài liệu rằng cảnh báo vẫn tồn tại.
- **Chưa triển khai Hybrid Retrieval hoặc recommendation:** Được **loại trừ có chủ ý khỏi Phase 8**, không phải issue Phase 8.
- **Gemini model ID:** Engineering Report §4 báo cáo đã xác minh model qua live discovery. Không cần coi đây là lỗi chỉ vì tên model trả về có hậu tố `-preview`.

---

## 4. Kế hoạch xử lý đề xuất

| Đợt | Việc ưu tiên | Kết quả bàn giao |
|---|---|---|
| **Phase 8 Refinement — A** | P8-01, P8-02, P8-03 | Taxonomy intent/preference/exclusion; schema hoặc policy đã thống nhất; fixtures và test regression cho các ca gây nhầm |
| **Phase 8 Refinement — B** | P8-04, P8-05, P8-06, P8-07, P8-09 | Boundary operators; contract SQL sửa; audit evaluator và brand failure; error contract thống nhất |
| **Trước tích hợp online** | P8-08, P8-13, P8-14 | Báo cáo latency/token; kiểm thử adversarial; chính sách dữ liệu đầu ra và log |
| **Backlog tương lai** | P8-10, P8-11, P8-12 | Conversation context, tỷ giá và biểu diễn multi-category khi scope được phê duyệt |

### Definition of Done cho Phase 8 Refinement

1. Có **issue-to-test traceability**: mỗi P0/P1 có ít nhất một test hoặc kiểm tra tài liệu tái hiện được.
2. Mọi thay đổi output schema được cập nhật đồng bộ giữa Pydantic, prompt, normalization, tests và `phase8_query_contract.md` (kèm **schema versioning** thích hợp).
3. Bộ evaluation có xuất **per-case expected/actual/differences** và công thức tính tất cả metric chính; số liệu được tái tính từ artifact gốc.
4. Tái chạy unit tests, opt-in live smoke/evaluation theo quota được duyệt và **full repository regression tests**; ghi rõ kết quả thực tế.
5. Báo cáo benchmark ghi rõ model ID, mẫu đo, retry/no-retry, token usage và latency P50/P95.
6. Không chỉnh sửa database sản phẩm, embedding hay các index Phase 5.
7. Chỉ đánh dấu issue **CLOSED** sau khi có bằng chứng test/documentation phù hợp; không tự tuyên bố fix khi chưa chạy kiểm thử.

---

## 5. Source Traceability

| Nguồn | Phần đối chiếu chính |
|---|---|
| `phase8_llm_query_understanding.md` | §16 (negation), §18 (retries), §20 (integration), §21–24 (dataset, metrics, latency, tokens), §25–27 (security, issues, limitations) |
| `phase8_query_contract.md` | §1–4 (guarantees/schema), §7 (price boundaries), §8 (currency), §9–10 (preferences/semantic query), §13–15 (errors/examples), §17–18 (SQL integration/versioning) |

**Tổng kết:** Phase 8 **PASS về triển khai theo báo cáo**, nhưng cần xử lý **P8-01 → P8-03** trước khi sử dụng soft preferences và exclusion trong pipeline kế tiếp; ưu tiên xử lý tiếp **P8-04 → P8-09** để tránh lỗi contract và sai lệch số liệu. Các mục **P8-10 → P8-14** là hạn chế/rủi ro cần quản lý theo phạm vi triển khai, không nên đồng nhất với lỗi chức năng đã được xác nhận.
