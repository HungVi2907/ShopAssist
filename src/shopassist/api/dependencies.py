"""FastAPI dependency injection providers (Phase 15)."""

from __future__ import annotations

from typing import cast
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from shopassist.api.config import APISettings, get_api_settings
from shopassist.api.exceptions import DependencyUnavailableException
from shopassist.api.services.orchestrator import RecommendationOrchestrator
from shopassist.api.session import InMemorySessionStore


def get_settings() -> APISettings:
    """Dependency providing validated APISettings."""
    return get_api_settings()


def get_orchestrator(request: Request) -> RecommendationOrchestrator:
    """Dependency providing initialized RecommendationOrchestrator from application state."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise DependencyUnavailableException(
            component="orchestrator",
            details="RecommendationOrchestrator is not initialized in application state.",
        )
    return cast(RecommendationOrchestrator, orchestrator)


def get_session_store(request: Request) -> InMemorySessionStore:
    """Dependency providing InMemorySessionStore from application state."""
    store = getattr(request.app.state, "session_store", None)
    if store is None:
        raise DependencyUnavailableException(
            component="session_store",
            details="InMemorySessionStore is not initialized in application state.",
        )
    return cast(InMemorySessionStore, store)


def get_db_engine(request: Request) -> AsyncEngine:
    """Dependency providing SQLAlchemy AsyncEngine from application state."""
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise DependencyUnavailableException(
            component="database",
            details="SQLAlchemy AsyncEngine is not initialized in application state.",
        )
    return cast(AsyncEngine, engine)
