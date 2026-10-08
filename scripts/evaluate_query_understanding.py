"""Run extraction accuracy evaluation and latency benchmarking for Phase 8.

Evaluates Query Understanding accuracy against curated ground-truth fixtures,
measuring field-level metrics, exact match rate, API latency quantiles, and token consumption.
Saves machine-readable report to data/interim/phase8_query_understanding_report.json.

Examples:
    python scripts/evaluate_query_understanding.py --limit 5
    python scripts/evaluate_query_understanding.py --pacing 0.5
    python scripts/evaluate_query_understanding.py --output data/interim/phase8_query_understanding_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
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
from shopassist.llm.evaluation import (
    DEFAULT_FIXTURE_PATH,
    evaluate_query_understanding,
    load_evaluation_cases,
)
from shopassist.llm.query_understanding import QueryUnderstandingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("evaluate_query_understanding")

DEFAULT_REPORT_PATH = PROJECT_ROOT / "data" / "interim" / "phase8_query_understanding_report.json"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run Phase 8 LLM Query Understanding evaluation against ground truth dataset."
    )
    parser.add_argument(
        "--cases-file",
        type=str,
        default=str(DEFAULT_FIXTURE_PATH),
        help=f"Path to evaluation cases JSON fixture (default: {DEFAULT_FIXTURE_PATH}).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=str(DEFAULT_REPORT_PATH),
        help=f"Path to output report JSON (default: {DEFAULT_REPORT_PATH}).",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Optional maximum number of test cases to evaluate (default: all).",
    )
    parser.add_argument(
        "--pacing",
        type=float,
        default=0.5,
        help="Delay in seconds between requests to avoid rate limits (default: 0.5).",
    )
    return parser.parse_args()


async def run_evaluation(
    cases_file: str,
    output_path: str,
    limit: int | None = None,
    pacing: float = 0.5,
) -> int:
    """Execute evaluation and compile report."""
    print("=" * 75)
    print("SHOPASSIST PHASE 8: LLM QUERY UNDERSTANDING EVALUATION BENCHMARK")
    print("=" * 75)

    settings = get_llm_settings()
    print(f"Provider:           {settings.provider}")
    print(f"Model:              {settings.model}")
    print(f"Temperature:        {settings.temperature}")
    print(f"Pacing delay:       {pacing} seconds")

    cases = load_evaluation_cases(cases_file)
    if limit is not None and limit > 0:
        cases = cases[:limit]
        print(f"Loaded cases subset: {len(cases)} cases (limit={limit})")
    else:
        print(f"Loaded full test dataset: {len(cases)} cases")

    engine = QueryUnderstandingEngine(settings=settings)

    try:
        t0 = datetime.datetime.now(datetime.timezone.utc)
        print("\nStarting evaluation run against Gemini API...")
        results = await evaluate_query_understanding(
            engine=engine,
            cases=cases,
            pacing_delay_sec=pacing,
        )
        t1 = datetime.datetime.now(datetime.timezone.utc)

        hc_metrics = results.get("hard_constraints_metrics", {})
        # Assemble full machine-readable report
        report = {
            "phase": "Phase 8",
            "phase_name": "LLM Query Understanding",
            "timestamp_start_utc": t0.isoformat(),
            "timestamp_end_utc": t1.isoformat(),
            "duration_seconds": round((t1 - t0).total_seconds(), 2),
            "status": "PASS" if results.get("schema_validity_rate", 0.0) >= 0.95 else "PARTIAL",
            "llm_provider": settings.provider,
            "verified_model": settings.model,
            "settings": settings.to_safe_dict(),
            "evaluation_cases_file": str(cases_file),
            "metrics": {
                "total_cases_evaluated": results.get("total_cases_evaluated", len(cases)),
                "schema_validity_rate": results.get("schema_validity_rate", 0.0),
                "category_accuracy": results.get("category_accuracy", 0.0),
                "brand_accuracy": results.get("brand_accuracy", 0.0),
                "price_accuracy": results.get("price_accuracy", 0.0),
                "rating_accuracy": results.get("rating_accuracy", 0.0),
                "currency_accuracy": results.get("currency_accuracy", 0.0),
                "clarification_accuracy": results.get("clarification_accuracy", 0.0),
                "hard_constraints_precision": hc_metrics.get("precision", 0.0),
                "hard_constraints_recall": hc_metrics.get("recall", 0.0),
                "hard_constraints_f1": hc_metrics.get("f1_score", 0.0),
                "soft_preferences_f1_mean": results.get("soft_preferences_mean_f1", 0.0),
                "exact_match_accuracy": results.get("overall_exact_match_rate", 0.0),
            },
            "latency_benchmarks_ms": results.get("latency_stats_ms", {}),
            "token_usage": results.get("token_usage_stats", {}),
            "per_case_evaluations": results.get("case_details", []),
        }

        # Ensure output directory exists and save
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print("\n" + "=" * 75)
        print("EVALUATION BENCHMARK RESULTS SUMMARY:")
        print("=" * 75)
        m = report["metrics"]
        print(f"Total Cases Evaluated:       {m['total_cases_evaluated']}")
        print(f"Schema Validity Rate:        {m['schema_validity_rate']:.2%}")
        print(f"Category Accuracy:           {m['category_accuracy']:.2%}")
        print(f"Brand Accuracy:              {m['brand_accuracy']:.2%}")
        print(f"Price Accuracy:              {m['price_accuracy']:.2%}")
        print(f"Rating Accuracy:             {m['rating_accuracy']:.2%}")
        print(f"Clarification Accuracy:      {m['clarification_accuracy']:.2%}")
        print(f"Hard Constraints Precision:  {m['hard_constraints_precision']:.2%}")
        print(f"Hard Constraints Recall:     {m['hard_constraints_recall']:.2%}")
        print(f"Hard Constraints F1:         {m['hard_constraints_f1']:.2%}")
        print(f"Soft Preferences F1:         {m['soft_preferences_f1_mean']:.2%}")
        print(f"Overall Exact Match Rate:    {m['exact_match_accuracy']:.2%}")

        print("\nAPI LATENCY BENCHMARKS (ms):")
        lat = report["latency_benchmarks_ms"]
        print(f"  Min:  {lat.get('min', 0.0):.1f} ms | P50: {lat.get('p50', 0.0):.1f} ms | Mean: {lat.get('mean', 0.0):.1f} ms | P95: {lat.get('p95', 0.0):.1f} ms | Max: {lat.get('max', 0.0):.1f} ms")

        print("\nTOKEN USAGE BENCHMARKS:")
        tok = report["token_usage"]
        print(f"  Total Prompt Tokens:     {tok.get('total_prompt_tokens', 0)}")
        print(f"  Total Output Tokens:     {tok.get('total_candidates_tokens', 0)}")
        print(f"  Total Tokens Consumed:   {tok.get('total_tokens', 0)}")
        print(f"  Average Tokens / Query:  {tok.get('avg_tokens_per_request', 0.0):.1f}")

        print(f"\nMachine-readable report written to: {out_p}")
        print("=" * 75)
        return 0

    except Exception as exc:
        logger.error("Evaluation failed with error: %s", exc, exc_info=True)
        return 1
    finally:
        await engine.aclose()


def main() -> int:
    args = parse_args()
    return asyncio.run(
        run_evaluation(
            cases_file=args.cases_file,
            output_path=args.output,
            limit=args.limit,
            pacing=args.pacing,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
