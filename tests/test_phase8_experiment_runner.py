"""Unit tests for ExperimentRegistry and ExperimentRunner (100% offline)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from shopassist.llm.config import LLMSettings
from shopassist.llm.experiments.registry import ExperimentConfig, ExperimentRegistry
from shopassist.llm.experiments.runner import ExperimentRunner
from shopassist.llm.schemas import QueryUnderstandingOutput, TokenUsageMetadata


class TestExperimentRunner:
    """Test suite for experiment runner execution and caching."""

    def test_registry_lookup(self):
        cfg = ExperimentRegistry.get("E1-A")
        assert cfg.id == "E1-A"
        assert cfg.prompt_variant == "E1-A"
        assert cfg.temperature == 0.0

        all_cfgs = ExperimentRegistry.list_all()
        assert len(all_cfgs) >= 9

    def test_cache_key_generation(self, tmp_path):
        runner = ExperimentRunner(cache_path=tmp_path / "cache.json")
        cfg = ExperimentConfig(
            id="TEST",
            name="Test Exp",
            variable_changed="none",
            purpose="test",
            hypothesis="test",
            prompt_variant="E1-A",
            schema_version="v1.0.0",
            temperature=0.0,
            model="gemini-3.1-flash-lite",
        )
        key1 = runner._compute_cache_key(cfg, "Puma running shoes under 2000 rupees")
        key2 = runner._compute_cache_key(cfg, "Puma running shoes under 2000 rupees")
        key3 = runner._compute_cache_key(cfg, "Nike running shoes")

        assert key1 == key2
        assert key1 != key3

    def test_offline_runner_execution_with_mock_client(self, tmp_path):
        async def _run():
            runner = ExperimentRunner(
                cache_path=tmp_path / "cache.json",
                max_requests=10,
                pacing_delay_sec=0.0,
            )

            mock_client = MagicMock()
            mock_output = QueryUnderstandingOutput(
                semantic_query="Puma running shoes",
                hard_constraints={
                    "category": "Footwear",
                    "brand": "Puma",
                    "max_price": 2000.0,
                },
                soft_preferences=["comfortable"],
            )
            mock_client.generate_structured_async = AsyncMock(
                return_value=(
                    mock_output,
                    '{"semantic_query": "Puma running shoes"}',
                    150.0,
                    TokenUsageMetadata(prompt_tokens=1000, candidates_tokens=100, total_tokens=1100),
                )
            )
            runner._client = mock_client

            cfg = ExperimentRegistry.get("E1-A")
            cases = [
                {
                    "test_id": "T01",
                    "query": "Puma running shoes under 2000 rupees",
                    "expected": {
                        "hard_constraints": {"category": "Footwear", "brand": "Puma", "max_price": 2000.0},
                        "soft_preferences": ["comfortable"],
                    },
                }
            ]

            res = await runner.execute_experiment(config=cfg, cases=cases)
            assert res["experiment_id"] == "E1-A"
            assert res["cases_evaluated_count"] == 1
            assert res["metrics"]["schema_validity_rate"] == 1.0
            assert res["metrics"]["legacy_exact_match_rate"] == 1.0
            assert res["metrics"]["strict_complete_exact_match_rate"] == 1.0
            assert runner.requests_made == 1

            # Second call for identical query should hit cache (requests_made stays 1)
            res2 = await runner.execute_experiment(config=cfg, cases=cases)
            assert runner.requests_made == 1
            assert res2["metrics"]["legacy_exact_match_rate"] == 1.0

        asyncio.run(_run())
