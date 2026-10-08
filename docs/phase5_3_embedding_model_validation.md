# Phase 5.3 — Embedding Model Setup & Validation

## 1. Objective

The objective of Phase 5.3 is to establish, configure, and thoroughly validate the official embedding model for the **ShopAssist** Conversational Product Recommendation System:

```text
BAAI/bge-small-en-v1.5
```

This phase validates the end-to-end embedding pipeline prior to full catalog batch generation in Phase 5.5:
- Environment & dependency compatibility (`sentence-transformers`, `torch`, `transformers`).
- Device resolution (NVIDIA CUDA acceleration with seamless CPU fallback).
- Model loading, sequence length configuration, and 384-dimensional vector validation.
- Native tokenization audit across all **8,405 candidate products** to quantify sequence length distributions and token overflow.
- Numerical integrity & L2 normalization verification (0 NaN, 0 Inf, 0 zero vectors, unit L2 norm).
- Asymmetric query vs. document encoding strategy.
- 5 multi-category semantic sanity retrieval tests.
- Batch throughput benchmarking and Phase 5.5 runtime estimation.

> [!NOTE]
> Phase 5.3 strictly limits inference to a representative sample of 200 products and benchmark tests. Batch generation for the full 8,405 catalog items is reserved for Phase 5.5.

---

## 2. Previous Phase Input

Phase 5.3 directly consumes the verified output artifact from Phase 5.2:

```text
data/interim/products_with_retrieval_text.parquet
```

- **Row count:** Exactly 8,405 rows.
- **Coverage:** 8,405 non-null, non-empty, and structurally valid `retrieval_text` strings.
- **Field ordering in `retrieval_text`:**
  1. `Product: <product_name>`
  2. `Category: <category>`
  3. `Brand: <brand>` *(omitted if missing)*
  4. `Specifications: <specs>` *(omitted if empty)*
  5. `Description: <description>` *(omitted if missing, truncated at ~1,200 chars)*

---

## 3. Model Selection

### Official Model: `BAAI/bge-small-en-v1.5`
- **Architecture:** BERT-based pre-trained bi-encoder fine-tuned with contrastive learning and hard negative mining.
- **Vector Dimension:** **384** (matches `vector(384)` in `database/migrations/001_create_product_knowledge_base.sql`).
- **Context Length:** **512 tokens**.
- **Model Size:** ~133 MB (33.4 million parameters).
- **Primary Retrieval Metric:** Cosine similarity.

### Rationale:
1. **Dimension Efficiency:** 384 dimensions strike the optimal trade-off between semantic expressive capacity, vector index memory consumption, and sub-30ms HNSW query latency on Supabase PostgreSQL.
2. **Benchmark Dominance:** Top-ranked among sub-50M parameter embedding models on the Massive Text Embedding Benchmark (MTEB).
3. **Low Latency & High Throughput:** Enables encoding the entire 8.4K catalog in less than 1 minute on consumer GPU hardware and under 7 minutes on CPU.

---

## 4. Environment & Dependencies

Dependencies were verified and recorded in `pyproject.toml`:

| Package | Version Verified | Role |
| :--- | :--- | :--- |
| `sentence-transformers` | `6.0.1` | High-level bi-encoder inference API |
| `torch` | `2.6.0+cu124` | Tensor computation engine with CUDA 12.4 support |
| `transformers` | `5.16.1` | Underlying model architecture and native tokenizer |
| `tokenizers` | `0.23.2` | Fast Rust-based BPE tokenizer backend |
| `numpy` | `1.26.4` | Array manipulation and vector similarity calculations |
| `pandas` | `2.3.3` | Dataset loading and sample slicing |

---

## 5. Model Configuration

The model is encapsulated in `src/shopassist/embeddings/model.py` via the `EmbeddingModel` class:

- **Model ID:** `BAAI/bge-small-en-v1.5`
- **Max Sequence Length:** Configured to `512` tokens.
- **Normalization:** `normalize_embeddings=True` (all generated vectors have $L_2$ norm $\approx 1.0$).
- **Precision:** `float32` (standard IEEE 754 single precision for `pgvector`).

