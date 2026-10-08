# ShopAssist — Conversational Product Recommendation System

ShopAssist is an end-to-end conversational product recommendation system using LLM-based query understanding, structured filtering, and hybrid retrieval to recommend consumer products based on both explicit constraints and semantic user preferences.

---

## 1. Dataset

- **Primary Dataset**: Flipkart Products 20K (canonical e-commerce product catalog with ~20,000 items).
- **Expected Local Path**: `data/raw/flipkart_products.csv`
- **Acquisition Script**:
  ```bash
  python scripts/download_dataset.py
  ```

---

## 2. Directory Structure

```text
ShopAssist/
├── data/
│   ├── raw/                  # Raw immutable dataset (flipkart_products.csv)
│   ├── interim/              # EDA reports, intermediate candidates (Phase 2-4)
│   └── processed/            # Final clean products (products.parquet)
├── docs/
│   └── proposal.md           # Project Proposal (Single Source of Truth)
├── scripts/
│   ├── download_dataset.py   # Download raw Flipkart dataset
│   └── inspect_dataset.py    # Raw dataset inspection CLI
├── src/
│   └── shopassist/
│       ├── core/             # Configuration and path resolution
│       └── data/             # Data loading and validation modules
└── tests/
    └── test_data_loader.py   # Unit tests for data loading and schema validation
```

---

## 3. How to Inspect & Profile Dataset

To verify file integrity and inspect the raw schema:

```bash
python scripts/inspect_dataset.py
```

To run Phase 2 Dataset Profiling & EDA:

```bash
python scripts/run_eda.py
```

To run Phase 3 Category Selection:

```bash
python scripts/select_categories.py
```

Generated Phase 3 artifacts:
- `data/interim/selected_categories.json`
- `data/interim/selected_category_candidates.parquet`
- `docs/phase3_category_selection.md`

To run Phase 4 Dataset Cleaning:

```bash
python scripts/clean_dataset.py
```

Generated Phase 4 artifacts:
- `data/interim/cleaned_candidates.parquet`
- `data/interim/cleaning_report.json`
- `docs/phase4_cleaning_report.md`

---

## 4. Running Tests

```bash
python -m pytest
```

---

## 5. Development Status

- **Phase 1 — Dataset Acquisition** (Completed)
  - Raw Flipkart Products 20K dataset acquired and verified.
- **Phase 2 — Dataset Profiling / EDA** (Completed)
  - Comprehensive profiling of missing values, duplicates, price, rating, brand, description, specifications, and category distribution.
- **Phase 3 — Category Selection** (Completed)
  - 16 diverse Level 1 categories selected (8,683 candidate products, target: 5,000 – 15,000).
  - Outlier/dominating categories rejected (`Clothing`, `Jewellery`).
  - Candidate subset extracted to `data/interim/selected_category_candidates.parquet` with raw values preserved.
- **Phase 4 — Dataset Cleaning** (Completed)
  - Required fields validated and missing price records excluded.
  - Ratings normalized (1.0–5.0 float or null).
  - Brand casing canonicalized (63 variations fixed).
  - Product specifications safely parsed via regex without `eval()` into JSON format.
  - Conservative deduplication performed: redundant duplicates removed while 1,913 product variants preserved.
  - Cleaned dataset exported: 8,405 products (3.2% loss, well within < 15% threshold).
- **Phase 5.1 — Product Knowledge Base Data Model & Schema Specification** (Completed)
  - Production database architecture finalized: Supabase Cloud managed PostgreSQL + pgvector.
  - Single-table `products` schema designed with `product_specifications JSONB`, `embedding vector(384)`, constraints, and `updated_at` trigger.
  - SQL migration created: `database/migrations/001_create_product_knowledge_base.sql`.
  - Pydantic schema contract defined in `src/shopassist/data/schema.py`.
  - 8,405 cleaned candidate products validated with 100% pass rate (`data/interim/phase5_schema_readiness.json`).
  - Architecture documentation created: `docs/phase5_1_product_data_model.md`.
- **Phase 5.2 — retrieval_text Construction & Validation** (Completed)
  - Standardized semantic `retrieval_text` built for all 8,405 products with deterministic field ordering (`Product` -> `Category` -> `Brand` -> `Specifications` -> `Description`).
  - Robust specification flattening with placeholder filtering (`NA`, `N/A`, `None`, `null`) and whitespace normalization.
  - Safe description truncation at word boundaries (max ~1,200 chars) ensuring compatibility with `BAAI/bge-small-en-v1.5` context window.
  - Numerical hard constraints (`discounted_price`, `retail_price`, `rating`) strictly excluded from semantic text.
  - 100% valid retrieval_text rows verified (8,405 / 8,405) with 0 invalid emissions.
  - Intermediate dataset exported: `data/interim/products_with_retrieval_text.parquet`.
  - Quality audit report generated: `data/interim/phase5_2_retrieval_text_report.json`.
  - Technical documentation completed: `docs/phase5_2_retrieval_text.md`.
- **Phase 5.3 — Embedding Model Setup & Validation** (Completed)
  - `BAAI/bge-small-en-v1.5` loaded and validated with exact 384-dimensional dense vectors and unit $L_2$ normalization.
  - Native tokenization audit performed across all 8,405 products (mean: 212.9 tokens, only 1.94% $> 512$ tokens with entity/spec preservation).
  - Numerical integrity verified on 200 representative products: 0 NaN, 0 Inf, 0 zero vectors.
  - 5 multi-category semantic sanity retrieval scenarios passed (100% success).
  - Batch performance benchmarked on NVIDIA RTX 3050 GPU (167–210 texts/s, ~50s for full catalog) and CPU fallback (~6.7 mins).
  - Reusable `EmbeddingModel` module created in `src/shopassist/embeddings/`.
  - Machine-readable audit report generated: `data/interim/phase5_3_embedding_model_report.json`.
  - Engineering documentation created: `docs/phase5_3_embedding_model_validation.md`.
- **Phase 5.4 — Supabase PostgreSQL + pgvector Provisioning** (Completed)
  - Supabase Session Pooler connectivity verified (port 5432, SSL enabled, masked credentials).
  - pgvector extension enabled and validated (`vector v0.8.2`).
  - Base `products` schema provisioned (17 columns, `product_id` primary key, `product_specifications JSONB`).
  - `vector(384)` schema type and dimension verified via PostgreSQL catalog.
  - 6 integrity CHECK constraints and automatic `updated_at` trigger verified.
  - Transactional smoke test passed with negative constraint checks, temporary vector inserts, `<=>` cosine distance ranking, and clean rollback (0 residual test records).
  - Production B-Tree and HNSW indexes cleanly separated in `database/migrations/002_create_product_indexes.sql` and deferred to Phase 5.7.
  - Machine-readable audit report generated: `data/interim/phase5_4_database_provisioning_report.json`.
  - Engineering documentation created: `docs/phase5_4_supabase_provisioning.md`.
- **Next Phase**: **Phase 5.5 — Batch Embedding Generation & products.parquet Export**

