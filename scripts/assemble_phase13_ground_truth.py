"""Assemble reviewer submissions into a new, unfrozen dataset version.

This script only transcribes explicit human decisions. It never creates a
reviewer, grade, claim label, or adjudicated interpretation on its own.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.validate_phase13_dataset import read_csv, read_jsonl, validate
except ModuleNotFoundError:  # direct script execution
    from validate_phase13_dataset import read_csv, read_jsonl, validate

FLAGS = ("category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation")
QUERY_FIELDS = ("semantic_query", "category", "brand", "min_price", "max_price", "min_rating", "currency", "min_operator", "max_operator", "soft_preferences_json", "needs_clarification", "clarification_reason", "expected_status")
CLAIM_FIELDS = ("support_label", "factual_correctness", "recommendation_relevance", "missing_information_handling")


def _pairs(rows: list[dict], key_fields: tuple[str, ...]) -> dict[tuple, tuple[dict, dict]]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        grouped[key].append(row)
    result = {}
    for key, pair in grouped.items():
        ids = {row.get("annotator_id") for row in pair}
        if len(pair) != 2 or len(ids) != 2 or not all(ids):
            raise ValueError(f"{key}: exactly two distinct, identified reviewer submissions are required")
        result[key] = tuple(sorted(pair, key=lambda row: row["annotator_id"]))
    return result


def _decisions(rows: list[dict], key_fields: tuple[str, ...]) -> dict[tuple, dict]:
    result = {}
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        if key in result or not row.get("adjudicator_id"):
            raise ValueError(f"{key}: duplicate decision or missing adjudicator")
        result[key] = row
    return result


def assemble_queries(queries: list[dict], reviews: list[dict], decisions: list[dict]) -> list[dict]:
    pairs = _pairs(reviews, ("query_id",))
    adjudicated = _decisions(decisions, ("query_id",))
    expected_ids = {(q["query_id"],) for q in queries}
    if set(pairs) != expected_ids or set(adjudicated) != expected_ids:
        raise ValueError("Every query needs two reviews and one explicit adjudication decision")
    result = []
    for original in queries:
        qid = original["query_id"]
        left, right = pairs[(qid,)]
        decision = adjudicated[(qid,)]
        for field in QUERY_FIELDS:
            if field not in decision or decision[field] is None:
                raise ValueError(f"{qid}: final interpretation missing {field}")
        if any(left.get(field) != right.get(field) for field in QUERY_FIELDS) and not decision.get("disagreement_reason"):
            raise ValueError(f"{qid}: reviewer disagreement needs a reason")
        try:
            preferences = json.loads(decision["soft_preferences_json"])
        except json.JSONDecodeError as exc:
            raise ValueError(f"{qid}: invalid adjudicated preferences JSON") from exc
        if not isinstance(preferences, list) or any(not isinstance(p, str) for p in preferences):
            raise ValueError(f"{qid}: adjudicated preferences must be strings")
        def number(field: str) -> float | None:
            return float(decision[field]) if str(decision[field]).strip() else None
        final = dict(original)
        final["expected_query_understanding"] = {
            "semantic_query": decision["semantic_query"],
            "hard_constraints": {"category": decision["category"] or None, "brand": decision["brand"] or None,
                                 "min_price": number("min_price"), "max_price": number("max_price"),
                                 "min_rating": number("min_rating"), "currency": decision["currency"] or "INR"},
            "soft_preferences": preferences,
            "needs_clarification": str(decision["needs_clarification"]).strip().lower() == "true",
            "clarification_reason": decision["clarification_reason"] or None,
        }
        final["price_boundary_semantics"] = {"min_operator": decision["min_operator"] or None, "max_operator": decision["max_operator"] or None}
        final["expected_status"] = decision["expected_status"]
        final["annotation_status"] = "ADJUDICATED"
        result.append(final)
    return result


def assemble_qrels(pools: list[dict], reviews: list[dict], decisions: list[dict]) -> list[dict]:
    pairs = _pairs(reviews, ("query_id", "product_id"))
    adjudicated = _decisions(decisions, ("query_id", "product_id"))
    expected = {(p["query_id"], c["product_id"]) for p in pools for c in p.get("candidates", [])}
    if set(pairs) != expected or set(adjudicated) != expected:
        raise ValueError("Every frozen candidate pair needs two reviews and one explicit decision")
    result = []
    for key in sorted(expected):
        left, right = pairs[key]
        decision = adjudicated[key]
        if left.get("relevance_grade") not in {"0", "1", "2", "3"} or right.get("relevance_grade") not in {"0", "1", "2", "3"} or decision.get("adjudicated_grade") not in {"0", "1", "2", "3"}:
            raise ValueError(f"{key}: invalid relevance grade")
        if any(str(review.get(flag, "")).lower() not in {"true", "false"} for review in (left, right) for flag in FLAGS):
            raise ValueError(f"{key}: reviewer constraint flags are incomplete")
        if (left["relevance_grade"] != right["relevance_grade"] or any(left.get(f) != right.get(f) for f in FLAGS)) and not decision.get("disagreement_reason"):
            raise ValueError(f"{key}: reviewer disagreement needs a reason")
        flags = {field: str(decision.get(field, "")).lower() for field in FLAGS}
        if any(value not in {"true", "false"} for value in flags.values()):
            raise ValueError(f"{key}: adjudicated constraint flags are incomplete")
        if int(decision["adjudicated_grade"]) >= 2 and "true" in flags.values():
            raise ValueError(f"{key}: hard violation conflicts with relevant grade")
        result.append({
            "query_id": key[0], "product_id": key[1],
            "reviewer_a_id": left["annotator_id"], "reviewer_b_id": right["annotator_id"],
            "reviewer_a_grade": left["relevance_grade"], "reviewer_b_grade": right["relevance_grade"],
            "adjudicated_grade": decision["adjudicated_grade"], **flags,
            "disagreement_reason": decision.get("disagreement_reason", ""),
        })
    return result


def assemble_claims(claims: list[dict], reviews: list[dict], decisions: list[dict]) -> list[dict]:
    if not claims:
        if reviews or decisions:
            raise ValueError("Claim reviews exist without frozen source claims")
        return []
    pairs = _pairs(reviews, ("claim_id",))
    adjudicated = _decisions(decisions, ("claim_id",))
    expected = {(c["claim_id"],) for c in claims}
    if set(pairs) != expected or set(adjudicated) != expected:
        raise ValueError("Every source claim needs two reviews and one explicit decision")
    result = []
    for claim in claims:
        key = (claim["claim_id"],)
        left, right = pairs[key]
        decision = adjudicated[key]
        if any(left.get(field) != right.get(field) for field in CLAIM_FIELDS) and not decision.get("disagreement_reason"):
            raise ValueError(f"{key}: reviewer disagreement needs a reason")
        for field in ("adjudicated_support", "adjudicated_factual", "adjudicated_relevance", "missing_information_handling"):
            if not decision.get(field):
                raise ValueError(f"{key}: final claim judgment missing {field}")
        final = dict(claim)
        final.update({
            "reviewer_a_id": left["annotator_id"], "reviewer_b_id": right["annotator_id"],
            "adjudicator_id": decision["adjudicator_id"],
            "reviewer_a_support": left["support_label"], "reviewer_b_support": right["support_label"],
            "adjudicated_support": decision["adjudicated_support"],
            "reviewer_a_factual": left["factual_correctness"], "reviewer_b_factual": right["factual_correctness"],
            "adjudicated_factual": decision["adjudicated_factual"],
            "reviewer_a_relevance": left["recommendation_relevance"], "reviewer_b_relevance": right["recommendation_relevance"],
            "adjudicated_relevance": decision["adjudicated_relevance"],
            "missing_information_handling": decision["missing_information_handling"],
            "disagreement_reason": decision.get("disagreement_reason", ""),
        })
        result.append(final)
    return result


def _write_csv(path: Path, rows: list[dict], template: Path) -> None:
    with template.open(encoding="utf-8-sig", newline="") as handle:
        fields = next(csv.reader(handle))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _review_rows(paths: Path | list[Path]) -> list[dict]:
    inputs = [paths] if isinstance(paths, Path) else paths
    return [row for path in inputs for row in read_csv(path)]


def assemble_version(dataset: Path, out: Path, *, query_reviews: Path | list[Path], query_decisions: Path,
                     relevance_reviews: Path | list[Path], relevance_decisions: Path,
                     claim_reviews: Path | list[Path], claim_decisions: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite dataset version: {out}")
    source_queries = read_jsonl(dataset / "queries.jsonl")
    source_pools = read_jsonl(dataset / "candidate_pools.jsonl")
    source_claims = read_csv(dataset / "generation_claims.csv")
    reviewed_queries = _review_rows(query_reviews)
    reviewed_relevance = _review_rows(relevance_reviews)
    reviewed_claims = _review_rows(claim_reviews)
    decisions_query = read_jsonl(query_decisions)
    decisions_relevance = read_csv(relevance_decisions)
    decisions_claim = read_csv(claim_decisions)
    queries = assemble_queries(source_queries, reviewed_queries, decisions_query)
    qrels = assemble_qrels(source_pools, reviewed_relevance, decisions_relevance)
    claims = assemble_claims(source_claims, reviewed_claims, decisions_claim)
    out.mkdir(parents=True)
    for name in ("candidate_pools.jsonl", "splits.json"):
        shutil.copy2(dataset / name, out / name)
    if (dataset / "catalog_draft_audit.json").is_file():
        shutil.copy2(dataset / "catalog_draft_audit.json", out / "catalog_draft_audit.json")
    (out / "queries.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in queries), encoding="utf-8")
    _write_csv(out / "qrels.csv", qrels, dataset / "qrels.csv")
    _write_csv(out / "generation_claims.csv", claims, dataset / "generation_claims.csv")
    _write_csv(out / "query_annotations.csv", reviewed_queries, dataset / "query_annotations.csv")
    _write_csv(out / "relevance_annotations.csv", reviewed_relevance, dataset / "relevance_annotations.csv")
    for source, name in ((query_decisions, "query_adjudications.jsonl"), (relevance_decisions, "relevance_adjudications.csv"),
                         (claim_decisions, "claim_adjudications.csv")):
        shutil.copy2(source, out / name)
    _write_csv(out / "claim_annotations.csv", reviewed_claims,
               (claim_reviews if isinstance(claim_reviews, Path) else claim_reviews[0]))
    manifest = json.loads((dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
    manifest.update({
        "dataset_version": f"phase13-{out.name}", "source_version": manifest["dataset_version"],
        "source_dataset_relpath": str(dataset.resolve().relative_to(Path(__file__).resolve().parents[1])).replace("\\", "/"),
        "created_utc": datetime.now(timezone.utc).isoformat(), "query_count": len(queries),
        "qrel_count": len(qrels), "annotation_status": "ADJUDICATED", "frozen": False,
        "reviewer_count": len({r["annotator_id"] for r in reviewed_queries + reviewed_relevance + reviewed_claims}),
        "source_file_sha256": {name: hashlib.sha256((dataset / name).read_bytes()).hexdigest() for name in ("queries.jsonl", "candidate_pools.jsonl", "generation_claims.csv")},
        "artifact_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in out.iterdir()
                            if path.name in {"queries.jsonl", "candidate_pools.jsonl", "qrels.csv",
                                             "query_annotations.csv", "relevance_annotations.csv", "generation_claims.csv",
                                             "query_adjudications.jsonl", "relevance_adjudications.csv",
                                             "claim_annotations.csv", "claim_adjudications.csv"}},
    })
    (out / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate(out)
    (out / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        raise ValueError(f"Assembled version has validation errors; inspect {out / 'validation_report.json'}")
    return {"queries": len(queries), "qrels": len(qrels), "claims": len(claims), "reviewers": manifest["reviewer_count"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    for name in ("query-reviews", "query-decisions", "relevance-reviews", "relevance-decisions", "claim-reviews", "claim-decisions"):
        parser.add_argument(f"--{name}", required=True, type=Path,
                            nargs="+" if name.endswith("reviews") else None)
    args = parser.parse_args()
    result = assemble_version(args.dataset, args.out, query_reviews=args.query_reviews, query_decisions=args.query_decisions,
                              relevance_reviews=args.relevance_reviews, relevance_decisions=args.relevance_decisions,
                              claim_reviews=args.claim_reviews, claim_decisions=args.claim_decisions)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
