"""Offline tests for experiment runner opt-in and Gateway rollback boundaries."""
import asyncio

import pytest


def test_phase81_runner_is_dry_run_by_default(monkeypatch):
    from scripts import run_phase8_experiments as cli

    args = cli.parse_args([])
    assert args.live is False
    assert asyncio.run(cli.main_async(args)) == 0


def test_phase81_live_refuses_to_bypass_enabled_gateway(monkeypatch):
    from scripts import run_phase8_experiments as cli

    monkeypatch.setenv("LLM_GATEWAY_ENABLED", "true")
    args = cli.parse_args(["--live"])
    with pytest.raises(RuntimeError, match="cannot bypass the enabled Gateway"):
        asyncio.run(cli.main_async(args))


def test_phase82_live_refuses_to_bypass_enabled_gateway(monkeypatch):
    from scripts import run_phase8_2_experiments as cli

    monkeypatch.setenv("LLM_GATEWAY_ENABLED", "true")
    args = cli.parse_args(["--live", "--max-requests", "1", "--max-tokens", "1000"])
    with pytest.raises(RuntimeError, match="cannot bypass the enabled Gateway"):
        asyncio.run(cli.run(args))
