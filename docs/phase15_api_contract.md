# Phase 15 — REST API Specification & Contract Reference

**API Version:** `v1`  
**Contract Version:** `1.0.0`  
**Base URL:** `http://localhost:8000/api/v1`  

---

## 1. Overview & Endpoints

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `POST` | `/api/v1/recommend` | Primary conversational recommendation endpoint. | None (Dev prototype) |
| `POST` | `/recommend` | Backward-compatible root alias for `/api/v1/recommend`. | None |
| `GET` | `/api/v1/health` | Comprehensive readiness probe checking DB, TF-IDF, embeddings, and LLM setup. | None |
| `GET` | `/api/v1/health/live` | Lightweight liveness probe for process monitoring. | None |
| `GET` | `/docs` | Interactive Swagger UI API documentation. | None |
| `GET` | `/redoc` | Interactive ReDoc API documentation. | None |
| `GET` | `/openapi.json` | OpenAPI 3.1 JSON schema specification. | None |

---

## 2. Recommendation Endpoint (`POST /api/v1/recommend`)

### 2.1. Request Schema (`RecommendationRequest`)

```json
{
  "query": "Puma running shoes under 3000 INR",
  "top_k": 5,
  "language": "en",
  "session_id": "telegram-chat-987654321"
}
```

#### Field Specifications:
- `query` (*string, required*): Natural language user shopping query in English or Vietnamese.
  - Length: `1` to `500` characters. Empty or whitespace-only queries are rejected with HTTP 422.
- `top_k` (*integer, optional, default: 5*): Maximum number of recommendations to return.
  - Range: `1` to `20`. Values outside this range are rejected with HTTP 422.
- `language` (*string, optional, default: "auto"*): Preferred response language.
  - Allowed values: `"auto"`, `"en"`, `"vi"`. Other values are rejected with HTTP 422.
- `session_id` (*string, optional, default: null*): Identifier for session tracking and conversation turn logging.
- **Strict Validation Rule:** Extra or unrecognized fields in request body are forbidden (`extra="forbid"`) and rejected with HTTP 422.

---

### 2.2. Response Schema (`RecommendationResponse`)

```json
{
  "request_id": "3ee45430-2ddd-4e81-8d1a-cc240b6274b6",
  "status": "SUCCESS",
  "overview": "Here are 3 top-rated Puma running shoes under 3000 INR from our catalog.",
  "products": [
    {
      "product_id": "c1f79f425bc535492fec793ab908b8b0",
      "product_name": "Puma Descendant v3 Running Shoes",
      "brand": "Puma",
      "category": "Footwear",
      "discounted_price": 2499.0,
      "currency": "INR",
      "rating": 4.2,
      "summary_reason": "Puma running shoe featuring breathable air mesh and durable rubber outsole, comfortably priced under 3000 INR.",
      "strengths": [
        {
          "claim": "Features breathable air mesh upper for ventilation",
          "evidence_ids": ["c1f79f425bc535492fec793ab908b8b0-E2"]
        },
        {
          "claim": "Priced at 2499 INR, satisfying your budget limit under 3000 INR",
          "evidence_ids": ["c1f79f425bc535492fec793ab908b8b0-E4"]
        }
      ],
      "limitations": [
        {
          "claim": "Waterproof rating is not specified in catalog",
          "evidence_ids": []
        }
      ],
      "comparison_note": "More lightweight compared to standard training sneakers.",
      "available_evidence": [
        {
          "evidence_id": "c1f79f425bc535492fec793ab908b8b0-E1",
          "source_field": "product_name",
          "text": "Puma Descendant v3 Running Shoes"
        },
        {
          "evidence_id": "c1f79f425bc535492fec793ab908b8b0-E2",
          "source_field": "description",
          "text": "Air mesh upper provides optimal breathability and comfort."
        },
        {
          "evidence_id": "c1f79f425bc535492fec793ab908b8b0-E4",
          "source_field": "discounted_price",
          "text": "2499.0"
        }
      ]
    }
  ],
  "metadata": {
    "recommended_count": 1,
    "retrieval_method": "HYBRID_RRF",
    "reranking_method": "RRF",
    "fallback_used": false,
    "session_id": "telegram-chat-987654321",
    "applied_constraints": {
      "category": "Footwear",
      "brand": "Puma",
      "max_price": 3000.0,
      "max_inclusive": false
    }
  },
  "usage": {
    "total_tokens": 620,
    "prompt_tokens": 480,
    "completion_tokens": 140,
    "estimated_cost_usd": 0.0,
    "total_latency_ms": 1420.5,
    "stage_latencies_ms": {
      "phase8_query_understanding": 510.2,
      "phase9_preferences": 85.4,
      "phase10_hybrid_retrieval": 120.6,
      "phase11_reranking": 12.1,
      "phase12_recommendation": 692.2
    }
  }
}
```

