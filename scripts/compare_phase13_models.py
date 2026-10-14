"""Perform cross-model comparison between Codex Silver labels and Antigravity Silver labels.

This analysis is executed ONLY AFTER independent judging has completed in full.
It does NOT modify any existing Codex Silver labels.
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
from sklearn.metrics import cohen_kappa_score

from shopassist.evaluation.silver import PROJECT_ROOT, read_csv_rows

CODEX_DIR = PROJECT_ROOT / "data/evaluation/phase13/ai_silver/v3_codex_native"
ANTIGRAVITY_DIR = PROJECT_ROOT / "data/evaluation/phase13/ai_silver/audit_antigravity_10pair"


def compare_labels() -> dict[str, Any]:
    codex_qrels = pd.DataFrame(read_csv_rows(CODEX_DIR / "qrels_silver.csv"))
    ag_qrels = pd.DataFrame(read_csv_rows(ANTIGRAVITY_DIR / "qrels_silver.csv"))

    # Filter Codex qrels to the exact 10 products evaluated by Antigravity
    merged = pd.merge(
        ag_qrels[["query_id", "product_id", "relevance_grade", "label_source", "adjudication_fingerprint"]],
        codex_qrels[["query_id", "product_id", "relevance_grade", "label_source", "adjudication_fingerprint"]],
        on=["query_id", "product_id"],
        suffixes=("_antigravity", "_codex"),
    )

    merged["relevance_grade_antigravity"] = merged["relevance_grade_antigravity"].astype(int)
    merged["relevance_grade_codex"] = merged["relevance_grade_codex"].astype(int)

    total_pairs = len(merged)
    exact_matches = (merged["relevance_grade_antigravity"] == merged["relevance_grade_codex"]).sum()
    exact_agreement_rate = round(float(exact_matches) / total_pairs, 4)

    # Compute Cohen's kappa (quadratic weighted)
    y_ag = merged["relevance_grade_antigravity"].tolist()
    y_codex = merged["relevance_grade_codex"].tolist()
    try:
        kappa = round(float(cohen_kappa_score(y_ag, y_codex, weights="quadratic")), 4)
    except Exception:
        kappa = None

    # Load candidate product metadata for rich discrepancy analysis
    tasks = {
        row["product_id"]: row
        for row in [
            json.loads(line)
            for line in open(ANTIGRAVITY_DIR / "codex_native_inputs/relevance_task_index.jsonl", encoding="utf-8")
            if line.strip()
        ]
    }

    item_comparisons = []
    for _, row in merged.iterrows():
        pid = row["product_id"]
        task = tasks.get(pid, {})
        cand = task.get("evidence", {}).get("candidate", {})
        pname = cand.get("product_name", "Unknown")
        brand = cand.get("brand", "Unknown")
        ag_grade = int(row["relevance_grade_antigravity"])
        codex_grade = int(row["relevance_grade_codex"])
        ag_source = row["label_source_antigravity"]
        codex_source = row["label_source_codex"]
        matches = ag_grade == codex_grade

        item_comparisons.append({
            "product_id": pid,
            "product_name": pname,
            "brand": brand,
            "antigravity_grade": ag_grade,
            "codex_grade": codex_grade,
            "exact_match": matches,
            "antigravity_label_source": ag_source,
            "codex_label_source": codex_source,
        })

    report = {
        "benchmark_context": {
            "query_id": "Q0007",
            "raw_query": "Ốp điện thoại chống sốc, cầm không bị trơn",
            "semantic_intent": "Shock-resistant phone case with a non-slip grip",
            "sample_size": total_pairs,
        },
        "metrics": {
            "total_pairs_compared": total_pairs,
            "exact_matches": int(exact_matches),
            "exact_agreement_rate": exact_agreement_rate,
            "quadratic_weighted_cohen_kappa": kappa,
            "grade_distribution_antigravity": {
                str(k): int(v) for k, v in merged["relevance_grade_antigravity"].value_counts().items()
            },
            "grade_distribution_codex": {
                str(k): int(v) for k, v in merged["relevance_grade_codex"].value_counts().items()
            },
        },
        "item_breakdown": item_comparisons,
    }

    out_path = ANTIGRAVITY_DIR / "cross_model_comparison_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Comparison report written to {out_path}")
    return report


if __name__ == "__main__":
    report = compare_labels()
    print("\n--- Summary ---")
    print(f"Total pairs: {report['metrics']['total_pairs_compared']}")
    print(f"Exact Agreement: {report['metrics']['exact_agreement_rate'] * 100:.1f}% ({report['metrics']['exact_matches']}/{report['metrics']['total_pairs_compared']})")
    print(f"Quadratic-weighted Kappa: {report['metrics']['quadratic_weighted_cohen_kappa']}")
    print(f"Antigravity Grade Distribution: {report['metrics']['grade_distribution_antigravity']}")
    print(f"Codex Grade Distribution: {report['metrics']['grade_distribution_codex']}")
    print("\nDetailed Items:")
    for item in report["item_breakdown"]:
        mark = "MATCH" if item["exact_match"] else "DISAGREE"
        print(f"[{mark}] PID={item['product_id'][:8]} | AG={item['antigravity_grade']} | Codex={item['codex_grade']} | {item['product_name'][:50]}")
