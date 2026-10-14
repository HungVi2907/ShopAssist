# Bài 06 — Các Chỉ Số Đánh Giá Hệ Thống AI & Information Retrieval (IR)

---

## 1. Khái Niệm Cốt Lõi: Bản Chất Của Đánh Giá (Evaluation) Trong AI

Trong kỹ thuật phần mềm truyền thống, kiểm thử (Testing) dựa trên logic Đúng/Sai tuyệt đối (Boolean Assertions: `assert result == expected`). Nhưng trong hệ thống AI & Tìm kiếm thông tin (IR):
- Không có câu trả lời duy nhất: Với câu hỏi *"giày chạy bộ Puma"*, có hàng chục sản phẩm phù hợp ở các mức độ khác nhau: Rất phù hợp (Grade 3), Phù hợp một phần (Grade 2), Liên quan yếu (Grade 1), hoặc Hoàn toàn không liên quan (Grade 0).
- Hệ thống trả về một **danh sách có thứ tự (Ranked List)**. Một hệ thống đưa sản phẩm tốt lên vị trí số 1 phải có điểm số cao hơn hệ thống đẩy sản phẩm tốt xuống vị trí số 5.

Để đánh giá khoa học, AI Engineering sử dụng các thang đo toán học định lượng chuyên biệt.

---

## 2. Thang Điểm Đánh Giá Mức Độ Liên Quan (Relevance Grades)

Trong ShopAssist, bộ dữ liệu **AI-Silver v4** sử dụng thang đo 4 mức chuẩn mực:
- **Grade 3 (Highly Relevant - Rất phù hợp):** Sản phẩm khớp hoàn toàn với danh mục, thương hiệu và tất cả các thuộc tính tích cực được yêu cầu.
- **Grade 2 (Relevant - Phù hợp):** Sản phẩm khớp danh mục và phần lớn thuộc tính, chỉ thiếu một chi tiết phụ nhỏ.
- **Grade 1 (Weakly Related - Liên quan yếu):** Cùng họ sản phẩm nhưng sai phong cách, sai màu hoặc thiếu thuộc tính quan trọng.
- **Grade 0 (Irrelevant - Không liên quan):** Sai danh mục hoàn toàn (ví dụ: tìm giày nhưng ra ốp điện thoại) hoặc vi phạm điều kiện cứng (giá quá đắt, sai hãng).

*Quy ước nhị phân (Binary Relevance):* Các chỉ số như Precision@K hoặc MRR coi **Grade $\ge 2$ là Relevant (Có liên quan)**, và Grade $< 2$ là Not Relevant.

---

## 3. Chi Tiết Các Chỉ Số Đánh Giá Cốt Lõi

### 3.1. Precision@K (Độ Chính Xác Tại Vị Trí K)

#### Định nghĩa trực quan:
Trong số $K$ sản phẩm đầu tiên mà hệ thống gợi ý cho người dùng, có bao nhiêu phần trăm sản phẩm thực sự hữu ích (Grade $\ge 2$)?

#### Công thức toán học:
$$\text{Precision@K} = \frac{\sum_{i=1}^K \mathbb{I}(\text{grade}_i \ge 2)}{K}$$
*(với $\mathbb{I}$ là hàm chỉ báo, nhận giá trị 1 nếu đúng, 0 nếu sai).*

#### Ví dụ tính tay:
Hệ thống trả về Top 5 sản phẩm có nhãn relevance lần lượt là: `[Grade 3, Grade 1, Grade 2, Grade 0, Grade 2]`.
- Số sản phẩm liên quan (Grade $\ge 2$): 3 sản phẩm (vị trí 1, 3, 5).
- $\text{Precision@5} = \frac{3}{5} = 0.60$ (60%).

