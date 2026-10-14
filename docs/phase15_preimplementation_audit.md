# Phase 15 — Pre-Implementation Codebase Audit & Integration Design

**Date:** 2026-10-14  
**Author:** ShopAssist Engineering Team  
**Scope:** Phase 15 FastAPI Backend & End-to-End AI Pipeline Integration  
**Target Branch:** `feat/phase15-fastapi-backend` (branched from `d431ba7`)  
**Status:** COMPLETE — PRE-IMPLEMENTATION AUDIT  

---

## 1. Executive Summary

Phase 15 unifies the modular AI capabilities developed across Phases 8–12 into a robust, high-performance, asynchronous RESTful API powered by FastAPI. This audit inspects all active contracts, interfaces, resource requirements, synchronization boundaries, error mappings, and technical debt from upstream phases, establishing the blueprint for the backend architecture.

---

## 2. Codebase Component Audit (Phases 8–12 & Database)

### 2.1. Phase 8: LLM Query Understanding
- **Module:** `src/shopassist/llm/query_understanding.py`, `src/shopassist/llm/schemas.py`, `src/shopassist/llm/gemini_client.py`
- **Primary Async Interface:**
  ```python
  await query_engine.parse_query_async(query: str, system_instruction: str = ...) -> QueryUnderstandingResult
  ```
- **Output Contract:** `QueryUnderstandingResult`
  - `output.semantic_query: str`
  - `output.hard_constraints: HardConstraints` (`category`, `brand`, `min_price`, `max_price`, `min_rating`, `currency`)
  - `output.soft_preferences: list[str]`
  - `output.needs_clarification: bool`
  - `output.clarification_reason: str | None`
  - `is_valid: bool`
  - `validation_errors: list[str]`
  - `token_usage: TokenUsageMetadata | None`
- **Key Constraints & Boundaries:**
  - Production uses Gemini `gemini-3.1-flash-lite`, temperature `0.0`, Schema v1.
  - Schema v1 does **not** include strict/inclusive boolean operator flags for price bounds (`min_inclusive`, `max_inclusive`).
  - Max input query length is 500 characters. Input validation throws `ValueError` or returns `is_valid=False` with `needs_clarification=True`.
  - Client cleanup requires `await query_engine.client.aclose()`.

### 2.2. Phase 9: Soft Preference Representation
- **Module:** `src/shopassist/preferences/service.py`, `src/shopassist/preferences/schemas.py`, `src/shopassist/preferences/embedding.py`
- **Primary Interface:**
  ```python
  preference_service.represent(query_result: QueryUnderstandingResult) -> PreferenceRepresentationResult
  ```
- **Output Contract:** `PreferenceRepresentationResult`
  - `status: RepresentationStatus` (`SUCCESS`, `NO_PREFERENCES`, `CLARIFICATION_REQUIRED`, `INVALID_INPUT`, `UNSUPPORTED_INTENT`, `EMBEDDING_FAILURE`)
  - `preference_embedding: list[float] | None` (384-dimensional unit vector)
  - `has_preferences: bool`
  - `normalized_preferences: list[str]`
- **Key Constraints & Boundaries:**
  - Synchronous CPU operation (PyTorch / BGE embedding inference).
  - Conservative negative intent guard: calls `find_unsafe_negative_preferences` and halts as `UNSUPPORTED_INTENT` if negative preferences or exclusions are detected.
  - If `currency != "INR"`, returns `UNSUPPORTED_INTENT`.
  - When `NO_PREFERENCES`, returns `has_preferences=False` without vector; downstream Phase 10 falls back to encoding `semantic_query` using base encoder.

### 2.3. Phase 10: Hybrid Candidate Retrieval
- **Module:** `src/shopassist/retrieval/hybrid.py`, `src/shopassist/retrieval/semantic.py`, `src/shopassist/retrieval/tfidf.py`
- **Primary Async Interface:**
  ```python
  await hybrid_service.retrieve(
      query_result: QueryUnderstandingResult,
      preference_result: PreferenceRepresentationResult,
      *,
      top_n: int | None = None,
      price_boundary_semantics: Mapping[str, bool] | None = None,
  ) -> HybridRetrievalResult
  ```
