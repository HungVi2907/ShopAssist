"""Export score-blind reviewer tasks from a Phase 13 dataset version."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

try:
    from scripts.validate_phase13_dataset import DEFAULT_DATASET, read_csv, read_jsonl
except ModuleNotFoundError:  # direct script execution
    from validate_phase13_dataset import DEFAULT_DATASET, read_csv, read_jsonl


def write_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to replace reviewer task file: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export(dataset: Path, output: Path, reviewer_ids: tuple[str, str] | None = None) -> dict[str, int]:
    if reviewer_ids is not None and (reviewer_ids[0] == reviewer_ids[1] or not all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", x) for x in reviewer_ids)):
        raise ValueError("Two distinct real reviewer IDs using letters, digits, _ or - are required")
    names = ["query_tasks.csv", "relevance_tasks.csv", "claim_tasks.csv",
             "query_adjudications_template.jsonl", "relevance_adjudications_template.csv",
             "claim_adjudications_template.csv"]
    if reviewer_ids is not None:
        names += [f"{kind}_tasks_{reviewer}.csv" for reviewer in reviewer_ids for kind in ("query", "relevance", "claim")]
    if any((output / name).exists() for name in names):
        raise FileExistsError("Refusing to partially overwrite reviewer task files")
    output.mkdir(parents=True, exist_ok=True)
    queries = read_jsonl(dataset / "queries.jsonl")
    pools = read_jsonl(dataset / "candidate_pools.jsonl")
    claims = read_csv(dataset / "generation_claims.csv")
    query_map = {q["query_id"]: q for q in queries}
    query_fields = ["query_id", "raw_query", "language", "semantic_query", "category", "brand", "min_price", "max_price", "min_rating", "currency", "min_operator", "max_operator", "soft_preferences_json", "needs_clarification", "clarification_reason", "expected_status", "annotator_id", "comment"]
    query_rows = [{"query_id": q["query_id"], "raw_query": q["raw_query"], "language": q["language"]} for q in queries]
    relevance_fields = ["query_id", "raw_query", "adjudicated_requirements_json", "product_id", "product_name", "category", "brand", "discounted_price", "rating", "canonical_retrieval_text", "relevance_grade", "category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation", "annotator_id", "comment"]
    relevance_rows = []
    for pool in pools:
        qid = pool["query_id"]
        for candidate in pool["candidates"]:
            relevance_rows.append({
                "query_id": qid, "raw_query": query_map[qid]["raw_query"],
                "adjudicated_requirements_json": json.dumps(query_map[qid].get("expected_query_understanding"), ensure_ascii=False),
                "product_id": candidate["product_id"], "product_name": candidate["product_name"],
                "category": candidate["category"], "brand": candidate.get("brand"),
                "discounted_price": candidate["discounted_price"], "rating": candidate.get("rating"),
                "canonical_retrieval_text": candidate["retrieval_text"],
            })
    # Stable blind ordering does not disclose Phase 10 rank or score.
    relevance_rows.sort(key=lambda r: hashlib.sha256(f"{r['query_id']}:{r['product_id']}".encode()).hexdigest())
    claim_fields = ["claim_id", "query_id", "raw_query", "product_id", "claim", "evidence_ids_json", "evidence_text_json", "support_label", "factual_correctness", "recommendation_relevance", "missing_information_handling", "annotator_id", "comment"]
    claim_rows = [{key: c.get(key, "") for key in ("claim_id", "query_id", "product_id", "claim", "evidence_ids_json", "evidence_text_json")} | {"raw_query": query_map[c["query_id"]]["raw_query"]} for c in claims]
    claim_rows.sort(key=lambda r: r["claim_id"])
    write_rows(output / "query_tasks.csv", query_fields, query_rows)
    write_rows(output / "relevance_tasks.csv", relevance_fields, relevance_rows)
    write_rows(output / "claim_tasks.csv", claim_fields, claim_rows)
    query_decision_fields = ("semantic_query", "category", "brand", "min_price", "max_price",
                             "min_rating", "currency", "min_operator", "max_operator",
                             "soft_preferences_json", "needs_clarification", "clarification_reason", "expected_status",
                             "adjudicator_id", "disagreement_reason")
    (output / "query_adjudications_template.jsonl").write_text("".join(
        json.dumps({"query_id": row["query_id"], **{field: "" for field in query_decision_fields}}, ensure_ascii=False) + "\n"
        for row in query_rows), encoding="utf-8")
    relevance_decision_fields = ["query_id", "product_id", "adjudicated_grade", "category_violation",
                                 "brand_violation", "price_violation", "rating_violation", "other_violation",
                                 "adjudicator_id", "disagreement_reason"]
    write_rows(output / "relevance_adjudications_template.csv", relevance_decision_fields,
               [{"query_id": row["query_id"], "product_id": row["product_id"]} for row in relevance_rows])
    claim_decision_fields = ["claim_id", "adjudicated_support", "adjudicated_factual",
                             "adjudicated_relevance", "missing_information_handling", "adjudicator_id",
                             "disagreement_reason"]
    write_rows(output / "claim_adjudications_template.csv", claim_decision_fields,
               [{"claim_id": row["claim_id"]} for row in claim_rows])
    if reviewer_ids is not None:
        for reviewer in reviewer_ids:
            for kind, fields, rows in (("query", query_fields, query_rows), ("relevance", relevance_fields, relevance_rows), ("claim", claim_fields, claim_rows)):
                assigned = [dict(row, annotator_id=reviewer) for row in rows]
                write_rows(output / f"{kind}_tasks_{reviewer}.csv", fields, assigned)
    return {"queries": len(query_rows), "candidate_pairs": len(relevance_rows), "claims": len(claim_rows)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reviewer-a-id", help="Actual reviewer ID; supply with --reviewer-b-id")
    parser.add_argument("--reviewer-b-id", help="Actual reviewer ID; supply with --reviewer-a-id")
    args = parser.parse_args()
    if bool(args.reviewer_a_id) != bool(args.reviewer_b_id):
        parser.error("both reviewer IDs must be supplied together")
    reviewers = (args.reviewer_a_id, args.reviewer_b_id) if args.reviewer_a_id else None
    print(json.dumps(export(args.dataset, args.out, reviewers)))


if __name__ == "__main__":
    main()