---

## 3. Business Status Enums & HTTP Status Codes

The API distinguishes between HTTP protocol errors and domain/business workflow outcomes. Successful HTTP communication (HTTP 200) can carry business stop-states:

| Business `status` | HTTP Code | Meaning & Typical Occurrence |
|---|---|---|
| `SUCCESS` | **200** | End-to-end pipeline completed successfully; recommendations grounded and verified. |
| `DETERMINISTIC_FALLBACK` | **200** | Upstream generation hit rate limit or format failure; catalog products safely delivered with template-based grounded summaries (`fallback_used=True`). |
| `NO_RESULTS` | **200** | Query was valid, but no products in the catalog satisfied the combination of hard constraints and filters. |
| `CLARIFICATION_REQUIRED` | **200** | Query is too ambiguous (e.g. "recommend something nice") or price boundary operator is unclear ("around 2000"). Guidance provided in `overview`. |
| `UNSUPPORTED_INTENT` | **200** | Query requested an unsupported currency (non-INR) or negative exclusion semantics (e.g. "no leather"). |
| `INVALID_INPUT` | **200 / 422** | HTTP 422 if JSON schema fails; HTTP 200 with status `INVALID_INPUT` if Phase 8 semantic parser rejects input. |
| `EMBEDDING_FAILURE` | **200** | Neural embedding encoding failed. |
| `RETRIEVAL_FAILURE` | **200 / 503** | Local TF-IDF or pgvector retrieval failed. |
| `SERVICE_UNAVAILABLE` | **503** | Mandatory backend dependency (DB, TF-IDF) is not ready during health check. |
| `GATEWAY_TIMEOUT` | **504** | Total orchestration time exceeded `API_REQUEST_TIMEOUT_SECONDS` (default: 90s). |
| `INTERNAL_SERVER_ERROR`| **500** | Unhandled internal exception; response is sanitized, zero credentials exposed. |

---

## 4. Response Examples

### 4.1. Clarification Required (Ambiguous Query)
**Request:** `{"query": "recommend something good", "top_k": 3}`  
**Response (HTTP 200):**
```json
{
  "request_id": "893c7d6a-6a9b-4497-b956-65be7df84421",
  "status": "CLARIFICATION_REQUIRED",
  "overview": "Your shopping query is very broad. Please specify what type of product you are looking for (e.g., shoes, laptop, headphones).",
  "products": [],
  "metadata": {
    "recommended_count": 0,
    "retrieval_method": "HYBRID_RRF",
    "reranking_method": "RRF",
    "fallback_used": false,
    "session_id": null,
    "applied_constraints": {}
  },
  "usage": {
    "total_tokens": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "estimated_cost_usd": 0.0,
    "total_latency_ms": 380.0,
    "stage_latencies_ms": {
      "phase8_query_understanding": 380.0
    }
  }
}
```

### 4.2. Unsupported Intent (Foreign Currency)
**Request:** `{"query": "Dell laptop under 700 USD", "top_k": 3}`  
**Response (HTTP 200):**
```json
{
  "request_id": "8fa24b55-829d-471a-969c-ea0bf3487c69",
  "status": "UNSUPPORTED_INTENT",
  "overview": "Catalog prices are in INR; currency 'USD' is not supported.",
  "products": [],
  "metadata": {
    "recommended_count": 0,
    "retrieval_method": "HYBRID_RRF",
    "reranking_method": "RRF",
    "fallback_used": false,
    "session_id": null,
    "applied_constraints": {}
  },
  "usage": {
    "total_tokens": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "estimated_cost_usd": 0.0,
    "total_latency_ms": 410.5,
    "stage_latencies_ms": {
      "phase8_query_understanding": 410.5
    }
  }
}
```