#### Cách ShopAssist triển khai & Xử lý nhãn thiếu (Judgment Coverage):
Trong thực tế đánh giá bằng phương pháp pooling, một số sản phẩm trả về chưa kịp gán nhãn (Unjudged). ShopAssist phân định minh bạch 2 chỉ số:
- `precision_judged`: Chỉ tính trên những sản phẩm đã có nhãn $\rightarrow \frac{\text{Số liên quan}}{\text{Số đã gán nhãn}}$.
- `precision_conservative`: Coi sản phẩm chưa gán nhãn là không liên quan $\rightarrow \frac{\text{Số liên quan}}{K}$.
- Xem code tại [src/shopassist/evaluation/phase14_metrics.py:L114](file:///d:/Project/ShopAssist/src/shopassist/evaluation/phase14_metrics.py#L114).

---

### 3.2. MRR — Mean Reciprocal Rank (Nghịch Đảo Thứ Hạng Đầu Tiên)

#### Định nghĩa trực quan:
Người dùng thường chỉ nhìn vào vị trí đầu tiên. MRR đo lường: **Hệ thống mất bao lâu để đưa được sản phẩm tốt ĐẦU TIÊN tới mắt người dùng?**

#### Công thức toán học:
$$\text{Reciprocal Rank (RR)} = \frac{1}{\min \{r \mid \text{grade}_r \ge 2\}}$$
$$\text{MRR} = \frac{1}{|Q|} \sum_{q \in Q} \text{RR}_q$$

#### Ví dụ tính tay:
- Truy vấn 1: Sản phẩm liên quan đầu tiên nằm ở vị trí 1 $\rightarrow \text{RR}_1 = \frac{1}{1} = 1.0$.
- Truy vấn 2: Sản phẩm liên quan đầu tiên nằm ở vị trí 2 $\rightarrow \text{RR}_2 = \frac{1}{2} = 0.5$.
- Truy vấn 3: Sản phẩm liên quan đầu tiên nằm ở vị trí 4 $\rightarrow \text{RR}_3 = \frac{1}{4} = 0.25$.
- $\text{MRR} = \frac{1.0 + 0.5 + 0.25}{3} = \frac{1.75}{3} \approx 0.5833$.

#### Cạm bẫy sống còn: Bảo toàn thứ hạng gốc (Rank Preservation)
Giả sử kết quả trả về là:
- Vị trí 1: Sản phẩm chưa gán nhãn (Unjudged)
- Vị trí 2: Sản phẩm liên quan (Grade 3)

Nhiều thư viện bị lỗi nén danh sách (Compaction): bỏ qua vị trí 1 và đẩy sản phẩm vị trí 2 lên làm phần tử thứ 0 trong mảng Python, dẫn đến tính sai: $\text{RR} = \frac{1}{1} = 1.0$!  
ShopAssist bắt buộc **bảo toàn nguyên vẹn rank gốc** $r = 2 \rightarrow \text{RR} = \frac{1}{2} = 0.5$. Xem unit test chứng minh tại [tests/test_phase14_evaluation.py:L40](file:///d:/Project/ShopAssist/tests/test_phase14_evaluation.py#L40).

---

### 3.3. nDCG@K — Normalized Discounted Cumulative Gain

Đây là **chỉ số toàn diện và quan trọng nhất** trong mọi hệ thống tìm kiếm hiện đại.

#### 1. Cumulative Gain (CG):
Cộng dồn điểm độ liên quan: $\text{CG@K} = \sum_{i=1}^K (2^{\text{grade}_i} - 1)$.  
*(Dùng hàm số mũ $2^{\text{grade}} - 1$ để thưởng điểm cực lớn cho Grade 3 ($2^3 - 1 = 7$) so với Grade 2 ($2^2 - 1 = 3$)).*

#### 2. Discounted Cumulative Gain (DCG):
Sản phẩm tốt nằm ở vị trí thấp phải bị phạt (giảm giá trị) theo hàm logarit vị trí:
$$\text{DCG@K} = \sum_{i=1}^K \frac{2^{\text{grade}_i} - 1}{\log_2(i + 1)}$$
- Vị trí 1 ($i=1$): chia cho $\log_2(2) = 1.0$ (giữ nguyên 100% điểm).
- Vị trí 2 ($i=2$): chia cho $\log_2(3) \approx 1.585$ (chỉ còn ~63% giá trị).
- Vị trí 3 ($i=3$): chia cho $\log_2(4) = 2.0$ (chỉ còn 50% giá trị).

#### 3. Ideal DCG (IDCG@K) & Chuẩn hóa:
Một câu hỏi: DCG = 5.2 là tốt hay xấu? Không biết được, trừ khi ta so sánh nó với **Kịch bản hoàn hảo nhất có thể đạt được (IDCG)**.
$$\text{nDCG@K} = \frac{\text{DCG@K}}{\text{IDCG@K}} \in [0, 1]$$

#### Cạm bẫy IDCG: Tính trên Tập Hoàn Vũ (Judgment Universe)
- **Cách làm sai:** Sắp xếp lại chính các sản phẩm mà hệ thống vừa tìm được để tính IDCG. Nếu hệ thống tìm ra 5 sản phẩm tệ hại (Grade 1, 0, 1, 0, 0), khi sắp lại ta vẫn có thể được nDCG = 1.0 vì tự so sánh với chính cái dở của mình!
- **Cách làm chuẩn mực của ShopAssist:** IDCG@K được tính bằng cách lấy ra $K$ sản phẩm có điểm số cao nhất trong **toàn bộ kho ứng viên của truy vấn đó** (Pool Universe). Xem triển khai tại [src/shopassist/evaluation/phase14_metrics.py:L70](file:///d:/Project/ShopAssist/src/shopassist/evaluation/phase14_metrics.py#L70).

---

### 3.4. Pool-Conditional Recall@K (Độ Bao Phủ Ứng Viên)

#### Định nghĩa & Giới hạn:
- Trong môi trường học thuật lý tưởng với tập dữ liệu nhỏ (như Cranfield), toàn bộ tài liệu trong kho đều được con người đọc và gán nhãn $\rightarrow$ Tính được **Catalog-wide Recall**.
- Trong thực tế e-commerce với 8,405 sản phẩm, con người không thể đọc hết cả catalog cho mỗi câu hỏi. Nhãn chỉ được gán trên các ứng viên được gom từ các thuật toán (Pooling).
- Do đó, ShopAssist gọi chỉ số này là **`pool_conditional_recall@K`**:
  $$\text{Pool Recall@K} = \frac{\text{Số sản phẩm liên quan tìm được trong Top K}}{\text{Tổng số sản phẩm liên quan đã biết trong Pool}}$$
  Tuyệt đối không tuyên bố đây là catalog-wide recall!

---

### 3.5. Constraint Satisfaction Rate (Tỷ Lệ Thỏa Mãn Ràng Buộc Cứng)

#### Định nghĩa:
Tỷ lệ sản phẩm trong Top K thỏa mãn hoàn toàn các bộ lọc thuộc tính cấu trúc (Category, Brand, Min/Max Price, Min Rating).
- Nếu người dùng tìm điện thoại dưới 5 triệu, mà vị trí số 1 là điện thoại 15 triệu $\rightarrow$ Vi phạm ràng buộc cứng.
- Trong Phase 14, ShopAssist đạt **100% Constraint Satisfaction Rate** nhờ lớp lọc SQL tiền truy vấn.

---

## 4. Bảng Tra Cứu Nhanh Cách Diễn Giải Chỉ Số

| Chỉ số | Giá trị cao nghĩa là gì? | Giá trị thấp nghĩa là gì? | Hướng xử lý khi điểm thấp |
|---|---|---|---|
| **nDCG@5** | Thứ tự sắp xếp từ trên xuống dưới rất hợp lý; sản phẩm tốt nhất luôn nằm ở đầu. | Xếp lộn xộn; sản phẩm điểm thấp lại nằm đè lên sản phẩm điểm cao. | Nâng cấp thuật toán Reranking (dùng Multi-Signal hoặc Cross-Encoder). |
| **MRR** | Người dùng mở ra là thấy ngay ít nhất 1 sản phẩm ưng ý tại vị trí số 1. | Phải cuộn chuột xuống sâu mới thấy sản phẩm đúng đầu tiên. | Tăng cường trọng số tìm kiếm từ khóa chính xác (TF-IDF/Exact Match). |
| **Precision@5** | Đa số các sản phẩm gợi ý đều dùng được. | Danh sách gợi ý lẫn nhiều sản phẩm rác, không liên quan. | Siết chặt ngưỡng tương đồng vector hoặc lọc điều kiện danh mục. |
| **Coverage** | Hầu hết các sản phẩm hiển thị đều đã được kiểm định chất lượng. | Nhiều sản phẩm trả về chưa có nhãn trong benchmark. | Mở rộng độ sâu gom mẫu (Contribution Depth) khi xây dựng benchmark. |

---

## 5. Cạm Bẫy Thường Gặp (Common Mistakes)

1. **Đồng hóa sản phẩm chưa gán nhãn thành Grade 0:** Trong kỹ thuật pooling, một sản phẩm chưa gán nhãn đơn giản là "chưa được duyệt", không có nghĩa là nó dở. Việc tự tiện gán nó bằng 0 sẽ làm méo mó kết quả của những thuật toán mới có khả năng tìm ra sản phẩm mới lạ.
2. **Không dùng Bootstrap Confidence Intervals:** Báo cáo một con số trung bình duy nhất (ví dụ: `nDCG = 0.83`) mà không có khoảng tin cậy 95% có thể dẫn đến kết luận sai lầm do sự biến động ngẫu nhiên của một vài câu truy vấn ngoại lai.

---

## 6. Bài Học Cốt Lõi (Key Takeaways)
1. **nDCG@K là tiêu chuẩn vàng:** Luôn dùng nDCG khi cần đánh giá chất lượng của danh sách kết quả có phân cấp mức độ liên quan.
2. **Bảo toàn vị trí rank gốc:** Tuyệt đối không nén danh sách khi tính MRR và nDCG trong trường hợp có dữ liệu chưa gán nhãn.
3. **Trung thực về tập dữ liệu:** Luôn công khai rõ ràng giới hạn của phương pháp pooling (Pool-conditional Recall thay vì Catalog Recall).
