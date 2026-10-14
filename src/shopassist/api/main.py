"""FastAPI application factory and lifecycle management (Phase 15)."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import sys
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shopassist.api.config import APISettings, get_api_settings
from shopassist.api.exceptions import register_exception_handlers
from shopassist.api.middleware.request_context import RequestContextMiddleware
from shopassist.api.routes import health, recommendations
from shopassist.api.services.orchestrator import RecommendationOrchestrator
from shopassist.api.session import InMemorySessionStore
from shopassist.core.config import PROCESSED_DATA_DIR
from shopassist.db.connection import ensure_windows_event_loop_policy, get_async_engine
from shopassist.llm.query_understanding import QueryUnderstandingEngine
from shopassist.preferences.embedding import PreferenceQueryEncoder
from shopassist.preferences.service import PreferenceRepresentationService
from shopassist.recommendation.core import RecommendationService
from shopassist.reranking.core import load_canonical_product_texts, RerankingService
from shopassist.retrieval.hybrid import HybridRetrievalService
from shopassist.retrieval.semantic import DenseQueryEncoder
from shopassist.retrieval.tfidf import DEFAULT_TFIDF_ARTIFACT_DIR, TFIDFIndex

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup, shared singleton resource allocation, and clean shutdown."""
    settings = getattr(app.state, "settings", None) or get_api_settings()

    logger.info("Initializing ShopAssist backend services and model assets...")
    ensure_windows_event_loop_policy()

    # 1. Database AsyncEngine
    engine = get_async_engine(pool_size=5, max_overflow=2, pool_pre_ping=True)
    app.state.engine = engine

    # 2. Local TF-IDF Retrieval Index
    tfidf_path = DEFAULT_TFIDF_ARTIFACT_DIR
    if tfidf_path.exists():
        tfidf_index = TFIDFIndex.load(tfidf_path)
        logger.info("Loaded TFIDFIndex with %d product documents.", len(tfidf_index.product_ids))
    else:
        logger.warning("TF-IDF directory %s does not exist; creating unfitted index.", tfidf_path)
        tfidf_index = TFIDFIndex()
    app.state.tfidf_index = tfidf_index

    # 3. Dense Query Encoder (BGE Embedding Model)
    # Reused across Phase 9 and Phase 10 to avoid redundant weights loading
    logger.info("Initializing shared DenseQueryEncoder (BAAI/bge-small-en-v1.5)...")
    dense_query_encoder = DenseQueryEncoder()
    app.state.query_encoder = dense_query_encoder

    # 4. Canonical Product Text Provider (Phase 11 & Phase 12 text handoff)
    products_parquet_path = PROCESSED_DATA_DIR / "products.parquet"
    if products_parquet_path.exists():
        product_text_provider = load_canonical_product_texts(str(products_parquet_path))
        logger.info(
            "Loaded canonical ProductTextProvider with %d products.",
            len(product_text_provider.texts),
        )
    else:
        logger.warning("Products Parquet file %s missing.", products_parquet_path)
        from shopassist.reranking.core import MappingProductTextProvider
        product_text_provider = MappingProductTextProvider(texts={})
    app.state.product_text_provider = product_text_provider

    # 5. Core Pipeline Services
    query_engine = QueryUnderstandingEngine()
    pref_encoder = PreferenceQueryEncoder(dense_query_encoder=dense_query_encoder)
    preference_service = PreferenceRepresentationService(encoder=pref_encoder)
    hybrid_service = HybridRetrievalService(
        engine=engine,
        tfidf_index=tfidf_index,
        query_encoder=dense_query_encoder,
    )
    reranking_service = RerankingService(text_provider=product_text_provider)
    recommendation_service = RecommendationService()

    app.state.query_engine = query_engine
    app.state.preference_service = preference_service
    app.state.hybrid_service = hybrid_service
    app.state.reranking_service = reranking_service
    app.state.recommendation_service = recommendation_service

    # 6. Session Manager (Phase 16 Telegram integration foundation)
    session_store = InMemorySessionStore(
        ttl_seconds=settings.api_session_ttl_seconds,
        max_messages=settings.api_session_max_messages,
    )
    app.state.session_store = session_store

    # 7. Orchestrator Singleton
    orchestrator = RecommendationOrchestrator(
        query_engine=query_engine,
        preference_service=preference_service,
        hybrid_service=hybrid_service,
        reranking_service=reranking_service,
        recommendation_service=recommendation_service,
        session_store=session_store,
        settings=settings,
    )
    app.state.orchestrator = orchestrator

    logger.info("ShopAssist backend startup complete. All pipeline stages ready.")

    yield

    # Teardown & Resource Disposal on Shutdown
    logger.info("Shutting down ShopAssist backend; releasing resources...")

    # Close query understanding client
    if hasattr(query_engine, "_client") and query_engine._client is not None:
        try:
            await query_engine._client.aclose()
        except Exception as exc:
            logger.debug("Error closing GeminiClient: %s", exc)

    # Close recommendation provider HTTP client
    provider = getattr(recommendation_service, "provider", None)
    if provider is not None and hasattr(provider, "_http_client"):
        http_client = getattr(provider, "_http_client", None)
        if http_client is not None:
            try:
                await http_client.aclose()
            except Exception as exc:
                logger.debug("Error closing OpenRouterProvider client: %s", exc)

    # Dispose database engine pool
    if engine is not None:
        try:
            await engine.dispose()
            logger.info("Database AsyncEngine connection pool disposed.")
        except Exception as exc:
            logger.debug("Error disposing database engine: %s", exc)

    logger.info("ShopAssist backend shutdown complete.")


def create_app(settings: APISettings | None = None) -> FastAPI:
    """Application factory building and configuring the FastAPI backend."""
    cfg = settings or get_api_settings()

    app = FastAPI(
        title="ShopAssist AI Recommendation API",
        version="0.1.0",
        description=(
            "Production-grade conversational e-commerce product recommendation backend. "
            "Integrates LLM Query Understanding, Soft Preference Representation, "
            "Hybrid pgvector + TF-IDF Retrieval, Reranking, and Grounded Recommendation Generation."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.state.settings = cfg

    # Register custom exception handlers
    register_exception_handlers(app)

    # Register middlewares (order: outermost to innermost)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include Versioned Routers (/api/v1)
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(recommendations.router, prefix="/api/v1")

    # Backward-compatible root alias for recommendations (/recommend)
    app.include_router(
        recommendations.router,
        prefix="",
        tags=["Recommendations (Root Alias)"],
        include_in_schema=True,
    )

    return app


# Module-level ASGI app for uvicorn
app = create_app()


def main() -> None:
    """CLI entry point ensuring proper event loop policy on Windows."""
    import uvicorn
    ensure_windows_event_loop_policy()
    cfg = get_api_settings()
    loop_arg = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "asyncio"
    uvicorn.run("shopassist.api.main:app", host=cfg.api_host, port=cfg.api_port, loop=loop_arg)


if __name__ == "__main__":
    main()
