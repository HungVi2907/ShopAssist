# Lesson 12: Telegram Bot Integration & Conversational Interface Design

**Module:** Advanced AI Engineering & System Integration  
**Component:** `shopassist.bot`  
**Prerequisites:** Lesson 11 (FastAPI Backend & AI Orchestration)  

---

## 1. Introduction & The Presentation Boundary

In modern AI engineering, separating the **Core AI Orchestration Layer** from the **User Presentation Layer** is an essential architectural principle. 

Earlier in ShopAssist (Phases 8–15), we developed complex, multi-stage pipelines:
1. LLM Query Understanding (Phase 8)
2. Soft Preference Representation (Phase 9)
3. Hybrid Vector + Lexical Candidate Retrieval (Phase 10)
4. Candidate Reranking (Phase 11)
5. Grounded Recommendation Generation (Phase 12)
6. Asynchronous RESTful API Backend (Phase 15)

In **Phase 16**, our goal is to build an independent conversational interface using Telegram. A common anti-pattern in early AI projects is coupling the bot directly to the AI components (e.g. importing the LLM clients, database connections, and embedding models inside the bot handlers). 

### Why Keep the Bot Independent?
- **Separation of Concerns:** The bot's job is presentation, session resolution, user interaction, and chat transport. It should not know how embeddings are calculated or how PostgreSQL queries are optimized.
- **Polyglot & Multi-Client Support:** By exposing a clean REST API in Phase 15, the same backend can simultaneously serve a Telegram bot, a Web React app, a mobile app, or automated evaluation benchmarks without altering recommendation logic.
- **Independent Scaling & Reliability:** If Telegram Cloud experiences outages or rate limits, the core recommendation API remains operational. Conversely, if a background AI model worker restarts, the bot can catch the HTTP 503/504 error and present a friendly status message to the user.

---

## 2. Long Polling vs. Webhooks: Transport Trade-Offs

When integrating with Telegram Bot API, there are two primary communication patterns:

```
Pattern A: Long Polling (Local Dev / Prototyping)
Bot (Localhost) ────── Outbound HTTPS /getUpdates ──────> Telegram Cloud
Bot (Localhost) <───── Batch of JSON Updates <─────────── Telegram Cloud

Pattern B: Webhook (Production Deployment)
Telegram Cloud ────── Inbound HTTPS POST /webhook ──────> Nginx / Reverse Proxy ──> Bot
```

| Criterion | Long Polling | Webhook |
|---|---|---|
| **Network Ingress** | Zero ingress required (purely outbound HTTPS). | Requires public IP, domain, and valid SSL/TLS certificate. |
| **Firewall / NAT** | Works behind NAT, home routers, and firewalls. | Requires open inbound port (8443, 443, 80). |
| **Setup Complexity** | Minimal: just supply `TELEGRAM_BOT_TOKEN`. | High: DNS records, reverse proxy, certificate renewal. |
| **Resource Usage** | Continuous polling loop (uses HTTP keep-alive). | Event-driven (invoked only when updates occur). |
| **Concurrency / Conflicts** | Only one active poller per token (conflicts error out). | Highly scalable behind load balancers. |
| **Recommended Use** | Local development, testing, private staging. | High-throughput multi-worker production. |

For Phase 16 local development, **Long Polling** is chosen because it allows complete local execution without exposing developer machines through external tunnels.

---

## 3. Asynchronous HTTP Client Architecture (`httpx.AsyncClient`)

Rather than creating a new HTTP connection for every incoming Telegram message (which introduces high connection handshake latency), we implement a shared client using `httpx.AsyncClient`:

```python
class FastAPIRecommendationClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout_seconds: float = 95.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            headers={"User-Agent": "ShopAssist-TelegramBot/1.0"},
        )
```

### Key Engineering Practices:
1. **Connection Pooling:** `httpx.AsyncClient` keeps a pool of open HTTP/1.1 connections to localhost, dropping request overhead to under 2ms.
2. **Timeout Alignment with Safety Margins:**
   - The FastAPI backend enforces an internal orchestration timeout of **90 seconds** (`API_REQUEST_TIMEOUT_SECONDS=90.0`).
   - The bot client configures an HTTP timeout of **95 seconds** (`BOT_REQUEST_TIMEOUT_SECONDS=95.0`).
   - This 5-second transport margin ensures that if the backend pipeline times out, the backend has enough time to return a structured HTTP 504 JSON response rather than the client abruptly severing the socket.
3. **Graceful Shutdown:** The client implements `aclose()`, which is registered with Telegram application lifecycle hooks (`post_shutdown`) to close active socket connections cleanly when polling stops.

---

## 4. Typed Response Handling & Schema Validation

When consuming responses from an AI backend, never treat JSON payloads as arbitrary dictionaries. If the backend schema evolves or a field is missing, raw dictionary lookups (`data["products"][0]["name"]`) fail with unhandled `KeyError` exceptions.

