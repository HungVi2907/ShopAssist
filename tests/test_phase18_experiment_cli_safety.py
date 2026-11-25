"""Offline tests for experiment runner opt-in and Gateway rollback boundaries."""
import asyncio

import pytest


def test_phase81_runner_is_dry_run_by_default(monkeypatch):
    from scripts import run_phase8_experiments as cli

    args = cli.parse_args([])
    assert args.live is False
    assert asyncio.run(cli.main_async(args)) == 0


def test_phase81_live_uses_pending_yaml_profile_and_fails_closed(monkeypatch):
    from scripts import run_phase8_experiments as cli
    from shopassist.llm_gateway.errors import GatewayError

    monkeypatch.setenv("LLM_GATEWAY_ENABLED", "true")
    monkeypatch.setattr(cli, "load_dataset", lambda split: [{"query": "synthetic", "expected": {}, "test_id": "T"}])
    monkeypatch.setattr(cli, "load_catalog_brands_set", lambda: set())
    args = cli.parse_args(["--live", "--experiments", "E1-A", "--limit", "1"])
    with pytest.raises(GatewayError) as error:
        asyncio.run(cli.main_async(args))
    assert error.value.attempts == ()


def test_phase82_live_uses_pending_yaml_profile_and_fails_closed(monkeypatch, tmp_path):
    from scripts import run_phase8_2_experiments as cli
    from shopassist.llm_gateway.errors import GatewayError

    monkeypatch.setenv("LLM_GATEWAY_ENABLED", "true")
    args = cli.parse_args([
        "--live", "--max-requests", "1", "--max-tokens", "100000",
        "--experiments", "B0", "--limit", "1", "--output-dir", str(tmp_path),
    ])
    with pytest.raises(GatewayError) as error:
        asyncio.run(cli.run(args))
    assert error.value.attempts == ()
