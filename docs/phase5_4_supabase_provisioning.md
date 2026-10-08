# Phase 5.4 — Supabase PostgreSQL + pgvector Provisioning

## 1. Objective

Phase 5.4 transforms the Product Knowledge Base architectural schema designed in Phase 5.1 into an active, validated production database on Supabase Cloud PostgreSQL with pgvector.

The objective was to provision the `products` table, enable the `vector` extension, programmatically verify column definitions, nullability, constraints, defaults, triggers, and execute transactional smoke tests with rollback to verify pgvector operations without altering catalog state.

---

## 2. Connection Strategy

### ShopAssist V1 Database Connection Strategy

```text
Connection Method:  Supavisor Session Pooler
Port:               5432
SSL:                Enabled (Verified active)
Target Variable:    SUPABASE_DB_URL
```

- **Single Connection Endpoint**: All database connectivity in ShopAssist V1 utilizes `SUPABASE_DB_URL` configured for the Supavisor Session Pooler (port 5432).
- **Direct Connection Not Used**: Direct PostgreSQL connections (e.g. port 5432 to AWS instance directly or `DIRECT_DATABASE_URL`) are intentionally **not used** in V1.
- **Transaction Pooler Not Used**: The Supavisor Transaction Pooler (port 6543) is intentionally **not used** in V1 to maintain full compatibility with session-level features, prepared statements, and async pooling.
- **Connection Pool Configuration**: Client-side application pooling is conservatively set:
  - `pool_size = 5` (or 2-3 during provisioning/testing)
  - `max_overflow = 2`
  - `pool_pre_ping = True` (validates liveness before checkout)

---

## 3. Environment Configuration

- **Configuration Loading**: Leveraged `shopassist.core.config.Settings` (built on `pydantic-settings` and `python-dotenv`).
- **Validation**:
  - `SUPABASE_DB_URL` presence and non-emptiness are enforced via `settings.get_raw_supabase_db_url()`.
  - Missing or blank configuration raises an explicit `ValueError`.
- **Async Driver Adaptation**: Automatically adapts standard `postgresql://` URIs to SQLAlchemy 2.0 async driver URI format (`postgresql+psycopg_async://`) via `get_async_database_url()`.

---

## 4. Security Handling

To adhere strictly to zero-credential leakage requirements:
- **Masking Mechanism**: Implemented `mask_database_url()` using SQLAlchemy's `make_url()`. Credentials, project reference, and infrastructure details are masked:
  ```text
  postgresql://postgres.***:***@***.pooler.supabase.com:5432/postgres
  ```
- **Error Sanitization**: `check_connection()` and database drivers intercept all connection exceptions to strip user credentials and passwords before logging or re-raising.
- **Zero Secrets in Artifacts**:
  - `SUPABASE_DB_URL` is never printed to console or logs.
  - JSON validation report (`data/interim/phase5_4_database_provisioning_report.json`) contains zero secret fields.
  - Automated tests verify that masked representations omit passwords, project refs, and connection strings.

---

## 5. PostgreSQL Connectivity

Programmatic verification was executed via `check_connection()` using a ping probe (`SELECT 1;`) and system metadata queries:

| Metric | Verification Result |
| :--- | :--- |
| **Connection Status** | `PASS` |
| **Connection Method** | Supavisor Session Pooler (Port 5432) |
| **Database Name** | `postgres` |
| **PostgreSQL Version** | `PostgreSQL 17.11` |
| **Host Environment** | `aarch64-unknown-linux-gnu` |
| **SSL Active** | `True` (client-driver verified) |

---

## 6. pgvector Provisioning

