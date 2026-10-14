"""Execute the 10-pair Antigravity AI relevance judging experiment for Phase 13.

Requirements:
- Native Antigravity inference under Google account.
- No external paid APIs (Gemini API, OpenAI, OpenRouter, Groq).
- Preserves all 90 Silver qrels in v3_codex_native.
- Isolates new judgments into data/evaluation/phase13/ai_silver/audit_antigravity_10pair.
- Uses existing deterministic Python validation and metrics.
- Performs post-hoc cross-model quality comparison with historical Codex labels.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shopassist.evaluation.codex_native import (
    CODEX_NATIVE_ANNOTATION_METHOD,
    CODEX_NATIVE_PROVIDER,
    import_native_relevance_reviews,
    prepare_native_relevance_adjudication_tasks,
    finalise_native_relevance_adjudications,
    _require_native_dataset,
    _refresh_native_manifest,
)
from shopassist.evaluation.silver import (
    PROJECT_ROOT,
    file_sha256,
    fingerprint,
    read_jsonl,
    write_jsonl,
    utc_now,
    load_manifest,
    write_manifest,
)

AUDIT_DIR = PROJECT_ROOT / "data/evaluation/phase13/ai_silver/audit_antigravity_10pair"
CODEX_V3_DIR = PROJECT_ROOT / "data/evaluation/phase13/ai_silver/v3_codex_native"
SOURCE_V3 = PROJECT_ROOT / "data/evaluation/phase13/v3"

ANTIGRAVITY_MODEL = "gemini-3.8-flash"


def setup_audit_dataset() -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    input_dir = AUDIT_DIR / "codex_native_inputs"
    rel_dir = input_dir / "relevance"
    rel_dir.mkdir(parents=True, exist_ok=True)

    # Copy source queries snapshot
    queries = read_jsonl(CODEX_V3_DIR / "queries.jsonl")
    write_jsonl(AUDIT_DIR / "queries.jsonl", queries)

    # Copy Q0007 query audit
    codex_audits = read_jsonl(CODEX_V3_DIR / "query_audit.jsonl")
    q7_audit = [a for a in codex_audits if a["query_id"] == "Q0007"]
    write_jsonl(AUDIT_DIR / "query_audit.jsonl", q7_audit)

    # 10 selected candidates from batch 1
    tasks_a = read_jsonl(CODEX_V3_DIR / "codex_native_inputs/relevance/judge_a_batch_001.jsonl")
    selected_pids = [t["product_id"] for t in tasks_a]
    assert len(selected_pids) == 10

    # Build candidate_pools.jsonl with exactly these 10 candidates
    codex_pools = read_jsonl(CODEX_V3_DIR / "candidate_pools.jsonl")
    q7_pool = [p for p in codex_pools if p["query_id"] == "Q0007"][0]
    capped_candidates = [c for c in q7_pool["candidates"] if c["product_id"] in selected_pids]
    assert len(capped_candidates) == 10

    pool_10 = [{
        **q7_pool,
        "candidates": capped_candidates,
        "candidate_count": 10,
        "candidate_cap": {
            "max_total_pairs": 10,
            "original_query_candidate_count": len(q7_pool["candidates"]),
            "selected_query_candidate_count": 10,
            "selection_rule": "Audit sample: exact Batch 001 10-pair slice for cross-model quality comparison.",
        },
        "pool_fingerprint": fingerprint({
            "source_pool_fingerprint": q7_pool.get("pool_fingerprint"),
            "candidate_cap": {"max_total_pairs": 10},
            "candidates": capped_candidates,
        }),
    }]
    write_jsonl(AUDIT_DIR / "candidate_pools.jsonl", pool_10)

    # Copy task index and batch files
    write_jsonl(input_dir / "relevance_task_index.jsonl", tasks_a)
    write_jsonl(rel_dir / "judge_a_batch_001.jsonl", tasks_a)

    tasks_b = read_jsonl(CODEX_V3_DIR / "codex_native_inputs/relevance/judge_b_batch_001.jsonl")
    write_jsonl(rel_dir / "judge_b_batch_001.jsonl", tasks_b)

    # Initialize manifest
    v3_manifest = load_manifest(CODEX_V3_DIR)
    manifest = {
        "format_version": "1.0.0",
        "dataset_version": "audit_antigravity_10pair",
        "source_dataset_version": "v3_codex_native",
        "source_dataset_relpath": "data/evaluation/phase13/ai_silver/v3_codex_native",
        "source_git_commit": v3_manifest.get("source_git_commit", "UNKNOWN"),
        "source_query_sha256": v3_manifest.get("source_query_sha256"),
        "queries_snapshot_sha256": file_sha256(AUDIT_DIR / "queries.jsonl"),
        "catalog_artifact": v3_manifest.get("catalog_artifact"),
        "catalog_sha256": v3_manifest.get("catalog_sha256"),
        "catalog_product_count": v3_manifest.get("catalog_product_count"),
        "query_count": len(queries),
        "annotation_method": CODEX_NATIVE_ANNOTATION_METHOD,
        "label_quality": "SILVER",
        "human_verified": False,
        "phase14_ready": False,
        "silver_ready": False,
        "completion_status": "RELEVANCE_TASKS_PREPARED",
        "created_utc": utc_now(),
        "judge_configuration": {
            "prompt_version": "phase13-codex-native-2026-10-14",
            "execution_mode": "ANTIGRAVITY_NATIVE",
            "judge_a": {"provider": "GOOGLE_ANTIGRAVITY", "model": ANTIGRAVITY_MODEL},
            "judge_b": {"provider": "GOOGLE_ANTIGRAVITY", "model": ANTIGRAVITY_MODEL},
            "adjudicator": {"provider": "GOOGLE_ANTIGRAVITY", "model": ANTIGRAVITY_MODEL},
            "same_model_correlation_risk": "SHARED_ANTIGRAVITY_GEMINI_MODEL",
            "independence": "BLINDED_ANTIGRAVITY_AGENT_EVALUATION; separate prompt contexts",
        },
        "codex_native": {
            "execution_mode": "ANTIGRAVITY_NATIVE",
            "external_provider_calls": "DISABLED_BY_DESIGN",
            "model_metadata": ANTIGRAVITY_MODEL,
            "judge_separation": "Blinded evaluation packets; separate Judge A and Judge B scoring passes",
            "same_model_correlation_risk": "SHARED_ANTIGRAVITY_GEMINI_MODEL",
            "adjudication": "Machine adjudication with deterministic constraint overrides",
            "known_blindness_limit": "Judges evaluate blinded packets without access to prior Codex grades or each other's outputs.",
            "task_prompt_version": "phase13-codex-native-2026-10-14",
            "relevance_task_schema_version": "codex-native-relevance-task-v1",
            "relevance_task_count": 10,
            "relevance_batch_size": 10,
            "relevance_batch_count": 1,
            "relevance_pair_cap": 10,
            "relevance_task_fingerprints": {
                f"{row['query_id']}/{row['product_id']}": row["task_fingerprint"] for row in tasks_a
            },
        },
        "known_limitations": [
            "AI-generated Silver labels are not independently human-verified ground truth.",
            "No Phase 14 promotion is permitted from Silver labels alone.",
            "Antigravity judges use Gemini 3.8 Flash inference under the user's Google account; agreement is a consistency signal, not ground truth.",
            "Audit experiment is strictly capped at 10 query-product pairs.",
        ],
        "unresolved_cases": [],
        "artifact_sha256": {},
    }
    write_manifest(AUDIT_DIR, manifest)
    print("Audit dataset initialized at:", AUDIT_DIR)


if __name__ == "__main__":
    setup_audit_dataset()
