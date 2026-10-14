"""Capture an explicitly unverified v3 retrieval smoke test.

This command makes no LLM call and writes only a provisional diagnostic under
``data/interim``.  Its outputs must never be copied into an AI-Silver release.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from shopassist.evaluation.silver import capture_multi_method_pools, read_jsonl, write_jsonl  # noqa: E402


SOURCE = ROOT / "data/evaluation/phase13/v3"
DEFAULT_QUERY_IDS = {"Q0007", "Q0008", "Q0013", "Q0045"}


async def run(args: argparse.Namespace) -> dict:
    if args.out.exists():
        raise FileExistsError(f"Refusing to overwrite provisional smoke output: {args.out}")
    manifest = json.loads((SOURCE / "dataset_manifest.json").read_text(encoding="utf-8"))
    catalog = ROOT / manifest["catalog_artifact"]
    digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
    if digest != manifest["catalog_sha256"]:
        raise ValueError("Pinned catalog SHA-256 differs from v3 manifest")
    wanted = set(args.query_id or DEFAULT_QUERY_IDS)
    queries = [row for row in read_jsonl(SOURCE / "queries.jsonl") if row["query_id"] in wanted]
    missing = wanted - {row["query_id"] for row in queries}
    if missing:
        raise ValueError(f"Unknown v3 query IDs: {sorted(missing)}")
    pools, runs, blockers = await capture_multi_method_pools(
        queries, catalog_path=catalog, catalog_sha256=digest, methods=args.methods.split(","), contribution_depth=args.depth,
        allow_partial_methods=args.allow_partial_methods, allow_unverified_v3_reference=True,
    )
    args.out.mkdir(parents=True, exist_ok=False)
    write_jsonl(args.out / "candidate_pools_unverified_v3.jsonl", pools)
    write_jsonl(args.out / "retrieval_runs_unverified_v3.jsonl", runs)
    write_jsonl(args.out / "blockers.jsonl", blockers)
    report = {
        "status": "PROVISIONAL_UNVERIFIED_V3_REFERENCE", "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_dataset": "phase13-v3", "catalog_sha256": digest, "query_ids": sorted(wanted),
        "methods_requested": args.methods.split(","), "frozen_provisional_pools": len(pools), "retrieval_runs": len(runs),
        "blockers": len(blockers), "not_a_silver_benchmark": True,
        "prohibition": "These captures use unverified v3 interpretations and must not be promoted, judged as Silver, or used for Phase 14 claims.",
    }
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--query-id", action="append")
    parser.add_argument("--methods", default="tfidf,dense,hybrid")
    parser.add_argument("--depth", type=int, default=10)
    parser.add_argument("--allow-partial-methods", action="store_true")
    args = parser.parse_args()
    # psycopg async requires a Selector event loop on Windows.
    if sys.platform.startswith("win"):
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            report = runner.run(run(args))
    else:
        report = asyncio.run(run(args))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
