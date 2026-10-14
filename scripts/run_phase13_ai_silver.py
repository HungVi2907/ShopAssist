"""Run the resumable Phase 13 AI-Silver dataset pipeline.

This command operates only on ``data/evaluation/phase13/ai_silver/<version>``.
It never writes to v1/v2/v3 and never changes the human Phase 14 readiness
gate.  API credentials are opt-in through the isolated
``SHOPASSIST_SILVER_{A,B,ADJUDICATOR}_*`` environment variables documented in
``docs/phase13_ai_silver_pipeline.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Allow ``python scripts/run_phase13_ai_silver.py`` from a checkout that has
# not been installed as an editable package yet.
_SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_SCRIPT_ROOT / "src"))

from shopassist.evaluation.silver import (
    PROJECT_ROOT,
    QREL_FIELDS,
    OpenAICompatibleJudgeProvider,
    agreement_statistics,
    adjudicate_pair,
    audit_query_with_judges,
    query_audit_statistics,
    audited_queries,
    capture_real_generation_claims,
    capture_multi_method_pools,
    evaluate_retrieval_runs,
    file_sha256,
    initialise_silver_dataset,
    load_manifest,
    qrels_from_adjudications,
    plan_grouped_split,
    read_jsonl,
    read_csv_rows,
    refresh_manifest,
    select_pilot_queries,
    validate_silver_dataset,
    judge_generation_claim,
    adjudicate_generation_claim,
    write_csv_rows,
    write_jsonl,
    write_validation_report,
)
from shopassist.evaluation.codex_native import (
    capture_native_candidate_pools,
    finalise_native_query_audits,
    finalise_native_relevance_adjudications,
    import_native_query_reviews,
    import_native_relevance_reviews,
    initialise_codex_native_dataset,
    prepare_native_query_adjudication_tasks,
    prepare_native_query_tasks,
    prepare_native_relevance_adjudication_tasks,
    prepare_native_relevance_tasks,
)


DEFAULT_SOURCE = PROJECT_ROOT / "data/evaluation/phase13/v3"
DEFAULT_DATASET = PROJECT_ROOT / "data/evaluation/phase13/ai_silver/v1"
DEFAULT_CODEX_NATIVE_DATASET = PROJECT_ROOT / "data/evaluation/phase13/ai_silver/v3_codex_native"


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "UNKNOWN"


def _categories() -> set[str]:
    source = PROJECT_ROOT / "data/interim/selected_categories.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    return {str(item["category"]) for item in data["selected_categories"] if item.get("selection_status") == "SELECT"}


def _require_mutable(dataset: Path) -> None:
    manifest = load_manifest(dataset)
    if manifest.get("completion_status") == "RELEASED":
        raise RuntimeError("Released Silver datasets are immutable. Create a new version instead.")


def _write_stage(path: Path, rows: Iterable[dict[str, Any]], *, resume: bool) -> None:
    if path.exists() and not resume:
        raise FileExistsError(f"{path} already exists. Use --resume to reuse compatible checkpoint rows.")
    write_jsonl(path, rows, overwrite=path.exists())


def _load_queries(dataset: Path) -> list[dict[str, Any]]:
    return read_jsonl(dataset / "queries.jsonl")


def _apply_limit(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    wanted = set(args.query_id or [])
    if getattr(args, "pilot", False):
        wanted.update(select_pilot_queries(rows, size=args.pilot_size, seed=args.seed))
    chosen = [row for row in rows if not wanted or str(row["query_id"]) in wanted]
    return chosen[:args.limit] if args.limit is not None else chosen


async def run_audit(args: argparse.Namespace) -> dict[str, Any]:
    _require_mutable(args.dataset)
    source_rows = _load_queries(args.dataset)
    chosen = _apply_limit(source_rows, args)
    prior = {str(row.get("query_id")): row for row in read_jsonl(args.dataset / "query_audit.jsonl")} if args.resume else {}
    provider_a = None if args.offline_only else OpenAICompatibleJudgeProvider.from_environment("A")
    provider_b = None if args.offline_only else OpenAICompatibleJudgeProvider.from_environment("B")
    adjudicator = None if args.offline_only else OpenAICompatibleJudgeProvider.from_environment("ADJUDICATOR")
    request_budget = args.max_requests
    used = 0
    rows: list[dict[str, Any]] = []
    for query in chosen:
        # A completed row can be reused only when the stored input fingerprint
        # is still the deterministic fingerprint for exactly this source row.
        previous = prior.get(str(query["query_id"]))
        if previous and previous.get("status") == "COMPLETE":
            # Calling the audit function without providers gives the canonical
            # input fingerprint without spending an API request.
            from shopassist.evaluation.silver import deterministic_audit
            if previous.get("input_fingerprint") == deterministic_audit(query, allowed_categories=_categories()).get("input_fingerprint"):
                rows.append(previous)
                continue
        if provider_a and provider_b and used + 2 > request_budget:
            from shopassist.evaluation.silver import deterministic_audit
            blocked = deterministic_audit(query, allowed_categories=_categories())
            rows.append({**blocked, "judge_a": None, "judge_b": None, "adjudication": None, "audit_method": "AI_MULTI_JUDGE",
                         "status": "BLOCKED", "final_interpretation": None, "blocker": "REQUEST_BUDGET_EXCEEDED"})
            continue
        # Reserve an additional request for an available adjudicator.  It is
        # not used when judges agree, but never lets the run exceed its budget.
        available_adjudicator = adjudicator if (adjudicator is None or used + 3 <= request_budget) else None
        row = await audit_query_with_judges(query, judge_a=provider_a, judge_b=provider_b,
                                            adjudicator=available_adjudicator, allowed_categories=_categories())
        if provider_a and provider_b:
            used += 2
            if (row.get("adjudication") or {}).get("resolution") == "AI_ADJUDICATION":
                used += 1
        rows.append(row)
    # Preserve checkpoint rows for queries outside the requested subset.
    if args.resume:
        rows = [*rows, *(row for qid, row in prior.items() if qid not in {str(item["query_id"]) for item in rows})]
    rows.sort(key=lambda row: str(row["query_id"]))
    _write_stage(args.dataset / "query_audit.jsonl", rows, resume=args.resume)
    audit_report = query_audit_statistics(rows, {str(query["query_id"]): query for query in source_rows})
    audit_report.update({"generated_utc": datetime.now(timezone.utc).isoformat(),
                         "judge_configuration": {"judge_a": _provider_descriptor(provider_a), "judge_b": _provider_descriptor(provider_b),
                                                 "adjudicator": _provider_descriptor(adjudicator), "requests_used": used, "max_requests": request_budget}})
    audit_report_path = args.dataset / "query_audit_report.json"
    if audit_report_path.exists() and not args.resume:
        raise FileExistsError(f"{audit_report_path} already exists. Use --resume.")
    audit_report_path.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    refresh_manifest(args.dataset, completion_status="QUERY_AUDIT_PARTIAL" if any(row["status"] != "COMPLETE" for row in rows) else "QUERY_AUDIT_COMPLETE",
                     judge_configuration={"prompt_version": "phase13-silver-2026-10-13", "query_audit": {
                         "judge_a": _provider_descriptor(provider_a), "judge_b": _provider_descriptor(provider_b),
                         "adjudicator": _provider_descriptor(adjudicator), "requests_used": used, "max_requests": request_budget}})
    return {"queries_considered": len(chosen), "audit_rows": len(rows), "requests_used": used,
            "complete": sum(row["status"] == "COMPLETE" for row in rows),
            "blocked_or_unresolved": sum(row["status"] != "COMPLETE" for row in rows)}


def _provider_descriptor(provider: Any) -> dict[str, Any] | None:
    if provider is None:
        return None
    descriptor = {"provider": provider.provider_id, "model": provider.model}
    request_options = getattr(provider, "request_options", None)
    if isinstance(request_options, dict) and request_options:
        descriptor["request_options"] = request_options
    for name in ("max_retries", "max_completion_tokens"):
        value = getattr(provider, name, None)
        if isinstance(value, int):
            descriptor[name] = value
    return descriptor


async def run_capture(args: argparse.Namespace) -> dict[str, Any]:
    _require_mutable(args.dataset)
    manifest = load_manifest(args.dataset)
    catalog = PROJECT_ROOT / str(manifest["catalog_artifact"])
    if not catalog.is_file():
        raise FileNotFoundError(f"Pinned catalog is unavailable: {catalog}")
    if file_sha256(catalog) != manifest["catalog_sha256"]:
        raise ValueError("Pinned catalog SHA-256 does not match manifest")
    source = _load_queries(args.dataset)
    audits = read_jsonl(args.dataset / "query_audit.jsonl")
    if not audits:
        raise RuntimeError("Run the audit stage before capture")
    queries = audited_queries(source, audits)
    chosen = _apply_limit(queries, args)
    existing_pools = read_jsonl(args.dataset / "candidate_pools.jsonl") if args.resume else []
    existing_runs = read_jsonl(args.dataset / "retrieval_runs.jsonl") if args.resume else []
    existing_ids = {str(pool["query_id"]) for pool in existing_pools}
    capture_rows, retrieval_runs, blockers = await capture_multi_method_pools(
        [row for row in chosen if str(row["query_id"]) not in existing_ids], catalog_path=catalog,
        catalog_sha256=manifest["catalog_sha256"], methods=args.methods.split(","), contribution_depth=args.depth,
        allow_partial_methods=args.allow_partial_methods,
    )
    if not capture_rows and not existing_pools:
        # A blocker report is actual execution evidence; do not fabricate empty
        # frozen pool artifacts.
        _write_stage(args.dataset / "capture_blockers.jsonl", blockers, resume=args.resume)
        refresh_manifest(args.dataset, completion_status="CAPTURE_BLOCKED")
        return {"frozen_pools": 0, "retrieval_runs": 0, "blockers": len(blockers), "status": "BLOCKED"}
    pools = [*existing_pools, *capture_rows]
    runs = [*existing_runs, *retrieval_runs]
    _write_stage(args.dataset / "candidate_pools.jsonl", sorted(pools, key=lambda row: row["query_id"]), resume=args.resume)
    _write_stage(args.dataset / "retrieval_runs.jsonl", sorted(runs, key=lambda row: (row["query_id"], row["method"])), resume=args.resume)
    _write_stage(args.dataset / "capture_blockers.jsonl", blockers, resume=args.resume)
    refresh_manifest(args.dataset, completion_status="CANDIDATES_CAPTURED")
    return {"frozen_pools": len(pools), "retrieval_runs": len(runs), "blockers": len(blockers), "status": "COMPLETE"}


async def run_judge(args: argparse.Namespace) -> dict[str, Any]:
    _require_mutable(args.dataset)
    provider_a = None if args.offline_only else OpenAICompatibleJudgeProvider.from_environment("A")
    provider_b = None if args.offline_only else OpenAICompatibleJudgeProvider.from_environment("B")
    if provider_a is None or provider_b is None:
        return {"status": "BLOCKED", "reason": "SHOPASSIST_SILVER_A/B provider configuration is unavailable"}
    source = _load_queries(args.dataset)
    audits = read_jsonl(args.dataset / "query_audit.jsonl")
    queries = audited_queries(source, audits)
    pools = read_jsonl(args.dataset / "candidate_pools.jsonl")
    if not pools:
        raise RuntimeError("No frozen candidate pools are available")
    existing_a = read_jsonl(args.dataset / "judge_a_reviews.jsonl") if args.resume else []
    existing_b = read_jsonl(args.dataset / "judge_b_reviews.jsonl") if args.resume else []
    from shopassist.evaluation.silver import judge_frozen_pools
    reviews_a, reviews_b = await judge_frozen_pools(queries, pools, judge_a=provider_a, judge_b=provider_b,
                                                     max_requests=args.max_requests, concurrency=args.concurrency,
                                                     max_cost_usd=args.max_cost_usd,
                                                     reusable_reviews=[*existing_a, *existing_b])
    _write_stage(args.dataset / "judge_a_reviews.jsonl", reviews_a, resume=args.resume)
    _write_stage(args.dataset / "judge_b_reviews.jsonl", reviews_b, resume=args.resume)
    same_model = provider_a.provider_id == provider_b.provider_id and provider_a.model == provider_b.model
    refresh_manifest(args.dataset, completion_status="JUDGING_COMPLETE", judge_configuration={
        "prompt_version": "phase13-silver-2026-10-13", "relevance_judge_a": _provider_descriptor(provider_a),
        "relevance_judge_b": _provider_descriptor(provider_b),
        "independence": "REDUCED_SHARED_MODEL" if same_model else "SEPARATE_CONFIGURED_MODELS",
        "max_requests": args.max_requests, "max_cost_usd": args.max_cost_usd, "concurrency": args.concurrency,
    })
    return {"status": "COMPLETE", "judge_a_reviews": len(reviews_a), "judge_b_reviews": len(reviews_b),
            "reduced_independence": same_model}


async def run_adjudicate(args: argparse.Namespace) -> dict[str, Any]:
    _require_mutable(args.dataset)
    source = _load_queries(args.dataset)
    audits = read_jsonl(args.dataset / "query_audit.jsonl")
    queries = {str(row["query_id"]): row for row in audited_queries(source, audits)}
    pools = read_jsonl(args.dataset / "candidate_pools.jsonl")
    if not pools:
        raise RuntimeError("No frozen pools are available")
    a = {(str(row["query_id"]), str(row["product_id"])): row for row in read_jsonl(args.dataset / "judge_a_reviews.jsonl")}
    b = {(str(row["query_id"]), str(row["product_id"])): row for row in read_jsonl(args.dataset / "judge_b_reviews.jsonl")}
    existing = {(str(row["query_id"]), str(row["product_id"])): row for row in read_jsonl(args.dataset / "adjudications.jsonl")} if args.resume else {}
    provider = None if args.offline_only else OpenAICompatibleJudgeProvider.from_environment("ADJUDICATOR")
    rows: list[dict[str, Any]] = []
    for pool in pools:
        query = queries[str(pool["query_id"])]
        for candidate in pool.get("candidates", []):
            key = (str(pool["query_id"]), str(candidate["product_id"]))
            if key in existing:
                rows.append(existing[key])
                continue
            rows.append(await adjudicate_pair(query, candidate, a.get(key), b.get(key), provider))
    _write_stage(args.dataset / "adjudications.jsonl", rows, resume=args.resume)
    qrels = qrels_from_adjudications(rows)
    qrels_path = args.dataset / "qrels_silver.csv"
    if qrels_path.exists() and not args.resume:
        raise FileExistsError(f"{qrels_path} already exists. Use --resume.")
    write_csv_rows(qrels_path, qrels, QREL_FIELDS, overwrite=qrels_path.exists())
    candidates = {(str(pool["query_id"]), str(candidate["product_id"])): candidate for pool in pools for candidate in pool.get("candidates", [])}
    agreement = agreement_statistics(a.values(), b.values(), queries, candidates)
    agreement_path = args.dataset / "judge_agreement.json"
    if agreement_path.exists() and not args.resume:
        raise FileExistsError(f"{agreement_path} already exists. Use --resume.")
    agreement_path.write_text(json.dumps(agreement, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    unresolved = [row for row in rows if row.get("resolution_status") != "RESOLVED"]
    refresh_manifest(args.dataset, completion_status="ADJUDICATION_COMPLETE" if not unresolved else "ADJUDICATION_UNRESOLVED",
                     unresolved_cases=unresolved)
    return {"status": "COMPLETE" if not unresolved else "UNRESOLVED", "adjudications": len(rows), "qrels": len(qrels),
            "unresolved": len(unresolved), "agreement": agreement}


def run_validate(args: argparse.Namespace) -> dict[str, Any]:
    _require_mutable(args.dataset)
    report = validate_silver_dataset(args.dataset)
    write_validation_report(args.dataset, report)
    refresh_manifest(args.dataset, completion_status="VALIDATED" if report["silver_ready"] else load_manifest(args.dataset).get("completion_status"))
    return report


def run_evaluate(args: argparse.Namespace) -> dict[str, Any]:
    _require_mutable(args.dataset)
    runs = read_jsonl(args.dataset / "retrieval_runs.jsonl")
    qrels_path = args.dataset / "qrels_silver.csv"
    if not runs or not qrels_path.is_file():
        return {"status": "BLOCKED", "reason": "Frozen retrieval runs and Silver qrels are both required"}
    import csv
    with qrels_path.open(encoding="utf-8-sig", newline="") as handle:
        qrels = list(csv.DictReader(handle))
    report = {"status": "PROVISIONAL_SILVER", "oracle_query_understanding": evaluate_retrieval_runs(runs, qrels, k=args.k),
              "end_to_end_query_understanding": {"status": "BLOCKED", "reason": "No actual Phase 8 outputs were captured; oracle and end-to-end scores are intentionally separate."},
              "reranking": {"status": "BLOCKED", "reason": "No separately captured reranking runs are available."},
              "limitation": "This report is provisional AI-Silver evidence, not a production-promotion decision or human-ground-truth result."}
    output = args.dataset / "provisional_phase14_evaluation.json"
    if output.exists() and not args.resume:
        raise FileExistsError(f"{output} already exists. Use --resume.")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    refresh_manifest(args.dataset)
    return report


def run_freeze_split(args: argparse.Namespace) -> dict[str, Any]:
    _require_mutable(args.dataset)
    validation = validate_silver_dataset(args.dataset)
    if not validation.get("silver_ready"):
        raise RuntimeError("Silver labels must be complete and structurally valid before a development/held-out split is frozen")
    split = plan_grouped_split(_load_queries(args.dataset), held_out_fraction=args.held_out_fraction, seed=args.seed)
    if split["status"] != "FROZEN":
        raise RuntimeError(f"Split leakage checks failed: {split['leakage_checks']}")
    path = args.dataset / "splits.json"
    if path.exists() and not args.resume:
        raise FileExistsError(f"{path} already exists. Use --resume only after verifying the frozen split.")
    path.write_text(json.dumps(split, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    refresh_manifest(args.dataset, completion_status="SPLIT_FROZEN")
    return split


def run_generation_capture(args: argparse.Namespace) -> dict[str, Any]:
    """Flatten only supplied real Phase 12 outputs into Silver claim tasks."""
    _require_mutable(args.dataset)
    pools = read_jsonl(args.dataset / "candidate_pools.jsonl")
    if not pools:
        raise RuntimeError("Frozen candidate pools are required before capturing generation claims")
    snapshots, claims = capture_real_generation_claims(args.source_results, pools)
    snapshots_path, claims_path = args.dataset / "generation_snapshots.jsonl", args.dataset / "generation_claims_silver.csv"
    if (snapshots_path.exists() or claims_path.exists()) and not args.resume:
        raise FileExistsError("Generation capture artifacts already exist. Use --resume only after verifying compatible source snapshots.")
    _write_stage(snapshots_path, snapshots, resume=args.resume)
    from shopassist.evaluation.silver import GENERATION_CLAIM_FIELDS
    write_csv_rows(claims_path, claims, GENERATION_CLAIM_FIELDS, overwrite=claims_path.exists())
    refresh_manifest(args.dataset, completion_status="GENERATION_CLAIMS_CAPTURED")
    return {"status": "COMPLETE", "real_generation_snapshots": len(snapshots), "claims": len(claims)}


async def run_generation_judge(args: argparse.Namespace) -> dict[str, Any]:
    _require_mutable(args.dataset)
    a_provider = None if args.offline_only else OpenAICompatibleJudgeProvider.from_environment("A")
    b_provider = None if args.offline_only else OpenAICompatibleJudgeProvider.from_environment("B")
    if a_provider is None or b_provider is None:
        return {"status": "BLOCKED", "reason": "Two isolated AI judge provider configurations are required"}
    claims_path = args.dataset / "generation_claims_silver.csv"
    claims = read_csv_rows(claims_path)
    if not claims:
        raise RuntimeError("No real generation claims have been captured")
    required = len(claims) * 2
    if required > args.max_requests:
        raise RuntimeError(f"Request budget exceeded: {required} required > max_requests={args.max_requests}")
    a_reviews, b_reviews = [], []
    for claim in claims:
        a_reviews.append(await judge_generation_claim(claim, a_provider, "A"))
        b_reviews.append(await judge_generation_claim(claim, b_provider, "B"))
    _write_stage(args.dataset / "generation_judge_a_reviews.jsonl", a_reviews, resume=args.resume)
    _write_stage(args.dataset / "generation_judge_b_reviews.jsonl", b_reviews, resume=args.resume)
    adjudicator = None if args.offline_only else OpenAICompatibleJudgeProvider.from_environment("ADJUDICATOR")
    decisions = [await adjudicate_generation_claim(claim, a, b, adjudicator) for claim, a, b in zip(claims, a_reviews, b_reviews)]
    _write_stage(args.dataset / "generation_claim_adjudications.jsonl", decisions, resume=args.resume)
    by_id = {str(row["claim_id"]): row for row in decisions}
    for claim in claims:
        decision = by_id[str(claim["claim_id"])]
        if decision.get("resolution_status") == "RESOLVED":
            for field in ("support_label", "factual_correctness", "recommendation_relevance", "missing_information_handling"):
                claim[field] = decision.get(field, "")
    from shopassist.evaluation.silver import GENERATION_CLAIM_FIELDS
    write_csv_rows(claims_path, claims, GENERATION_CLAIM_FIELDS, overwrite=True)
    refresh_manifest(args.dataset, completion_status="GENERATION_CLAIMS_JUDGED")
    return {"status": "COMPLETE", "claims": len(claims), "resolved": sum(row.get("resolution_status") == "RESOLVED" for row in decisions),
            "unresolved": sum(row.get("resolution_status") != "RESOLVED" for row in decisions)}


async def run_pilot(args: argparse.Namespace) -> dict[str, Any]:
    if not args.dataset.exists():
        initialise_silver_dataset(args.source, args.dataset, source_git_commit=_git_commit())
    source = _load_queries(args.dataset)
    selected = select_pilot_queries(source, size=args.pilot_size, seed=args.seed)
    selection_path = args.dataset / "pilot_selection.json"
    if selection_path.exists() and not args.resume:
        raise FileExistsError(f"{selection_path} already exists. Use --resume.")
    selection_path.write_text(json.dumps({"selection_seed": args.seed, "query_ids": selected, "selection_size": len(selected),
                                          "purpose": "Representative Silver pilot; not a held-out split."}, indent=2) + "\n", encoding="utf-8")
    refresh_manifest(args.dataset, completion_status="PILOT_SELECTED")
    audit_values = dict(vars(args))
    audit_values.update({"query_id": selected, "pilot": False, "limit": None})
    audit_args = argparse.Namespace(**audit_values)
    audit = await run_audit(audit_args)
    # Capture only proceeds after genuine two-judge audits.  It is important
    # that a deterministic-only audit not be mislabeled as AI-Silver evidence.
    capture: dict[str, Any]
    if audit["complete"] == len(selected):
        capture_values = dict(vars(args))
        capture_values.update({"query_id": selected, "pilot": False, "limit": None})
        capture_args = argparse.Namespace(**capture_values)
        capture = await run_capture(capture_args)
    else:
        capture = {"status": "BLOCKED", "reason": "Pilot query audits are not all complete AI multi-judge audits."}
    report = {"pilot_size": len(selected), "query_ids": selected, "audit": audit, "capture": capture,
              "judging": {"status": "NOT_RUN" if capture.get("status") != "COMPLETE" else "PENDING"},
              "actual_execution_boundary": "Pipeline stopped before relevance judging unless independent AI audit and required retrieval services completed.",
              "human_verified": False, "phase14_ready": False}
    report_path = args.dataset / "pilot_report_silver.json"
    if report_path.exists() and not args.resume:
        raise FileExistsError(f"{report_path} already exists. Use --resume.")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    refresh_manifest(args.dataset, completion_status="PILOT_BLOCKED" if capture.get("status") != "COMPLETE" else "PILOT_CAPTURED")
    return report


async def run_full(args: argparse.Namespace) -> dict[str, Any]:
    if not args.dataset.exists():
        initialise_silver_dataset(args.source, args.dataset, source_git_commit=_git_commit())
    audit = await run_audit(args)
    if audit["complete"] != len(_load_queries(args.dataset)):
        return {"status": "BLOCKED", "stage": "audit", "detail": audit}
    capture = await run_capture(args)
    if capture.get("status") != "COMPLETE":
        return {"status": "BLOCKED", "stage": "capture", "detail": capture}
    judging = await run_judge(args)
    if judging.get("status") != "COMPLETE":
        return {"status": "BLOCKED", "stage": "judge", "detail": judging}
    adjudication = await run_adjudicate(args)
    validation = run_validate(args)
    evaluation = run_evaluate(args) if validation.get("silver_ready") else {"status": "BLOCKED", "reason": "Silver validation is not ready"}
    return {"status": "COMPLETE" if validation.get("silver_ready") else "UNRESOLVED", "audit": audit, "capture": capture,
            "judging": judging, "adjudication": adjudication, "validation": validation, "evaluation": evaluation}


# ---------------------------------------------------------------------------
# CODEX_NATIVE boundary
# ---------------------------------------------------------------------------
# These handlers intentionally do not instantiate OpenAICompatibleJudgeProvider
# or inspect SHOPASSIST_SILVER_* settings.  Native reasoning happens only in
# the interactive parent/subagent sessions; this CLI prepares/imports files.


def run_native_init(args: argparse.Namespace) -> dict[str, Any]:
    return initialise_codex_native_dataset(args.source, args.dataset, source_git_commit=_git_commit())


def run_native_prepare_query(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_native_query_tasks(
        args.dataset,
        query_ids=args.query_id,
        allowed_categories=_categories(),
        resume=args.resume,
    )


def run_native_import_query(args: argparse.Namespace) -> dict[str, Any]:
    return import_native_query_reviews(
        args.dataset,
        judge_slot=args.judge,
        submission=args.submission,
        resume=args.resume,
        model=args.native_model,
    )


def run_native_prepare_query_adjudication(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_native_query_adjudication_tasks(args.dataset, resume=args.resume)


def run_native_finalize_query(args: argparse.Namespace) -> dict[str, Any]:
    return finalise_native_query_audits(
        args.dataset,
        submission=args.submission,
        allowed_categories=_categories(),
        resume=args.resume,
        model=args.native_model,
    )


async def run_native_capture(args: argparse.Namespace) -> dict[str, Any]:
    methods = tuple(item.strip() for item in args.methods.split(",") if item.strip())
    return await capture_native_candidate_pools(
        args.dataset,
        methods=methods,
        contribution_depth=args.depth,
        max_pairs=args.max_pairs,
        allow_partial_methods=args.allow_partial_methods,
        resume=args.resume,
    )


def run_native_prepare_relevance(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_native_relevance_tasks(
        args.dataset,
        batch_size=args.batch_size,
        max_pairs=args.max_pairs,
        resume=args.resume,
    )


def run_native_import_relevance(args: argparse.Namespace) -> dict[str, Any]:
    return import_native_relevance_reviews(
        args.dataset,
        judge_slot=args.judge,
        submission=args.submission,
        resume=args.resume,
        model=args.native_model,
    )


def run_native_prepare_relevance_adjudication(args: argparse.Namespace) -> dict[str, Any]:
    return prepare_native_relevance_adjudication_tasks(args.dataset, resume=args.resume)


def run_native_finalize_relevance(args: argparse.Namespace) -> dict[str, Any]:
    return finalise_native_relevance_adjudications(
        args.dataset,
        submission=args.submission,
        resume=args.resume,
        model=args.native_model,
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    def common(command: argparse.ArgumentParser, *, source: bool = False) -> None:
        command.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
        if source:
            command.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
        command.add_argument("--resume", action="store_true")
        command.add_argument("--offline-only", action="store_true", help="Do not read or call any AI-provider configuration.")
    init = sub.add_parser("init")
    common(init, source=True)
    audit = sub.add_parser("audit")
    common(audit)
    capture = sub.add_parser("capture")
    common(capture)
    judge = sub.add_parser("judge")
    common(judge)
    adjudicate = sub.add_parser("adjudicate")
    common(adjudicate)
    validate = sub.add_parser("validate")
    common(validate)
    evaluate = sub.add_parser("evaluate")
    common(evaluate)
    split = sub.add_parser("freeze-split")
    common(split)
    split.add_argument("--held-out-fraction", type=float, default=.2)
    split.add_argument("--seed", type=int, default=13013)
    generation_capture = sub.add_parser("capture-generation")
    common(generation_capture)
    generation_capture.add_argument("--source-results", type=Path, required=True, help="Actual saved Phase 12 result JSONL; mock output is refused.")
    generation_judge = sub.add_parser("judge-generation")
    common(generation_judge)
    pilot = sub.add_parser("run-pilot")
    common(pilot, source=True)
    full = sub.add_parser("run-full")
    common(full, source=True)
    resume = sub.add_parser("resume")
    common(resume, source=True)

    # Native commands form a deliberately file-mediated workflow.  The CLI
    # cannot run a model; it only prepares blinded packets and validates/imports
    # JSON emitted by real interactive Codex judge threads.
    def native_common(command: argparse.ArgumentParser, *, source: bool = False) -> None:
        command.add_argument("--dataset", type=Path, default=DEFAULT_CODEX_NATIVE_DATASET)
        if source:
            command.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
        command.add_argument("--resume", action="store_true")

    native_init = sub.add_parser("native-init", help="Create a new CODEX_NATIVE Silver namespace; no provider is configured.")
    native_common(native_init, source=True)
    native_prepare_query = sub.add_parser("native-prepare-query", help="Prepare blind four-query packets for native Judge A/B.")
    native_common(native_prepare_query)
    native_prepare_query.add_argument("--query-id", action="append", required=True)
    native_import_query = sub.add_parser("native-import-query", help="Import one real native query-review submission.")
    native_common(native_import_query)
    native_import_query.add_argument("--judge", choices=("A", "B"), required=True)
    native_import_query.add_argument("--submission", type=Path, required=True)
    native_import_query.add_argument("--native-model", default="UNKNOWN",
                                     help="Observable session model only; leave UNKNOWN when it is not observable.")
    native_prepare_query_adjudication = sub.add_parser("native-prepare-query-adjudication", help="Prepare post-review query adjudication packets.")
    native_common(native_prepare_query_adjudication)
    native_finalize_query = sub.add_parser("native-finalize-query", help="Import query adjudications and write query_audit.jsonl.")
    native_common(native_finalize_query)
    native_finalize_query.add_argument("--submission", type=Path, required=True)
    native_finalize_query.add_argument("--native-model", default="UNKNOWN")
    native_capture = sub.add_parser("native-capture", help="Capture real retrieval pools after native audits; no LLM provider is called.")
    native_common(native_capture)
    native_capture.add_argument("--methods", default="tfidf,dense,hybrid")
    native_capture.add_argument("--depth", type=int, default=20)
    native_capture.add_argument("--max-pairs", type=int, default=90)
    native_capture.add_argument("--allow-partial-methods", action="store_true")
    native_prepare_relevance = sub.add_parser("native-prepare-relevance", help="Prepare 5--10 pair blind relevance batches.")
    native_common(native_prepare_relevance)
    native_prepare_relevance.add_argument("--batch-size", type=int, default=10)
    native_prepare_relevance.add_argument("--max-pairs", type=int, default=90)
    native_import_relevance = sub.add_parser("native-import-relevance", help="Import one real native relevance-review submission.")
    native_common(native_import_relevance)
    native_import_relevance.add_argument("--judge", choices=("A", "B"), required=True)
    native_import_relevance.add_argument("--submission", type=Path, required=True)
    native_import_relevance.add_argument("--native-model", default="UNKNOWN")
    native_prepare_relevance_adjudication = sub.add_parser("native-prepare-relevance-adjudication", help="Prepare canonical evidence for Judge A/B disagreements.")
    native_common(native_prepare_relevance_adjudication)
    native_finalize_relevance = sub.add_parser("native-finalize-relevance", help="Finalize native relevance adjudications and qrels.")
    native_common(native_finalize_relevance)
    native_finalize_relevance.add_argument("--submission", type=Path,
                                           help="JSONL decisions for disagreement tasks; omit only if there are no disagreements.")
    native_finalize_relevance.add_argument("--native-model", default="UNKNOWN")
    native_validate = sub.add_parser("native-validate", help="Run deterministic validation for a CODEX_NATIVE namespace.")
    native_common(native_validate)
    for command in (audit, capture, pilot, full, resume):
        command.add_argument("--query-id", action="append", default=[])
        command.add_argument("--limit", type=int)
        command.add_argument("--pilot", action="store_true")
        command.add_argument("--pilot-size", type=int, default=40)
        command.add_argument("--seed", type=int, default=13013)
    for command in (audit, pilot):
        command.add_argument("--max-requests", type=int, default=100)
    for command in (capture, pilot, full, resume):
        command.add_argument("--methods", default="tfidf,dense,hybrid")
        command.add_argument("--depth", type=int, default=20)
        command.add_argument("--allow-partial-methods", action="store_true")
    for command in (judge, full, resume):
        command.add_argument("--max-requests", type=int, default=100)
        command.add_argument("--max-cost-usd", type=float, default=None, help="Preflight dollar cap; requires provider pricing configuration.")
        command.add_argument("--concurrency", type=int, default=2)
    generation_judge.add_argument("--max-requests", type=int, default=100)
    evaluate.add_argument("--k", type=int, default=5)
    return root


async def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "native-init":
        return run_native_init(args)
    if args.command == "native-prepare-query":
        return run_native_prepare_query(args)
    if args.command == "native-import-query":
        return run_native_import_query(args)
    if args.command == "native-prepare-query-adjudication":
        return run_native_prepare_query_adjudication(args)
    if args.command == "native-finalize-query":
        return run_native_finalize_query(args)
    if args.command == "native-capture":
        return await run_native_capture(args)
    if args.command == "native-prepare-relevance":
        return run_native_prepare_relevance(args)
    if args.command == "native-import-relevance":
        return run_native_import_relevance(args)
    if args.command == "native-prepare-relevance-adjudication":
        return run_native_prepare_relevance_adjudication(args)
    if args.command == "native-finalize-relevance":
        return run_native_finalize_relevance(args)
    if args.command == "native-validate":
        return run_validate(args)
    if args.command == "init":
        return initialise_silver_dataset(args.source, args.dataset, source_git_commit=_git_commit())
    if args.command == "audit":
        return await run_audit(args)
    if args.command == "capture":
        return await run_capture(args)
    if args.command == "judge":
        return await run_judge(args)
    if args.command == "adjudicate":
        return await run_adjudicate(args)
    if args.command == "validate":
        return run_validate(args)
    if args.command == "evaluate":
        return run_evaluate(args)
    if args.command == "freeze-split":
        return run_freeze_split(args)
    if args.command == "capture-generation":
        return run_generation_capture(args)
    if args.command == "judge-generation":
        return await run_generation_judge(args)
    if args.command == "run-pilot":
        return await run_pilot(args)
    if args.command in {"run-full", "resume"}:
        return await run_full(args)
    raise ValueError(args.command)


def main() -> None:
    args = parser().parse_args()
    # psycopg async does not support Windows' default Proactor event loop.
    # Keep this adapter at the evaluation CLI boundary; it does not alter any
    # production service contract or global event-loop policy.
    if sys.platform.startswith("win"):
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            report = runner.run(dispatch(args))
    else:
        report = asyncio.run(dispatch(args))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