- **Output Contract:** `HybridRetrievalResult`
  - `status: HybridRetrievalStatus` (`SUCCESS`, `NO_RESULTS`, `INVALID_INPUT`, `CLARIFICATION_REQUIRED`, `UNSUPPORTED_INTENT`, `EMBEDDING_FAILURE`, `RETRIEVAL_FAILURE`)
  - `candidates: list[HybridCandidate]`
  - `applied_constraints: dict[str, Any]`
  - `stage_latency_ms: dict[str, float]`
- **Key Constraints & Boundaries:**
  - Requires `AsyncEngine` (Supabase PostgreSQL / pgvector) and fitted `TFIDFIndex`.
  - **Deliberate safeguard:** If `min_price` or `max_price` is present in `HardConstraints`, Phase 10 requires `price_boundary_semantics` containing `"min_inclusive"` or `"max_inclusive"`. If missing, it fails closed returning `UNSUPPORTED_INTENT`.
  - Requires an independent, safely tested `PriceBoundaryAdapter` at the API layer to resolve explicit operator semantics (e.g., "under 3000" -> `max_inclusive=False`, "up to 3000" -> `max_inclusive=True`) from raw text without assuming all prices are inclusive.
  - SQL filters enforce category, brand, and rating >= min_rating (null ratings rejected).

### 2.4. Phase 11: Candidate Reranking
- **Module:** `src/shopassist/reranking/core.py`
- **Primary Interface:**
  ```python
  reranking_service.rerank(
      query_result: QueryUnderstandingResult,
      preference_result: PreferenceRepresentationResult,
      retrieval_result: HybridRetrievalResult,
      *,
      top_k: int | None = None,
      method: RerankingMethod | None = None,
  ) -> RerankingResult
  ```
- **Output Contract:** `RerankingResult`
  - `status: RerankingStatus` (`SUCCESS`, `NO_RESULTS`, `INVALID_INPUT`, `CLARIFICATION_REQUIRED`, `UNSUPPORTED_INTENT`, `EMBEDDING_FAILURE`, `RETRIEVAL_FAILURE`, `MODEL_UNAVAILABLE`, `MODEL_FAILURE`, `CONSTRAINT_VIOLATION`)
  - `products: list[RerankedProduct]`
  - `method: str` (default `RRF`, optional `MULTI_SIGNAL`, `CROSS_ENCODER`, `COMBINED`)
- **Key Constraints & Boundaries:**
  - Synchronous CPU operation.
  - Default reranker is RRF (preserves candidate-subset invariant, verifies hard constraints, resolves canonical `retrieval_text` via `ProductTextProvider`).
  - Cross-Encoder requires pinned checkpoint `cross-encoder/ms-marco-MiniLM-L2-v2`; must not trigger automatic model downloads during normal application startup.

### 2.5. Phase 12: Grounded Recommendation Generation
- **Module:** `src/shopassist/recommendation/core.py`, `src/shopassist/recommendation/provider.py`, `src/shopassist/recommendation/validation.py`
- **Primary Async Interface:**
  ```python
  await recommendation_service.generate(
      query_result: QueryUnderstandingResult,
      preference_result: PreferenceRepresentationResult | None,
      reranking_result: RerankingResult,
      *,
      top_k: int | None = None,
      language: str | None = None,
  ) -> RecommendationResult
  ```
- **Output Contract:** `RecommendationResult`
  - `status: RecommendationStatus` (`SUCCESS`, `NO_RESULTS`, `INVALID_INPUT`, `CLARIFICATION_REQUIRED`, `UNSUPPORTED_INTENT`, `GENERATION_FAILURE`, `VALIDATION_FAILURE`, `DETERMINISTIC_FALLBACK`)
  - `overview: str`
  - `products: list[RecommendedProduct]`
  - `usage: TokenUsage` (`prompt_tokens`, `completion_tokens`, `total_tokens`, `latency_ms`, `estimated_cost_usd`)
- **Key Constraints & Boundaries:**
  - Uses OpenRouter (`google/gemma-4-26b-a4b-it:free`) by default, with Groq preserved as fallback/alternative.
  - Enforces authoritative metadata merge: LLM output cannot override product ID, title, price, brand, rating from Phase 11.
  - Implements `DETERMINISTIC_FALLBACK` when the upstream provider fails (e.g. HTTP 429 rate limit or schema failure), preserving valid product recommendations with template-based summaries rather than crashing.

### 2.6. Database Infrastructure
- **Module:** `src/shopassist/db/connection.py`, `src/shopassist/core/config.py`
- **Engine:** `get_async_engine(pool_size=5, max_overflow=2, pool_pre_ping=True)`
- **Event Loop Policy:** `ensure_windows_event_loop_policy()` required on Windows platform for psycopg 3 async compatibility.
- **Engine Lifecycle:** Created on FastAPI startup in lifespan context, cleanly disposed on shutdown (`await engine.dispose()`).

