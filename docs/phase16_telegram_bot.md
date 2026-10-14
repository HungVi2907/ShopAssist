# Phase 16 — Telegram Bot Integration & Conversational Interface

**Date:** 2026-10-15  
**Version:** 1.0.0  
**Component:** `shopassist.bot`  
**Status:** IMPLEMENTED (PENDING LIVE USER VALIDATION)  

---

## 1. Overview

Phase 16 delivers a production-grade Telegram conversational interface for ShopAssist. The Telegram Bot acts as an independent, lightweight presentation and integration layer connecting Telegram users with the Phase 15 FastAPI backend (`http://127.0.0.1:8000`).

The bot accepts natural language shopping queries in English and Vietnamese, communicates with the backend over asynchronous HTTP, presents grounded product recommendations with rich HTML formatting, price tags in Indian Rupees (INR), ratings, verified strengths, limitations, and catalog image/URL links, and handles all network transport and business stop-states gracefully.

---

## 2. Architecture & Data Flow

```mermaid
graph TD
    User([Telegram User])
    TGCloud[Telegram Cloud Server]
    BotApp["ShopAssist Telegram Bot<br/>(python -m shopassist.bot.main)"]
    SessionMgr["BotSessionManager<br/>(Per-Chat Isolation & Locks)"]
    Formatter["Telegram Response Formatter<br/>(HTML Escaping & Card Layout)"]
    HTTPClient["FastAPIRecommendationClient<br/>(httpx.AsyncClient / Pool)"]
    FastAPI["FastAPI Backend<br/>(POST /api/v1/recommend)"]
    Orchestrator["RecommendationOrchestrator<br/>(Phases 8–12 Pipeline)"]
    CatalogDB[("Supabase PostgreSQL<br/>+ pgvector")]

    User <-->|HTTPS / Messages| TGCloud
    TGCloud <-->|Long Polling / getUpdates| BotApp
    BotApp --> SessionMgr
    BotApp --> HTTPClient
    HTTPClient <-->|POST /api/v1/recommend| FastAPI
    FastAPI --> Orchestrator
    Orchestrator <-->|Hybrid Retrieval & Catalog Metadata| CatalogDB
    FastAPI -->> HTTPClient: Structured RecommendationResponse
    HTTPClient -->> BotApp: Typed Pydantic Response
    BotApp --> Formatter
    Formatter -->> BotApp: Rendered HTML Cards & Photos
    BotApp -->> TGCloud: send_photo / send_message
```

### 2.1. Strict Architectural Boundaries
- **No Direct AI Pipeline Duplication:** The bot never imports PyTorch, SentenceTransformers, BGE embedding weights, TF-IDF matrices, or Gemini/OpenRouter API clients directly.
- **No Direct Database Access:** The bot never queries Supabase PostgreSQL or pgvector directly.
- **Single Source of Truth:** FastAPI remains the sole owner of AI orchestration, semantic parsing, constraint validation, and recommendation generation.
- **Local Network Boundary:** The bot interacts with FastAPI locally on `http://127.0.0.1:8000`. No public domain, reverse proxy, or ngrok tunnel is required.

---

## 3. Package Structure & Components

```
src/shopassist/bot/
├── __init__.py               # Package metadata and exports
├── config.py                 # BotSettings with Pydantic validation and token masking
├── application.py            # ApplicationBuilder factory and shutdown lifecycle
├── main.py                   # Main CLI entry point: python -m shopassist.bot.main
├── session.py                # BotSessionManager: session nonces and per-chat asyncio locks
├── clients/
│   ├── __init__.py           # Client exports and custom exceptions
│   └── recommendation.py     # FastAPIRecommendationClient with httpx.AsyncClient
├── formatters/
│   ├── __init__.py           # Formatter exports
│   └── products.py           # HTML cards, escaping, claim formatting, status rendering
└── handlers/
    ├── __init__.py           # Handler exports
    ├── commands.py           # /start, /help, /reset command logic
    └── messages.py           # Text query dispatcher, typing indicator, error handling
```

