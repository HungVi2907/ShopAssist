"""Command-line runner for Phase 8.1 experiments.

Supports:
- Running specific experiments (e.g. E1-A, E1-B, E1-C, E2-A, E2-B, E2-C, E3, E4, E5-B)
- Safe API request budgeting, response caching, and pacing
- Splitting between development (dev_15) and held-out (heldout_20) datasets
- Saving machine-readable artifacts to data/interim/phase8_1/experiment_results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shopassist.llm.config import get_llm_settings
from shopassist.llm.experiments.comparison import format_markdown_comparison_table
from shopassist.llm.experiments.registry import ExperimentConfig, ExperimentRegistry
from shopassist.llm.experiments.runner import ExperimentRunner
from shopassist.llm.query_understanding import load_catalog_brands_set

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("run_phase8_experiments")

RESULTS_PATH = PROJECT_ROOT / "data" / "interim" / "phase8_1" / "experiment_results.json"
DEV_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "dev_evaluation_cases.json"
HELDOUT_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "heldout_evaluation_cases.json"
BASELINE_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "query_understanding_cases.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run controlled Phase 8.1 experiments.")
    parser.add_argument(
        "--experiments",
        "-e",
        type=str,
        default="E1-A,E1-B,E1-C,E2-A,E2-B,E2-C,E3,E4,E5-B",
        help="Comma-separated experiment IDs or 'all' or 'screening' (default: all core screening experiments).",
    )
    parser.add_argument(
        "--split",
        type=str,
        choices=["dev_15", "heldout_20", "baseline_50"],
        default="dev_15",
        help="Evaluation dataset partition (default: 'dev_15').",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Optional limit on number of cases per experiment.",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=150,
        help="Maximum API request quota for this execution (default: 150).",
    )
    parser.add_argument(
        "--pacing",
        type=float,
        default=0.5,
        help="Delay in seconds between API calls to avoid rate limits (default: 0.5).",
    )
    return parser.parse_args()


def load_dataset(split: str) -> list[dict[str, Any]]:
    if split == "dev_15":
        p = DEV_FIXTURE
    elif split == "heldout_20":
        p = HELDOUT_FIXTURE
    elif split == "baseline_50":
        p = BASELINE_FIXTURE
    else:
        raise ValueError(f"Unknown split '{split}'")

    if not p.exists():
        raise FileNotFoundError(f"Fixture file not found at {p}")

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("cases", [])


async def main_async(args: argparse.Namespace) -> int:
    print("=" * 80)
    print("SHOPASSIST PHASE 8.1: CONTROLLED QUERY UNDERSTANDING EXPERIMENTS")
    print("=" * 80)

    settings = get_llm_settings()
    print(f"LLM Provider:       {settings.provider}")
    print(f"Configured Model:   {settings.model}")
    print(f"API Key:            {settings.masked_api_key}")
    print(f"Dataset Split:      {args.split}")
    print(f"Request Budget:     {args.max_requests}")
    print(f"Pacing Delay:       {args.pacing}s")

    cases = load_dataset(args.split)
    if args.limit and args.limit > 0:
        cases = cases[:args.limit]
    print(f"Loaded Cases:       {len(cases)} cases")

    catalog_brands = load_catalog_brands_set()
    print(f"Catalog Brands:     {len(catalog_brands)} unique brands")

    # Determine experiments to run
    if args.experiments.lower() == "all":
        exp_ids = ["E1-A", "E1-B", "E1-C", "E2-A", "E2-B", "E2-C", "E3", "E4", "E5-B"]
    elif args.experiments.lower() == "screening":
        exp_ids = ["E1-A", "E1-B", "E1-C", "E2-A", "E2-C", "E3", "E4"]
    else:
        exp_ids = [e.strip() for e in args.experiments.split(",") if e.strip()]

    print(f"Experiments to Run: {exp_ids}")

    results_path = RESULTS_PATH if args.split == "dev_15" else PROJECT_ROOT / "data" / "interim" / "phase8_1" / f"experiment_results_{args.split}.json"
    existing_results: dict[str, Any] = {}
    if results_path.exists():
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                existing_results = json.load(f)
        except Exception:
            existing_results = {}

    runner = ExperimentRunner(
        settings=settings,
        max_requests=args.max_requests,
        pacing_delay_sec=args.pacing,
    )

    try:
        for exp_id in exp_ids:
            try:
                cfg = ExperimentRegistry.get(exp_id)
            except KeyError:
                print(f"Skipping unknown experiment ID '{exp_id}'", file=sys.stderr)
                continue

            print(f"\n>>> Running Experiment {cfg.id}: {cfg.name} (prompt={cfg.prompt_variant}, schema={cfg.schema_version}, temp={cfg.temperature:.1f}, rules={cfg.apply_rules})...")
            exp_result = await runner.execute_experiment(
                config=cfg,
                cases=cases,
                catalog_brands=catalog_brands,
            )

            # Store in results map
            existing_results[exp_id] = exp_result
            m = exp_result["metrics"]
            print(f"    Schema Validity:  {m.get('schema_validity_rate'):.1%}")
            print(f"    Hard Const F1:    {m.get('hard_constraints_metrics', {}).get('f1_score'):.1%}")
            print(f"    Soft Prefs F1:    {m.get('soft_preferences_metrics', {}).get('mean_f1'):.1%}")
            print(f"    Strict Compl EM:  {m.get('strict_complete_exact_match_rate'):.1%}")
            print(f"    Latency P50:      {m.get('latency_stats_ms', {}).get('p50'):.1f} ms")

            # Persist after each experiment
            results_path.parent.mkdir(parents=True, exist_ok=True)
            with open(results_path, "w", encoding="utf-8") as f:
                json.dump(existing_results, f, indent=2)

        print("\n" + "=" * 80)
        print("EXPERIMENT SUITE SUMMARY COMPARISON TABLE:")
        print("=" * 80)
        table_md = format_markdown_comparison_table(existing_results)
        print(table_md)

        print(f"\nSaved full results to: {results_path}")
        print(f"Total API requests made in this run: {runner.requests_made}")
        print(f"Total tokens consumed in this run:   {runner.tokens_consumed}")
        return 0

    finally:
        await runner.aclose()


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
