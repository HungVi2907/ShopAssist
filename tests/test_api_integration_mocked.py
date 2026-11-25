"""API integration tests using httpx.AsyncClient and mock dependencies (Phase 15).

Verifies HTTP status codes, headers, response schemas, error handlers,
and all 18 edge-case scenarios required by Phase 15.
"""

from __future__ import annotations

import asyncio
import functools
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient
import pytest

from shopassist.api.config import APISettings
from shopassist.api.dependencies import get_orchestrator
from shopassist.api.main import create_app
from shopassist.api.schemas import (
    ProductClaimItem,
    ProductEvidenceItem,
    ProductResponseItem,
    RecommendationMetadata,
    RecommendationResponse,
    RecommendationUsage,
)
from shopassist.llm_gateway.errors import ErrorCategory, GatewayError, ReasonCode


def async_test(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapped


@pytest.fixture
def test_app():
    settings = APISettings(api_request_timeout_seconds=2.0)
    app = create_app(settings=settings)
    app.state.orchestrator = MagicMock()
    return app


@async_test
async def test_recommend_success_scenario(test_app):
    mock_orchestrator = MagicMock()
    mock_response = RecommendationResponse(
        request_id="req-12345",
        status="SUCCESS",
        overview="Here are your top recommended running shoes.",
        products=[
            ProductResponseItem(
                product_id="PUMA001",
                product_name="Puma Nitro Runner",
                brand="Puma",
                category="Footwear",
                discounted_price=2499.0,
                rating=4.5,
                summary_reason="Lightweight running shoe within budget.",
                strengths=[ProductClaimItem(claim="Responsive foam", evidence_ids=["PUMA001-E1"])],
                limitations=[],
                available_evidence=[ProductEvidenceItem(evidence_id="PUMA001-E1", source_field="specifications", text="Nitro foam")],
            )
        ],
        metadata=RecommendationMetadata(
            recommended_count=1,
            retrieval_method="HYBRID_RRF",
            reranking_method="RRF",
            fallback_used=False,
            session_id="sess-abc",
        ),
        usage=RecommendationUsage(
            total_tokens=250,
            prompt_tokens=180,
            completion_tokens=70,
            estimated_cost_usd=0.0,
            total_latency_ms=350.0,
        ),
    )
    mock_orchestrator.orchestrate = AsyncMock(return_value=mock_response)
    test_app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "query": "Puma running shoes under 3000 INR",
            "top_k": 5,
            "language": "en",
            "session_id": "sess-abc",
        }
        res = await client.post("/api/v1/recommend", json=payload)

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert len(data["products"]) == 1
    assert data["products"][0]["product_id"] == "PUMA001"
    assert "X-Request-ID" in res.headers
    assert "X-Response-Time-MS" in res.headers
    forwarded = mock_orchestrator.orchestrate.await_args.kwargs
    assert forwarded["request_id"] == res.headers["X-Request-ID"]
    assert forwarded["parent_deadline_mono"] > asyncio.get_running_loop().time() - 10


@async_test
async def test_parent_gateway_deadline_maps_to_504(test_app):
    mock_orchestrator = MagicMock()
    mock_orchestrator.orchestrate = AsyncMock(side_effect=GatewayError(
        request_id="internal", task_id="task",
        category=ErrorCategory.DEADLINE_EXCEEDED,
        reason_code=ReasonCode.DEADLINE_EXCEEDED,
        source="deadline", deadline_scope="parent",
    ))
    test_app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.post("/api/v1/recommend", json={"query": "shoes"})

    assert response.status_code == 504
    assert "Gateway Timeout" in response.json()["error"]


@async_test
async def test_recommend_root_alias_backward_compatibility(test_app):
    mock_orchestrator = MagicMock()
    mock_response = RecommendationResponse(
        request_id="req-alias",
        status="SUCCESS",
        overview="Root alias test.",
        products=[],
    )
    mock_orchestrator.orchestrate = AsyncMock(return_value=mock_response)
    test_app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/recommend", json={"query": "shoes", "top_k": 3})

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"