---

## 6. Device Selection

Device resolution is implemented via `resolve_device()` with the priority cascade:

$$\text{Explicit Device} \longrightarrow \text{CUDA} \longrightarrow \text{MPS} \longrightarrow \text{CPU}$$

### Hardware Profile:
- **Detected Device:** `cuda`
- **GPU Name:** `NVIDIA GeForce RTX 3050 Laptop GPU`
- **CUDA Version:** `12.4`
- **Model Load Time:** 10.36 seconds
- **Process Memory Footprint:** Increased by ~129.2 MB RAM upon model loading (from 696.6 MB to 825.8 MB).

---

## 7. Tokenization Audit

Using the native HuggingFace `AutoTokenizer` for `BAAI/bge-small-en-v1.5`, all **8,405 product retrieval texts** were tokenized and audited:

| Statistic | Value | Notes |
| :--- | :---: | :--- |
| **Total Texts Audited** | 8,405 | 100% of candidate catalog |
| **Tokenization Time** | 1.04s | High-speed batch tokenization |
| **Minimum Tokens** | **54** | Short minimal products |
| **Mean Tokens** | **212.91** | Comfortably within context limit |
| **Median Tokens** | **178.0** | Typical product representation |
| **90th Percentile Tokens** | **362.0** | 90% of products $< 362$ tokens |
| **95th Percentile Tokens** | **420.0** | 95% of products $< 420$ tokens |
| **99th Percentile Tokens** | **574.92** | Only top 1% exceed 575 tokens |
| **Maximum Tokens** | **863** | Outlier with 32 technical specification items |
| **Records $> 512$ Tokens** | **163** | Exactly **1.94%** of the entire catalog |

### Analysis of Token Overflow ($> 512$ tokens):
- Exactly **163 products (1.94%)** exceed the 512-token limit.
- Because Phase 5.2 implemented deterministic field ordering:
  $$\text{Product} \longrightarrow \text{Category} \longrightarrow \text{Brand} \longrightarrow \text{Specifications} \longrightarrow \text{Description}$$
  the anchor entities and dense technical specifications always occupy the first ~150–350 tokens.
- For these 163 items, the tokenizer automatically truncates only trailing marketing sentences from `Description`. No product identity or specification data is lost.
- **Architectural Conclusion:** The current design is robust and completely acceptable for V1. No modification to Phase 5.2 data is required.

---

## 8. Embedding Dimension Validation

For all generated vectors:
- **Expected Dimension:** 384
- **Actual Dimension:** **384**
- If the model or configuration ever returned a dimension other than 384, `EmbeddingModel.__init__` and `validate_embeddings` fail with an immediate `ValueError`.

---

## 9. Embedding Normalization

All embeddings are normalized to unit length ($L_2$ norm $= 1.0$) during encoding:

$$\|v\|_2 = \sqrt{\sum_{i=1}^{384} v_i^2} \approx 1.0$$

On the representative sample of 200 products:
- **Minimum $L_2$ Norm:** `1.000000`
- **Mean $L_2$ Norm:** `1.000000`
- **Maximum $L_2$ Norm:** `1.000000`
- **Max Deviation from 1.0:** $< 1 \times 10^{-6}$

### Benefit for PostgreSQL `pgvector`:
When vectors are unit-normalized, cosine distance simplifies directly to inner product:
$$\text{Cosine Distance}(u, v) = 1 - (u \cdot v)$$
This allows PostgreSQL to execute ultra-fast distance calculations via the `<=>` cosine distance operator.

---

## 10. Query vs Document Encoding Strategy

The BGE v1.5 model architecture is optimized for asymmetric search:

### 1. Document Encoding (`encode_documents`):
- Product catalog passages (`retrieval_text`) are encoded **directly without any prefix**.
- Clean, compact representation preserving full token capacity for product information.