---

## 3. Dependency Initialization & Lifecycle Management

| Resource / Component | Lifecycle Scope | Initialization Strategy | Cleanup on Shutdown |
|---|---|---|---|
| **SQLAlchemy AsyncEngine** | Lifespan Singleton | `get_async_engine(pool_size=5, max_overflow=2)` | `await engine.dispose()` |
| **TF-IDF Index** | Lifespan Singleton | `TFIDFIndex.load(PROCESSED_DATA_DIR / "tfidf")` | In-memory dereference |
| **DenseQueryEncoder (BGE)** | Lifespan Singleton | Shared instance for both Phase 9 & Phase 10 | PyTorch memory release |
| **ProductTextProvider** | Lifespan Singleton | `load_canonical_product_texts(products.parquet)` | In-memory dereference |
| **QueryUnderstandingEngine** | Lifespan Singleton | Reusable instance with `GeminiClient` | `await query_engine.client.aclose()` |
| **PreferenceService** | Lifespan Singleton | Reusable wrapper sharing `DenseQueryEncoder` | None |
| **HybridRetrievalService** | Lifespan Singleton | Reusable instance sharing `AsyncEngine` & `TFIDF` | None |
| **RerankingService** | Lifespan Singleton | Reusable instance sharing `ProductTextProvider` | None |
| **RecommendationService** | Lifespan Singleton | Reusable instance sharing `OpenRouterProvider` | `await provider.aclose()` |
| **SessionStore** | Lifespan Singleton | In-memory TTL bounded cache | Cache eviction / clear |

---

## 4. Async / Sync Synchronization Strategy

To avoid blocking the FastAPI asyncio event loop during compute-intensive tasks, operations are partitioned:

1. **Async I/O Tasks (native await):**
   - Phase 8 Gemini Query Understanding (`client.generate_structured_async`).
   - Phase 10 pgvector retrieval (`await conn.execute(...)`).
   - Phase 12 OpenRouter / Groq HTTP calls (`await client.post(...)` / `chat.completions.create`).
2. **CPU-bound Tasks (threadpool execution via `asyncio.to_thread`):**
   - Phase 9 BGE embedding computation (`encoder.encode(preference_query)`).
   - Phase 10 local TF-IDF sparse matrix transform and dot product search.
   - Phase 11 Cross-Encoder inference (if activated) and canonical product text resolution.
   - Large JSON schema validations and evidence pruning.

---

## 5. Status Propagation and Public API Mapping

The following table formalizes how internal pipeline statuses map to the external HTTP response:

| Phase Source Status | Orchestrator Action | API Status Code | Public Response `status` | Response Body Action |
|---|---|---|---|---|
| Schema Validation Error | Fast reject | **422 Unprocessable Entity** | `INVALID_INPUT` | Standard FastAPI error detail |
| Request Timeout (>90s) | Terminate | **504 Gateway Timeout** | `TIMEOUT` | Request ID & timeout notice |
| Dependency Unavailable | Terminate | **503 Service Unavailable** | `SERVICE_UNAVAILABLE` | Component health diagnostics |
| P8 `is_valid=False` | Short-circuit | **200 OK** | `INVALID_INPUT` | Explanation in `overview`, 0 products |
| P8 `needs_clarification=True` | Short-circuit | **200 OK** | `CLARIFICATION_REQUIRED` | Clarification question in `overview` |
| P8 Foreign Currency / Exclusion | Short-circuit | **200 OK** | `UNSUPPORTED_INTENT` | Explanation in `overview`, 0 products |
| Ambiguous Price Semantics | Short-circuit | **200 OK** | `CLARIFICATION_REQUIRED` / `UNSUPPORTED_INTENT` | Guidance on budget expression |
| P9 `EMBEDDING_FAILURE` | Short-circuit | **200 OK** | `EMBEDDING_FAILURE` | Explanation in `overview`, 0 products |
| P10 `NO_RESULTS` | Short-circuit | **200 OK** | `NO_RESULTS` | Helpful no-match summary in `overview` |
| P10 `RETRIEVAL_FAILURE` | Short-circuit | **503 / 500** | `RETRIEVAL_FAILURE` | Sanitized diagnostic error |
| P11 `CONSTRAINT_VIOLATION` | Short-circuit | **200 OK** | `NO_RESULTS` | Filtered out safely |
| P12 `DETERMINISTIC_FALLBACK` | Safe delivery | **200 OK** | `DETERMINISTIC_FALLBACK` | Real products, rule-based text, `fallback_used=True` |
| Complete Pipeline Success | Delivery | **200 OK** | `SUCCESS` | Grounded products, explanations, full usage |

