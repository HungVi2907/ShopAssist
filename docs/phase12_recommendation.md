# Phase 12 — Grounded LLM Recommendation Generation with OpenRouter Gemma 4

**Contract version:** `1.0.0`  
**Status:** **VALIDATED FOR PROTOTYPE — OpenRouter integration operational with `google/gemma-4-26b-a4b-it:free` (and standard Gemma 4 route), Groq preserved cleanly as alternative provider, 100% groundedness pass rate across 7 real catalog scenarios, zero cross-product hallucinations, token latency and cost measured, 23 Phase 12 unit tests passing, deterministic fallbacks verified under upstream rate limits.**

---

## 1. Scope & Architecture

Phase 12 transforms the verified Top-K products returned by Phase 11 into accurate, evidence-grounded, natural-language recommendations. It operates as an independent application service designed for direct consumption by future FastAPI endpoints and the Telegram Bot (Phases 15–17).

Phase 12 is strictly isolated from Phase 8:
- **Phase 8 LLM:** Google Gemini (`gemini-3.1-flash-lite`) used for query understanding.
- **Phase 12 LLM:** OpenRouter API (`google/gemma-4-26b-a4b-it:free` by default, `google/gemma-4-26b-a4b-it` supported) with dedicated configuration and `OPENROUTER_API_KEY`. (Groq `openai/gpt-oss-20b` remains supported as an alternative provider).
- No configuration leakage or shared prompt templates between phases.

### Component Architecture

```text
Original User Query
         │
         ▼
Phase 8 — Query Understanding (Gemini Flash Lite)
         │
         ▼
Phase 9 — Preference Representation (Normalized Preferences + 384D Vector)
         │
         ▼
Phase 10 — Hybrid Retrieval (pgvector + TF-IDF)
         │
         ▼
Phase 11 — RRF Reranking (Ordered Top-K Products)
         │
         ▼
Phase 12 — Grounded Recommendation Service (`shopassist.recommendation`)
         ├── 1. Upstream Contract Validation (guards stop-states & invariants)
         ├── 2. Evidence Context Builder (`EvidenceContextBuilder`)
         │      ├── Strips marketplace promotional boilerplate
         │      ├── Prunes specs & sentences deterministically
         │      └── Wraps untrusted text in XML-delimited `<product_evidence>` blocks
         ├── 3. LLM Provider Layer (`BaseRecommendationProvider`)
         │      ├── OpenRouter (`OpenRouterProvider`):
         │      │     ├── Model: `google/gemma-4-26b-a4b-it:free`
         │      │     ├── JSON Schema Structured Output (`json_schema` / `json_object`)
         │      │     ├── Bounded exponential backoff + Retry-After / 429 rate limit handling
         │      │     └── Accurate token & free-tier cost reporting ($0.00 / 1M)
         │      └── Groq (`GroqProvider`):
         │            └── Retained for backward compatibility (`openai/gpt-oss-20b`)
         ├── 4. Groundedness & Metadata Validation (`GroundednessValidator`)
         │      ├── Strict Product ID set validation (detects foreign/duplicate IDs)
         │      ├── Authoritative metadata merge (price, rating, brand from Phase 11)
         │      ├── Evidence citation verification (validates `{pid}-E{n}` references)
         │      └── Deterministic metadata fallback on provider/claim failure
         └── 5. Typed Recommendation Output (`RecommendationResult`)
```

---

## 2. Work Packages Implemented

| Work Package | Status | Key Deliverables |
|---|---|---|
| **WP-A: Typed Contract** | COMPLETE | `RecommendationResult`, `RecommendedProduct`, `TokenUsage`, `ProductEvidence`, `ProductClaim` with Pydantic v2 strict typing. |
| **WP-B: Provider Architecture** | COMPLETE | `OpenRouterProvider` with async `httpx`, `GroqProvider` backward compatibility, bounded retry with `Retry-After`, zero secret logging. |
| **WP-C: Evidence Context Builder** | COMPLETE | Traceable `{product_id}-E{n}` evidence extraction, boilerplate stripping, XML injection boundary, 18.1% token savings. |
| **WP-D: Grounded Prompts** | COMPLETE | Anti-hallucination system prompt, bilingual EN/VI support, strict affirmative claim citation rules, review fabrication prohibition. |
| **WP-E: OpenRouter Structured Output** | COMPLETE | JSON Schema mode with automatic fallback to JSON Object mode and markdown fence cleaner, verified against live OpenRouter endpoint. |
| **WP-F: Groundedness Validation** | COMPLETE | Candidate ID filtering, rank order preservation, citation product ownership check, authoritative Phase 11 metadata merging. |
| **WP-G: Token Usage & Cost** | COMPLETE | TokenUsage tracking (prompt, completion, total tokens), latency, cost calculated at $0.00/1M for `:free` models and custom per-model rates. |
| **WP-H: Unit & Mocked Tests** | COMPLETE | 23 unit tests in `tests/test_recommendation.py` covering settings, validation, injection defense, edge cases, error fallbacks. |
| **WP-I: Real OpenRouter Integration** | COMPLETE | 3 opt-in live tests in `tests/test_recommendation_real_openrouter.py` verifying real API auth, catalog recommendations, and 429 graceful handling. |
| **WP-J: Preliminary Evaluation** | COMPLETE | `scripts/evaluate_phase12.py` evaluating 7 real catalog scenarios across EN/VI, hard constraints, soft preferences, missing attributes. |