### 3.1. Component Responsibilities
- **`BotSettings` (`config.py`):** Reads environment variables (`TELEGRAM_BOT_TOKEN`, `SHOPASSIST_API_URL`, `BOT_REQUEST_TIMEOUT_SECONDS`, `BOT_DEFAULT_TOP_K`, `BOT_DEFAULT_LANGUAGE`, `BOT_LOG_LEVEL`). Validates token syntax and guarantees that `__repr__` and logs never reveal raw credentials.
- **`FastAPIRecommendationClient` (`clients/recommendation.py`):** Reusable async HTTP client using connection pooling. Serializes validated `RecommendationRequest` payloads, enforces timeouts with transport margins (default 95.0s against backend 90s timeout), validates incoming JSON against `RecommendationResponse`, and translates HTTP errors into typed exceptions (`BackendConnectionError`, `BackendTimeoutError`, `BackendResponseError`, `BackendSchemaError`).
- **`formatters/products.py`:** Formats product cards into Telegram HTML mode (`ParseMode.HTML`). Strictly sanitizes all input strings using `html.escape`, preserves catalog INR currency format (`₹{price:,.0f} INR`), displays ratings (`⭐ 4.2/5.0` or `⭐ Not rated`), lists verified strengths with citations and limitations, embeds external catalog links (`<a href="...">`), and splits messages that exceed Telegram length limits (4000 characters).
- **`BotSessionManager` (`session.py`):** Maintains per-chat session isolation (`tg_{chat_id}_{nonce}`). Provides atomic per-chat `asyncio.Lock` to eliminate race conditions from concurrent message updates. Implements session rotation on `/reset`.
- **`handlers/messages.py`:** Dispatches text queries, displays background typing indicators (`ChatAction.TYPING`) while FastAPI processes, delivers photos with captions (with automatic fallback to text if photo delivery fails), and translates business stop states and exceptions into user-friendly messages.

---

## 4. Command & Interaction Reference

| Command / Event | Description | Action Taken |
|---|---|---|
| `/start` | Introduces ShopAssist and shows shopping examples. | Returns formatted welcome message with bilingual query suggestions. |
| `/help` | Complete search manual and command guide. | Displays search tips (specifying product, budget in INR, brand) and limitations. |
| `/reset` | Rotates conversation context. | Generates a new session token (`tg_{chat_id}_{new_nonce}`), starting a clean backend turn. |
| *Text Query* | Natural language shopping query (1–500 chars). | Triggers typing indicator, calls `POST /api/v1/recommend`, and returns product cards. |
| *Non-Text Message* | Photos, stickers, voice, audio, files. | Politely informs the user that ShopAssist only accepts text queries. |
| *Group Interaction* | Any update in non-private chat (`group`, `supergroup`). | Silently ignored to protect user conversation privacy. |

---

## 5. Product Presentation & Formatting Specifications

### 5.1. Product Card Layout Example
```html
<b>1. Puma Descendant v3 Running Shoes</b>
🏷️ <i>Brand:</i> Puma | 📁 <i>Category:</i> Footwear
💰 <b>₹2,499 INR</b>  •  ⭐ 4.2/5.0

💡 <i>Why this matches:</i>
Puma running shoe featuring breathable air mesh and durable rubber outsole, comfortably priced under 3000 INR.

✨ <b>Key Strengths:</b>
• Features breathable air mesh upper for ventilation <i>[c1f79f-E2]</i>
• Priced at 2499 INR, satisfying your budget limit under 3000 INR <i>[c1f79f-E4]</i>

⚠️ <b>Limitations & Caveats:</b>
• Waterproof rating is not specified in catalog

🔍 <i>Comparison:</i> More lightweight compared to standard training sneakers.

🔗 <a href="http://www.flipkart.com/puma-descendant-v3...">View Product on Flipkart</a>
```

