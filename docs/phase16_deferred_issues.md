# Phase 16 — Deferred Issues & Technical Debt Register

**Creation Date:** 2026-10-15  
**Status:** **REGISTERED / TRACKED**  
**Component:** `shopassist.bot`  

---

## 1. Overview

Phase 16 has delivered a complete Telegram Bot conversational interface, asynchronous HTTP client integration, grounded HTML product formatting, catalog URL/image propagation, per-chat concurrency locking, and safe session rotation. To preserve architectural modularity, maintain strict single-turn grounding invariants, and respect project boundaries, the following non-blocking technical debt items and future enhancements have been cataloged and deferred to Phase 17 (Dockerization & Deployment) or future iterations.

---

## 2. Technical Debt Register

### P16-01: Multi-Turn Context-Aware Query Reformulation (Carried from P15-01)
- **Impact:** MEDIUM (Single-turn shopping queries are 100% operational with stable session logging; implicit follow-up queries like *"Có mẫu nào rẻ hơn không?"* or *"Show me the second one in blue"* require explicit product phrasing).
- **Current Behavior:** `BotSessionManager` passes a stable `session_id` to FastAPI's `InMemorySessionStore`. `RecommendationOrchestrator` records conversational history but deliberately refrains from guessing or carrying over stale constraints into follow-up queries, preserving hard-constraint invariants.
- **Recommended Solution:** Introduce an LLM-based query reformulator that takes the last $N$ turns of session history and produces a self-contained query before dispatching to Phase 8.
- **Target Phase:** Phase 17 / Post-MVP Conversational Enhancement.

---

### P16-02: Production Telegram Webhook Transport with Reverse Proxy
- **Impact:** LOW for single-instance prototype; HIGH for containerized Kubernetes/production deployment.
- **Current Behavior:** The bot uses Telegram Long Polling (`run_polling`), which makes outbound HTTPS requests to Telegram Cloud and requires zero public IP or ingress configuration.
- **Recommended Solution:** In Phase 17 containerization, introduce an optional Webhook mode (`set_webhook`) managed by an Nginx or Traefik reverse proxy with TLS termination.
- **Target Phase:** Phase 17 (Dockerization & Deployment).

---

### P16-03: Telegram Inline Keyboard Buttons & Interactive Pagination
- **Impact:** LOW (Product cards currently render links and detailed claims in clean scrollable messages).
- **Current Behavior:** Recommendations are delivered as sequential cards with direct Flipkart hyperlinks.
- **Recommended Solution:** Implement interactive Telegram inline keyboards (`InlineKeyboardMarkup`) allowing users to tap buttons to view more candidates, request alternative brands, or filter by rating without typing text queries.
- **Target Phase:** Post-MVP UX Enhancement.

---

### P16-04: Distributed Session State & Rate Limiting (Redis)
- **Impact:** LOW for single-process bot; MEDIUM for multi-replica bot deployment.
- **Current Behavior:** `BotSessionManager` uses in-process asyncio locks and memory dicts.
- **Recommended Solution:** Implement Redis-backed distributed locks (`redlock-py`) and token-bucket rate limiters when scaling bot worker instances horizontally.
- **Target Phase:** Phase 17 (Production Readiness).

---

### P16-05: High-Resolution Image Proxy & CDN Caching
- **Impact:** LOW (Primary product image URLs from Flipkart CDN are delivered directly to Telegram).
- **Current Behavior:** The bot passes external Flipkart image URLs to Telegram Cloud (`send_photo`). If Telegram servers cannot resolve a particular third-party image, the bot catches the error and cleanly falls back to text cards.
- **Recommended Solution:** In Phase 17, provide a lightweight local image proxy or caching layer to guarantee image availability even if external CDNs throttle Telegram's crawler.
- **Target Phase:** Phase 17.
