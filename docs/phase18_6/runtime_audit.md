# Phase 18.6 runtime audit

2026-11-27, Asia/Saigon. Started from clean `main` at `ab48e05`, equal to `origin/main` after fetch. Reviewed the Phase 18 handover, Phase 18.3 evaluation, Phase 18.4 implementation/evaluation and all four Phase 18.5 reports before changes. No production routes, public schemas, frozen Q1S prompt/parser/transformation, frozen R3 prompt, historical artifacts or T17 ledger were changed.

## Actual resources

| Resource | Verified result |
|---|---|
| Python/environment | `.venv\Scripts\python.exe`, Python 3.10.11; installed packages are recorded in `runtime_validation/audit_03.json`. |
| Backend/transport | FastAPI 0.138.0, Uvicorn 0.49.0, HTTPX 0.28.1, Pydantic 2.12.5. |
| Database libraries | SQLAlchemy 2.0.51, psycopg 3.3.6, Python pgvector 0.5.0. |
| Neural stack | Torch 2.6.0+cu124, sentence-transformers 6.0.1, scikit-learn 1.7.2. |
| GPU | NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB, driver 566.07. BGE used CUDA; existing CrossEncoder verification used CPU. |
| Ollama | Native server 0.40.18 on loopback; existing `qwen2.5:1.5b-instruct-local`; `/api/tags` matches digest `d010eb818583111cfafeb3523cc17802f85dcb7f4fe5e8ecdd4927dca40e3174`. No model download or modification. |
| Local catalog | 8,405 rows, zero duplicate product IDs. SHA-256 `bd9bac023368289629c903ad04fc98bae85c347777f646dca63ad4bdfb029cdc`. |
| TF-IDF | Existing 8,405-document, 61,979-feature index; ID set matches catalog exactly. Manifest source hash equals the current catalog hash. Existing artifacts were loaded, not rebuilt. |
| BGE | Existing cached `BAAI/bge-small-en-v1.5` loaded with offline flags; query encoding produces 384 dimensions. Cached weights/config/tokenizer/module hashes are saved in the resource summary. |
| Reranking | Existing canonical text provider and RRF work. Existing pinned local `ms-marco-MiniLM-L2-v2` also loaded/scored offline and was used in relevance diagnostics; no new reranker was introduced. |
| PostgreSQL | 17.11, pgvector extension 0.8.2; read-only connection/query audit passed on the third attempt. |

The first database audit timed out before a query. A second attempt with explicit connection timeout also failed with `ConnectionTimeout`; after the operator requested a retry, the third audit succeeded in about 3.0 seconds. No credential, URL or database configuration was changed to obtain that success. Initial outage evidence remains in `audit_01.json`, `audit_02.json` and the first live API run. An isolated later reference ablation also saw one transient timeout; the targeted retry succeeded. These observations remain operational risks rather than evidence of a permanently repaired network.

## Read-only database consistency

`public.products` contains 8,405 records and the same product IDs as the local catalog and TF-IDF index. All 8,405 embeddings are present, have dimension 384 and declare `BAAI/bge-small-en-v1.5`. There are no missing names, categories or prices. Missing brands: 1,988; missing ratings: 7,511. Those are catalog limitations; minimum-rating filters must exclude null ratings.

Required fields and indexes were inspected, including primary key, category, price, brand, category/price and HNSW cosine embedding index (`m=16`, `ef_construction=64`). No migration, reseeding, write, embedding regeneration or index rebuild was performed. Audit queries explicitly use read-only transactions; live harnesses use `PGOPTIONS=-c default_transaction_read_only=on` and the existing connection utilities.

Names, categories, brands and prices showed no catalog/database mismatch. The first strict cross-type equality audit listed 261 rating differences. A follow-up comparison of all 894 non-null ratings after consistent numeric conversion found **zero differences**, maximum absolute difference 0.0. The initial findings are preserved; they were a representation/comparison issue, not a reason to rewrite database values. See `retrieval_results/live_hybrid_preflight_01.json: rating_precision`.

## Runtime composition and ownership

| Concern | Existing module |
|---|---|
| Startup/shutdown | `api/main.py:lifespan`, `_build_gateway`, `main` |
| HTTP routes and deadlines | `api/routes/recommendations.py`; `api/services/orchestrator.py` |
| Database connectivity | `db/connection.py:get_async_engine` |
| Preference representation | `preferences/service.py`, `preferences/embedding.py` |
| BGE encoding / SQL dense retrieval | `retrieval/semantic.py:DenseQueryEncoder`; `retrieval/hybrid.py:_fetch_dense_rows` |
| Lexical retrieval / fusion | `retrieval/tfidf.py:TFIDFIndex`; `retrieval/hybrid.py:HybridRetrievalService` |
| Reranking / filter validation | `reranking/core.py:RerankingService` |
| Product relevance / source assembly | `recommendation/local.py`; `recommendation/context.py`; `recommendation/validation.py` |
| Authoritative URLs/images and public response | `api/services/orchestrator.py:_enrich_product_presentation` |
| Readiness | `api/routes/health.py` |
| Presentation-only Telegram client | `bot/main.py`, `bot/client.py` and existing handlers |

Actual local settings: API deadline 90 seconds, bot timeout 95 seconds, API/bot default top-k 3, retrieval top-n 20, RRF reranking. Both consumers share the existing single native Gateway, adapter and async HTTP client. All application runs used one worker and shut down cleanly; operator Ollama was left running. No actual `.env` file was edited, and no Telegram network call was made.

The checked-in production YAML and experimental template remain disabled/pending. Supervised API validation used a separate time-limited config with normal artifact-hash, approval, digest, schema fingerprint, cost and expiry checks. This is test permission, not semantic production approval. Standard application defaults remain unchanged.

Evidence: [database/runtime audit](../../data/interim/phase18_6/runtime_validation/audit_03.json), [neural resources](../../data/interim/phase18_6/runtime_validation/neural_resources.json), [branch/resource summary](../../data/interim/phase18_6/performance_results/branch_and_resource_summary.json). The final experiment index supplies artifact/source hashes.
