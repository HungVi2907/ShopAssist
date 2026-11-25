"""FastAPI Gateway lifecycle tests use local config and inert adapters."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from shopassist.api.config import APISettings
from shopassist.api.main import lifespan
from shopassist.llm_gateway.config import GatewaySettings, ROOT
from shopassist.llm_gateway.schemas import TaskType


class InertAdapter:
    def __init__(self):
        self.close_count = 0

    def prepare(self, request, route):
        raise AssertionError("Lifecycle tests must not dispatch providers")

    async def complete_once(self, prepared, *, timeout_s, on_dispatch):
        raise AssertionError("Lifecycle tests must not dispatch providers")

    async def aclose(self):
        self.close_count += 1


def patch_local_dependencies(monkeypatch, tmp_path, *, gateway_enabled=True, fail_dense=False):
    import shopassist.api.main as main

    engine = MagicMock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr(main, "get_async_engine", lambda **kwargs: engine)
    monkeypatch.setattr(main, "ensure_windows_event_loop_policy", lambda: None)
    monkeypatch.setattr(main, "DEFAULT_TFIDF_ARTIFACT_DIR", tmp_path / "missing-tfidf")
    monkeypatch.setattr(main, "PROCESSED_DATA_DIR", tmp_path / "missing-data")

    class Dense:
        def __init__(self):
            if fail_dense:
                raise RuntimeError("synthetic startup failure")

    monkeypatch.setattr(main, "DenseQueryEncoder", Dense)
    monkeypatch.setattr(main, "PreferenceQueryEncoder", lambda **kwargs: object())
    monkeypatch.setattr(main, "PreferenceRepresentationService", lambda **kwargs: object())
    monkeypatch.setattr(main, "HybridRetrievalService", lambda **kwargs: object())
    monkeypatch.setattr(main, "RerankingService", lambda **kwargs: object())
    adapters = {name: InertAdapter() for name in ("gemini", "openrouter", "groq")}
    monkeypatch.setattr(main, "GeminiAdapter", lambda: adapters["gemini"])
    monkeypatch.setattr(main, "OpenRouterAdapter", lambda: adapters["openrouter"])
    monkeypatch.setattr(main, "GroqAdapter", lambda: adapters["groq"])
    gw_settings = GatewaySettings(
        _env_file=None, enabled=gateway_enabled,
        config_path=ROOT / "config" / "llm_gateway.yaml",
        telemetry_dir=tmp_path / "telemetry",
    )
    monkeypatch.setattr(main, "GatewaySettings", lambda: gw_settings)
    return main, engine, adapters, gw_settings


def test_lifespan_injects_one_gateway_and_closes_owned_adapters_once(tmp_path, monkeypatch):
    async def run():
        main, engine, adapters, _ = patch_local_dependencies(monkeypatch, tmp_path)
        app = main.create_app(APISettings())
        async with lifespan(app):
            gateway = app.state.gateway
            assert gateway is not None
            assert app.state.query_engine.gateway is gateway
            assert app.state.recommendation_service.gateway is gateway
            assert app.state.orchestrator.query_engine is app.state.query_engine
            assert app.state.orchestrator.recommendation_service is app.state.recommendation_service
            assert gateway.primary_provider(TaskType.QUERY_UNDERSTANDING) == "gemini"
        assert all(adapter.close_count == 1 for adapter in adapters.values())
        engine.dispose.assert_awaited_once()
        assert gateway.telemetry._closed

    asyncio.run(run())


def test_lifespan_closes_gateway_and_database_if_later_startup_fails(tmp_path, monkeypatch):
    async def run():
        main, engine, adapters, _ = patch_local_dependencies(monkeypatch, tmp_path, fail_dense=True)
        app = main.create_app(APISettings())
        with pytest.raises(RuntimeError, match="synthetic startup failure"):
            async with lifespan(app):
                raise AssertionError("Startup should have failed before lifespan yield")
        assert all(adapter.close_count == 1 for adapter in adapters.values())
        engine.dispose.assert_awaited_once()

    asyncio.run(run())


def test_gateway_disabled_keeps_legacy_injection_and_creates_no_gateway_adapters(tmp_path, monkeypatch):
    async def run():
        main, engine, adapters, _ = patch_local_dependencies(
            monkeypatch, tmp_path, gateway_enabled=False,
        )
        app = main.create_app(APISettings())
        async with lifespan(app):
            assert app.state.gateway is None
            assert app.state.query_engine.gateway is None
            assert app.state.recommendation_service.gateway is None
        assert all(adapter.close_count == 0 for adapter in adapters.values())
        engine.dispose.assert_awaited_once()

    asyncio.run(run())


def test_enabled_gateway_rejects_missing_yaml_before_allocating_database_or_adapters(tmp_path, monkeypatch):
    async def run():
        main, engine, adapters, _ = patch_local_dependencies(monkeypatch, tmp_path)
        invalid_settings = GatewaySettings(
            _env_file=None, enabled=True, config_path=tmp_path / "missing.yaml",
            telemetry_dir=tmp_path / "telemetry",
        )
        monkeypatch.setattr(main, "GatewaySettings", lambda: invalid_settings)
        app = main.create_app(APISettings())
        with pytest.raises(ValueError, match="Invalid or unavailable gateway configuration"):
            async with lifespan(app):
                raise AssertionError("Invalid config must reject startup")
        assert all(adapter.close_count == 0 for adapter in adapters.values())
        engine.dispose.assert_not_awaited()

    asyncio.run(run())
