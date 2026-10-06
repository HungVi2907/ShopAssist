"""Validate Phase 4B metadata rules against the completed Phase 4A audit."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from cleaning_rules import resolve_candidate
from phase4b_common import DEFAULT_CANDIDATES, DEFAULT_LABELS, INVALID_LABELS, LABELS, load_audit_records


PREDICTION_FIELDS = ("parent_asin", "candidate_family", "title", "true_label", "predicted_label",
                     "decision", "predicted_family", "rule_id", "matched_signals", "reason")


def safe_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def metrics(tp: int, fp: int, fn: int) -> dict:
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    return {"precision": precision, "recall": recall,
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
            "tp": tp, "fp": fp, "fn": fn}


def evaluate(rows: list[tuple[dict, dict]]) -> tuple[dict, list[dict]]:
    predictions = []
    matrix = {label: Counter() for label in LABELS}
    rules = Counter()
    for labeled, record in rows:
        result = resolve_candidate(record)
        true = labeled["audit_label"]
        if true not in matrix:
            raise ValueError(f"Unexpected audit label: {true}")
        matrix[true][result["predicted_label"]] += 1
        rules[result["rule_id"]] += 1
        predictions.append({
            "parent_asin": labeled["parent_asin"],
            "candidate_family": labeled["candidate_family"],
            "title": labeled["title"], "true_label": true,
            "predicted_label": result["predicted_label"], "decision": result["decision"],
            "predicted_family": result["predicted_family"] or "", "rule_id": result["rule_id"],
            "matched_signals": json.dumps(result["matched_signals"], ensure_ascii=False),
            "reason": result["reason"],
        })
    evaluated = [row for row in predictions if row["true_label"] != "AMBIGUOUS"]
    valid = [row for row in evaluated if row["true_label"] == "VALID_PRODUCT"]
    invalid = [row for row in evaluated if row["true_label"] in INVALID_LABELS]
    keep_tp = sum(row["decision"] == "KEEP" for row in valid)
    keep_fp = sum(row["decision"] == "KEEP" for row in invalid)
    remove_tp = sum(row["decision"] == "REMOVE" for row in invalid)
    remove_fp = sum(row["decision"] == "REMOVE" for row in valid)
    per_label = {}
    for label in ("VALID_PRODUCT", *INVALID_LABELS):
        tp = sum(row["true_label"] == label and row["predicted_label"] == label for row in evaluated)
        fp = sum(row["true_label"] != label and row["predicted_label"] == label for row in evaluated)
        fn = sum(row["true_label"] == label and row["predicted_label"] != label for row in evaluated)
        per_label[label] = metrics(tp, fp, fn)
    result = {
        "total_labeled_rows": len(rows), "evaluated_rows_excluding_ambiguous": len(evaluated),
        "ambiguous_true_rows": len(rows) - len(evaluated),
        "prediction_counts": dict(Counter(row["predicted_label"] for row in predictions)),
        "confusion_matrix": {label: dict(matrix[label]) for label in LABELS},
        "per_label_metrics": per_label,
        "keep_metrics": metrics(keep_tp, keep_fp, len(valid) - keep_tp),
        "remove_metrics": metrics(remove_tp, remove_fp, len(invalid) - remove_tp),
        "valid_product_false_rejections": remove_fp,
        "valid_product_false_rejection_rate": safe_ratio(remove_fp, len(valid)),
        "invalid_product_false_acceptances": keep_fp,
        "invalid_product_false_acceptance_rate": safe_ratio(keep_fp, len(invalid)),
        "valid_product_review_count": sum(row["decision"] == "REVIEW" for row in valid),
        "invalid_product_review_count": sum(row["decision"] == "REVIEW" for row in invalid),
        "ambiguous_prediction_counts": dict(matrix["AMBIGUOUS"]),
        "committed_decision_coverage": safe_ratio(sum(row["decision"] != "REVIEW" for row in evaluated), len(evaluated)),
        "rule_coverage": dict(sorted(rules.items())),
        "metric_note": "True AMBIGUOUS rows excluded from class and KEEP/REMOVE metrics; REVIEW counts as neither KEEP nor REMOVE and lowers recall. False rejection means VALID_PRODUCT predicted REMOVE, not REVIEW.",
    }
    return result, predictions


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PREDICTION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def render_markdown(result: dict, predictions: list[dict]) -> str:
    lines = ["# Phase 4B — Rule validation", "",
             f"Labeled sample: **{result['total_labeled_rows']}**; evaluated known-label rows: **{result['evaluated_rows_excluding_ambiguous']}**; true AMBIGUOUS: **{result['ambiguous_true_rows']}**.",
             "The sample is stratified and risk-enriched. Metrics describe this sample only and are not an independent holdout estimate.",
             "REVIEW is an explicit abstention. It lowers recall but is not counted as a mistaken removal or acceptance.", "",
             "## Aggregate decisions", "",
             "| Measure | Value |", "| --- | ---: |",
             f"| KEEP precision / recall / F1 | {result['keep_metrics']['precision']} / {result['keep_metrics']['recall']} / {result['keep_metrics']['f1']} |",
             f"| REMOVE precision / recall / F1 | {result['remove_metrics']['precision']} / {result['remove_metrics']['recall']} / {result['remove_metrics']['f1']} |",
             f"| VALID_PRODUCT falsely removed | {result['valid_product_false_rejections']} / 142 ({result['valid_product_false_rejection_rate']:.2%}) |",
             f"| Invalid products falsely kept | {result['invalid_product_false_acceptances']} / 232 ({result['invalid_product_false_acceptance_rate']:.2%}) |",
             f"| Valid / invalid sent to REVIEW | {result['valid_product_review_count']} / {result['invalid_product_review_count']} |",
             f"| Committed decision coverage (known labels) | {result['committed_decision_coverage']:.2%} |", "",
             "## Per-class metrics", "",
             "| Class | Precision | Recall | F1 | TP | FP | FN |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for label, item in result["per_label_metrics"].items():
        lines.append(f"| {label} | {item['precision']} | {item['recall']} | {item['f1']} | {item['tp']} | {item['fp']} | {item['fn']} |")
    columns = ("VALID_PRODUCT", *INVALID_LABELS, "REVIEW")
    lines.extend(["", "## Confusion matrix", "",
                  "Rows are audit labels; columns are rule predictions. True AMBIGUOUS is shown separately and excluded from metrics.", "",
                  "| True \\ Predicted | " + " | ".join(columns) + " |",
                  "| --- | " + " | ".join("---:" for _ in columns) + " |"])
    for label in LABELS:
        row = result["confusion_matrix"][label]
        lines.append("| " + label + " | " + " | ".join(str(row.get(column, 0)) for column in columns) + " |")
    lines.extend(["", "## Rule coverage", "", "| Rule ID | Rows |", "| --- | ---: |"])
    for rule, count in result["rule_coverage"].items():
        lines.append(f"| `{rule}` | {count} |")
    lines.extend(["", "## Error examples", ""])
    for heading, selected in (
        ("False rejections (VALID_PRODUCT → REMOVE)", [row for row in predictions if row["true_label"] == "VALID_PRODUCT" and row["decision"] == "REMOVE"]),
        ("False acceptances (invalid → KEEP)", [row for row in predictions if row["true_label"] in INVALID_LABELS and row["decision"] == "KEEP"]),
        ("Valid products deferred for review", [row for row in predictions if row["true_label"] == "VALID_PRODUCT" and row["decision"] == "REVIEW"]),
    ):
        lines.extend([f"### {heading}", ""])
        if not selected:
            lines.append("None in this labeled sample.")
        else:
            for row in selected[:20]:
                lines.append(f"- `{row['parent_asin']}` — {row['title'][:150]} — `{row['rule_id']}` → {row['predicted_label']}.")
            if len(selected) > 20:
                lines.append(f"- {len(selected) - 20} more in the prediction CSV.")
        lines.append("")
    lines.append("Full row-level evidence is in `phase4b_predictions.csv`; error subsets are in the false-rejection and false-acceptance CSVs. No full-candidate selection was performed.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=Path("data/interim"))
    args = parser.parse_args()
    result, predictions = evaluate(load_audit_records(args.labels, args.candidates))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "phase4b_predictions.csv", predictions)
    write_csv(args.out_dir / "phase4b_false_rejections.csv", [row for row in predictions if row["true_label"] == "VALID_PRODUCT" and row["decision"] == "REMOVE"])
    write_csv(args.out_dir / "phase4b_false_acceptances.csv", [row for row in predictions if row["true_label"] in INVALID_LABELS and row["decision"] == "KEEP"])
    (args.out_dir / "phase4b_rule_validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "phase4b_rule_validation.md").write_text(render_markdown(result, predictions), encoding="utf-8")
    print(f"Evaluated {result['evaluated_rows_excluding_ambiguous']} known-label rows; false rejections={result['valid_product_false_rejections']}; false acceptances={result['invalid_product_false_acceptances']}")


if __name__ == "__main__":
    main()