@async_test
async def test_recommend_empty_query_returns_422(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/recommend", json={"query": "   "})

    assert res.status_code == 422
    data = res.json()
    assert "Unprocessable Request" in data["error"]
    assert "X-Request-ID" in res.headers


@async_test
async def test_recommend_excessive_query_length_returns_422(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/recommend", json={"query": "a" * 501})

    assert res.status_code == 422


@async_test
async def test_recommend_invalid_top_k_returns_422(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/recommend", json={"query": "shoes", "top_k": 0})
        assert res.status_code == 422

        res2 = await client.post("/api/v1/recommend", json={"query": "shoes", "top_k": 25})
        assert res2.status_code == 422


@async_test
async def test_recommend_unsupported_extra_field_returns_422(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/recommend", json={"query": "shoes", "malicious_field": True})

    assert res.status_code == 422


@async_test
async def test_recommend_clarification_required_business_status(test_app):
    mock_orchestrator = MagicMock()
    mock_response = RecommendationResponse(
        request_id="req-clarify",
        status="CLARIFICATION_REQUIRED",
        overview="Please specify category.",
        products=[],
    )
    mock_orchestrator.orchestrate = AsyncMock(return_value=mock_response)
    test_app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/recommend", json={"query": "something good"})

    assert res.status_code == 200
    assert res.json()["status"] == "CLARIFICATION_REQUIRED"


@async_test
async def test_recommend_unsupported_intent_business_status(test_app):
    mock_orchestrator = MagicMock()
    mock_response = RecommendationResponse(
        request_id="req-unsupp",
        status="UNSUPPORTED_INTENT",
        overview="Foreign currencies unsupported.",
        products=[],
    )
    mock_orchestrator.orchestrate = AsyncMock(return_value=mock_response)
    test_app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/recommend", json={"query": "laptop under 500 USD"})

    assert res.status_code == 200
    assert res.json()["status"] == "UNSUPPORTED_INTENT"


@async_test
async def test_recommend_no_results_business_status(test_app):
    mock_orchestrator = MagicMock()
    mock_response = RecommendationResponse(
        request_id="req-no-res",
        status="NO_RESULTS",
        overview="No matching products found.",
        products=[],
    )
    mock_orchestrator.orchestrate = AsyncMock(return_value=mock_response)
    test_app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/recommend", json={"query": "rare item xyz"})

    assert res.status_code == 200
    assert res.json()["status"] == "NO_RESULTS"


@async_test
async def test_recommend_deterministic_fallback_business_status(test_app):
    mock_orchestrator = MagicMock()
    mock_response = RecommendationResponse(
        request_id="req-fallback",
        status="DETERMINISTIC_FALLBACK",
        overview="Catalog recommendations generated via fallback.",
        products=[
            ProductResponseItem(
                product_id="PROD99",
                product_name="Basic Shoes",
                category="Footwear",
                discounted_price=1200.0,
                summary_reason="Priced within budget.",
            )
        ],
        metadata=RecommendationMetadata(recommended_count=1, fallback_used=True),
    )
    mock_orchestrator.orchestrate = AsyncMock(return_value=mock_response)
    test_app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/recommend", json={"query": "shoes under 2000"})

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "DETERMINISTIC_FALLBACK"
    assert data["metadata"]["fallback_used"] is True
    assert len(data["products"]) == 1


@async_test
async def test_recommend_timeout_returns_504(test_app):
    from shopassist.api.dependencies import get_settings
    tiny_settings = APISettings(api_request_timeout_seconds=0.05)
    test_app.dependency_overrides[get_settings] = lambda: tiny_settings

    async def slow_orchestration(*args, **kwargs):
        await asyncio.sleep(0.3)
        return RecommendationResponse(request_id="t", status="SUCCESS", overview="", products=[])

    mock_orchestrator = MagicMock()
    mock_orchestrator.orchestrate = slow_orchestration
    test_app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/recommend", json={"query": "shoes"})

    assert res.status_code == 504
    data = res.json()
    assert "Gateway Timeout" in data["error"]


@async_test
async def test_recommend_unhandled_exception_returns_500_sanitized(test_app):
    mock_orchestrator = MagicMock()
    mock_orchestrator.orchestrate = AsyncMock(
        side_effect=RuntimeError("SecretDatabasePassword: 12345 failed to connect")
    )
    test_app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/recommend", json={"query": "shoes"})

    assert res.status_code == 500
    data = res.json()
    assert data["error"] == "Internal Server Error"
    # Secrets/credentials must NOT be leaked in error message
    assert "SecretDatabasePassword" not in str(data)


@async_test
async def test_concurrent_recommendation_requests(test_app):
    mock_orchestrator = MagicMock()

    async def mock_call(request, request_id, parent_deadline_mono=None):
        await asyncio.sleep(0.01)
        return RecommendationResponse(
            request_id=request_id,
            status="SUCCESS",
            overview=f"Handled {request.query}",
            products=[],
            metadata=RecommendationMetadata(session_id=request.session_id),
        )

    mock_orchestrator.orchestrate = mock_call
    test_app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tasks = [
            client.post("/api/v1/recommend", json={"query": f"query {i}", "session_id": f"sess-{i}"})
            for i in range(5)
        ]
        responses = await asyncio.gather(*tasks)

    for i, res in enumerate(responses):
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "SUCCESS"
        assert f"Handled query {i}" in data["overview"]
        assert data["metadata"]["session_id"] == f"sess-{i}"


@async_test
async def test_health_live_endpoint(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/health/live")

    assert res.status_code == 200
    assert res.json() == {"status": "alive"}


@async_test
async def test_health_readiness_healthy_state(test_app):
    # Mock healthy components on app.state
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_scalar = MagicMock(return_value=1)
    mock_execute = AsyncMock(return_value=MagicMock(scalar=mock_scalar))
    mock_conn.execute = mock_execute

    @functools.wraps(mock_engine.connect)
    def connect_mock():
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_engine.connect = connect_mock
    test_app.state.engine = mock_engine

    mock_tfidf = MagicMock()
    mock_tfidf.is_fitted = True
    test_app.state.tfidf_index = mock_tfidf

    mock_encoder = MagicMock()
    test_app.state.query_encoder = mock_encoder

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/health")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["components"]["database"] == "healthy"
    assert data["components"]["tfidf"] == "ready"
    assert data["components"]["embedding"] == "ready"


@async_test
async def test_health_uses_gateway_local_readiness_without_legacy_settings(test_app, monkeypatch):
    from shopassist.llm_gateway.schemas import TaskType

    engine = MagicMock()
    connection = AsyncMock()
    connection.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=1)))
    context = AsyncMock()
    context.__aenter__ = AsyncMock(return_value=connection)
    context.__aexit__ = AsyncMock(return_value=None)
    engine.connect.return_value = context
    test_app.state.engine = engine
    test_app.state.tfidf_index = MagicMock(is_fitted=True)
    test_app.state.query_encoder = MagicMock()

    gateway = MagicMock()
    gateway.primary_provider.side_effect = lambda task: {
        TaskType.QUERY_UNDERSTANDING: "gemini",
        TaskType.RECOMMENDATION_GENERATION: "openrouter",
    }[task]
    gateway.readiness_snapshot.return_value = {"routes": []}
    test_app.state.gateway = gateway
    monkeypatch.setattr("shopassist.api.routes.health.get_llm_settings", lambda: pytest.fail("legacy settings read"))
    monkeypatch.setattr("shopassist.api.routes.health.get_recommendation_settings", lambda: pytest.fail("legacy settings read"))

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    components = response.json()["components"]
    assert components["query_understanding"] == "configured (gemini)"
    assert components["recommendation_provider"] == "configured (openrouter)"
    gateway.primary_provider.assert_any_call(TaskType.QUERY_UNDERSTANDING)
    gateway.primary_provider.assert_any_call(TaskType.RECOMMENDATION_GENERATION)
    gateway.readiness_snapshot.assert_called_once_with()


@async_test
async def test_health_readiness_degraded_when_db_fails(test_app):
    mock_engine = MagicMock()

    def connect_fail():
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("DB connection refused"))
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    mock_engine.connect = connect_fail
    test_app.state.engine = mock_engine

    mock_tfidf = MagicMock()
    mock_tfidf.is_fitted = True
    test_app.state.tfidf_index = mock_tfidf
    test_app.state.query_encoder = MagicMock()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/health")

    assert res.status_code == 503
    data = res.json()
    assert data["status"] == "degraded"
    assert data["components"]["database"] == "unhealthy"


@pytest.mark.parametrize("stall_stage", ["connect", "query"])
@async_test
async def test_health_readiness_times_out_database_probe(test_app, monkeypatch, stall_stage):
    monkeypatch.setattr(
        "shopassist.api.routes.health.DATABASE_PROBE_TIMEOUT_SECONDS", 0.01
    )
    cancelled = asyncio.Event()

    async def stall(*args, **kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=stall) if stall_stage == "query" else AsyncMock()
    context = AsyncMock()
    context.__aenter__ = (
        AsyncMock(side_effect=stall) if stall_stage == "connect" else AsyncMock(return_value=connection)
    )
    engine = MagicMock()
    engine.connect.return_value = context
    test_app.state.engine = engine
    test_app.state.tfidf_index = MagicMock(is_fitted=True)
    test_app.state.query_encoder = MagicMock()

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        response = await asyncio.wait_for(client.get("/api/v1/health"), timeout=1.0)

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["components"]["database"] == "unhealthy"
    assert cancelled.is_set()
    if stall_stage == "connect":
        connection.execute.assert_not_called()
    else:
        context.__aexit__.assert_awaited_once()
