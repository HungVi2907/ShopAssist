"""Flatten saved, real Phase 12 results into claim review rows.

Input is JSONL with {query_id, generation_snapshot, result}; result must be a
serialized RecommendationResult. This script does not generate claims or labels.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

try:
    from scripts.validate_phase13_dataset import DEFAULT_DATASET, read_jsonl
except ModuleNotFoundError:  # direct script execution
    from validate_phase13_dataset import DEFAULT_DATASET, read_jsonl


def capture(source: Path, dataset: Path, output: Path) -> int:
    if output.exists():
        raise FileExistsError(f"Refusing to replace generation capture: {output}")
    query_ids = {q["query_id"] for q in read_jsonl(dataset / "queries.jsonl")}
    manifest = json.loads((dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
    v2 = manifest.get("dataset_version") != "phase13-pilot-v1"
    pools = {p["query_id"]: {c["product_id"]: c for c in p["candidates"]}
             for p in read_jsonl(dataset / "candidate_pools.jsonl")}
    rows = []
    for case in read_jsonl(source):
        qid = case.get("query_id")
        snapshot = case.get("generation_snapshot")
        result = case.get("result", {})
        if qid not in query_ids or not snapshot or result.get("status") not in {"SUCCESS", "DETERMINISTIC_FALLBACK"}:
            raise ValueError(f"Invalid query, snapshot, or Phase 12 status: {qid}")
        provenance = {key: case.get(key) for key in ("provider", "model_version", "prompt_configuration")}
        if v2 and any(not value for value in provenance.values()):
            raise ValueError(f"{qid}: provider, model version and prompt configuration are required")
        for product in result.get("products", []):
            pid = product["product_id"]
            if v2 and (pid not in pools.get(qid, {}) or not product.get("available_evidence")):
                raise ValueError(f"{qid}/{pid}: generation product or evidence is absent from the frozen pool")
            evidence = {item["evidence_id"]: item["text"] for item in product.get("available_evidence", []) if item.get("product_id") == pid}
            metadata = pools.get(qid, {}).get(pid, {})
            common = {"generation_snapshot": snapshot, **provenance,
                      "source_result_sha256": hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
                      "product_metadata_json": json.dumps({key: metadata.get(key) for key in
                          ("product_name", "category", "brand", "discounted_price", "rating")}, ensure_ascii=False)}
            groups = [product.get("strengths", []), product.get("limitations", [])]
            for group_name, group in zip(("strength", "limitation"), groups):
                for index, claim in enumerate(group, 1):
                    citations = claim.get("evidence_ids", [])
                    if any(eid not in evidence for eid in citations):
                        raise ValueError(f"{qid}/{pid}: evidence ID absent or belongs to another product")
                    rows.append({
                        "claim_id": f"{qid}:{pid}:{group_name}:{index}", "query_id": qid,
                        "product_id": pid, "claim": claim["claim"],
                        "evidence_ids_json": json.dumps(citations, ensure_ascii=False),
                        "evidence_text_json": json.dumps(evidence, ensure_ascii=False),
                        **common,
                    })
            for field in ("summary_reason", "comparison_note"):
                if product.get(field):
                    rows.append({
                        "claim_id": f"{qid}:{pid}:{field}", "query_id": qid,
                        "product_id": pid, "claim": product[field],
                        "evidence_ids_json": "[]", "evidence_text_json": json.dumps(evidence, ensure_ascii=False),
                        **common,
                    })
    if not rows:
        raise ValueError("No real Phase 12 claims found")
    with (dataset / "generation_claims.csv").open(encoding="utf-8-sig", newline="") as template:
        fields = next(csv.reader(template))
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(f"Captured {capture(args.source, args.dataset, args.out)} unlabeled claims")


if __name__ == "__main__":
    main()