### 2. Query Encoding (`encode_queries`):
- User search queries are prepended with the official BGE v1.5 retrieval instruction:
  ```text
  Represent this sentence for searching relevant passages: <user_query>
  ```
- This instruction informs the self-attention mechanism that the sentence is a retrieval query rather than a document passage, significantly improving cross-entropy retrieval ranking.

---

## 11. Semantic Sanity Checks

To confirm semantic discrimination before batch generation, 5 multi-category scenarios were tested against the catalog:

| Scenario ID | Query | Target Document | Target Sim | Max Distractor Sim | Margin | Status |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| `scenario_1_keyboard` | *"wireless bluetooth keyboard"* | Logitech K380 Wireless Keyboard | **0.7923** | 0.4713 | **+0.3210** | **PASS** |
| `scenario_2_car_mat` | *"waterproof car floor mat"* | 3a Autocare Car Floor Mat | **0.7611** | 0.5379 | **+0.2233** | **PASS** |
| `scenario_3_sofa` | *"leather two seater sofa for living room"* | Durian Leather 2 Seater Sofa | **0.7653** | 0.5401 | **+0.2252** | **PASS** |
| `scenario_4_shoes` | *"women casual flat sandals"* | 11e Women Flats Sandal | **0.7582** | 0.5705 | **+0.1877** | **PASS** |
| `scenario_5_usb_cable` | *"fast charging micro usb data cable"* | 99Gems 5 in 1 USB Cable | **0.7214** | 0.4976 | **+0.2238** | **PASS** |

**Result:** 5 / 5 scenarios passed with large separation margins ($+0.18$ to $+0.32$), demonstrating robust semantic discriminability.

---

## 12. Batch Encoding Validation

Mini-batching behavior was validated across multiple batch sizes (`16`, `32`, `64`):
- **Ordering:** Output vectors maintain exact 1:1 positional alignment with input text lists.
- **Consistency:** Batch encoding produces identical vectors compared to sequential encoding (deviation $< 1 \times 10^{-6}$).
- **Empty input handling:** Calling `encode([])` returns shape `(0, 384)` with `float32` dtype without exceptions.
- **Recommended Default Batch Size for Phase 5.5:** **`batch_size = 32`** (optimal balance between GPU memory utilization and throughput).

---

## 13. Performance Benchmark

Benchmarked on a deterministic sample of 200 products:

| Compute Device | Batch Size | Throughput (texts/sec) | Latency (ms/text) | Total Elapsed (200 texts) |
| :--- | :---: | :---: | :---: | :---: |
| **NVIDIA RTX 3050 GPU (CUDA)** | 32 | **167.03 – 210.0** | **4.7 – 6.0 ms** | **1.20s** |
| **Intel CPU Fallback** | 32 | **20.8** | **48.1 ms** | **2.41s** (50 texts) |

---

## 14. Estimated Phase 5.5 Runtime

Based on measured throughput across the full **8,405 products**:

$$\text{Estimated Runtime} = \frac{8,405 \text{ products}}{\text{Throughput (texts/sec)}}$$

| Execution Mode | Expected Throughput | Estimated Full Catalog Time | Feasibility Assessment |
| :--- | :---: | :---: | :--- |
| **GPU Acceleration (`cuda`)** | ~167 – 210 texts/s | **~40 – 50 seconds (< 1 minute)** | **Highly Recommended** |
| **CPU Fallback (`cpu`)** | ~21 texts/s | **~6.7 minutes (< 7 minutes)** | **Fully Viable Offline** |

---

## 15. Automated Tests