### 4.3. Vietnamese Language Request
**Request:** `{"query": "giày chạy bộ Puma dưới 3000 INR", "top_k": 2, "language": "vi"}`  
**Response (HTTP 200):**
```json
{
  "request_id": "4b6de809-5a12-4eb2-a1f0-4560d2e8b61c",
  "status": "SUCCESS",
  "overview": "Dưới đây là 2 mẫu giày chạy bộ Puma chính hãng dưới 3000 INR phù hợp với nhu cầu của bạn.",
  "products": [
    {
      "product_id": "a908b8b0c1f79f425bc535492fec793a",
      "product_name": "Puma Carson Runner",
      "brand": "Puma",
      "category": "Footwear",
      "discounted_price": 2299.0,
      "currency": "INR",
      "rating": 4.3,
      "summary_reason": "Giày chạy bộ Puma êm ái, đệm lót thoáng khí với mức giá 2299 INR rất hợp lý.",
      "strengths": [
        {
          "claim": "Đế đệm giảm chấn tốt cho chạy bộ",
          "evidence_ids": ["a908b8b0c1f79f425bc535492fec793a-E1"]
        }
      ],
      "limitations": [],
      "comparison_note": null,
      "available_evidence": [
        {
          "evidence_id": "a908b8b0c1f79f425bc535492fec793a-E1",
          "source_field": "description",
          "text": "Lightweight injection-moulded EVA midsole provides optimal cushioning."
        }
      ]
    }
  ],
  "metadata": {
    "recommended_count": 1,
    "retrieval_method": "HYBRID_RRF",
    "reranking_method": "RRF",
    "fallback_used": false,
    "session_id": null,
    "applied_constraints": {
      "category": "Footwear",
      "brand": "Puma",
      "max_price": 3000.0,
      "max_inclusive": false
    }
  },
  "usage": {
    "total_tokens": 580,
    "prompt_tokens": 460,
    "completion_tokens": 120,
    "estimated_cost_usd": 0.0,
    "total_latency_ms": 1390.0,
    "stage_latencies_ms": {
      "phase8_query_understanding": 490.0,
      "phase9_preferences": 70.0,
      "phase10_hybrid_retrieval": 110.0,
      "phase11_reranking": 10.0,
      "phase12_recommendation": 710.0
    }
  }
}
```

---

## 5. Health & Readiness Endpoint (`GET /api/v1/health`)

Checks the live readiness state of all internal dependencies without making billable external LLM inference calls.

### 5.1. Healthy Response (HTTP 200)
```json
{
  "status": "healthy",
  "components": {
    "database": "healthy",
    "tfidf": "ready",
    "embedding": "ready",
    "query_understanding": "configured",
    "recommendation_provider": "configured (openrouter)"
  },
  "timestamp": "2026-10-14T15:35:00.123456+00:00"
}
```

### 5.2. Degraded Response (HTTP 503)
If PostgreSQL connection fails or TF-IDF matrix is missing:
```json
{
  "status": "degraded",
  "components": {
    "database": "unhealthy",
    "tfidf": "ready",
    "embedding": "ready",
    "query_understanding": "configured",
    "recommendation_provider": "configured (openrouter)"
  },
  "timestamp": "2026-10-14T15:35:00.123456+00:00"
}
```

---

## 6. Phase 16 Telegram Bot Integration Considerations

The Phase 15 API contract was designed specifically to support direct, seamless integration by the Phase 16 Telegram Bot:

1. **Session Continuity:** The Telegram Bot can pass `session_id: str(update.effective_chat.id)` in every request to maintain conversation history in `InMemorySessionStore`.
2. **Clear Formatting:** The structured `ProductResponseItem` provides all necessary elements to format rich Telegram messages:
   - Product name with markdown bolding
   - Formatted price: `₹{discounted_price:,.0f}`
   - Star rating: `⭐ {rating}/5.0`
   - Bulleted strengths and limitations with citation tags
   - Comparison note for follow-up decision making
3. **Graceful Handling of Stop States:**
   - If `status == "CLARIFICATION_REQUIRED"`, Telegram Bot displays the `overview` as a helpful prompt for the user to refine their query.
   - If `status == "NO_RESULTS"`, Telegram Bot suggests relaxing price or brand filters.
4. **Latency Budget:** The response payload provides full latency telemetry, allowing the Telegram Bot to trigger typing animations (`send_chat_action("typing")`) during the 1–3 second processing window.
