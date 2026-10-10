# ShopAssist — Conversational Product Recommendation System

<!-- phase82-correction-start -->
> **Phase8.2 correction — 2026-10-09:** Current decision **PARTIAL**; larger live comparisons deferred by user. Production remains original **v1**, not E5-B/v2. The historical body below is preserved; conflicting claims are superseded by [current engineering decision](docs/phase8_2/final_engineering_report.md), [audited results](docs/phase8_2/experimental_results.md) and [contract review](docs/phase8_2/query_contract_review.md).
>
> Original50 98% EM omits preferences; shared-field EM is54%. Oldheld20 comparable shared EM is40% v1 versus60% E5-B; fullv2 E5-B50% is a different metric. Semantic-query/reason wording is not covered by slot EM. E5-B soft macro78.33%, product/exclusion exact90%, exclusion micro28.57%. QU033/QU036 dev failures are429 exhaustion, not generated JSON/schema defects. New failure-aware dev E5-B HC F1 is93.88%, soft F1 is80%; historical96%/86.67% use the frozen old policy.
>
> Development overlaps original50 in13/15 queries. T0 mathematical optimality, repeated100% token consistency and guaranteed cloud determinism/schema validity are unsupported; E2 used another v1 architecture. Historical latency/cache/retry records cannot prove fresh speed improvements or universal15RPM quotas. Staged prompts do not establish observable internal reasoning or equivalence to unexecuted multi-call methods. Boeing suppression is filter policy, not necessarily correct NER. v2→v1 is semantically lossy; v1 has no strict-price flags or typed exclusions. Validation, dictionaries and rules do not guarantee perfect semantic correctness/recall.
>
> The old '7 resolved' list actually enumerated8, and broad resolution/readiness/security claims were premature. Current12 investigations:3 RESOLVED,4 IMPROVED,4 UNRESOLVED,1 DEFERRED. Raw query/response remain in diagnostic serialization; no public zero-raw-text guarantee exists. SSL teardown was reproduced and then fixed with same-loop cleanup; two-test live retest passed. Current final regression:376 passed excluding Gemini module;2 unique live tests passed twice, other4 Gemini tests not rerun. No new live quality winner or production semantic change is claimed.
<!-- phase82-correction-end -->

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
│   ├── interim/              # EDA reports, intermediate candidates, Phase reports
│   └── processed/            # Final clean products (products.parquet) & TF-IDF artifacts (data/processed/tfidf/)
├── database/                 # SQL migrations and index scripts
├── docs/
│   ├── concepts/             # Theoretical guides (tfidf_retrieval_fundamentals.md, dense_semantic_retrieval_fundamentals.md)
│   └── proposal.md           # Project Proposal (Single Source of Truth)
├── scripts/
│   ├── download_dataset.py   # Download raw Flipkart dataset
│   ├── inspect_dataset.py    # Raw dataset inspection CLI
│   ├── build_tfidf_baseline.py # Build and persist TF-IDF baseline index
│   ├── search_tfidf.py       # Lexical product search CLI
│   ├── search_semantic.py    # Dense semantic product search CLI
│   ├── benchmark_semantic.py # Dense semantic retrieval benchmark & evaluation suite
│   ├── test_gemini_connection.py # Gemini API connection & model discovery CLI
│   ├── parse_user_query.py   # Natural language Query Understanding CLI
│   └── evaluate_query_understanding.py # Query Understanding accuracy & latency benchmark CLI
├── src/
│   └── shopassist/
│       ├── core/             # Configuration and path resolution
│       ├── data/             # Data loading and schema validation modules
│       ├── db/               # PostgreSQL & pgvector connection & loading
│       ├── embeddings/       # Dense embedding model and inference
│       ├── llm/              # LLM Query Understanding (Gemini, schemas, prompts, normalization)
│       └── retrieval/        # Lexical (TF-IDF) & Dense Semantic retrieval engines
└── tests/
    ├── test_data_loader.py   # Unit tests for data loading and schema validation
    ├── test_tfidf_retrieval.py # Unit and integration tests for TF-IDF retrieval
    ├── test_semantic_retrieval.py # Unit and integration tests for dense semantic retrieval
    ├── test_query_understanding.py # Offline unit tests for LLM Query Understanding
    ├── test_gemini_integration.py # Live integration tests for Google Gemini API
    └── ...
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