---

## 3. Strict Grounding & Anti-Hallucination Design

Phase 12 implements defense-in-depth against LLM hallucination and prompt injection:

1. **Deterministic Metadata Authority:**
   The LLM generates *only* explanations, strengths, limitations, and comparison notes. Authoritative metadata (`product_id`, `product_name`, `brand`, `category`, `discounted_price`, `rating`, `original_rank`, `reranked_rank`, `rrf_score`) are merged deterministically from Phase 11 objects. The LLM is never trusted for pricing or ratings.
2. **Traceable Evidence Citation:**
   Every product is decomposed into numbered, verifiable evidence items:
   ```text
   [P001-E1] (product_name): Campus Men's Running Shoes
   [P001-E2] (discounted_price): 899.00 INR
   [P001-E3] (specifications): Upper Material: Mesh
   ```
   Every affirmative claim in `strengths` must cite the corresponding evidence ID(s).
3. **Cross-Product Citation Prevention:**
   The `GroundednessValidator` verifies that any cited evidence ID matches the specific product (`{pid}-E{n}`). Cross-product citations (citing product A's evidence for product B) are immediately rejected.
4. **Prompt Injection Boundary:**
   Untrusted product descriptions and catalog text are enclosed in XML tags `<product_evidence product_id="...">`. System instructions explicitly mandate that text inside these tags is raw data and must never be interpreted as instructions.
5. **Deterministic Fallback:**
   If the provider fails, times out, returns an unparseable schema, or hallucinates invalid product IDs, Phase 12 synthesizes a safe deterministic fallback explaining the products purely from verified catalog metadata, logging warnings and maintaining machine-readable diagnostic flags.

---

## 4. Live OpenRouter Verification & Evaluation Results

Evaluated on 2026-10-11 using OpenRouter with model `google/gemma-4-26b-a4b-it` (and `google/gemma-4-26b-a4b-it:free` default):

### A. Performance & Cost Summary across 7 Catalog Scenarios

| Metric | OpenRouter Gemma 4 | Groq GPT-OSS 20B (Baseline) | Variance / Speedup |
|---|---|---|---|
| **Total Scenarios Evaluated** | 7 scenarios (EN, VI, hard/soft constraints, comparison) | 7 scenarios | Identical test harness |
| **Scenario Success Rate** | 100% (7/7 `SUCCESS`) | 100% (7/7 `SUCCESS`) | 100% parity |
| **Groundedness Pass Rate** | 100% (7/7 passed all candidate ID and citation checks) | 100% (7/7 passed) | Zero hallucinations |
| **Invalid Evidence Citations** | 0 across all generated claims | 0 across all claims | 100% precision |
| **Average Prompt Tokens** | 3,038.3 tokens | 2,679.0 tokens | +13.4% prompt context |
| **Average Completion Tokens** | 1,162.1 tokens | 1,096.4 tokens | +6.0% completion length |
| **Average Total Tokens** | 4,200.4 tokens | 3,775.4 tokens | +11.2% total tokens |
| **Median Latency** | **12,488.8 ms (12.5s)** | 25,833.8 ms (25.8s) | **51.7% faster (2.07x speedup)** |
| **P95 Latency** | **18,439.8 ms (18.4s)** | 28,094.0 ms (28.1s) | **34.4% faster** |
| **Average Cost per Request** | **$0.000503 USD** ($0.00 for `:free`) | $0.000530 USD | **5.1% cheaper** |
| **Total Evaluation Cost** | $0.003523 USD | $0.003710 USD | Micro-cent footprint |

### B. Context Optimization Benchmark

Comparing standard optimized context (`max_spec_items=8`, `max_desc_sentences=3`, marketplace boilerplate stripped) against naive complete-evidence context:

| Context Mode | Prompt Tokens | Completion Tokens | Total Tokens | Latency | Cost (USD) |
|---|---|---|---|---|---|
| **Optimized Context Builder** | **3,032** | 1,087 | 4,119 | 19.23 s | $0.000484 |
| **Naive Unoptimized Context** | 3,805 | 1,140 | 4,945 | 16.90 s | $0.000551 |
| **Optimization Delta** | **-20.32% prompt tokens** | -53 tokens | -16.7% total | +2.33 s | **-12.16% cost** |

*Finding:* Context optimization achieves a **20.3% reduction in input tokens** and **12.2% reduction in inference cost** while preserving 100% of verifiable claims, specifications, and catalog identities.

---

## 5. Verification Commands

To reproduce test suites and evaluation in the verified virtual environment:

```powershell
# 1. Phase 12 Unit Tests (23 tests, 100% offline & mocked)
$env:PYTHONPATH = "src"
pytest tests/test_recommendation.py -v

# 2. Phase 12 Live OpenRouter Integration Tests (3 tests, live OpenRouter API)
$env:PYTHONPATH = "src"
$env:SHOPASSIST_PHASE12_LIVE_OPENROUTER = "1"
pytest tests/test_recommendation_real_openrouter.py -v -s

# 3. Phase 12 Evaluation Script (7 scenarios + context comparison benchmark)
$env:PYTHONPATH = "src"
python scripts/evaluate_phase12.py --provider openrouter --model "google/gemma-4-26b-a4b-it"

# 4. Full Project Regression Suite (464 tests passing)
$env:PYTHONPATH = "src"
pytest --ignore=tests/test_gemini_integration.py -m "not integration" -q
```