---

## 6. Price-Boundary Semantics Adapter Design

To bridge the gap between Phase 8 Schema v1 (which only extracts numbers) and Phase 10 (which rejects ambiguous operators), an independent adapter `PriceBoundaryAdapter` will be implemented:

- **Strict `<` (exclusive):**
  - Patterns: `under \d+`, `below \d+`, `less than \d+`, `cheaper than \d+`, `dưới \d+`, `thấp hơn \d+`, `nhỏ hơn \d+`
  - Mapping: `max_inclusive = False`
- **Inclusive `<=` (at most):**
  - Patterns: `up to \d+`, `at most \d+`, `max(imum)? \d+`, `not exceeding \d+`, `within \d+`, `tối đa \d+`, `không quá \d+`, `nhiều nhất \d+`
  - Mapping: `max_inclusive = True`
- **Strict `>` (exclusive):**
  - Patterns: `above \d+`, `over \d+`, `more than \d+`, `greater than \d+`, `trên \d+`, `cao hơn \d+`, `lớn hơn \d+`
  - Mapping: `min_inclusive = False`
- **Inclusive `>=` (at least):**
  - Patterns: `at least \d+`, `min(imum)? \d+`, `from \d+`, `tối thiểu \d+`, `ít nhất \d+`, `từ \d+`
  - Mapping: `min_inclusive = True`
- **Explicit Range `between X and Y` / `from X to Y` / `từ X đến Y`:**
  - Mapping: `min_inclusive = True, max_inclusive = True`
- **Ambiguous expressions (`around \d+`, `khoảng \d+`, or bare budgets):**
  - Mapping: Returns `None` -> Triggers `CLARIFICATION_REQUIRED` or Phase 10's safe `UNSUPPORTED_INTENT` stop. **No silent inclusive assumption.**

---

## 7. Security, Privacy & Secret Redaction

1. **Secret Masking:**
   - Database credentials, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY` are read strictly from environment / `.env`.
   - Health endpoints report component configuration status (`"configured"`, `"ready"`, `"healthy"`), never exposing key values or substring lengths.
   - Database URLs logged via existing `mask_database_url`.
2. **Data Minimization:**
   - Conversation text in request logging is truncated or redacted.
   - Stack traces are caught by global exception handlers; clients receive sanitized error payloads with traceable `request_id`.
3. **CORS:**
   - Configurable origins via `API_CORS_ORIGINS` (defaults to localhost development origins; wildcards disallowed by default).

---

## 8. Planned File Structure

```text
src/shopassist/api/
├── __init__.py
├── main.py                     # FastAPI application factory & lifespan
├── config.py                   # Pydantic Settings for API (API_HOST, API_PORT, etc.)
├── schemas.py                  # Public Pydantic v2 API request/response contracts
├── dependencies.py             # FastAPI dependency injection providers
├── price_adapter.py            # Narrowly scoped, verified PriceBoundaryAdapter
├── session.py                  # In-memory bounded session store (Phase 16 preparation)
├── exceptions.py               # Custom API exception handlers & status mapping
├── middleware/
│   ├── __init__.py
│   └── request_context.py      # Request ID generation, latency timing, logging
├── routes/
│   ├── __init__.py
│   ├── health.py               # GET /api/v1/health, GET /api/v1/health/live
│   └── recommendations.py      # POST /api/v1/recommend, POST /recommend alias
└── services/
    ├── __init__.py
    └── orchestrator.py         # RecommendationOrchestrator coordinating Phases 8–12
```

---

## 9. Next Steps

With the pre-implementation audit completed and verified against active contracts:
1. Initialize FastAPI application settings and schema contracts.
2. Implement `PriceBoundaryAdapter` and unit tests.
3. Build the `RecommendationOrchestrator` coordinating Phases 8–12 with short-circuiting.
4. Implement route handlers, lifespan resource management, and dependency injection.
5. Create comprehensive unit and API integration tests.
6. Verify live execution against local model assets, Supabase PostgreSQL, and LLM APIs.
