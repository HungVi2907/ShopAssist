"""Real end-to-end integration smoke tests for ShopAssist FastAPI backend (Phase 15).

Exercises the full live pipeline:
FastAPI -> Gemini (Phase 8) -> BGE (Phase 9) -> Supabase PostgreSQL/pgvector + TF-IDF (Phase 10)
-> RRF Reranking (Phase 11) -> OpenRouter / Groq (Phase 12) -> Structured JSON Response.

Opt-in via:
    pytest tests/test_api_real_smoke.py -v
or
    set SHOPASSIST_PHASE15_LIVE_TEST=1
"""

from __future__ import annotations

import asyncio
import functools
import os
from httpx import ASGITransport, AsyncClient
import pytest

from shopassist.api.main import create_app
from shopassist.core.config import PROCESSED_DATA_DIR, settings as core_settings
from shopassist.llm.config import get_llm_settings
from shopassist.recommendation.config import get_recommendation_settings


def async_test(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapped


def check_live_prerequisites() -> tuple[bool, str]:
    """Check whether all live environment credentials and local assets exist."""
    # 1. DB URL
    if not core_settings.supabase_db_url or not core_settings.supabase_db_url.strip():
        return False, "SUPABASE_DB_URL is not configured."

    # 2. Gemini API Key
    llm_settings = get_llm_settings()
    if not llm_settings.gemini_api_key or not llm_settings.gemini_api_key.strip():
        return False, "GEMINI_API_KEY is not configured."

    # 3. Recommendation API Key
    rec_settings = get_recommendation_settings()
    api_key = rec_settings.get_api_key()
    if not api_key or not api_key.strip():
        return False, f"API key for {rec_settings.phase12_llm_provider} is not configured."

    # 4. Local artifacts
    tfidf_dir = PROCESSED_DATA_DIR / "tfidf"
    if not tfidf_dir.exists():
        return False, f"TF-IDF directory {tfidf_dir} is missing."

    parquet_file = PROCESSED_DATA_DIR / "products.parquet"
    if not parquet_file.exists():
        return False, f"Products Parquet {parquet_file} is missing."

    return True, "Ready"


has_prereqs, prereq_reason = check_live_prerequisites()
live_flag = os.getenv("SHOPASSIST_PHASE15_LIVE_TEST", "0").lower() in ("1", "true", "yes")
skip_reason = None if (has_prereqs and live_flag) else (prereq_reason if not has_prereqs else "Live smoke test is opt-in (set SHOPASSIST_PHASE15_LIVE_TEST=1)")

pytestmark = pytest.mark.live_api


@pytest.mark.skipif(skip_reason is not None, reason=str(skip_reason))
@async_test
async def test_live_health_endpoint():
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/v1/health")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["components"]["database"] == "healthy"
    assert data["components"]["tfidf"] == "ready"
    assert data["components"]["embedding"] == "ready"
    assert "configured" in data["components"]["query_understanding"]
    assert "configured" in data["components"]["recommendation_provider"]


@pytest.mark.skipif(skip_reason is not None, reason=str(skip_reason))
@async_test
async def test_live_recommendation_with_hard_constraint():
    """Scenario 1: Verified hard constraint (Puma running shoes under 3000 INR)."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "query": "Puma running shoes under 3000 INR",
                "top_k": 3,
                "language": "en",
                "session_id": "live-smoke-hard-constraint",
            }
            res = await client.post("/api/v1/recommend", json=payload)

    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("SUCCESS", "DETERMINISTIC_FALLBACK")
    assert len(data["products"]) > 0
    assert len(data["products"]) <= 3

    # Invariant checks:
    for prod in data["products"]:
        # Constraint checks: max_price < 3000
        assert prod["discounted_price"] < 3000.0
        # Brand constraint
        if prod["brand"]:
            assert "puma" in prod["brand"].lower()
        # Catalog ID
        assert len(prod["product_id"]) > 0
        # Non-empty summary reason
        assert len(prod["summary_reason"]) > 0

    assert data["usage"]["total_latency_ms"] > 0
    assert data["usage"]["total_tokens"] >= 0


@pytest.mark.skipif(skip_reason is not None, reason=str(skip_reason))
@async_test
async def test_live_recommendation_without_price_constraint():
    """Scenario 2: Query without price constraints (wireless bluetooth headphones)."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "query": "wireless bluetooth headphones",
                "top_k": 3,
                "language": "en",
            }
            res = await client.post("/api/v1/recommend", json=payload)

    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("SUCCESS", "DETERMINISTIC_FALLBACK")
    assert len(data["products"]) > 0


@pytest.mark.skipif(skip_reason is not None, reason=str(skip_reason))
@async_test
async def test_live_recommendation_no_soft_preferences():
    """Scenario 3: Direct product lookup with no soft preferences (Samsung mobile phone)."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "query": "Samsung mobile phone",
                "top_k": 3,
                "language": "en",
            }
            res = await client.post("/api/v1/recommend", json=payload)

    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("SUCCESS", "DETERMINISTIC_FALLBACK")
    assert len(data["products"]) > 0


@pytest.mark.skipif(skip_reason is not None, reason=str(skip_reason))
@async_test
async def test_live_recommendation_vietnamese_query():
    """Scenario 4: Vietnamese shopping query."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "query": "giày chạy bộ Puma dưới 3000 INR",
                "top_k": 3,
                "language": "vi",
            }
            res = await client.post("/api/v1/recommend", json=payload)

    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("SUCCESS", "DETERMINISTIC_FALLBACK")
    assert len(data["products"]) > 0
    # Price constraint check
    for prod in data["products"]:
        assert prod["discounted_price"] < 3000.0


@pytest.mark.skipif(skip_reason is not None, reason=str(skip_reason))
@async_test
async def test_live_clarification_safeguard():
    """Scenario 5: Ambiguous query safely halts at clarification."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "query": "recommend something nice",
                "top_k": 3,
            }
            res = await client.post("/api/v1/recommend", json=payload)

    assert res.status_code == 200
    data = res.json()
    # Ambiguous query must halt with CLARIFICATION_REQUIRED and 0 products
    assert data["status"] == "CLARIFICATION_REQUIRED"
    assert len(data["products"]) == 0
    assert len(data["overview"]) > 0