### 5.2. Presentation Rules
1. **Currency Invariant:** Catalog prices are always denominated in Indian Rupees (`INR` or `₹`). The bot never converts to USD or VND.
2. **Missing Ratings:** Products without a catalog rating display `⭐ Not rated`, never `0.0/5.0`.
3. **Structured Claims:** Claims display the actual factual claim string with evidence citations when available (`[E1, E2]`), rather than raw dictionaries.
4. **URL Validation:** All external links must begin with `http://` or `https://` and have a valid netloc. Unsafe schemes (`javascript:`, `file:`) are rejected.
5. **Image Delivery Fallback:** If Telegram fails to deliver a product image (e.g. broken external URL), the handler catches the exception and immediately falls back to sending the formatted text card, ensuring the recommendation is never lost.

---

## 6. Business Status & Error Mapping

| Response / Error | Category | User-Facing Telegram Message |
|---|---|---|
| `SUCCESS` | Business Status | Overview message followed by individual product cards and images. |
| `DETERMINISTIC_FALLBACK` | Business Status | Notice: `Showing grounded catalog recommendations (standard generation fallback).` followed by catalog cards. |
| `NO_RESULTS` | Business Status | `No Matching Products Found` with advice to relax budget or brand filters. |
| `CLARIFICATION_REQUIRED` | Business Status | `Clarification Needed` displaying `overview` and search tips. |
| `UNSUPPORTED_INTENT` | Business Status | `Unsupported Request` explaining INR currency and lack of negative exclusions. |
| `INVALID_INPUT` | Business Status | `Invalid Query` requesting a valid shopping description. |
| `EMBEDDING_FAILURE` / `RETRIEVAL_FAILURE` | Business Status | `Temporary Catalog Issue` advising the user to try again shortly. |
| `BackendConnectionError` | Network Error | `Backend Connection Unavailable`: Explains that FastAPI backend is unreachable. |
| `BackendTimeoutError` / `504` | Timeout | `Request Timed Out`: Explains that the search pipeline exceeded the timeout limit. |
| `BackendResponseError (422)` | Client Error | `Request Validation Error`: Instructs the user to provide a 1–500 character query. |
| `BackendResponseError (500)` | Server Error | `Backend Error (500)` with sanitized request ID for diagnostics. |

---

## 7. Execution Guide

### 7.1. Prerequisites
Ensure `.env` contains valid credentials:
```ini
TELEGRAM_BOT_TOKEN=8960905170:AAH...your-token
SHOPASSIST_API_URL=http://127.0.0.1:8000
BOT_REQUEST_TIMEOUT_SECONDS=95.0
BOT_DEFAULT_TOP_K=5
BOT_DEFAULT_LANGUAGE=auto
BOT_LOG_LEVEL=INFO
```

### 7.2. Starting the Services

**Terminal 1 — FastAPI Backend:**
```powershell
python -m shopassist.api.main
```
*Note: On Windows, running via `python -m shopassist.api.main` automatically configures `WindowsSelectorEventLoopPolicy` required by psycopg async.*

**Terminal 2 — Telegram Bot:**
```powershell
python -m shopassist.bot.main
```

---

## 8. Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `❌ Polling conflict: Another instance...` | Another polling process is running with the same token. | Run `Get-Process python | Stop-Process` or terminate other bot terminal. |
| `❌ Configuration error: TELEGRAM_BOT_TOKEN must not be empty` | Token missing from `.env`. | Add `TELEGRAM_BOT_TOKEN=<token>` to `.env`. |
| `🔌 Backend Connection Unavailable` | FastAPI backend is not running on port 8000. | Start Terminal 1: `python -m shopassist.api.main`. |
| `psycopg.InterfaceError: ProactorEventLoop` | Uvicorn started with Proactor loop on Windows. | Start backend via `python -m shopassist.api.main` (sets selector loop automatically). |
| `Port 8000 already in use` | A prior Uvicorn instance is still bound to port 8000. | Run `Get-NetTCPConnection -LocalPort 8000` and stop the corresponding process. |