Instead, validate the response through Pydantic v2 schemas:

```python
try:
    return RecommendationResponse.model_validate(response.json())
except ValidationError as exc:
    logger.error("Backend response failed Pydantic validation: %s", exc)
    raise BackendSchemaError(
        f"Response schema mismatch: {exc.error_count()} errors",
        raw_payload=data,
    ) from exc
```

By validating against `RecommendationResponse`, the bot guarantees that:
- Every field (`product_name`, `discounted_price`, `currency`, `strengths`) has expected types.
- Missing optional fields (`rating`, `comparison_note`, `image`) default safely to `None`.
- Business statuses (`SUCCESS`, `NO_RESULTS`, `CLARIFICATION_REQUIRED`) are strictly typed enums.

---

## 5. Rich Telegram Presentation & Safe HTML Escaping

Telegram supports `MarkdownV2` and `HTML` formatting. In e-commerce applications, **HTML mode is strongly preferred** because product titles and specifications frequently contain characters like `_`, `*`, `[`, `]`, `~`, and `|`, which break MarkdownV2 unless meticulously escaped with backslashes.

### 5.1. Strict HTML Escaping
Every piece of untrusted text (user query, product title, catalog description, evidence text) must be escaped:
```python
def escape_html(text: str | None) -> str:
    if text is None:
        return ""
    return html.escape(str(text).strip(), quote=True)
```

### 5.2. Graceful Plain-Text Fallback
Even with escaping, Telegram Cloud may reject messages containing nested tags or malformed entities with a `400 Bad Request: Can't parse entities`. To prevent messages from being lost:
```python
async def _safe_reply_html(update, context, text: str) -> None:
    chunks = split_telegram_message(text)
    for chunk in chunks:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
            )
        except BadRequest as exc:
            logger.warning("HTML parse error, falling back to plain text: %s", exc)
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=None,  # Plain text fallback
            )
```

### 5.3. Image Delivery Fallbacks
If a catalog image URL is expired or unreachable by Telegram's media crawler, `send_photo` raises an error. The bot catches this exception and falls back to delivering the formatted text card immediately:
```python
if image_url:
    try:
        await context.bot.send_photo(chat_id=chat_id, photo=image_url, caption=card_text, parse_mode=ParseMode.HTML)
    except Exception as img_exc:
        logger.warning("Image delivery failed, falling back to text: %s", img_exc)
        await _safe_reply_html(update, context, card_text)
```

---

## 6. Session Management & Per-User Concurrency Control

### 6.1. Session Isolation
Telegram updates include an `update.effective_chat.id`. To track conversation turns without leaking history across users:
- The bot formats session IDs as `tg_{chat_id}_{nonce}`.
- Every chat gets a distinct, isolated session in FastAPI's `InMemorySessionStore`.
- When the user runs `/reset`, the bot rotates `nonce`, generating a fresh session ID.

### 6.2. Per-Chat Concurrency Locking
If a user rapidly taps "Send" multiple times or submits a new query while an expensive LLM pipeline is still calculating:
- Without concurrency locking, both requests trigger simultaneous LLM inferences, causing out-of-order responses and race conditions in session history.
- With per-chat `asyncio.Lock`, if a search is in progress, the second request immediately receives a friendly notification:
  `⏳ I am already searching for your previous query. Please give me a moment to finish!`

---

## 7. Testing Strategy for Conversational Interfaces

Testing asynchronous bot handlers without relying on live Telegram servers is critical for continuous integration:

1. **Unit Testing Configuration & Formatters:** Verify token validation, secret masking (`masked_token`), HTML escaping, and price formatting in isolation.
2. **Mocking HTTP Client with `httpx.MockTransport`:** Test network failure modes (`ConnectError`, `TimeoutException`, HTTP 422, 500, 504) and schema validation errors without spinning up an actual Uvicorn server.
3. **Mocking Telegram Updates (`unittest.mock.AsyncMock`):** Simulate incoming updates and verify that `context.bot.send_message` or `send_photo` are awaited with expected HTML strings.
4. **Live Verification Sequence:**
   - Verify token with `telegram.Bot(token).get_me()`.
   - Verify backend health with `GET /api/v1/health`.
   - Run end-to-end request through the live backend and verify grounded output.

---

## 8. Summary Checklist for Phase 16

- [x] Independent `shopassist.bot` package structure.
- [x] Zero direct AI or database dependencies in bot code.
- [x] Asynchronous HTTP client calling `POST /api/v1/recommend`.
- [x] Pydantic response validation and typed error handling.
- [x] Robust HTML product cards with verified claims and INR prices.
- [x] External URL validation and image delivery with text fallback.
- [x] Periodic background typing indicator during AI orchestration.
- [x] Per-chat session isolation and concurrency locking.
- [x] 100% automated test coverage across unit and integration suites.
