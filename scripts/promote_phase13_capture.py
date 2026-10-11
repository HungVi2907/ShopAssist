"""Promote an authentic, staged Phase 10 or Phase 12 capture to a new version.

No labels are inferred. The source remains immutable, and review can begin on
the newly versioned frozen capture after structural validation passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.validate_phase13_dataset import ROOT, read_csv, read_jsonl, validate
except ModuleNotFoundError:
    from validate_phase13_dataset import ROOT, read_csv, read_jsonl, validate


CORE = ("queries.jsonl", "candidate_pools.jsonl", "qrels.csv", "query_annotations.csv",
        "relevance_annotations.csv", "generation_claims.csv", "splits.json")
REVIEW = ("query_adjudications.jsonl", "relevance_adjudications.csv", "claim_annotations.csv",
          "claim_adjudications.csv")


def promote(source: Path, capture: Path, out: Path, *, kind: str) -> dict:
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite dataset version: {out}")
    if kind not in {"candidates", "generation"}:
        raise ValueError("kind must be candidates or generation")
    source_manifest = json.loads((source / "dataset_manifest.json").read_text(encoding="utf-8"))
    source_split = json.loads((source / "splits.json").read_text(encoding="utf-8"))
    if source_split.get("status") == "FROZEN":
        raise ValueError("Cannot change captures after split freeze")
    queries = read_jsonl(source / "queries.jsonl")
    source_pools = read_jsonl(source / "candidate_pools.jsonl")
    if kind == "candidates":
        if source_pools:
            raise ValueError("Candidate pool already exists; use a fresh source version")
        captured = read_jsonl(capture)
        eligible = {q["query_id"] for q in queries if q.get("annotation_status") == "ADJUDICATED" and q.get("expected_status") in {"SUCCESS", "NO_RESULTS"}}
        if not eligible or {p.get("query_id") for p in captured} != eligible or len(captured) != len(eligible):
            raise ValueError("Candidate capture must cover every eligible adjudicated query exactly once")
        if any(p.get("capture_status") != "FROZEN" for p in captured):
            raise ValueError("Candidate capture is not frozen")
        target_name = "candidate_pools.jsonl"
    else:
        if not source_pools or read_csv(source / "generation_claims.csv"):
            raise ValueError("Frozen candidate pools and an empty source claim file are required")
        captured = read_csv(capture)
        if not captured or len({row.get("claim_id") for row in captured}) != len(captured):
            raise ValueError("Generation capture has no claims or duplicate claim IDs")
        target_name = "generation_claims.csv"
    out.mkdir(parents=True)
    for name in (*CORE, *REVIEW, "catalog_draft_audit.json"):
        if (source / name).is_file():
            shutil.copy2(source / name, out / name)
    shutil.copy2(capture, out / target_name)
    manifest = dict(source_manifest)
    manifest.update({"dataset_version": f"phase13-{out.name}", "source_version": source_manifest["dataset_version"],
                     "source_dataset_relpath": str(source.resolve().relative_to(ROOT)).replace("\\", "/"),
                     "created_utc": datetime.now(timezone.utc).isoformat(), "frozen": False,
                     "source_file_sha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                                            for name in CORE if (source / name).is_file()},
                     "candidate_capture_status" if kind == "candidates" else "generation_capture_status": "FROZEN",
                     "artifact_sha256": {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                                         for name in (*CORE, *REVIEW) if name != "splits.json" and (out / name).is_file()}})
    (out / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate(out)
    (out / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        raise ValueError(f"Promoted dataset validation failed: {report['errors']}")
    return {"version": out.name, "kind": kind, "captured_rows": len(captured), "phase14_ready": report["phase14_ready"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kind", choices=("candidates", "generation"), required=True)
    args = parser.parse_args()
    print(json.dumps(promote(args.source, args.capture, args.out, kind=args.kind)))


if __name__ == "__main__":
    main()