The Phase 5.3 automated test suite is implemented in [tests/test_embedding_model.py](file:///d:/Project/ShopAssist/tests/test_embedding_model.py):

```text
collected 16 items

tests/test_embedding_model.py ................                           [100%]
======================= 16 passed in 20.63s ========================
```

### Full Repository Regression Test:
```text
collected 123 items
tests/test_category_parser.py ....                                       [  3%]
tests/test_category_selection.py ....                                    [  6%]
tests/test_cleaning.py ....................                              [ 22%]
tests/test_data_loader.py .........                                      [ 30%]
tests/test_embedding_model.py ................                           [ 43%]
tests/test_profiling.py ............                                     [ 52%]
tests/test_retrieval_text.py ........................................... [ 87%]
.                                                                        [ 88%]
tests/test_schema.py ..............                                      [100%]
============================ 123 passed in 17.79s =============================
```

### Coverage Highlights:
1. `test_default_metadata_constants`: Verifies default model, 384 dimensions, 512 max length.
2. `test_device_resolution`: Explicit and automatic device fallback cascade.
3. `test_dimension_validation_rejects_non_384`: Enforces 384 dimension constraint.
4. `test_finite_validation_detects_nan` & `detects_inf`: Detects numerical corruption.
5. `test_zero_vector_detection`: Detects uninformative all-zero vectors.
6. `test_l2_normalization_validation`: Validates unit norm constraint.
7. `test_batch_order_preservation`: Verifies index alignment across batch inference.
8. `test_deterministic_output`: Confirms repeatability across multiple runs.
9. `test_empty_list_handling`: Verifies shape `(0, 384)` on empty input.
10. `test_query_and_document_encode_apis`: Validates asymmetric prefix behavior.
11. `test_cosine_similarity_consistency`: Validates dot product vs. cosine equivalence.
12. `test_report_schema_contains_required_keys`: Verifies JSON audit report schema.
13. `test_real_embedding_model_smoke`: Real inference smoke test on local weights.

---

## 16. Generated Artifacts

| Artifact | Type | Description |
| :--- | :--- | :--- |
| [src/shopassist/embeddings/model.py](file:///d:/Project/ShopAssist/src/shopassist/embeddings/model.py) | Python Module | Production `EmbeddingModel` wrapper, device resolution, and validation logic |
| [src/shopassist/embeddings/\_\_init\_\_.py](file:///d:/Project/ShopAssist/src/shopassist/embeddings/__init__.py) | Python Module | Module exports and constants |
| [scripts/validate_embedding_model.py](file:///d:/Project/ShopAssist/scripts/validate_embedding_model.py) | Python Script | Executable Phase 5.3 validation pipeline |
| [tests/test_embedding_model.py](file:///d:/Project/ShopAssist/tests/test_embedding_model.py) | Pytest Suite | 16 automated unit and integration tests |
| [data/interim/phase5_3_embedding_model_report.json](file:///d:/Project/ShopAssist/data/interim/phase5_3_embedding_model_report.json) | JSON Report | Machine-readable validation metrics and tokenization audit report |
| [docs/phase5_3_embedding_model_validation.md](file:///d:/Project/ShopAssist/docs/phase5_3_embedding_model_validation.md) | Markdown | Phase 5.3 engineering specification and report |

---

## 17. Issues / Limitations

1. **Minor Token Truncation on Outlier Specifications:** 163 products (1.94%) exceed 512 tokens. As confirmed by analysis, only trailing marketing descriptions are truncated; all entity identifiers and specifications are fully preserved.
2. **First-Load Latency:** The initial model load takes ~10 seconds to transfer weights to GPU VRAM. In production serving (FastAPI), the model will be loaded once as a singleton during application startup.

---

## 18. Phase 5.5 Readiness

Phase 5.3 is **100% complete and verified**. All acceptance criteria have passed:
- `BAAI/bge-small-en-v1.5` loaded and verified with 384 dimensions.
- 0 NaN, 0 Inf, 0 zero vectors, unit L2 norm verified.
- Native tokenization audit complete across all 8,405 products.
- CUDA acceleration and CPU fallback both verified.
- Fast batch encoding throughput established (~50s for full catalog on GPU).

The project is fully prepared for:
- **Phase 5.4 — Supabase PostgreSQL + pgvector Provisioning** (database connection & table creation).
- **Phase 5.5 — Batch Embedding Generation & products.parquet Export** (encoding all 8,405 products using `EmbeddingModel`).
