"""Check Phase 13 draft coverage against the pinned product catalog.

This audit checks literal price hypotheses only. It never sets expected_status
or substitutes for review of semantic availability or a live database snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.validate_phase13_dataset import ROOT, near_duplicates, read_jsonl
except ModuleNotFoundError:
    from validate_phase13_dataset import ROOT, near_duplicates, read_jsonl


def audit(dataset: Path) -> dict:
    import pandas as pd

    manifest = json.loads((dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
    catalog = ROOT / manifest["catalog_artifact"]
    digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
    if digest != manifest["catalog_sha256"]:
        raise ValueError("Pinned catalog hash differs from manifest")
    frame = pd.read_parquet(catalog, columns=["product_id", "category", "discounted_price"])
    if len(frame) != manifest["catalog_product_count"] or frame.product_id.nunique() != len(frame):
        raise ValueError("Pinned catalog row count or product IDs are invalid")
    queries = read_jsonl(dataset / "queries.jsonl")
    category_counts = dict(Counter(frame.category.astype(str)))
    if any(category_counts.get(q["planning_category"], 0) == 0 for q in queries):
        raise ValueError("A planning category has no catalog products")
    potential_zero = []
    for q in queries:
        if q["query_type"] != "NO_RESULT":
            continue
        match = re.search(r"\b(?:under|below)\s+(\d+(?:\.\d+)?)\s+INR\b", q["raw_query"], re.I)
        if not match:
            potential_zero.append({"query_id": q["query_id"], "check": "NOT_PARSABLE", "expected_status": None})
            continue
        limit = float(match.group(1))
        count = int(((frame.category == q["planning_category"]) & (frame.discounted_price < limit)).sum())
        potential_zero.append({"query_id": q["query_id"], "planning_category": q["planning_category"],
                               "literal_constraint": f"discounted_price < {limit} INR", "catalog_matching_count": count,
                               "check": "ZERO_UNDER_LITERAL_CONSTRAINT" if count == 0 else "HAS_CATALOG_MATCHES",
                               "expected_status": None})
    return {"status": "DRAFT_CATALOG_AUDIT", "created_utc": datetime.now(timezone.utc).isoformat(),
            "catalog_sha256": digest, "catalog_rows": len(frame), "queries": len(queries),
            "distinct_queries": len({q["raw_query"].casefold() for q in queries}),
            "near_duplicate_pairs": near_duplicates(queries),
            "catalog_category_counts": {name: category_counts[name] for name in sorted({q["planning_category"] for q in queries})},
            "planned_category_counts": dict(sorted(Counter(q["planning_category"] for q in queries).items())),
            "planned_type_counts": dict(sorted(Counter(q["query_type"] for q in queries).items())),
            "potential_no_result_cases": potential_zero,
            "interpretation": "Literal catalog checks are planning evidence only; human review and exact Phase 10 capture are required before NO_RESULTS ground truth."}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/evaluation/phase13/v2")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"Refusing to overwrite catalog audit: {args.out}")
    result = audit(args.dataset)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.out.parent.resolve() == args.dataset.resolve():
        manifest_path = args.dataset / "dataset_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["catalog_draft_audit_sha256"] = hashlib.sha256(args.out.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"catalog_rows": result["catalog_rows"], "queries": result["queries"],
                      "near_duplicates": len(result["near_duplicate_pairs"]),
                      "potential_no_result_cases": len(result["potential_no_result_cases"])}))


if __name__ == "__main__":
    main()