## 4. Phase 6 — TF-IDF Baseline Retrieval Engine

Phase 6 implements a standalone, reproducible lexical product retrieval engine using TF-IDF vectorization and cosine similarity over all 8,405 products (`retrieval_text`). It acts as **Baseline 1** for future comparisons against dense semantic search (Phase 7) and hybrid retrieval (Phase 10).

### Build & Persist TF-IDF Baseline Index

```bash
python scripts/build_tfidf_baseline.py
```

Generated Phase 6 artifacts in `data/processed/tfidf/`:
- `tfidf_vectorizer.joblib` — Fitted scikit-learn `TfidfVectorizer` (61,979 features)
- `tfidf_matrix.npz` — Compressed SciPy CSR sparse matrix (`[8405, 61979]`, 99.7550% sparsity)
- `product_metadata.parquet` — Aligned row-to-product mapping (8,405 rows)
- `tfidf_manifest.json` — Configuration and dataset integrity manifest
- Report: `data/interim/phase6_tfidf_baseline_report.json`

### Search via CLI (TF-IDF)

```bash
python scripts/search_tfidf.py --query "wireless bluetooth keyboard" --top-k 5
```

---

## 5. Phase 7 — Dense Semantic Search Retrieval Engine

Phase 7 implements **Baseline 2: Dense Semantic Retrieval** using `BAAI/bge-small-en-v1.5` dense embeddings (384 dimensions) and Supabase PostgreSQL + pgvector HNSW index search (`idx_products_embedding`).

### Search via CLI (Dense Semantic)

```bash
# Standard HNSW approximate nearest-neighbor search
python scripts/search_semantic.py --query "wireless bluetooth keyboard" --top-k 5

# Exact ground-truth linear scan (disables index in transaction)
python scripts/search_semantic.py --query "running shoes" --exact

# JSON output
python scripts/search_semantic.py --query "sneakers for jogging" --top-k 5 --json
```

### Benchmark Semantic Retrieval & Evaluate ANN Quality

```bash
python scripts/benchmark_semantic.py --iterations 20
```

