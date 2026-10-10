"""Attempt budgets, crash-safe resume, response cache separation, and dry-run safety."""
import asyncio
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from shopassist.llm.config import LLMSettings
from shopassist.llm.experiments.phase82.candidates import CANDIDATES
from shopassist.llm.experiments.phase82.runner import Budget, BudgetExceeded, ResearchRunner, fingerprint
from shopassist.llm.schema_variants import RefinedQueryUnderstandingOutput
from shopassist.llm.schemas import TokenUsageMetadata


def settings():
    return LLMSettings(_env_file=None,GEMINI_API_KEY="mock-key",GEMINI_MAX_RETRIES=0)


def test_budget_counts_attempts_and_survives_process_restart(tmp_path):
    path=tmp_path/"budget.json"
    b=Budget(path,2,100)
    b.reserve(30);b.reserve(30)
    b=Budget(path,2,100)
    with pytest.raises(BudgetExceeded): b.reserve(1)
    assert b.requests == 2 and b.charged_tokens == 60


def test_token_reservation_and_unknown_usage(tmp_path):
    b=Budget(tmp_path/"budget.json",5,100)
    b.reserve(80);b.settle(80,None)
    with pytest.raises(BudgetExceeded): b.reserve(30)
    b.settle(80,TokenUsageMetadata(total_tokens=40))
    assert b.charged_tokens == 40 and b.observed_tokens == 40


def test_cache_fingerprint_covers_content_schema_temperature_and_generation_settings():
    s=settings(); c=CANDIDATES["B0"]
    original=fingerprint(c,s,"pen")
    assert original != fingerprint(replace(c,prompt=c.prompt+" revised"),s,"pen")
    assert original != fingerprint(replace(c,temperature=.0001),s,"pen")
    assert original != fingerprint(CANDIDATES["D1"],s,"pen")
    assert original != fingerprint(c,s.model_copy(update={"gemini_max_output_tokens":100}),"pen")
    assert original != fingerprint(c,s.model_copy(update={"gemini_model":"other"}),"pen")


def mock_client(fail=False):
    client=MagicMock()
    async def generate(**kwargs):
        kwargs["on_attempt"]()
        kwargs["diagnostics"].update(attempts=1,response_received=True,json_valid=True,schema_valid=not fail)
        usage=TokenUsageMetadata(prompt_tokens=10,candidates_tokens=10,total_tokens=20)
        kwargs["on_response"](usage)
        if fail: raise ValueError("untrusted provider diagnostic")
        out=RefinedQueryUnderstandingOutput(product_type="pen",semantic_query="pen")
        return out,out.model_dump_json(),100,usage
    client.generate_structured_async=AsyncMock(side_effect=generate)
    client.aclose=AsyncMock()
    return client


CASE={"test_id":"P1","query":"pen","expected":{"product_type":"pen","exclusions":[],"soft_preferences":[],
      "hard_constraints":{"min_inclusive":True,"max_inclusive":True}}}


def test_response_cache_has_zero_new_calls_and_own_latency(tmp_path):
    async def run():
        runner=ResearchRunner(settings(),tmp_path,2,100000,pacing=0,use_cache=True)
        runner.client=mock_client()
        first=await runner.run_case(CANDIDATES["B0"],CASE,{"split":"dev"})
        second=await runner.run_case(CANDIDATES["B0"],CASE,{"split":"dev"},1)
        assert first["cache_status"] == "live" and second["cache_status"] == "hit"
        assert second["diagnostics"]["attempts"] == 0 and second["cache_lookup_ms"] is not None
        assert second["token_usage"] == {} and runner.budget.requests == 1
        assert second["score"]["full_v2_exact"]
    asyncio.run(run())


def test_failed_response_not_cached_but_usage_charged(tmp_path):
    async def run():
        runner=ResearchRunner(settings(),tmp_path,2,100000,pacing=0,use_cache=True)
        runner.client=mock_client(True)
        row=await runner.run_case(CANDIDATES["B0"],CASE,{"split":"dev"})
        assert not row["is_valid"] and row["error"]["stage"] == "schema"
        assert not list((tmp_path/"cache").glob("*.json"))
        assert runner.budget.observed_tokens == 20 and "untrusted provider diagnostic" not in json.dumps(row)
    asyncio.run(run())


def test_resume_and_repetition_do_not_merge_results(tmp_path):
    async def run():
        runner=ResearchRunner(settings(),tmp_path,2,100000,pacing=0)
        runner.client=mock_client()
        a=await runner.run_case(CANDIDATES["B0"],CASE,{"split":"dev"},0)
        b=await runner.run_case(CANDIDATES["B0"],CASE,{"split":"dev"},0,True)
        assert a == b and runner.budget.requests == 1
        await runner.run_case(CANDIDATES["B0"],CASE,{"split":"dev"},1,True)
        assert runner.budget.requests == 2
        assert len(list((tmp_path/"records").glob("*.json"))) == 2
    asyncio.run(run())


def test_exhausted_budget_does_not_write_fake_completed_result(tmp_path):
    async def run():
        runner=ResearchRunner(settings(),tmp_path,0,0,pacing=0)
        runner.client=mock_client()
        with pytest.raises(BudgetExceeded): await runner.run_case(CANDIDATES["B0"],CASE,{"split":"dev"})
        assert not list((tmp_path/"records").glob("*.json"))
    asyncio.run(run())


def test_dry_run_never_creates_client_or_output(tmp_path,monkeypatch):
    script=Path(__file__).resolve().parents[1]/"scripts/run_phase8_2_experiments.py"
    spec=importlib.util.spec_from_file_location("phase82_cli",script)
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    monkeypatch.setattr(cli,"ResearchRunner",lambda *a,**k:pytest.fail("dry-run initialized runner"))
    args=cli.parse_args(["--dry-run","--output-dir",str(tmp_path/"not_created")])
    assert asyncio.run(cli.run(args)) == 0 and not (tmp_path/"not_created").exists()


def test_cache_cannot_fake_repeated_temperature_consistency(tmp_path):
    script=Path(__file__).resolve().parents[1]/"scripts/run_phase8_2_experiments.py"
    spec=importlib.util.spec_from_file_location("phase82_cli_cache",script)
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    args=cli.parse_args(["--dry-run","--use-cache"])
    with pytest.raises(ValueError,match="sampling consistency"): asyncio.run(cli.run(args))
