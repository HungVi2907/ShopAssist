# Phase 12 — Deferred Issues & Technical Debt Register

**Creation Date:** 2026-10-11  
**Status:** **REGISTERED / TRACKED**  
**Component:** `shopassist.recommendation`

---

## 1. Overview

Phase 12 has achieved **VALIDATED FOR PROTOTYPE** status. To preserve system stability, avoid premature complexity, and respect component boundaries, the following non-blocking improvements have been explicitly cataloged and deferred to subsequent project phases.

---

## 2. Deferred Technical Debt Register

### P12-01: Offline Natural Language Inference (NLI) for Semantic Claim Entailment
- **Impact:** LOW (Deterministic citation checks already ensure cited evidence IDs exist and belong to the correct candidate product).
- **Current Status:** Deterministic validation verifies structural citation validity, cross-product citation absence, and ID presence. It does not measure semantic exaggeration (e.g. if a claim stretches "Mesh upper" into "Ultra-durable military-grade mesh").
- **Evidence Required:** Offline NLI entailment scoring model (e.g., DeBERTa-v3-NLI) evaluated on 50+ generated recommendations.
- **Recommended Phase:** Phase 13–14 (Offline System Evaluation).

---

### P12-02: Token Streaming & Chunked Delivery
- **Impact:** MEDIUM (Current median latency of ~25s with remote reasoning effort "low" is completely acceptable for batch prototype endpoints, but Telegram and web chat benefit from live token streaming).
- **Current Status:** Phase 12 uses non-streaming `AsyncGroq.chat.completions.create` to ensure complete JSON schema validation before returning results.
- **Evidence Required:** SSE (Server-Sent Events) in FastAPI (Phase 15) or typing animation / edit-message in Telegram (Phase 16).
- **Recommended Phase:** Phase 15 (FastAPI Backend) & Phase 16 (Telegram Bot).

---

### P12-03: Multi-Turn Dialogue Context & Clarification Feedback Loop
- **Impact:** LOW for single-turn recommendation; HIGH for multi-turn conversational shopping.
- **Current Status:** Phase 12 accepts single-turn queries and returns self-contained recommendations.
- **Evidence Required:** Session state management schema and chat history summarization.
- **Recommended Phase:** Phase 15–16.

---

### P12-04: Multi-Annotator Blind Quality Evaluation
- **Impact:** MEDIUM.
- **Current Status:** Preliminary evaluation verified 7 scenarios with 100% groundedness pass rate and zero cross-product hallucinations, reviewed by the engineering team.
- **Evidence Required:** Double-annotated human blind evaluation across 50+ diverse user shopping interactions.
- **Recommended Phase:** Phase 14 (End-to-End System Evaluation).

---

### P12-05: Dynamic Provider Pricing Rates
- **Impact:** LOW.
- **Current Status:** Pricing is configured via settings defaults ($0.00 / 1M for `:free` models on OpenRouter, $0.0675 / 1M prompt on standard Gemma 4, $0.075 / $0.30 for Groq).
- **Evidence Required:** Auto-fetching pricing rates from a remote config or cloud billing API.
- **Recommended Phase:** Phase 17 (Monitoring & Cloud Deployment).

---

### P12-06: OpenRouter Upstream Free-Tier Shared Pool Quota Management
- **Impact:** MEDIUM for production; handled cleanly in prototype via deterministic metadata fallbacks.
- **Current Status:** OpenRouter's free route `google/gemma-4-26b-a4b-it:free` shares public Google AI Studio upstream capacity, which intermittently returns HTTP 429 during global traffic surges. Phase 12 handles this cleanly via bounded exponential retries and deterministic catalog metadata fallback (`DETERMINISTIC_FALLBACK`), ensuring zero unhandled exceptions or customer-facing failures. Standard paid routes (`google/gemma-4-26b-a4b-it`) or BYOK (Bring Your Own Key) routes avoid the shared pool.
- **Evidence Required:** Production provider failover chain (OpenRouter free -> OpenRouter paid -> Groq) or dedicated quota allocation.
- **Recommended Phase:** Phase 15 (FastAPI Backend) & Phase 17 (Production Deployment).