- **DDL Execution**:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```
- **Catalog Verification**: Queried `pg_extension`:
  - `extname`: `vector`
  - `extversion`: `0.8.2`
  - Extension Status: `Enabled` (Actual version: `v0.8.2`)

---

## 7. Products Table Provisioning

Executed base schema migration from [001_create_product_knowledge_base.sql](file:///d:/Project/ShopAssist/database/migrations/001_create_product_knowledge_base.sql).

- **Target Table**: `public.products`
- **Execution Mode**: Idempotent DDL (`CREATE TABLE IF NOT EXISTS products`).
- **Catalog Population**: 0 catalog records ingested (catalog ingestion is reserved for Phase 5.6). Current row count: `0`.

---

## 8. Schema Verification

Programmatic audit was performed via PostgreSQL `information_schema.columns` and `information_schema.table_constraints`:

| Column Name | Data Type | UDT Name | Nullable | Default | Verified |
| :--- | :--- | :--- | :--- | :--- | :---: |
| `product_id` | `character varying` | `varchar` | NO | *None* | [x] |
| `product_name` | `text` | `text` | NO | *None* | [x] |
| `category` | `character varying` | `varchar` | NO | *None* | [x] |
| `brand` | `character varying` | `varchar` | YES | *None* | [x] |
| `retail_price` | `numeric` | `numeric` | YES | *None* | [x] |
| `discounted_price` | `numeric` | `numeric` | NO | *None* | [x] |
| `rating` | `numeric` | `numeric` | YES | *None* | [x] |
| `description` | `text` | `text` | YES | *None* | [x] |
| `product_specifications` | `jsonb` | `jsonb` | NO | `'[]'::jsonb` | [x] |
| `product_url` | `text` | `text` | YES | *None* | [x] |
| `image` | `text` | `text` | YES | *None* | [x] |
| `pid` | `character varying` | `varchar` | YES | *None* | [x] |
| `retrieval_text` | `text` | `text` | NO | *None* | [x] |
| `embedding` | `USER-DEFINED` | `vector` | NO | *None* | [x] |
| `embedding_model` | `character varying` | `varchar` | NO | `'BAAI/bge-small-en-v1.5'` | [x] |
| `created_at` | `timestamp with time zone` | `timestamptz` | NO | `now()` | [x] |
| `updated_at` | `timestamp with time zone` | `timestamptz` | NO | `now()` | [x] |

- **Column Count**: Exactly 17 required columns verified.
- **Primary Key**: Verified `product_id` is the solitary `PRIMARY KEY` via `information_schema.key_column_usage`.

---

## 9. Integrity Constraints

Queried PostgreSQL `pg_constraint` catalog (`contype = 'c'`) for `public.products`. All 6 check constraints were verified:

1. `products_product_name_check`: `CHECK ((length(TRIM(BOTH FROM product_name)) > 0))`
2. `products_category_check`: `CHECK ((length(TRIM(BOTH FROM category)) > 0))`
3. `products_retrieval_text_check`: `CHECK ((length(TRIM(BOTH FROM retrieval_text)) > 0))`
4. `products_discounted_price_check`: `CHECK ((discounted_price > (0)::numeric))`
5. `products_retail_price_check`: `CHECK (((retail_price IS NULL) OR (retail_price > (0)::numeric)))`
6. `products_rating_check`: `CHECK (((rating IS NULL) OR ((rating >= 1.0) AND (rating <= 5.0))))`

---

## 10. vector(384) Verification

Verified via `pg_attribute` catalog query `format_type(atttypid, atttypmod)`:
- **Full Catalog Type**: `vector(384)`
- **Dimension**: `384`
- **Model Compatibility**: 100% matched with `BAAI/bge-small-en-v1.5` embeddings validated in Phase 5.3.

---

## 11. updated_at Trigger Verification

Verified both trigger function and trigger definition on `public.products`:
- **Function**: `update_products_updated_at()` exists in `pg_proc`.
- **Trigger**: `trg_products_updated_at` exists in `information_schema.triggers`.
- **Timing / Event**: `BEFORE UPDATE` on `public.products`.
- **Behavioral Verification**: Verified in transactional smoke test — mutating a record updated `updated_at` to a later timestamp (`updated_at > updated_at_initial`).

---

## 12. Transactional Smoke Test

Executed an isolated transactional smoke test using atomic sub-transactions and an unconditional `ROLLBACK`:

1. **Negative Price Rejection**: Insert with `discounted_price = -10.0` was rejected by `products_discounted_price_check`.
2. **Invalid Rating Rejection**: Insert with `rating = 5.5` was rejected by `products_rating_check`.
3. **Empty Name Rejection**: Insert with `product_name = '   '` was rejected by `products_product_name_check`.
4. **Valid Insertions**: Successfully inserted 2 temporary records (`__phase5_4_smoke_test_a__` and `__phase5_4_smoke_test_b__`) with synthetic 384-dimensional unit vectors.
5. **Rollback Audit**: Executed `ROLLBACK`. Post-rollback audit confirmed **0 residual test records** remaining in `public.products`.

---

## 13. pgvector Cosine Distance Test

Within the transactional smoke test, evaluated pgvector's `<=>` (cosine distance) operator:

- **Query**:
  ```sql
  SELECT product_id, (embedding <=> CAST(:q_vec AS vector)) AS distance
  FROM products
  WHERE product_id IN (:pid_a, :pid_b)
  ORDER BY distance ASC;
  ```
- **Results**:
  - `__phase5_4_smoke_test_a__` (identical to query vector): `distance = 0.000000`
  - `__phase5_4_smoke_test_b__` (orthogonal unit vector): `distance = 1.002274`
- **Outcome**: Vector cosine distance calculation and ranking behavior operate correctly.

---

## 14. Automated Tests

Created a dedicated test suite [tests/test_database_provisioning.py](file:///d:/Project/ShopAssist/tests/test_database_provisioning.py):

| Test Case | Type | Status |
| :--- | :--- | :---: |
| `test_supabase_db_url_required_when_missing` | Unit | `PASS` |
| `test_mask_database_url_masks_credentials_and_host` | Unit | `PASS` |
| `test_mask_database_url_none_or_empty` | Unit | `PASS` |
| `test_get_async_database_url_conversion` | Unit | `PASS` |
| `test_check_connection_failure_handling` | Unit | `PASS` |
| `test_enable_pgvector_missing_raises_error` | Unit | `PASS` |
| `test_validate_products_table_missing_table_raises` | Unit | `PASS` |
| `test_validate_products_table_missing_columns_raises` | Unit | `PASS` |
| `test_validate_vector_dimension_success_and_failure` | Unit | `PASS` |
| `test_validate_constraints_detects_missing_check` | Unit | `PASS` |
| `test_validate_updated_at_trigger_missing_raises` | Unit | `PASS` |
| `test_validate_deferred_indexes_detects_phase5_7_indexes` | Unit | `PASS` |
| `test_phase5_4_report_schema_and_integrity` | Unit | `PASS` |
| `test_live_supabase_provisioning_integration` | Integration | `PASS` |

Total test suite status: **137 passed** across the entire repository.

---

## 15. Generated Artifacts

1. [src/shopassist/core/config.py](file:///d:/Project/ShopAssist/src/shopassist/core/config.py): Environment configuration and credential-masking utility.
2. [src/shopassist/db/connection.py](file:///d:/Project/ShopAssist/src/shopassist/db/connection.py): SQLAlchemy 2.0 AsyncEngine connection factory and liveness check.
3. [src/shopassist/db/validation.py](file:///d:/Project/ShopAssist/src/shopassist/db/validation.py): Catalog validation, constraint verification, trigger audit, and transactional smoke tests.
4. [scripts/provision_supabase.py](file:///d:/Project/ShopAssist/scripts/provision_supabase.py): Executable CLI provisioning and validation script (supports `--validate-only`).
5. [database/migrations/001_create_product_knowledge_base.sql](file:///d:/Project/ShopAssist/database/migrations/001_create_product_knowledge_base.sql): Base schema migration (extension, table, constraints, trigger).
6. [database/migrations/002_create_product_indexes.sql](file:///d:/Project/ShopAssist/database/migrations/002_create_product_indexes.sql): Separated index migration reserved for Phase 5.7.
7. [data/interim/phase5_4_database_provisioning_report.json](file:///d:/Project/ShopAssist/data/interim/phase5_4_database_provisioning_report.json): Machine-readable validation report.
8. [tests/test_database_provisioning.py](file:///d:/Project/ShopAssist/tests/test_database_provisioning.py): Unit and live integration test suite.

---

## 16. Deferred Index Construction

In strict alignment with the ShopAssist Development Plan:

> **B-Tree and HNSW production indexes are intentionally deferred to Phase 5.7.**

The following indexes have been preserved in [database/migrations/002_create_product_indexes.sql](file:///d:/Project/ShopAssist/database/migrations/002_create_product_indexes.sql) and will be constructed after bulk data ingestion:
- `idx_products_category` (B-Tree)
- `idx_products_price` (B-Tree)
- `idx_products_brand` (B-Tree)
- `idx_products_category_price` (B-Tree composite)
- `idx_products_embedding` (HNSW cosine similarity, $m=16, ef\_construction=64$)

Catalog audit during Phase 5.4 confirmed that only `products_pkey` exists on the database.

---

## 17. Issues / Limitations

1. **Driver Selection on Windows**:
   - `asyncpg` was blocked by Windows Application Control policies on local environments.
   - Resolved by configuring `psycopg` (psycopg 3 with `psycopg-binary`) and `WindowsSelectorEventLoopPolicy`.
2. **Catalog State**:
   - Database contains 0 catalog records. Bulk ingestion must proceed only after batch embeddings are generated in Phase 5.5.

---

## 18. Phase 5.5 Readiness

The Supabase PostgreSQL database is verified and fully ready for downstream phases:
- **Phase 5.5**: Generate 384-dimensional batch embeddings for all 8,405 products using `BAAI/bge-small-en-v1.5` and export `data/processed/products.parquet`.
- **Phase 5.6**: Bulk ingest 8,405 records into `public.products`.
- **Phase 5.7**: Construct relational B-Tree and HNSW vector indexes.
