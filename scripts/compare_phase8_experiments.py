"""Script to compare Phase 8.1 experiments, score candidates, and generate comparison artifacts.

Usage:
    python scripts/compare_phase8_experiments.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shopassist.llm.experiments.comparison import (
    evaluate_candidate_selection,
    format_markdown_comparison_table,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger("compare_phase8_experiments")

RESULTS_PATH = PROJECT_ROOT / "data" / "interim" / "phase8_1" / "experiment_results.json"
BASELINE_PATH = PROJECT_ROOT / "data" / "interim" / "phase8_1" / "baseline_audit.json"
COMPARISON_OUT = PROJECT_ROOT / "data" / "interim" / "phase8_1" / "experiment_comparison.json"


def main() -> int:
    print("=" * 80)
    print("SHOPASSIST PHASE 8.1: EXPERIMENTAL COMPARISON & CANDIDATE SELECTION")
    print("=" * 80)

    if not RESULTS_PATH.exists():
        print(f"Error: Results file not found at {RESULTS_PATH}. Run experiments first.", file=sys.stderr)
        return 1

    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        results = json.load(f)

    # Inject E0 baseline if available
    if BASELINE_PATH.exists():
        with open(BASELINE_PATH, "r", encoding="utf-8") as f:
            base_data = json.load(f)
        results["E0"] = {
            "experiment_id": "E0",
            "experiment_name": "Baseline Audit (Historical Report Recomputation)",
            "config": {
                "prompt_variant": "E1-A (Baseline)",
                "schema_version": "v1.0.0",
                "temperature": 0.0,
                "apply_rules": False,
            },
            "metrics": base_data.get("recomputed_metrics", {}),
        }

    print(f"\nEvaluated Experiments ({len(results)}): {list(results.keys())}")

    # Generate Markdown Table
    print("\n--- COMPARISON MATRIX ---")
    table_md = format_markdown_comparison_table(results)
    print(table_md)

    # Evaluate Candidate Selection
    eval_summary = evaluate_candidate_selection(results)
    best_id = eval_summary["best_candidate_id"]
    best_det = eval_summary["best_candidate_details"]

    print("\n--- CANDIDATE SELECTION ASSESSMENT ---")
    print(f"Winning Candidate:            **{best_id}**")
    print(f"Composite Score:              {best_det.get('composite_score', 0.0):.4f}")
    print(f"Soft Preferences F1:          {best_det.get('soft_f1', 0.0):.2%}")
    print(f"Strict Complete Exact Match:  {best_det.get('strict_em', 0.0):.2%}")
    print(f"Hard Constraints F1:          {best_det.get('hc_f1', 0.0):.2%}")
    print(f"Brand Accuracy:               {best_det.get('brand_acc', 0.0):.2%}")

    comparison_report = {
        "title": "Phase 8.1 Experiment Comparison & Candidate Selection",
        "experiments_included": list(results.keys()),
        "markdown_table": table_md,
        "candidate_ranking": eval_summary,
        "selected_candidate_id": best_id,
        "full_results": results,
    }

    COMPARISON_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(COMPARISON_OUT, "w", encoding="utf-8") as f:
        json.dump(comparison_report, f, indent=2)

    print(f"\nSaved comparison report to: {COMPARISON_OUT}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
