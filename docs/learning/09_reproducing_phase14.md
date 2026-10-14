# Bài 09 — Hướng Dẫn Tái Hiện Thực Nghiệm Phase 14 Từ A Đến Z

---

## 1. Giới Thiệu & Mục Tiêu

Một trong những tiêu chí quan trọng nhất của AI Engineering là **Khả Năng Tái Hiện (Reproducibility)**. Một nghiên cứu hay một hệ thống AI dù có tuyên bố kết quả tốt đến đâu, nếu người khác tải mã nguồn về mà không thể chạy lại được thì hoàn toàn vô giá trị.

Tài liệu này cung cấp hướng dẫn từng bước (Step-by-step Tutorial) với các câu lệnh có thể sao chép trực tiếp (Copyable Commands) để bạn có thể tự mình chạy lại toàn bộ thực nghiệm của Phase 14 trên máy tính cá nhân.

---

## 2. Chuẩn Bị Môi Trường Làm Việc

### 2.1. Kích hoạt Virtual Environment (Python 3.10+)
Mở cửa sổ dòng lệnh (PowerShell trên Windows) tại thư mục gốc của dự án `d:\Project\ShopAssist`:

```powershell
# Thiết lập biến môi trường PYTHONPATH trỏ vào thư mục src
$env:PYTHONPATH = "src"

# Kích hoạt môi trường ảo Python đã cài sẵn
& .venv\Scripts\Activate.ps1

# Kiểm tra phiên bản Python
python --version
# Kết quả mong đợi: Python 3.10.x
```

### 2.2. Kiểm tra các thư viện cốt lõi
Đảm bảo các gói phụ thuộc quan trọng đã sẵn sàng:

```powershell
& .venv\Scripts\python.exe -c "import torch, sentence_transformers, pydantic, sqlalchemy, pgvector; print('All core AI libraries imported successfully!')"
```

---

## 3. Kiểm Tra Tính Toàn Vẹn Của Bộ Dữ Liệu AI-Silver v4

Trước khi chạy bất kỳ phép tính nào, hãy kiểm tra tính toàn vẹn của bộ benchmark đóng băng tại `data/evaluation/phase13/ai_silver/v4_full_silver/`:

```powershell
& .venv\Scripts\python.exe -c "from pathlib import Path; from shopassist.evaluation.silver import validate_silver_dataset; report = validate_silver_dataset(Path('data/evaluation/phase13/ai_silver/v4_full_silver')); print('Status:', report['status'], '| Errors:', len(report['errors']), '| Warnings:', len(report['warnings']))"
```
**Kết quả mong đợi:**  
`Status: PASS | Errors: 0 | Warnings: 0`

---

## 4. Chạy Toàn Bộ Quy Trình Đánh Giá Phase 14 (Evaluation Runner)

