# Phase 15 — Deferred Issues & Technical Debt Register

**Creation Date:** 2026-10-14  
**Status:** **REGISTERED / TRACKED**  
**Component:** `shopassist.api`  

---

## 1. Overview

Phase 15 has successfully delivered the FastAPI backend, request validation, lifespan resource management, price boundary semantics adapter, short-circuit orchestration, and public API contracts. To preserve architectural simplicity, educational clarity, and maintain strict phase boundaries, the following non-blocking technical debt items and future enhancements have been cataloged and deferred to subsequent phases.

---

## 2. Technical Debt Register

### P15-01: Multi-Turn Context-Aware Query Reformulation
- **Impact:** MEDIUM (Single-turn recommendation is 100% functional; multi-turn follow-up queries like "Show me the second one in blue" currently require explicit phrasing).
- **Current Behavior:** `InMemorySessionStore` records conversational turns with TTL bounding, but `RecommendationOrchestrator` deliberately does not guess or inject stale constraints into follow-up queries, preserving hard-constraint invariants.
- **Recommended Solution:** Implement a contextual query re-writer in Phase 16 that takes recent conversation history and reformulates follow-up queries into self-contained product requests before dispatching to Phase 8.
- **Target Phase:** Phase 16 (Telegram Bot & Conversational Management).

---

### P15-02: Server-Sent Events (SSE) Live Token Streaming
- **Impact:** LOW for REST prototype; MEDIUM for web chat interfaces.
- **Current Behavior:** The `/api/v1/recommend` endpoint awaits full LLM completion and JSON schema validation before returning the structured response (1.2–2.0s warm latency).
- **Recommended Solution:** Introduce an alternative streaming endpoint `POST /api/v1/recommend/stream` using `StreamingResponse` with Server-Sent Events (SSE) for incremental token display.
- **Target Phase:** Phase 16 / Phase 17.

---

### P15-03: Distributed Session Storage (Redis) for Multi-Worker Deployments
- **Impact:** LOW for single-process prototype; MEDIUM for horizontally scaled Kubernetes/Docker production.
- **Current Behavior:** `InMemorySessionStore` uses in-process Python memory with asyncio locks. In a multi-worker Uvicorn deployment (`uvicorn --workers 4`), requests for the same session could land on different worker processes.
- **Recommended Solution:** Implement a Redis-backed session adapter adhering to the same interface when horizontal scaling is introduced.
- **Target Phase:** Phase 17 (Containerization & Deployment).

---

### P15-04: Client-Level Rate Limiting & API Key Authentication
- **Impact:** LOW (ShopAssist is intended for trusted local prototyping and Telegram Bot backend).
- **Current Behavior:** Endpoints are unauthenticated; CORS origins are restricted to localhost and configured domains.
- **Recommended Solution:** Add slowapi / token-bucket rate limiter middleware and optional Bearer API key authentication.
- **Target Phase:** Phase 17 (Production Readiness).

---

### P15-05: Upstream Multi-Provider Dynamic Failover Chain
- **Impact:** LOW (Deterministic fallback already handles provider rate-limit failures safely).
- **Current Behavior:** If OpenRouter returns HTTP 429, Phase 12 automatically switches to `DETERMINISTIC_FALLBACK` (rule-based grounded summary).
- **Recommended Solution:** Implement a dynamic provider failover router (OpenRouter free -> OpenRouter paid -> Groq -> Deterministic fallback) before falling back to rule-based generation.
- **Target Phase:** Phase 16 / Phase 17.
