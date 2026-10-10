"""Phase 8.2 opt-in live experiments, with dry-run default and persistent budgets."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import random
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from shopassist.llm.config import get_llm_settings
from shopassist.llm.experiments.phase82.candidates import CANDIDATES
from shopassist.llm.experiments.phase82.runner import BudgetExceeded, ResearchRunner, atomic_write, digest
from shopassist.llm.experiments.phase82.scoring import aggregate, consistency


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true", help="Explicitly submit Gemini requests within the supplied ceilings")
    p.add_argument("--max-requests", type=int, default=0)
    p.add_argument("--max-tokens", type=int, default=0)
    p.add_argument("--max-retries", type=int, default=0)
    p.add_argument("--pacing", type=float, default=4.0)
    p.add_argument("--experiments", default="B0,T05,T10")
    p.add_argument("--split", choices=["dev", "validation", "heldout", "legacy_heldout"], default="dev")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--use-cache", action="store_true", help="Replay path only; forbidden for temperature/repeated sampling")
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--limit", type=int)
    p.add_argument("--seed", type=int, default=82)
    p.add_argument("--output-dir", type=Path, default=ROOT / "data/interim/phase8_2/live")
    args = p.parse_args(argv)
    if min(args.max_requests, args.max_tokens, args.max_retries, args.pacing) < 0 or args.repetitions < 1:
        p.error("Budgets, retries, pacing must be nonnegative; repetitions positive")
    if args.limit is not None and args.limit < 1:
        p.error("Limit must be positive")
    return args


async def run(args):
    ids = args.experiments.split(",")
    if any(i not in CANDIDATES for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Unknown or duplicate experiment IDs")
    if args.use_cache and (args.repetitions > 1 or any(i in ids for i in ("T05", "T10"))):
        raise ValueError("Cache replay cannot establish sampling consistency")
    path = ROOT / "tests/fixtures/heldout_evaluation_cases.json" if args.split == "legacy_heldout" else ROOT / f"tests/fixtures/phase8_2/{args.split}.json"
    data = json.loads(path.read_text(encoding="utf8"))
    cases = data["cases"][:args.limit]
    case_ids = [c["test_id"] for c in cases]
    if not cases or len(set(case_ids)) != len(case_ids) or len({c["query"] for c in cases}) != len(cases):
        raise ValueError("Empty or duplicate evaluation records")
    settings = get_llm_settings().model_copy(update={"gemini_max_retries": args.max_retries})
    dataset = {"split": args.split, "version": data.get("version", data.get("dataset_version", "legacy")),
               "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "cases_hash": digest(cases)}
    schedule = [(i, c, rep) for rep in range(args.repetitions) for c in cases for i in ids]
    random.Random(args.seed).shuffle(schedule)
    plan = {"status": "PLANNED" if not args.live else "RUNNING", "model": settings.model,
            "experiments": [CANDIDATES[i].metadata() for i in ids], "dataset": dataset,
            "logical_requests": len(schedule), "maximum_attempts": len(schedule)*(args.max_retries+1),
            "request_ceiling": args.max_requests, "token_ceiling": args.max_tokens,
            "pacing_seconds": args.pacing, "repetitions": args.repetitions, "seed": args.seed,
            "cache_enabled": args.use_cache, "live_approval": "Must be obtained by operator before large runs",
            "token_limit_policy": "Reserve visible input byte estimate + output cap + overhead; unknown usage retains reservation. Hidden billing is not a guaranteed bound."}
    print(json.dumps(plan, indent=2))
    if not args.live:
        return 0
    if args.max_requests == 0 or args.max_tokens == 0:
        raise ValueError("Live runs require explicit positive request and token ceilings")
    atomic_write(args.output_dir / "plan.json", plan)
    runner = ResearchRunner(settings, args.output_dir, args.max_requests, args.max_tokens, args.pacing, args.use_cache)
    rows = []
    try:
        for i, case, rep in schedule:
            row = await runner.run_case(CANDIDATES[i], case, dataset, rep, args.resume)
            rows.append(row)
            atomic_write(args.output_dir / "results.json", {"plan": plan, "per_case_results": rows})
        plan["status"] = "COMPLETE"
    except BudgetExceeded:
        plan["status"] = "BUDGET_EXHAUSTED"
    finally:
        await runner.close()
        results = {i: aggregate([r for r in rows if r["candidate"]["id"] == i]) for i in ids}
        repeated = {i: consistency([r for r in rows if r["candidate"]["id"] == i]) for i in ids}
        atomic_write(args.output_dir / "results.json", {"plan": plan, "per_case_results": rows, "metrics": results,
                                                       "consistency": repeated,
                                                       "budget": {"requests": runner.budget.requests, "charged_tokens": runner.budget.charged_tokens}})
    return 0 if plan["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(run(parse_args())))