### 4.1. Câu lệnh chạy thực nghiệm hoàn chỉnh
Chạy script điều phối chính [scripts/run_phase14_evaluation.py](file:///d:/Project/ShopAssist/scripts/run_phase14_evaluation.py):

```powershell
& .venv\Scripts\python.exe scripts/run_phase14_evaluation.py --run-live-judge
```

*(Nếu bạn không có mạng Internet hoặc muốn chạy ở chế độ offline hoàn toàn, chỉ cần bỏ cờ `--run-live-judge`, script sẽ tự động dùng mô hình thẩm định offline demonstration).*

---

## 5. Đọc & Hiểu Kết Quả Trên Màn Hình Console

Khi script thực thi, bạn sẽ thấy 7 bước chạy tuần tự:

```text
==============================================================================
SHOPASSIST PHASE 14: AI ENGINEERING EXPERIMENTAL EVALUATION
==============================================================================
[Step 1] Validating frozen AI-Silver v4 benchmark...
  -> AI-Silver v4 benchmark validated: PASS (0 errors, 0 warnings)

[Step 2] Loading dataset and catalog into memory...
  -> Queries: 200 | Qrels: 2400 | Candidate Pools: 174 | Retrieval Runs: 522

[Step 3] Evaluating Baseline Retrieval (TF-IDF vs Dense vs Hybrid RRF)...
  --- RETRIEVAL RESULTS (All 174 Pools, Cutoff K=5) ---
  Method       | nDCG@5 (mean)  | MRR (mean)   | P@5 (judged)   | P@5 (cons)   | Coverage  
  ------------------------------------------------------------------------------------
  tfidf        | 0.8324         | 0.6050       | 0.5209         | 0.5054       | 1.0000    
  dense        | 0.7625         | 0.5651       | 0.4975         | 0.4785       | 1.0000    
  hybrid       | 0.9067         | 0.5322       | 0.4275         | 0.4275       | 1.0000    

[Step 4] Evaluating Phase 11 Reranking (RRF vs Multi-Signal vs Cross-Encoder)...
  --- RERANKING RESULTS (Cutoff K=5) ---
  Method           | nDCG@5     | MRR        | P@5        | Latency (ms)     | Mean Rank Shifts
  --------------------------------------------------------------------------------------
  RRF              | 0.9155     | 0.8750     | 0.9000     | 0.26             | 0.00            
  MULTI_SIGNAL     | 0.9342     | 1.0000     | 0.8500     | 0.16             | 3.00            
  CROSS_ENCODER    | 0.8624     | 0.8333     | 0.8500     | 545.66           | 12.00           

[Step 5] Building educational RAG execution trace (Q0001)...
  -> Saved RAG trace: rag_trace_demonstration.json

[Step 6] Running LLM-as-a-Judge demonstration...
  -> Connected to live GeminiClient for LLM Judge.
  -> LLM Judge Result: Decision=PASS, Groundedness=4/5, ExecutionMode=LIVE_API

[Step 7] Master manifest written to: data\evaluation\phase14\v1\manifest.json
==============================================================================
PHASE 14 EVALUATION COMPLETE: SUCCESS
phase14_learning_status = COMPLETE
==============================================================================
```

---

## 6. Khám Phá Các File Artifacts Được Tạo Ra

Toàn bộ kết quả đầu ra dạng JSON có cấu trúc máy đọc được lưu tại thư mục:  
`data/evaluation/phase14/v1/`

### 1. `retrieval_evaluation_summary.json`
Chứa toàn bộ số liệu thống kê chi tiết của TF-IDF, Dense và Hybrid phân theo 3 phân vùng: `all` (174 pools), `development` (140 queries) và `held_out` (60 queries). Đi kèm khoảng tin cậy 95% Bootstrap.

### 2. `per_query_metrics.jsonl`
Chứa chi tiết từng dòng đánh giá cho từng truy vấn độc lập:
```powershell
# Xem kết quả của 3 câu truy vấn đầu tiên
Get-Content data/evaluation/phase14/v1/per_query_metrics.jsonl -Head 3
```

### 3. `reranking_evaluation_summary.json`
Chứa so sánh đối đầu giữa RRF, Multi-Signal và Cross-Encoder về điểm nDCG@5, MRR và thời gian thực thi (Latency).

### 4. `rag_trace_demonstration.json`
Chứa toàn bộ nhật ký dữ liệu truyền tay qua 5 tầng của truy vấn `Q0001`.

### 5. `llm_judge_evaluation.json`
Chứa kết quả thẩm định thực tế của mô hình `gemini-3.1-flash-lite`, bao gồm cả lời bình phẩm phê bình (critique) và các câu bị nghi ngờ là ảo giác (`unsupported_claims`).

---

## 7. Chạy Bộ Kiểm Thử Tự Động (Unit Test Suite)

Để đảm bảo toàn bộ mã nguồn của Phase 14 không có lỗi cú pháp và đáp ứng tuyệt đối các bài toán tính tay:

```powershell
# Chạy toàn bộ 11 unit test của Phase 14
& .venv\Scripts\python.exe -m pytest tests/test_phase14_evaluation.py -v
```
**Kết quả mong đợi:**  
`11 passed in 0.60s` (100% PASS).

```powershell
# Chạy toàn bộ test suite của Phase 13 và Phase 14 để đảm bảo không bị hồi quy
& .venv\Scripts\python.exe -m pytest tests/test_phase13_dataset.py tests/test_phase13_workflow.py tests/test_phase14_evaluation.py -v
```
**Kết quả mong đợi:**  
`33 passed in 1.85s` (Toàn bộ kiểm thử hồi quy thành công mỹ mãn).

---

## 8. Hướng Dẫn Xử Lý Khi Gặp Sự Cố (Troubleshooting)

| Hiện tượng | Nguyên nhân có thể | Cách xử lý |
|---|---|---|
| `ModuleNotFoundError: No module named 'shopassist'` | Chưa thiết lập biến môi trường `PYTHONPATH`. | Chạy `$env:PYTHONPATH = "src"` trước khi gọi python. |
| `UnicodeEncodeError: 'charmap' codec can't encode...` | Cửa sổ PowerShell Windows đang dùng bảng mã `cp1252` thay vì UTF-8. | Chạy `$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()` hoặc xem kết quả trực tiếp trong file JSON. |
| `Groq API status error (HTTP 401)` | Khóa Groq API trong file `.env` đã hết hạn. | Hệ thống đã tự động chuyển sang dùng `gemini-3.1-flash-lite` hoặc chế độ offline demonstration an toàn. |
| `Rate limited by OpenRouter (HTTP 429)` | API miễn phí của OpenRouter bị giới hạn tốc độ gọi. | Bỏ cờ `--run-live-judge` để chạy chế độ thẩm định offline, hoặc dùng khóa Google AI Studio Gemini API. |

---

## 9. Bài Học Cốt Lõi (Key Takeaways)
1. **Khả năng tái hiện là thước đo chất lượng kỹ thuật:** Một dự án AI tốt phải có script chạy tự động từ đầu đến cuối chỉ với 1 câu lệnh duy nhất.
2. **Lưu trữ Manifest có mã băm SHA-256:** Giúp bạn tự tin rằng dữ liệu benchmark và kết quả đầu ra không bao giờ bị can thiệp hay thay đổi ngoài ý muốn.
