"""Execute multi-method candidate capture for v4_full_silver.

Runs TF-IDF, dense (pgvector BGE), and hybrid (Phase 10 RRF) across all eligible queries.
Preserves the complete, untruncated multi-method union at contribution depth 10.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shopassist.evaluation.codex_native import (
    _load_unique_queries,
    _refresh_native_manifest,
    _require_native_dataset,
    _verify_native_snapshot,
    _write_checkpoint,
    cap_native_candidate_pools,
)
from shopassist.evaluation.silver import (
    PROJECT_ROOT,
    audited_queries,
    capture_multi_method_pools,
    read_jsonl,
)

DATASET = PROJECT_ROOT / "data/evaluation/phase13/ai_silver/v4_full_silver"
CONTRIBUTION_DEPTH = 10
METHODS = ("tfidf", "dense", "hybrid")


async def run_capture(max_queries: int | None = None):
    manifest = _require_native_dataset(DATASET)
    _verify_native_snapshot(DATASET, manifest)

    audits = read_jsonl(DATASET / "query_audit.jsonl")
    if not audits:
        raise ValueError("Complete native query audits are required before candidate capture")

    source = _load_unique_queries(DATASET)
    eligible = [
        row for row in audited_queries(source.values(), audits)
        if row.get("silver_audit_status") == "COMPLETE"
    ]
    if max_queries:
        eligible = eligible[:max_queries]

    print(f"Starting candidate capture for {len(eligible)} audited queries...")
    print(f"Methods: {METHODS}, Contribution Depth: {CONTRIBUTION_DEPTH}")

    catalog = PROJECT_ROOT / str(manifest["catalog_artifact"])
    catalog_sha = str(manifest["catalog_sha256"])

    t0 = time.time()
    pools, runs, blockers = await capture_multi_method_pools(
        eligible,
        catalog_path=catalog,
        catalog_sha256=catalog_sha,
        methods=METHODS,
        contribution_depth=CONTRIBUTION_DEPTH,
        allow_partial_methods=False,
    )
    t1 = time.time()
    print(f"Capture completed in {t1 - t0:.1f}s.")
    print(f"Retrieved pools: {len(pools)}, Total retrieval runs: {len(runs)}, Blockers: {len(blockers)}")

    # Retain full multi-method union without artificial truncation
    total_pairs = sum(len(p.get("candidates") or []) for p in pools)
    print(f"Total candidate pairs in pool union: {total_pairs}")
    capped, cap_report = cap_native_candidate_pools(pools, max_pairs=max(10000, total_pairs))

    for target_file in (DATASET / "candidate_pools.jsonl", DATASET / "retrieval_runs.jsonl", DATASET / "capture_blockers.jsonl"):
        if target_file.exists():
            target_file.unlink()

    _write_checkpoint(DATASET / "candidate_pools.jsonl", capped, resume=False)
    _write_checkpoint(DATASET / "retrieval_runs.jsonl", runs, resume=False)
    _write_checkpoint(DATASET / "capture_blockers.jsonl", blockers, resume=False)

    _refresh_native_manifest(
        DATASET,
        completion_status="CANDIDATES_CAPTURED",
        native_updates={
            "capture_methods": list(METHODS),
            "capture_contribution_depth": CONTRIBUTION_DEPTH,
            "candidate_pair_cap": cap_report,
            "capture_blocker_count": len(blockers),
            "candidate_pool_count": len(capped),
            "candidate_pair_count": total_pairs,
        },
    )
    print("Checkpoint saved and manifest refreshed with CANDIDATES_CAPTURED.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Capture multi-method candidate pools for v4_full_silver")
    parser.add_argument("--max-queries", type=int, default=None, help="Limit number of queries to capture (for testing)")
    args = parser.parse_args()

    if sys.platform.startswith("win"):
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(run_capture(max_queries=args.max_queries))
    else:
        asyncio.run(run_capture(max_queries=args.max_queries))


if __name__ == "__main__":
    main()

