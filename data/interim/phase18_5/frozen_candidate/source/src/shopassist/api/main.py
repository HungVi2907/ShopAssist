"""FastAPI application factory and lifecycle management (Phase 15)."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
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
from shopassist.llm_gateway.adapters.gemini import GeminiAdapter
from shopassist.llm_gateway.adapters.groq import GroqAdapter
from shopassist.llm_gateway.config import GatewaySettings
from shopassist.llm_gateway.gateway import Gateway
from shopassist.llm_gateway.experiment_factory import experiment_schema_bindings
from shopassist.llm_gateway.registry import ProviderRegistry
from shopassist.llm_gateway.schemas import SCHEMA_IDS, TaskType
from shopassist.llm_gateway.telemetry import TelemetrySink
from shopassist.preferences.embedding import PreferenceQueryEncoder
from shopassist.preferences.service import PreferenceRepresentationService
from shopassist.recommendation.core import RecommendationService
from shopassist.recommendation.provider import decode_recommendation_gateway_output
from shopassist.reranking.core import load_canonical_product_texts, RerankingService
from shopassist.retrieval.hybrid import HybridRetrievalService
from shopassist.retrieval.semantic import DenseQueryEncoder
from shopassist.retrieval.tfidf import DEFAULT_TFIDF_ARTIFACT_DIR, TFIDFIndex

logger = logging.getLogger(__name__)


def _build_gateway(settings: GatewaySettings) -> Gateway | None:
    """Validate the configured snapshot before constructing any provider client."""
    if settings.runtime=='ollama_experimental':
        from shopassist.llm_gateway.native_runtime import build_native_gateway
        return build_native_gateway(settings)
    if not settings.enabled:
        return None
    registry = ProviderRegistry(settings, experiment_schema_bindings())
    return Gateway(
        settings,
        registry,
        {
            "gemini": GeminiAdapter(lambda: os.environ.get("GEMINI_API_KEY", "")),
            "gemini_recommendation": GeminiAdapter(lambda: os.environ.get("GEMINI_API_KEY_2", "")),
            "groq": GroqAdapter(lambda: os.environ.get("GROQ_API_KEY", "")),
        },
        decoders={SCHEMA_IDS[TaskType.RECOMMENDATION_GENERATION]: decode_recommendation_gateway_output},
        telemetry=TelemetrySink(settings),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup, shared singleton resource allocation, and clean shutdown."""
    settings = getattr(app.state, "settings", None) or get_api_settings()
    engine = None
    gateway = None
    query_engine = None
    recommendation_service = None
    app.state.gateway = None
    try:
        logger.info("Initializing ShopAssist backend services and model assets...")
        ensure_windows_event_loop_policy()

        # Configuration/evidence is validated before any provider adapter client is created.
        gateway_settings = GatewaySettings()
        gateway = _build_gateway(gateway_settings)
        app.state.gateway = gateway
        native=gateway_settings.runtime=='ollama_experimental'
        if native:
            from shopassist.llm_gateway.native_runtime import verify_native_gateway
            await verify_native_gateway(gateway)

        engine = get_async_engine(pool_size=5, max_overflow=2, pool_pre_ping=True)
        app.state.engine = engine

        tfidf_path = DEFAULT_TFIDF_ARTIFACT_DIR
        if tfidf_path.exists():
            tfidf_index = TFIDFIndex.load(tfidf_path)
            logger.info("Loaded TFIDFIndex with %d product documents.", len(tfidf_index.product_ids))
        else:
            logger.warning("TF-IDF directory %s does not exist; creating unfitted index.", tfidf_path)
            tfidf_index = TFIDFIndex()
        app.state.tfidf_index = tfidf_index

        logger.info("Initializing shared DenseQueryEncoder (BAAI/bge-small-en-v1.5)...")
        dense_query_encoder = DenseQueryEncoder()
        app.state.query_encoder = dense_query_encoder

        products_parquet_path = PROCESSED_DATA_DIR / "products.parquet"
        if products_parquet_path.exists():
            product_text_provider = load_canonical_product_texts(str(products_parquet_path))
            logger.info("Loaded canonical ProductTextProvider with %d products.", len(product_text_provider.texts))
        else:
            logger.warning("Products Parquet file %s missing.", products_parquet_path)
            from shopassist.reranking.core import MappingProductTextProvider
            product_text_provider = MappingProductTextProvider(texts={})
        app.state.product_text_provider = product_text_provider

        query_engine = QueryUnderstandingEngine(gateway=gateway,**({'gateway_native':True} if native else {}))
        pref_encoder = PreferenceQueryEncoder(dense_query_encoder=dense_query_encoder)
        preference_service = PreferenceRepresentationService(encoder=pref_encoder)
        hybrid_service = HybridRetrievalService(engine=engine, tfidf_index=tfidf_index, query_encoder=dense_query_encoder)
        reranking_service = RerankingService(text_provider=product_text_provider)
        if native:
            from shopassist.recommendation.local import LocalRecommendationGenerator
            recommendation_service=RecommendationService(gateway=gateway,local_generator=LocalRecommendationGenerator(gateway=gateway))
        else:
            recommendation_service = RecommendationService(gateway=gateway)

        app.state.query_engine = query_engine
        app.state.preference_service = preference_service
        app.state.hybrid_service = hybrid_service
        app.state.reranking_service = reranking_service
        app.state.recommendation_service = recommendation_service

        session_store = InMemorySessionStore(
            ttl_seconds=settings.api_session_ttl_seconds,
            max_messages=settings.api_session_max_messages,
        )
        app.state.session_store = session_store

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
    finally:
        logger.info("Shutting down ShopAssist backend; releasing resources...")
        if gateway is not None:
            try:
                await gateway.aclose()
            except Exception as exc:
                logger.debug("Error closing LLM Gateway (%s).", type(exc).__name__)
        else:
            clients = []
            legacy_client = getattr(query_engine, "_client", None)
            if legacy_client is not None:
                clients.append(legacy_client)
            provider = getattr(recommendation_service, "provider", None)
            http_client = getattr(provider, "_http_client", None)
            if http_client is not None:
                clients.append(http_client)
            seen: set[int] = set()
            for client in clients:
                if id(client) in seen:
                    continue
                seen.add(id(client))
                try:
                    await client.aclose()
                except Exception as exc:
                    logger.debug("Error closing legacy LLM client (%s).", type(exc).__name__)

        if engine is not None:
            try:
                await engine.dispose()
                logger.info("Database AsyncEngine connection pool disposed.")
            except Exception as exc:
                logger.debug("Error disposing database engine (%s).", type(exc).__name__)
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
