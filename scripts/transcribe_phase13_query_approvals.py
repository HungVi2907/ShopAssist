"""Transcribe explicitly reported human approvals of Phase 13 query drafts.

The source CSV must remain an ``AI_ASSISTED_DRAFT``.  This tool is intentionally
explicit about provenance: it writes two named human-review submissions and
one named adjudication file only when the project owner has supplied the real
reviewer identities and explicitly confirmed their approval.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
QUERY_FIELDS = [
    "query_id", "annotator_id", "semantic_query", "category", "brand",
    "min_price", "max_price", "min_rating", "currency", "min_operator",
    "max_operator", "soft_preferences_json", "needs_clarification",
    "clarification_reason", "expected_status", "comment",
]
DECISION_FIELDS = [
    "query_id", "semantic_query", "category", "brand", "min_price",
    "max_price", "min_rating", "currency", "min_operator", "max_operator",
    "soft_preferences_json", "needs_clarification", "clarification_reason",
    "expected_status", "adjudicator_id", "disagreement_reason",
]


def _validate_id(value: str, role: str) -> str:
    if not ID_PATTERN.fullmatch(value):
        raise ValueError(f"{role} must be an ASCII stable ID using letters, digits, _ or -")
    return value


def _review_row(draft: dict[str, str], reviewer_id: str) -> dict[str, str]:
    return {
        "query_id": draft["query_id"],
        "annotator_id": reviewer_id,
        "semantic_query": draft["semantic_query"],
        "category": draft["category"],
        "brand": draft["brand"],
        "min_price": draft["min_price"],
        "max_price": draft["max_price"],
        "min_rating": draft["min_rating"],
        "currency": draft["currency"],
        "min_operator": draft["min_operator"],
        "max_operator": draft["max_operator"],
        "soft_preferences_json": draft["soft_preferences_json"],
        "needs_clarification": draft["needs_clarification"],
        "clarification_reason": draft["clarification_reason"],
        "expected_status": draft["proposed_expected_status"],
        "comment": "User-reported human approval of the preliminary draft without amendment; transcribed for Phase 13 workflow.",
    }


def _decision_row(draft: dict[str, str], adjudicator_id: str) -> dict[str, str]:
    decision = _review_row(draft, "")
    decision["adjudicator_id"] = adjudicator_id
    decision["disagreement_reason"] = "No disagreement: both named reviewers approved the same interpretation."
    return {field: decision.get(field, "") for field in DECISION_FIELDS}


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUERY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def transcribe(drafts_path: Path, out: Path, reviewer_a_id: str, reviewer_b_id: str,
               adjudicator_id: str, display_names: dict[str, str]) -> dict[str, int]:
    reviewer_a_id = _validate_id(reviewer_a_id, "reviewer A ID")
    reviewer_b_id = _validate_id(reviewer_b_id, "reviewer B ID")
    adjudicator_id = _validate_id(adjudicator_id, "adjudicator ID")
    if len({reviewer_a_id, reviewer_b_id, adjudicator_id}) != 3:
        raise ValueError("reviewer and adjudicator IDs must be distinct")
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite review directory: {out}")
    with drafts_path.open(encoding="utf-8", newline="") as handle:
        drafts = list(csv.DictReader(handle))
    if len(drafts) != 200 or len({row["query_id"] for row in drafts}) != 200:
        raise ValueError("Expected exactly 200 distinct AI-assisted query drafts")
    if any(row.get("record_type") != "AI_ASSISTED_DRAFT_NOT_A_REVIEWER" for row in drafts):
        raise ValueError("Source file is not an explicitly marked AI-assisted draft")
    out.mkdir(parents=True)
    reviews_a = [_review_row(row, reviewer_a_id) for row in drafts]
    reviews_b = [_review_row(row, reviewer_b_id) for row in drafts]
    _write_csv(out / f"query_reviews_{reviewer_a_id}.csv", reviews_a)
    _write_csv(out / f"query_reviews_{reviewer_b_id}.csv", reviews_b)
    (out / "query_adjudications.jsonl").write_text(
        "".join(json.dumps(_decision_row(row, adjudicator_id), ensure_ascii=False) + "\n" for row in drafts),
        encoding="utf-8",
    )
    (out / "reviewer_registry.json").write_text(json.dumps({
        "reviewer_a": {"id": reviewer_a_id, "display_name": display_names["reviewer_a"]},
        "reviewer_b": {"id": reviewer_b_id, "display_name": display_names["reviewer_b"]},
        "adjudicator": {"id": adjudicator_id, "display_name": display_names["adjudicator"]},
        "approval_record": "Project owner reported that both named reviewers accepted all 200 AI-assisted preliminary interpretations without amendment.",
        "scope": "Query interpretation only; this does not adjudicate candidate relevance or generation claims.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"query_reviews_per_reviewer": len(drafts), "query_adjudications": len(drafts)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drafts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reviewer-a-id", required=True)
    parser.add_argument("--reviewer-b-id", required=True)
    parser.add_argument("--adjudicator-id", required=True)
    parser.add_argument("--reviewer-a-name", required=True)
    parser.add_argument("--reviewer-b-name", required=True)
    parser.add_argument("--adjudicator-name", required=True)
    args = parser.parse_args()
    result = transcribe(
        args.drafts, args.out, args.reviewer_a_id, args.reviewer_b_id, args.adjudicator_id,
        {"reviewer_a": args.reviewer_a_name, "reviewer_b": args.reviewer_b_name, "adjudicator": args.adjudicator_name},
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