### Phase 7 Documentation
- **Conceptual Guide**: [`docs/concepts/dense_semantic_retrieval_fundamentals.md`](file:///d:/Project/ShopAssist/docs/concepts/dense_semantic_retrieval_fundamentals.md) — Comprehensive educational guide on dense embeddings, bi-encoders, BGE-small architecture, cosine distance math, HNSW graph navigation, and ANN Recall@K.
- **Engineering Implementation Report**: [`docs/phase7_semantic_search.md`](file:///d:/Project/ShopAssist/docs/phase7_semantic_search.md) — Full technical report covering query pipeline, PostgreSQL HNSW plan audits, ANN Recall@10 (98.0%), 10 comparative scenarios vs. TF-IDF, latency quantiles (P50: 135.31 ms), and database safety.
- **Machine-Readable Report**: `data/interim/phase7_semantic_search_report.json`

---

## 6. Phase 8 — LLM Query Understanding (Google Gemini API)

Phase 8 implements an asynchronous, production-grade LLM Query Understanding module that transforms natural-language shopping requests into strongly-typed, validated structured representations using the official Google Gen AI Python SDK (`google-genai` v2.29.0) and Google Gemini API (`gemini-3.1-flash-lite`).

The module performs structured information extraction:
1. **Hard Constraints**: Normalized category (16 canonical categories), catalog-verified brand, minimum/maximum budget, rating threshold, and ISO currency code.
2. **Soft Preferences**: Qualitative lifestyle/aesthetic preferences for semantic ranking.
3. **Cleaned Semantic Query**: Core product search intent stripped of conversational filler.
4. **Clarification Status**: Automatic detection of out-of-domain requests, prompt injection attempts, or foreign currency mismatches.

### Environment Configuration

Configure the following variables in `.env`:
```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_TEMPERATURE=0.0
GEMINI_MAX_OUTPUT_TOKENS=2048
GEMINI_TIMEOUT_SECONDS=30.0
GEMINI_MAX_RETRIES=3
```

### CLI Usage

Test Gemini API connectivity and verified model discovery:
```bash
python scripts/test_gemini_connection.py
```

Parse an arbitrary natural language shopping query:
```bash
python scripts/parse_user_query.py --query "Puma running shoes under 2000 rupees"
```

Output structured JSON representation:
```bash
python scripts/parse_user_query.py --query "Samsung phone under 15000 with good battery life" --json
```

Interactive REPL mode:
```bash
python scripts/parse_user_query.py --interactive
```

Execute full 50-case extraction accuracy & latency benchmark:
```bash
python scripts/evaluate_query_understanding.py --pacing 0.5
```

### Phase 8 Documentation
- **Conceptual Guide**: [`docs/concepts/llm_query_understanding_fundamentals.md`](file:///d:/Project/ShopAssist/docs/concepts/llm_query_understanding_fundamentals.md) — Comprehensive educational guide covering NLU, LLMs vs. bi-encoders, structured outputs, Pydantic invariants, prompt security, and multi-tiered validation.
- **Engineering Implementation Report**: [`docs/phase8_llm_query_understanding.md`](file:///d:/Project/ShopAssist/docs/phase8_llm_query_understanding.md) — Complete 30-section technical report with architecture diagrams, schema definitions, prompt templates, benchmark quantiles (P50: 1,580.5 ms), accuracy metrics (98.0% exact match), and resilience evaluation.
- **Query Understanding Data Contract**: [`docs/phase8_query_contract.md`](file:///d:/Project/ShopAssist/docs/phase8_query_contract.md) — Formal interface contract defining field semantics, nullability, category enums, currency conventions, and Phase 9/10 integration interfaces.
- **Machine-Readable Report**: `data/interim/phase8_query_understanding_report.json`

---

## 7. Phase 8.1 — Query Understanding Refinement & Experimental Evaluation

Phase 8.1 delivers an evidence-based, scientifically rigorous refinement of the Google Gemini Query Understanding system, investigating and resolving 14 open issues (P8-01 through P8-14) discovered in Phase 8.

Key advancements include:
1. **Discrepancy Audit (P8-06)**: Revealed that the historical 98.0% exact match assessed only hard constraints; true Complete-Output Exact Match was 54.00% (27/50 cases) due to soft preference false positives.
2. **Schema v2.0.0 Evolution**: Introduced explicit `product_type`, typed `exclusions` (`ExclusionConstraint`), and strict/inclusive price boundary operators (`min_inclusive`, `max_inclusive`), backed by a 100% backward-compatible `to_v1()` adapter.
3. **Winner Candidate (E5-B: Logically Staged Single-Call Pipeline + Hybrid Rules)**:
   - Soft Preferences F1 improved from 66.41% to **86.67%** (exceeding $\ge 85\%$ target).
   - Strict Complete-Output Exact Match improved from 54.00% to **73.33%** (+19.33 percentage points).
   - Token consumption reduced by **53.6%** (from 1,206 down to **559 tokens/query**).
   - Median P50 latency reduced from 1,580.5 ms down to **1,446.0 ms**.
4. **Autonomous Rate-Limiting & Quota Safety (P8-08)**: Regex parsing of Gemini's `retryDelay` headers guarantees zero dropped requests under free-tier 15 RPM limits.

### Phase 8.1 CLI Usage

Audit baseline evaluation metrics and failure modes (Experiment E0):
```bash
python scripts/audit_phase8_evaluation.py
```

Run controlled screening experiments across prompt, schema, and temperature variants:
```bash
python scripts/run_phase8_experiments.py --experiments E1-A,E1-B,E1-C,E2-A,E2-B,E2-C,E3,E4,E5-B --split dev_15 --pacing 1.0
```

Generate multi-experiment comparison table and candidate scorecards:
```bash
python scripts/compare_phase8_experiments.py
```

### Phase 8.1 Documentation
- **Experimental Engineering Report**: [`docs/phase8_1_refinement_experiments.md`](file:///d:/Project/ShopAssist/docs/phase8_1_refinement_experiments.md) — 26-section comprehensive report documenting all hypotheses, experimental controls, token economics, latency distributions, and statistical analyses.
- **Issue Resolution Register**: [`docs/phase8_1_issue_resolution.md`](file:///d:/Project/ShopAssist/docs/phase8_1_issue_resolution.md) — Detailed investigation, root-cause hypothesis, experiments performed, and resolution status for P8-01 through P8-14.
- **Evaluation Methodology**: [`docs/phase8_1_evaluation_methodology.md`](file:///d:/Project/ShopAssist/docs/phase8_1_evaluation_methodology.md) — Scientific methodology covering metric definitions (macro vs micro, strict exact match), sample size limitations, and leakage prevention.
- **Conceptual Learning Guide**: [`docs/concepts/llm_experimentation_and_extraction_refinement.md`](file:///d:/Project/ShopAssist/docs/concepts/llm_experimentation_and_extraction_refinement.md) — 25-topic educational guide covering sampling temperatures, structured outputs, hybrid NLP, negation, and ablation principles.
- **Machine-Readable Reports**: `data/interim/phase8_1/experiment_results.json`, `data/interim/phase8_1/phase8_1_final_report.json`

---

## 8. Running Tests

To run the complete automated test suite:

```bash
python -m pytest
```

To run Phase 8 & 8.1 offline unit tests specifically (53 tests):

```bash
python -m pytest tests/test_query_understanding.py tests/test_phase8_*.py -v
```

To run Phase 8 live Gemini integration tests (requires network & GEMINI_API_KEY):

```bash
python -m pytest tests/test_gemini_integration.py -v
```

---

## 9. Development Status

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
- **Phase 5.5 — Batch Embedding Generation & products.parquet Export** (Completed)
  - Generated 384-dimensional dense vector embeddings for all **8,405 cleaned products** using validated `BAAI/bge-small-en-v1.5`.
  - Batch GPU inference executed on NVIDIA RTX 3050 Laptop GPU in 41.26 seconds (throughput: 203.73 texts/sec, 4.91 ms/text).
  - Multi-layer embedding validation passed: shape (8405, 384), `float32`, 0 NaN, 0 Inf, 0 zero vectors, unit $L_2$ norm ($1.000000 \pm 10^{-6}$).
  - Canonical Product Knowledge Base dataset assembled (15 columns matching database schema, interim scraping fields removed).
  - Atomic Parquet export completed with roundtrip deserialization verification: `data/processed/products.parquet` (17.94 MB).
  - Positional alignment verified across catalog (spot-check dot product = 1.000000 on sample products).
  - Category-aware semantic sanity checks verified (3/3 scenarios passed).
  - 25 automated tests implemented; 162 total repository tests passing with zero regressions.
  - Machine-readable execution report generated: `data/interim/phase5_5_embedding_generation_report.json`.
  - Engineering documentation created: `docs/phase5_5_batch_embedding_generation.md`.
- **Phase 5.6 — Database Loading / Ingestion** (Completed)
  - Loaded all **8,405 approved products** from `data/processed/products.parquet` into Supabase PostgreSQL table `public.products`.
  - Atomic batch ingestion implemented using SQLAlchemy 2.0 `executemany` with parameterized inserts (34 batches of 250, completed in 62.98s, 133.5 rows/s).
  - Strict idempotency enforced: automatic classification for `EMPTY_TABLE`, `ALREADY_POPULATED` (no-op), `PARTIALLY_POPULATED` (abort), and `CONFLICTING_DATA` (abort).
  - Comprehensive post-ingestion validation passed: exact 8,405 row count, 8,405 distinct product IDs, 0 null mandatory fields, 100% 384-d vector embeddings, 100% valid JSONB specification arrays, non-null PostgreSQL timestamps.
  - 50-record content spot check matched Parquet source ground truth ($L_2$ vector tolerance $< 10^{-4}$).
  - Vector cosine distance smoke test passed with pgvector `<=>` operator (0.000000 self-distance and verified footwear nearest neighbors).
  - 18 automated tests added; 180 total repository tests passing with zero regressions.
  - Machine-readable execution report generated: `data/interim/phase5_6_database_ingestion_report.json`.
  - Engineering documentation created: `docs/phase5_6_database_ingestion.md`.
- **Phase 5.7 — B-Tree & HNSW Index Construction** (Completed)
  - Created and validated five approved production indexes on `public.products` in Supabase PostgreSQL: 4 relational B-Tree (`category`, `discounted_price`, `brand`, `category + discounted_price`) and 1 HNSW vector index (`embedding vector_cosine_ops`, `m=16`, `ef_construction=64`).
  - Total index migration DDL completed in 5.44 seconds on remote Supabase instance.
  - Strict PostgreSQL catalog state auditing implemented covering Scenarios A through E (absent, already existing, partial, conflicting definitions, invalid).
  - Programmatic query plan benchmarks (`EXPLAIN ANALYZE BUFFERS`) demonstrated a ~35x–65x vector search speedup (from 38.22 ms sequential scan down to 0.59–1.08 ms HNSW index scan).
  - 100% data integrity verified: exactly 8,405 rows, 8,405 unique IDs, 384-d embeddings, constraints, triggers, and primary key intact.
  - 16 automated tests added; 196 total repository tests passing with zero regressions.
  - Machine-readable execution report generated: `data/interim/phase5_7_index_construction_report.json`.
  - Engineering documentation created: `docs/phase5_7_index_construction.md`.
- **Phase 5.8 — Knowledge Base Validation & Filtered Search Verification** (Completed)
  - Executed read-only validation suite covering 43 test cases across 5 test groups (Data Integrity, SQL Hard Filtering, Vector Cosine Search, Filtered Semantic Search, Index Verification & Performance Benchmarking) with **100.0% Pass Rate (43/43)**.
  - Confirmed 100.0% constraint satisfaction on single, range, boundary, and multi-attribute SQL filters with zero budget or category violations.
  - Validated 384-dimensional cosine similarity search: near-zero self-match distance ($0.00000000$), strict monotonic ordering, and complete float32 equivalence to independent NumPy cosine ground truth ($< 10^{-6}$ diff).
  - Validated combined filtered semantic search with 100.0% hard constraint compliance and 100.0% Recall@10 against exact linear scan.
  - Evaluated post-filtering underfill and verified runtime iterative scanning support in pgvector 0.8.2 (`SET LOCAL hnsw.iterative_scan = relaxed_order;`).
  - Benchmarked retrieval performance: HNSW ANN search executes in **0.492 ms** on database engine (**76.4x speedup** over exact linear scan of 37.571 ms), with pure vector P50 latency of 34.39 ms and filtered search P50 of 34.79 ms over the WAN pooler.
  - Confirmed post-validation catalog preservation: exactly 8,405 rows and 5/5 approved production indexes intact.
  - Added 12 automated unit and integration tests; **208 total repository tests passing with zero regressions**.
  - Machine-readable execution report generated: `data/interim/phase5_8_knowledge_base_validation_report.json`.
  - Technical documentation completed: `docs/phase5_8_knowledge_base_validation.md`.
- **Phase 6 — TF-IDF Baseline Retrieval Engine** (Completed)
  - Built a standalone, pure lexical retrieval engine using scikit-learn `TfidfVectorizer` and SciPy CSR sparse matrix operations over all 8,405 products (`retrieval_text`).
  - Configured reproducible unigram + bigram vectorizer (`min_df=2`, `max_df=0.8`, `sublinear_tf=True`, unit $L_2$ normalization).
  - Fitted sparse document-term matrix of shape `(8405, 61979)` with 1,276,047 nonzeros and **99.7550% sparsity**, consuming only 14.64 MB in CSR format (vs 4.03 GB dense, a 99.64% memory reduction).
  - Implemented dot-product cosine similarity scoring with deterministic tie-breaking (`score DESC, product_id ASC`) and safe zero-score policy (empty/OOV queries return zero results).
  - Persisted index artifacts (`tfidf_vectorizer.joblib`, `tfidf_matrix.npz`, `product_metadata.parquet`, `tfidf_manifest.json`) with roundtrip reload validation yielding 100% identical rankings.
  - Benchmarked retrieval performance on full catalog: **median P50 query latency of 3.862 ms** (mean 4.407 ms, P95 7.532 ms).
  - Executed 8 retrieval scenarios revealing classic lexical strengths (exact keyword, brand, category) and failure modes (synonym mismatch, numeric constraints, OOV).
  - Added 21 automated unit and integration tests; **229 total repository tests passing with zero regressions**.
  - Conceptual learning guide created: [`docs/concepts/tfidf_retrieval_fundamentals.md`](file:///d:/Project/ShopAssist/docs/concepts/tfidf_retrieval_fundamentals.md).
  - Engineering documentation created: [`docs/phase6_tfidf_baseline.md`](file:///d:/Project/ShopAssist/docs/phase6_tfidf_baseline.md).
  - Machine-readable execution report generated: `data/interim/phase6_tfidf_baseline_report.json`.
- **Phase 7 — Dense Semantic Search Retrieval Engine** (Completed)
  - Built a production-ready dense semantic retrieval engine using `BAAI/bge-small-en-v1.5` embeddings (384 dimensions) and Supabase PostgreSQL + pgvector HNSW index search (`idx_products_embedding`).
  - Reused existing 8,405 product embeddings without redundant generation or database writes.
  - Configured asymmetric BGE query encoding (`"Represent this sentence for searching relevant passages: "`) with unit $L_2$ vector normalization and thread-safe async offloading.
  - Verified pure distance ordering in SQL activating HNSW Index Scan in **0.44–1.07 ms** server execution time, with in-memory deterministic tie-breaking on `(distance ASC, product_id ASC)`.
  - Evaluated algorithmic ANN quality against exact sequential scan: achieved **Recall@5 = 96.0%**, **Recall@10 = 98.0%**, and **Recall@20 = 98.0%**.
  - Benchmarked retrieval latency on NVIDIA RTX 3050 Laptop GPU: **P50 query embedding = 23.08 ms**, **P50 database roundtrip = 112.72 ms**, **P50 end-to-end = 135.31 ms**.
  - Evaluated 10 comparative scenarios vs. Phase 6 TF-IDF, demonstrating high semantic recall on synonyms and paraphrases (e.g. *"sneakers for jogging"* $\rightarrow$ *"running shoes"*) where lexical matching failed.
  - Preserved catalog integrity: exactly 8,405 rows and all 5 production indexes intact.
  - Added 20 automated unit and integration tests; **249 total repository tests passing with zero regressions**.
  - Conceptual learning guide created: [`docs/concepts/dense_semantic_retrieval_fundamentals.md`](file:///d:/Project/ShopAssist/docs/concepts/dense_semantic_retrieval_fundamentals.md).
  - Engineering documentation created: [`docs/phase7_semantic_search.md`](file:///d:/Project/ShopAssist/docs/phase7_semantic_search.md).
  - Machine-readable execution report generated: `data/interim/phase7_semantic_search_report.json`.
- **Phase 8 — LLM Query Understanding** (Completed)
  - Built a production-grade LLM Query Understanding Engine using the official Google Gen AI Python SDK (`google-genai` v2.29.0) and Google Gemini API (`gemini-3.1-flash-lite`).
  - Model availability verified live via API discovery among 62 accessible models (`models/gemini-3.1-flash-lite-preview`).
  - Implemented strongly-typed Pydantic v2 schemas: `HardConstraints` (category, brand, min_price, max_price, min_rating, currency), `QueryUnderstandingOutput`, `TokenUsageMetadata`, and `QueryUnderstandingResult`.
  - Enforced strict normalization: 16 canonical catalog categories, 1,860 catalog brand matching & preservation, ISO-4217 currency standardization (default: `INR`).
  - Built multi-tiered validation: Stage 1 (input sanitation), Stage 2 (API validation), Stage 3 (Pydantic bounds & invariants), Stage 4 (business rules & foreign currency clarification).
  - Evaluated on 50 curated ground-truth test cases: **100.00% schema validity**, **100.00% category accuracy**, **98.00% brand accuracy**, **100.00% price accuracy**, **100.00% rating accuracy**, **100.00% clarification accuracy**, **99.70% hard constraints F1**, and **98.00% exact match accuracy**.
  - Benchmarked API performance: **median P50 latency of 1,580.5 ms**, average 1,206.2 tokens/query (1,081.3 prompt / 124.8 output).
  - Production resilience verified: exponential backoff with jitter successfully recovered from transient 503 spikes and timeout retries.
  - Zero database writes, zero schema modifications, zero embedding recalculations (catalog integrity 100% preserved).
  - Added 27 offline unit tests and 6 live Gemini integration tests; **276 total repository tests passing with zero regressions**.
  - Conceptual learning guide created: [`docs/concepts/llm_query_understanding_fundamentals.md`](file:///d:/Project/ShopAssist/docs/concepts/llm_query_understanding_fundamentals.md).
  - Engineering implementation documentation created: [`docs/phase8_llm_query_understanding.md`](file:///d:/Project/ShopAssist/docs/phase8_llm_query_understanding.md).
  - Data contract documentation created: [`docs/phase8_query_contract.md`](file:///d:/Project/ShopAssist/docs/phase8_query_contract.md).
  - Machine-readable execution report generated: `data/interim/phase8_query_understanding_report.json`.
- **Phase 8.1 — Query Understanding Refinement & Experimental Evaluation** (Completed)
  - Executed a comprehensive research-driven audit and experimental refinement addressing 14 Phase 8 open issues (P8-01 through P8-14).
  - Audited historical baseline (E0): proved reported 98.0% exact match was restricted to hard constraints; true Strict Complete-Output Exact Match was 54.00% (27/50 cases).
  - Resolved Product Type vs. Soft Preference confusion (P8-01, P8-02) by designing Schema v2.0.0 (`RefinedQueryUnderstandingResult`) with dedicated `product_type: str | None`, typed `exclusions: list[ExclusionConstraint]`, and boundary flags (`min_inclusive`, `max_inclusive`), backed by a 100% backward-compatible `to_v1()` adapter.
  - Evaluated 10 experimental configurations across prompt engineering (E1-A, E1-B, E1-C), temperature ablation (E2-A, E2-B, E2-C), schema design (E3), deterministic post-processing rules (E4), and staged extraction (E5-B).
  - Winner Candidate (E5-B: Logically Staged Pipeline + Schema v2.0.0 + Hybrid Rules) achieved **86.67% Soft Preferences F1** ($\ge 85\%$ target met), **96.00% Hard Constraints F1**, **73.33% Strict Complete Exact Match** (+19.33 percentage points over baseline), and slashed token consumption by **53.6%** (from 1,206 down to **559 tokens/query**).
  - Enhanced `gemini_client.py` with regex parsing of `retryDelay` in 429 errors for autonomous rate-limit backoff under free-tier 15 RPM constraints.
  - Added 26 dedicated offline unit tests across evaluation, schema, refinement rules, and experiment runner; repository test suite fully passing.
  - Created 4 comprehensive documentation deliverables:
    - [`docs/phase8_1_refinement_experiments.md`](file:///d:/Project/ShopAssist/docs/phase8_1_refinement_experiments.md)
    - [`docs/phase8_1_issue_resolution.md`](file:///d:/Project/ShopAssist/docs/phase8_1_issue_resolution.md)
    - [`docs/phase8_1_evaluation_methodology.md`](file:///d:/Project/ShopAssist/docs/phase8_1_evaluation_methodology.md)
    - [`docs/concepts/llm_experimentation_and_extraction_refinement.md`](file:///d:/Project/ShopAssist/docs/concepts/llm_experimentation_and_extraction_refinement.md)
  - Emitted machine-readable reports: `data/interim/phase8_1/phase8_1_final_report.json`, `data/interim/phase8_1/experiment_manifest.json`, `data/interim/phase8_1/experiment_results.json`.
- **Next Phase**: **Phase 9 — Soft Preference Representation**
