"""File-mediated helpers for the interactive Codex-native Silver workflow.

This module deliberately contains *no* model client, HTTP client, SDK, shell
invocation, credential lookup, or subprocess inference.  Python's role is
limited to constructing blinded evidence packets, importing structured output
written by real interactive Codex agents, and applying deterministic checks.

The interactive parent agent is responsible for spawning isolated native
subagents and for writing their returned JSON into submission files.  Keeping
that boundary explicit prevents a local script from being mistaken for an LLM
inference mechanism.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .silver import (
    FORBIDDEN_BLIND_FIELDS,
    PROJECT_ROOT,
    QREL_FIELDS,
    SILVER_PROMPT_VERSION,
    VALID_GRADES,
    _audit_provider_payload,
    _normalise_interpretation,
    _normalise_review_payload,
    _product_matches_constraints,
    agreement_statistics,
    audited_queries,
    blind_judging_input,
    capture_multi_method_pools,
    deterministic_audit,
    deterministic_violations,
    file_sha256,
    fingerprint,
    interpretation_diffs,
    load_manifest,
    qrels_from_adjudications,
    query_audit_statistics,
    read_jsonl,
    utc_now,
    write_csv_rows,
    write_jsonl,
    write_manifest,
)


CODEX_NATIVE_ANNOTATION_METHOD = "CODEX_NATIVE_MULTI_JUDGE"
CODEX_NATIVE_PROVIDER = "CODEX_NATIVE"
UNKNOWN_MODEL = "UNKNOWN"
NATIVE_PROMPT_VERSION = "phase13-codex-native-2026-10-14"
QUERY_TASK_SCHEMA_VERSION = "codex-native-query-task-v1"
QUERY_ADJUDICATION_TASK_SCHEMA_VERSION = "codex-native-query-adjudication-task-v1"
RELEVANCE_TASK_SCHEMA_VERSION = "codex-native-relevance-task-v1"
RELEVANCE_ADJUDICATION_TASK_SCHEMA_VERSION = "codex-native-relevance-adjudication-task-v1"
NATIVE_INPUT_DIRNAME = "codex_native_inputs"

QUERY_SCHEMA_FIELDS = [
    "semantic_query",
    "hard_constraints.category",
    "hard_constraints.brand",
    "hard_constraints.min_price",
    "hard_constraints.max_price",
    "hard_constraints.min_rating",
    "hard_constraints.currency",
    "price_boundary_semantics.min_operator",
    "price_boundary_semantics.max_operator",
    "soft_preferences",
    "exclusions",
    "needs_clarification",
    "clarification_reason",
    "expected_status",
    "limitations",
    "rationale",
    "confidence",
]

RELEVANCE_SCHEMA_FIELDS = [
    "relevance_grade",
    "category_violation",
    "brand_violation",
    "price_violation",
    "rating_violation",
    "other_violation",
    "missing_evidence",
    "relevant_evidence_references",
    "explanation",
    "confidence",
]


@dataclass(frozen=True)
class NativeProviderDescriptor:
    """Small compatibility descriptor; it never performs inference."""

    provider_id: str = CODEX_NATIVE_PROVIDER
    model: str = UNKNOWN_MODEL


def _native_input_dir(dataset: Path) -> Path:
    return dataset / NATIVE_INPUT_DIRNAME


def query_task_path(dataset: Path, judge_slot: str) -> Path:
    return _native_input_dir(dataset) / f"judge_{judge_slot.lower()}_query_tasks.jsonl"


def query_adjudication_task_path(dataset: Path) -> Path:
    return _native_input_dir(dataset) / "query_adjudication_tasks.jsonl"


def relevance_task_index_path(dataset: Path) -> Path:
    return _native_input_dir(dataset) / "relevance_task_index.jsonl"


def relevance_batch_path(dataset: Path, judge_slot: str, batch_number: int) -> Path:
    return _native_input_dir(dataset) / "relevance" / f"judge_{judge_slot.lower()}_batch_{batch_number:03d}.jsonl"


def relevance_adjudication_task_path(dataset: Path) -> Path:
    return _native_input_dir(dataset) / "relevance_adjudication_tasks.jsonl"


def _native_artifact_hashes(dataset: Path) -> dict[str, str]:
    return {
        str(path.relative_to(dataset)).replace("\\", "/"): file_sha256(path)
        for path in sorted(dataset.rglob("*"))
        if path.is_file() and path.name != "dataset_manifest.json"
    }


def _refresh_native_manifest(
    dataset: Path,
    *,
    completion_status: str | None = None,
    native_updates: Mapping[str, Any] | None = None,
    unresolved_cases: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(dataset)
    if manifest.get("annotation_method") != CODEX_NATIVE_ANNOTATION_METHOD:
        raise ValueError("Dataset is not configured for CODEX_NATIVE_MULTI_JUDGE")
    if completion_status is not None:
        manifest["completion_status"] = completion_status
    native = dict(manifest.get("codex_native") or {})
    if native_updates:
        native.update(dict(native_updates))
    manifest["codex_native"] = native
    if unresolved_cases is not None:
        manifest["unresolved_cases"] = list(unresolved_cases)
    # These are hard invariants for every native-Silver checkpoint.
    manifest["human_verified"] = False
    manifest["phase14_ready"] = False
    manifest["label_quality"] = "SILVER"
    manifest["annotation_method"] = CODEX_NATIVE_ANNOTATION_METHOD
    queries_path = dataset / "queries.jsonl"
    if queries_path.is_file():
        manifest["queries_snapshot_sha256"] = file_sha256(queries_path)
    manifest["artifact_sha256"] = _native_artifact_hashes(dataset)
    write_manifest(dataset, manifest)
    return manifest


def initialise_codex_native_dataset(
    source_dataset: Path,
    output_dataset: Path,
    *,
    source_git_commit: str = "UNKNOWN",
) -> dict[str, Any]:
    """Create a new immutable namespace without changing legacy Silver data."""
    if output_dataset.exists() and any(output_dataset.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing Silver namespace: {output_dataset}")
    source_manifest_path = source_dataset / "dataset_manifest.json"
    queries_path = source_dataset / "queries.jsonl"
    if not source_manifest_path.is_file() or not queries_path.is_file():
        raise FileNotFoundError("Source Phase 13 dataset must contain dataset_manifest.json and queries.jsonl")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_queries = read_jsonl(queries_path)
    if not source_queries:
        raise ValueError("Source dataset contains no queries")
    # An empty namespace may have been pre-created by a constrained workspace
    # filesystem.  It contains no checkpoint to overwrite and is safe to use.
    output_dataset.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dataset / "queries.jsonl", source_queries)
    manifest = {
        "format_version": "1.0.0",
        "dataset_version": output_dataset.name,
        "source_dataset_version": source_manifest.get("dataset_version"),
        "source_dataset_relpath": (
            str(source_dataset.relative_to(PROJECT_ROOT)).replace("\\", "/")
            if source_dataset.is_relative_to(PROJECT_ROOT)
            else str(source_dataset)
        ),
        "source_git_commit": source_git_commit or "UNKNOWN",
        "source_query_sha256": file_sha256(queries_path),
        # ``write_jsonl`` canonicalizes key order for the isolated copy, so
        # retain a separate fingerprint for its exact local bytes.  The source
        # hash remains provenance, while this one detects stale local tasks.
        "queries_snapshot_sha256": file_sha256(output_dataset / "queries.jsonl"),
        "catalog_artifact": source_manifest.get("catalog_artifact"),
        "catalog_sha256": source_manifest.get("catalog_sha256"),
        "catalog_product_count": source_manifest.get("catalog_product_count"),
        "query_count": len(source_queries),
        "annotation_method": CODEX_NATIVE_ANNOTATION_METHOD,
        "label_quality": "SILVER",
        "human_verified": False,
        "phase14_ready": False,
        "silver_ready": False,
        "completion_status": "INITIALIZED",
        "created_utc": utc_now(),
        "judge_configuration": {
            "prompt_version": NATIVE_PROMPT_VERSION,
            "execution_mode": "CODEX_NATIVE",
            "judge_a": {"provider": CODEX_NATIVE_PROVIDER, "model": UNKNOWN_MODEL},
            "judge_b": {"provider": CODEX_NATIVE_PROVIDER, "model": UNKNOWN_MODEL},
            "adjudicator": {"provider": CODEX_NATIVE_PROVIDER, "model": UNKNOWN_MODEL},
            "same_model_correlation_risk": "UNKNOWN_OR_SHARED_MODEL_POSSIBLE",
            "independence": "SEPARATE_NATIVE_SUBAGENT_CONTEXTS; not independent model families",
        },
        "codex_native": {
            "execution_mode": "CODEX_NATIVE",
            "external_provider_calls": "DISABLED_BY_DESIGN",
            "model_metadata": UNKNOWN_MODEL,
            "judge_separation": "Separate interactive native subagent contexts",
            "same_model_correlation_risk": "UNKNOWN_OR_SHARED_MODEL_POSSIBLE",
            "adjudication": "Machine adjudication; not independent human adjudication",
            "known_blindness_limit": "Filesystem access is procedurally restricted to prepared blind packets.",
            "task_prompt_version": NATIVE_PROMPT_VERSION,
        },
        "known_limitations": [
            "AI-generated Silver labels are not independently human-verified ground truth.",
            "No Phase 14 promotion is permitted from Silver labels alone.",
            "Native judges may share an underlying model family; agreement is not proof of correctness.",
        ],
        "unresolved_cases": [],
        "artifact_sha256": _native_artifact_hashes(output_dataset),
    }
    write_manifest(output_dataset, manifest)
    return manifest


def _require_native_dataset(dataset: Path) -> dict[str, Any]:
    manifest = load_manifest(dataset)
    if manifest.get("annotation_method") != CODEX_NATIVE_ANNOTATION_METHOD:
        raise ValueError("CODEX_NATIVE commands require a CODEX_NATIVE_MULTI_JUDGE dataset")
    if manifest.get("completion_status") == "RELEASED":
        raise RuntimeError("Released Silver datasets are immutable. Create a new version instead.")
    return manifest


def _load_unique_queries(dataset: Path) -> dict[str, dict[str, Any]]:
    rows = read_jsonl(dataset / "queries.jsonl")
    indexed = {str(row.get("query_id")): row for row in rows}
    if not rows or len(indexed) != len(rows) or any(not key or key == "None" for key in indexed):
        raise ValueError("queries.jsonl must contain unique non-empty query IDs")
    return indexed


def _choose_query_ids(queries: Mapping[str, Mapping[str, Any]], query_ids: Sequence[str]) -> list[str]:
    wanted = [str(value) for value in query_ids]
    if not wanted:
        raise ValueError("At least one query ID is required for native task preparation")
    if len(set(wanted)) != len(wanted):
        raise ValueError("Duplicate query IDs were supplied")
    missing = sorted(set(wanted) - set(queries))
    if missing:
        raise ValueError(f"Unknown query IDs: {missing}")
    return sorted(wanted)


def _assert_blind_packet(payload: Mapping[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden = {
        "expected_query_understanding",
        "existing_interpretation",
        "existing_expected_status",
        "v3_comparison",
        "deterministic_audit",
        *FORBIDDEN_BLIND_FIELDS,
    }
    leaked = sorted(field for field in forbidden if f'"{field}"' in rendered)
    if leaked:
        raise AssertionError(f"Native blind task leaked forbidden field(s): {leaked}")


def _query_task(
    query: Mapping[str, Any],
    *,
    allowed_categories: Iterable[str],
    dataset_fingerprint: str,
) -> dict[str, Any]:
    # This intentionally uses only raw query evidence, language, taxonomy,
    # schema, and contract limitations.  It never reads historical labels.
    evidence = _audit_provider_payload(query, allowed_categories)
    evidence["annotation_rubric"] = {
        "category": "Choose a value from allowed_categories only when supported by the raw request.",
        "price_operators": "under/below=<; up to/at most=<=; above/over=>; at least=>=.",
        "exclusions": "Preserve negated identity/compatibility requirements in exclusions; do not turn them into positive preferences.",
        "status": "Use UNSUPPORTED_INTENT when Phase 8 v1 cannot safely represent an explicit exclusion or foreign-currency filter.",
        "uncertainty": "Use needs_clarification and a concise rationale when the evidence is genuinely ambiguous.",
    }
    _assert_blind_packet(evidence)
    task_base = {
        "task_type": "QUERY_AUDIT",
        "task_schema_version": QUERY_TASK_SCHEMA_VERSION,
        "prompt_version": NATIVE_PROMPT_VERSION,
        "query_id": str(query["query_id"]),
        "dataset_fingerprint": dataset_fingerprint,
        "evidence": evidence,
        "evidence_fingerprint": fingerprint(evidence),
        "required_output_fields": QUERY_SCHEMA_FIELDS,
    }
    return {
        **task_base,
        "task_fingerprint": fingerprint(task_base),
    }


def _checkpoint_fingerprint(value: Any) -> str:
    """Compare checkpoints while ignoring only wall-clock bookkeeping fields."""
    volatile = {"imported_at_utc", "adjudicated_at_utc", "audit_timestamp_utc", "generated_utc"}

    def stable(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): stable(value) for key, value in item.items() if str(key) not in volatile}
        if isinstance(item, list):
            return [stable(value) for value in item]
        return item

    return fingerprint(stable(value))


def _write_checkpoint(path: Path, rows: Iterable[Mapping[str, Any]], *, resume: bool) -> None:
    values = [dict(row) for row in rows]
    if path.exists():
        existing = read_jsonl(path)
        if not resume:
            raise FileExistsError(f"{path} already exists. Use --resume only for an identical compatible checkpoint.")
        if _checkpoint_fingerprint(existing) != _checkpoint_fingerprint(values):
            raise ValueError(f"Incompatible resume checkpoint: {path}")
        return
    write_jsonl(path, values)


def prepare_native_query_tasks(
    dataset: Path,
    *,
    query_ids: Sequence[str],
    allowed_categories: Iterable[str],
    resume: bool = False,
) -> dict[str, Any]:
    """Write identical blinded task evidence to isolated Judge A/B packets."""
    manifest = _require_native_dataset(dataset)
    queries = _load_unique_queries(dataset)
    chosen = _choose_query_ids(queries, query_ids)
    task_rows = [
        _query_task(queries[qid], allowed_categories=allowed_categories, dataset_fingerprint=str(manifest["source_query_sha256"]))
        for qid in chosen
    ]
    for slot in ("A", "B"):
        rows = [{**task, "judge_slot": slot} for task in task_rows]
        _write_checkpoint(query_task_path(dataset, slot), rows, resume=resume)
    _refresh_native_manifest(
        dataset,
        completion_status="QUERY_TASKS_PREPARED",
        native_updates={
            "query_task_schema_version": QUERY_TASK_SCHEMA_VERSION,
            "query_task_ids": chosen,
            "query_task_count": len(chosen),
            "query_task_fingerprints": {row["query_id"]: row["task_fingerprint"] for row in task_rows},
        },
    )
    return {"status": "COMPLETE", "query_ids": chosen, "task_count": len(task_rows), "task_paths": {
        "judge_a": str(query_task_path(dataset, "A")), "judge_b": str(query_task_path(dataset, "B")),
    }}


def _load_expected_tasks(dataset: Path, judge_slot: str, *, kind: str) -> dict[str, dict[str, Any]]:
    if kind == "query":
        path = query_task_path(dataset, judge_slot)
    else:
        raise ValueError(f"Unsupported task kind: {kind}")
    rows = read_jsonl(path)
    if not rows:
        raise ValueError(f"No prepared {kind} task packet exists for Judge {judge_slot}: {path}")
    indexed = {str(row.get("query_id")): row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Prepared {kind} tasks contain duplicate query IDs")
    for qid, row in indexed.items():
        if row.get("judge_slot") != judge_slot or not row.get("task_fingerprint") or not row.get("evidence_fingerprint"):
            raise ValueError(f"Prepared {kind} task is malformed for {qid}")
    return indexed


def _confidence(value: Any) -> str:
    text = str(value or "UNCERTAIN").strip().upper()
    allowed = {"HIGH", "MEDIUM", "LOW", "UNCERTAIN"}
    if text not in allowed:
        raise ValueError("confidence must be HIGH, MEDIUM, LOW, or UNCERTAIN")
    return text


def _native_session_provenance(judge_slot: str, model: str | None = None) -> dict[str, Any]:
    return {
        "execution_mode": "INTERACTIVE_CODEX_NATIVE_SUBAGENT",
        "judge_slot": judge_slot,
        "provider": CODEX_NATIVE_PROVIDER,
        "model": (model or UNKNOWN_MODEL).strip() or UNKNOWN_MODEL,
        "model_metadata_observable": bool(model and model.strip() and model.strip() != UNKNOWN_MODEL),
        "context_separation": "SEPARATE_NATIVE_SUBAGENT_CONTEXT",
        "external_api_called": False,
    }


def import_native_query_reviews(
    dataset: Path,
    *,
    judge_slot: str,
    submission: Path,
    resume: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    """Validate one real native judge's structured query-review submission."""
    if judge_slot not in {"A", "B"}:
        raise ValueError("judge_slot must be A or B")
    _require_native_dataset(dataset)
    if not submission.is_file():
        raise FileNotFoundError(f"Native judge submission is missing: {submission}")
    tasks = _load_expected_tasks(dataset, judge_slot, kind="query")
    queries = _load_unique_queries(dataset)
    submitted = read_jsonl(submission)
    if not submitted:
        raise ValueError("Native judge submission has no rows")
    seen: set[str] = set()
    imported: list[dict[str, Any]] = []
    descriptor = NativeProviderDescriptor(model=(model or UNKNOWN_MODEL).strip() or UNKNOWN_MODEL)
    for row in submitted:
        qid = str(row.get("query_id") or "")
        if not qid:
            raise ValueError("Native query review is missing query_id")
        if qid in seen:
            raise ValueError(f"Duplicate native query review: {qid}")
        seen.add(qid)
        task = tasks.get(qid)
        if task is None:
            raise ValueError(f"Native query review has unknown or unassigned query_id: {qid}")
        if row.get("task_fingerprint") != task.get("task_fingerprint"):
            raise ValueError(f"Stale or mismatched query task fingerprint: {qid}")
        if not isinstance(row.get("interpretation"), Mapping):
            raise ValueError(f"Native query review lacks interpretation object: {qid}")
        interpretation = _normalise_interpretation(row["interpretation"], queries[qid])
        category = interpretation["hard_constraints"].get("category")
        allowed = set((task.get("evidence") or {}).get("allowed_categories") or [])
        if category is not None and category not in allowed:
            raise ValueError(f"Native query review selected an invalid category for {qid}: {category}")
        rationale = str(row.get("rationale") or "").strip()
        if not rationale:
            raise ValueError(f"Native query review lacks evidence-grounded rationale: {qid}")
        confidence = _confidence(row.get("confidence"))
        review = {
            "query_id": qid,
            "judge_slot": judge_slot,
            "status": "SUCCESS",
            "task_schema_version": task["task_schema_version"],
            "prompt_version": task["prompt_version"],
            "task_fingerprint": task["task_fingerprint"],
            "evidence_fingerprint": task["evidence_fingerprint"],
            "dataset_fingerprint": task["dataset_fingerprint"],
            "interpretation": interpretation,
            "rationale": rationale,
            "confidence": confidence,
            "judge_provider": descriptor.provider_id,
            "judge_model": descriptor.model,
            "session_provenance": _native_session_provenance(judge_slot, descriptor.model),
            "submitted_output_fingerprint": fingerprint(row),
            "imported_at_utc": utc_now(),
        }
        review["review_fingerprint"] = fingerprint({key: value for key, value in review.items() if key != "imported_at_utc"})
        imported.append(review)
    if seen != set(tasks):
        missing = sorted(set(tasks) - seen)
        extra = sorted(seen - set(tasks))
        raise ValueError(f"Native Judge {judge_slot} query output must cover every prepared task; missing={missing}, extra={extra}")
    path = dataset / f"judge_{judge_slot.lower()}_query_reviews.jsonl"
    _write_checkpoint(path, sorted(imported, key=lambda row: row["query_id"]), resume=resume)
    _refresh_native_manifest(
        dataset,
        completion_status="QUERY_REVIEWS_IMPORTED",
        native_updates={f"judge_{judge_slot.lower()}_query_review_count": len(imported)},
    )
    return {"status": "COMPLETE", "judge_slot": judge_slot, "review_count": len(imported), "path": str(path)}


def _load_query_reviews(dataset: Path, judge_slot: str) -> dict[str, dict[str, Any]]:
    path = dataset / f"judge_{judge_slot.lower()}_query_reviews.jsonl"
    rows = read_jsonl(path)
    indexed = {str(row.get("query_id")): row for row in rows}
    if not rows or len(indexed) != len(rows):
        raise ValueError(f"Judge {judge_slot} query review artifact is missing or has duplicate IDs")
    return indexed


def _native_query_checks(task: Mapping[str, Any]) -> dict[str, Any]:
    evidence = task.get("evidence") or {}
    raw = str(evidence.get("raw_query") or "")
    # Construct a deliberately label-free deterministic record for the
    # adjudicator.  The normalizer keeps the original raw query unchanged.
    from .silver import extract_negative_intent, extract_price_constraints, extract_soft_preferences

    price = extract_price_constraints(raw)
    negative = extract_negative_intent(raw)
    return {
        "explicit_price": {key: price.get(key) for key in ("min_price", "max_price", "min_operator", "max_operator", "currency", "evidence")},
        "explicit_exclusions": negative.get("exclusions", []),
        "detected_positive_preferences": extract_soft_preferences(raw),
    }


def prepare_native_query_adjudication_tasks(dataset: Path, *, resume: bool = False) -> dict[str, Any]:
    """Prepare evidence for the main-agent/native adjudication after both reviews."""
    _require_native_dataset(dataset)
    tasks = _load_expected_tasks(dataset, "A", kind="query")
    tasks_b = _load_expected_tasks(dataset, "B", kind="query")
    if {qid: row["task_fingerprint"] for qid, row in tasks.items()} != {qid: row["task_fingerprint"] for qid, row in tasks_b.items()}:
        raise ValueError("Judge A and B query task packets do not contain identical blinded evidence")
    reviews_a, reviews_b = _load_query_reviews(dataset, "A"), _load_query_reviews(dataset, "B")
    if set(reviews_a) != set(tasks) or set(reviews_b) != set(tasks):
        raise ValueError("Both native query judges must submit every prepared review before adjudication")
    rows: list[dict[str, Any]] = []
    for qid in sorted(tasks):
        task = tasks[qid]
        base = {
            "task_type": "QUERY_ADJUDICATION",
            "task_schema_version": QUERY_ADJUDICATION_TASK_SCHEMA_VERSION,
            "prompt_version": NATIVE_PROMPT_VERSION,
            "query_id": qid,
            "dataset_fingerprint": task["dataset_fingerprint"],
            "evidence": task["evidence"],
            "evidence_fingerprint": task["evidence_fingerprint"],
            "query_task_fingerprint": task["task_fingerprint"],
            "deterministic_checks": _native_query_checks(task),
            "judge_a": {key: reviews_a[qid][key] for key in ("interpretation", "rationale", "confidence", "review_fingerprint")},
            "judge_b": {key: reviews_b[qid][key] for key in ("interpretation", "rationale", "confidence", "review_fingerprint")},
            "required_output_fields": ["query_id", "task_fingerprint", "resolution_status", "final_interpretation", "rationale", "confidence"],
        }
        _assert_blind_packet(base["evidence"])
        rows.append({**base, "task_fingerprint": fingerprint(base)})
    _write_checkpoint(query_adjudication_task_path(dataset), rows, resume=resume)
    _refresh_native_manifest(dataset, completion_status="QUERY_ADJUDICATION_TASKS_PREPARED",
                             native_updates={"query_adjudication_task_count": len(rows)})
    return {"status": "COMPLETE", "task_count": len(rows), "path": str(query_adjudication_task_path(dataset))}


def _interpretation_constraint_errors(interpretation: Mapping[str, Any], checks: Mapping[str, Any]) -> list[str]:
    """Validate explicit, mechanically detectable requirements without guessing semantics."""
    errors: list[str] = []
    hard = interpretation.get("hard_constraints") or {}
    operators = interpretation.get("price_boundary_semantics") or {}
    price = checks.get("explicit_price") or {}
    for field, op_field in (("min_price", "min_operator"), ("max_price", "max_operator")):
        expected = price.get(field)
        if expected is not None:
            observed = hard.get(field)
            if observed is None or float(observed) != float(expected):
                errors.append(f"explicit {field} was not preserved")
            if operators.get(op_field) != price.get(op_field):
                errors.append(f"explicit {op_field} was not preserved")
    exclusions = list(checks.get("explicit_exclusions") or [])
    if exclusions:
        actual = [str(item).casefold() for item in interpretation.get("exclusions") or []]
        if not actual:
            errors.append("explicit exclusion intent was not preserved")
        if interpretation.get("expected_status") != "UNSUPPORTED_INTENT":
            errors.append("explicit exclusion lacks UNSUPPORTED_INTENT safe-stop")
    return errors


def finalise_native_query_audits(
    dataset: Path,
    *,
    submission: Path,
    allowed_categories: Iterable[str],
    resume: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    """Import actual adjudication decisions and create capture-compatible audits."""
    _require_native_dataset(dataset)
    if not submission.is_file():
        raise FileNotFoundError(f"Native query adjudication submission is missing: {submission}")
    tasks = {str(row.get("query_id")): row for row in read_jsonl(query_adjudication_task_path(dataset))}
    if not tasks:
        raise ValueError("Prepare native query adjudication tasks before importing decisions")
    if len(tasks) != len(read_jsonl(query_adjudication_task_path(dataset))):
        raise ValueError("Duplicate query adjudication task IDs")
    queries = _load_unique_queries(dataset)
    review_a, review_b = _load_query_reviews(dataset, "A"), _load_query_reviews(dataset, "B")
    rows = read_jsonl(submission)
    if not rows:
        raise ValueError("Native query adjudication submission has no rows")
    decisions: list[dict[str, Any]] = []
    seen: set[str] = set()
    native_model = (model or UNKNOWN_MODEL).strip() or UNKNOWN_MODEL
    for row in rows:
        qid = str(row.get("query_id") or "")
        if not qid:
            raise ValueError("Native query adjudication is missing query_id")
        if qid in seen:
            raise ValueError(f"Duplicate native query adjudication: {qid}")
        seen.add(qid)
        task = tasks.get(qid)
        if task is None:
            raise ValueError(f"Native query adjudication has unknown query_id: {qid}")
        if row.get("task_fingerprint") != task.get("task_fingerprint"):
            raise ValueError(f"Stale or mismatched query adjudication task fingerprint: {qid}")
        status = str(row.get("resolution_status") or "").upper()
        if status not in {"RESOLVED", "UNRESOLVED"}:
            raise ValueError(f"Native query adjudication has invalid resolution_status: {qid}")
        rationale = str(row.get("rationale") or "").strip()
        if not rationale:
            raise ValueError(f"Native query adjudication lacks rationale: {qid}")
        decision: dict[str, Any] = {
            "query_id": qid,
            "task_fingerprint": task["task_fingerprint"],
            "query_task_fingerprint": task["query_task_fingerprint"],
            "evidence_fingerprint": task["evidence_fingerprint"],
            "dataset_fingerprint": task["dataset_fingerprint"],
            "task_schema_version": task["task_schema_version"],
            "prompt_version": task["prompt_version"],
            "resolution_status": status,
            "rationale": rationale,
            "confidence": _confidence(row.get("confidence")),
            "adjudicator_provider": CODEX_NATIVE_PROVIDER,
            "adjudicator_model": native_model,
            "adjudicator_provenance": {
                "execution_mode": "INTERACTIVE_CODEX_MAIN_AGENT",
                "model": native_model,
                "machine_adjudication": True,
                "external_api_called": False,
            },
            "judge_a_review_fingerprint": review_a[qid]["review_fingerprint"],
            "judge_b_review_fingerprint": review_b[qid]["review_fingerprint"],
            "submitted_output_fingerprint": fingerprint(row),
            "adjudicated_at_utc": utc_now(),
        }
        if status == "RESOLVED":
            if not isinstance(row.get("final_interpretation"), Mapping):
                raise ValueError(f"Resolved native query adjudication lacks final_interpretation: {qid}")
            final = _normalise_interpretation(row["final_interpretation"], queries[qid])
            allowed = set((task.get("evidence") or {}).get("allowed_categories") or [])
            category = final["hard_constraints"].get("category")
            if category is not None and category not in allowed:
                raise ValueError(f"Native adjudication selected invalid category for {qid}: {category}")
            constraint_errors = _interpretation_constraint_errors(final, task.get("deterministic_checks") or {})
            if constraint_errors:
                raise ValueError(f"Native query adjudication failed deterministic checks for {qid}: {constraint_errors}")
            decision["final_interpretation"] = final
            decision["resolution"] = (
                "CODEX_NATIVE_EXACT_AGREEMENT"
                if review_a[qid]["interpretation"] == review_b[qid]["interpretation"]
                else "CODEX_NATIVE_ADJUDICATION"
            )
        else:
            decision["final_interpretation"] = None
            decision["unresolved_reason"] = str(row.get("unresolved_reason") or "INSUFFICIENT_EVIDENCE_OR_UNRESOLVED_SEMANTIC_AMBIGUITY")
            decision["resolution"] = "UNRESOLVED"
        decision["adjudication_fingerprint"] = fingerprint({key: value for key, value in decision.items() if key != "adjudicated_at_utc"})
        decisions.append(decision)
    if seen != set(tasks):
        raise ValueError(f"Native query adjudication must cover every prepared task; missing={sorted(set(tasks) - seen)}")
    decisions = sorted(decisions, key=lambda row: row["query_id"])
    _write_checkpoint(dataset / "query_adjudications.jsonl", decisions, resume=resume)

    source_queries = _load_unique_queries(dataset)
    audits: list[dict[str, Any]] = []
    for decision in decisions:
        qid = decision["query_id"]
        task = tasks[qid]
        source = source_queries[qid]
        # The source-v3 comparison is intentionally created only now, after
        # independent reviews and adjudication have completed.
        posthoc = deterministic_audit(source, allowed_categories=set(allowed_categories))
        final = decision.get("final_interpretation")
        audit = {
            **posthoc,
            "input_fingerprint": task["task_fingerprint"],
            "evidence_fingerprint": task["evidence_fingerprint"],
            "dataset_fingerprint": task["dataset_fingerprint"],
            "audit_method": CODEX_NATIVE_ANNOTATION_METHOD,
            "status": "COMPLETE" if decision["resolution_status"] == "RESOLVED" else "UNRESOLVED",
            "judge_a": review_a[qid],
            "judge_b": review_b[qid],
            "adjudication": decision,
            "final_interpretation": final,
            "field_diffs": interpretation_diffs(source, final) if final else [],
            "v3_comparison_performed_after_blind_judging": True,
        }
        audits.append(audit)
    _write_checkpoint(dataset / "query_audit.jsonl", audits, resume=resume)
    audit_report = query_audit_statistics(audits, source_queries)
    audit_report.update({
        "generated_utc": utc_now(),
        "annotation_method": CODEX_NATIVE_ANNOTATION_METHOD,
        "judge_configuration": load_manifest(dataset).get("judge_configuration"),
        "query_adjudication_count": len(decisions),
        "unresolved_count": sum(item["resolution_status"] != "RESOLVED" for item in decisions),
    })
    audit_report_path = dataset / "query_audit_report.json"
    if audit_report_path.exists() and not resume:
        raise FileExistsError(f"{audit_report_path} already exists. Use --resume for an identical compatible checkpoint.")
    if audit_report_path.exists() and resume:
        prior = json.loads(audit_report_path.read_text(encoding="utf-8"))
        if _checkpoint_fingerprint(prior) != _checkpoint_fingerprint(audit_report):
            raise ValueError(f"Incompatible resume checkpoint: {audit_report_path}")
    else:
        audit_report_path.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    unresolved = [item for item in decisions if item["resolution_status"] != "RESOLVED"]
    _refresh_native_manifest(
        dataset,
        completion_status="QUERY_AUDIT_COMPLETE" if not unresolved else "QUERY_AUDIT_UNRESOLVED",
        unresolved_cases=unresolved,
        native_updates={"query_audit_count": len(audits), "posthoc_v3_comparison": True},
    )
    return {"status": "COMPLETE" if not unresolved else "UNRESOLVED", "query_audits": len(audits), "unresolved": len(unresolved)}


def cap_native_candidate_pools(
    pools: Iterable[Mapping[str, Any]], *, max_pairs: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply a deterministic, method-balanced cap without using Hybrid rank alone.

    Candidate capture first creates the full union.  This function only limits
    which already-frozen members are sent to the native relevance reviewers.
    It round-robins across query and retrieval method, taking each method's
    highest not-yet-selected candidate.  Every retained candidate keeps all of
    its original per-method rank/score provenance.
    """
    if max_pairs <= 0:
        raise ValueError("max_pairs must be positive")
    originals = [dict(pool) for pool in pools]
    total = sum(len(pool.get("candidates") or []) for pool in originals)
    if total <= max_pairs:
        return originals, {
            "max_pairs": max_pairs,
            "original_pair_count": total,
            "selected_pair_count": total,
            "was_capped": False,
            "selection_rule": "Full multi-method union retained; cap was not reached.",
        }
    ordered = sorted(originals, key=lambda row: str(row.get("query_id")))
    selected: dict[str, list[str]] = {str(pool.get("query_id")): [] for pool in ordered}
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    rankings: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for pool in ordered:
        qid = str(pool.get("query_id"))
        for candidate in pool.get("candidates") or []:
            pid = str(candidate.get("product_id"))
            candidates[(qid, pid)] = dict(candidate)
            for membership in candidate.get("pool_membership") or []:
                method = str(membership.get("method") or "")
                rank = membership.get("rank")
                if method and isinstance(rank, int) and rank > 0:
                    rankings.setdefault((qid, method), []).append((rank, pid))
    for key in rankings:
        rankings[key].sort(key=lambda row: (row[0], row[1]))
    cursors: dict[tuple[str, str], int] = {key: 0 for key in rankings}
    methods_by_query = {
        str(pool.get("query_id")): sorted(method for (qid, method) in rankings if qid == str(pool.get("query_id")))
        for pool in ordered
    }
    while sum(len(items) for items in selected.values()) < max_pairs:
        made_progress = False
        for pool in ordered:
            qid = str(pool.get("query_id"))
            for method in methods_by_query[qid]:
                key = (qid, method)
                items = rankings[key]
                cursor = cursors[key]
                while cursor < len(items) and items[cursor][1] in selected[qid]:
                    cursor += 1
                cursors[key] = cursor
                if cursor >= len(items):
                    continue
                selected[qid].append(items[cursor][1])
                cursors[key] = cursor + 1
                made_progress = True
                if sum(len(items) for items in selected.values()) >= max_pairs:
                    break
            if sum(len(items) for items in selected.values()) >= max_pairs:
                break
        if not made_progress:
            break
    capped: list[dict[str, Any]] = []
    for pool in ordered:
        qid = str(pool.get("query_id"))
        retained = [candidates[(qid, pid)] for pid in selected[qid]]
        # Stable reviewer serialization only; it is not passed to judges.
        retained.sort(key=lambda candidate: (
            min(int(member["rank"]) for member in candidate.get("pool_membership") or []),
            str(candidate.get("product_id")),
        ))
        for index, candidate in enumerate(retained, 1):
            candidate["pool_position"] = index
        updated = dict(pool)
        updated["candidates"] = retained
        updated["candidate_count"] = len(retained)
        updated["candidate_cap"] = {
            "max_total_pairs": max_pairs,
            "original_query_candidate_count": len(pool.get("candidates") or []),
            "selected_query_candidate_count": len(retained),
            "selection_rule": "Round-robin by query and retrieval method using each method's rank; never Hybrid-only.",
        }
        updated["pool_fingerprint"] = fingerprint({
            "source_pool_fingerprint": pool.get("pool_fingerprint"),
            "candidate_cap": updated["candidate_cap"],
            "candidates": retained,
        })
        capped.append(updated)
    selected_count = sum(len(pool["candidates"]) for pool in capped)
    if selected_count > max_pairs:
        raise AssertionError("Candidate cap implementation exceeded max_pairs")
    return capped, {
        "max_pairs": max_pairs,
        "original_pair_count": total,
        "selected_pair_count": selected_count,
        "was_capped": True,
        "selection_rule": "Round-robin by query and retrieval method using each method's rank; never Hybrid-only.",
    }


def _load_native_pools(dataset: Path) -> list[dict[str, Any]]:
    pools = read_jsonl(dataset / "candidate_pools.jsonl")
    if not pools:
        raise ValueError("No native frozen candidate pools are available")
    indexed = {str(pool.get("query_id")): pool for pool in pools}
    if len(indexed) != len(pools):
        raise ValueError("Candidate pools contain duplicate query IDs")
    for pool in pools:
        if pool.get("capture_status") != "FROZEN":
            raise ValueError(f"Candidate pool is not frozen: {pool.get('query_id')}")
    return pools


def _relevance_task(
    query: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    dataset_fingerprint: str,
    catalog_fingerprint: str,
) -> dict[str, Any]:
    evidence = blind_judging_input(query, candidate)
    evidence["annotation_rubric"] = {
        "grade_3": "Strong relevance: product identity and all verifiable positive requirements fit.",
        "grade_2": "Relevant with a minor missing or weak secondary requirement.",
        "grade_1": "Related family but important mismatch.",
        "grade_0": "Irrelevant or contradictory.",
        "hard_constraints": "A confirmed category, brand, price, rating, or other hard violation cannot receive grade 2 or 3.",
        "missing_evidence": "Missing product attributes are unknown, not violations; record missing evidence explicitly.",
    }
    _assert_blind_packet(evidence)
    base = {
        "task_type": "RELEVANCE",
        "task_schema_version": RELEVANCE_TASK_SCHEMA_VERSION,
        "prompt_version": NATIVE_PROMPT_VERSION,
        "query_id": str(query["query_id"]),
        "product_id": str(candidate["product_id"]),
        "dataset_fingerprint": dataset_fingerprint,
        "catalog_fingerprint": catalog_fingerprint,
        "evidence": evidence,
        "evidence_fingerprint": fingerprint(evidence),
        "required_output_fields": RELEVANCE_SCHEMA_FIELDS,
    }
    return {**base, "task_fingerprint": fingerprint(base)}


def prepare_native_relevance_tasks(
    dataset: Path,
    *,
    batch_size: int = 10,
    max_pairs: int = 90,
    resume: bool = False,
) -> dict[str, Any]:
    """Create 5--10-pair blind packets after frozen native pools exist."""
    if batch_size < 5 or batch_size > 10:
        raise ValueError("batch_size must be between 5 and 10 for native relevance judging")
    manifest = _require_native_dataset(dataset)
    pools = _load_native_pools(dataset)
    total = sum(len(pool.get("candidates") or []) for pool in pools)
    if total > max_pairs:
        raise ValueError(f"Frozen native candidate pairs exceed cap: {total} > {max_pairs}")
    source = _load_unique_queries(dataset)
    audits = read_jsonl(dataset / "query_audit.jsonl")
    audited = {str(row["query_id"]): row for row in audited_queries(source.values(), audits)}
    tasks: list[dict[str, Any]] = []
    for pool in sorted(pools, key=lambda item: str(item.get("query_id"))):
        qid = str(pool.get("query_id"))
        query = audited.get(qid)
        if query is None or query.get("silver_audit_status") != "COMPLETE":
            raise ValueError(f"Native relevance task references incomplete query audit: {qid}")
        if query.get("audited_expected_status") not in {"SUCCESS", "NO_RESULTS"}:
            raise ValueError(f"Native relevance task must not be created for stopped query: {qid}")
        for candidate in pool.get("candidates") or []:
            tasks.append(_relevance_task(
                query,
                candidate,
                dataset_fingerprint=str(manifest["source_query_sha256"]),
                catalog_fingerprint=str(manifest["catalog_sha256"]),
            ))
    pairs = {(row["query_id"], row["product_id"]) for row in tasks}
    if len(tasks) != len(pairs):
        raise ValueError("Candidate pools contain duplicate query/product pairs")
    _write_checkpoint(relevance_task_index_path(dataset), sorted(tasks, key=lambda row: (row["query_id"], row["product_id"])), resume=resume)
    by_batch = [tasks[index:index + batch_size] for index in range(0, len(tasks), batch_size)]
    for slot in ("A", "B"):
        for number, batch in enumerate(by_batch, 1):
            rows = [{**row, "judge_slot": slot, "batch_number": number} for row in batch]
            _write_checkpoint(relevance_batch_path(dataset, slot, number), rows, resume=resume)
    _refresh_native_manifest(
        dataset,
        completion_status="RELEVANCE_TASKS_PREPARED",
        native_updates={
            "relevance_task_schema_version": RELEVANCE_TASK_SCHEMA_VERSION,
            "relevance_task_count": len(tasks),
            "relevance_batch_size": batch_size,
            "relevance_batch_count": len(by_batch),
            "relevance_pair_cap": max_pairs,
            "relevance_task_fingerprints": {
                f"{row['query_id']}/{row['product_id']}": row["task_fingerprint"] for row in tasks
            },
        },
    )
    return {
        "status": "COMPLETE",
        "pair_count": len(tasks),
        "batch_count": len(by_batch),
        "task_index": str(relevance_task_index_path(dataset)),
        "batch_paths": {
            slot: [str(relevance_batch_path(dataset, slot, number)) for number in range(1, len(by_batch) + 1)]
            for slot in ("A", "B")
        },
    }


def _load_relevance_tasks(dataset: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = read_jsonl(relevance_task_index_path(dataset))
    indexed = {(str(row.get("query_id")), str(row.get("product_id"))): row for row in rows}
    if not rows or len(indexed) != len(rows):
        raise ValueError("Native relevance task index is missing or contains duplicate pairs")
    for key, row in indexed.items():
        if not all(row.get(field) for field in ("task_fingerprint", "evidence_fingerprint", "dataset_fingerprint", "catalog_fingerprint")):
            raise ValueError(f"Malformed native relevance task: {key}")
    return indexed


def _pool_candidate_map(pools: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for pool in pools:
        qid = str(pool.get("query_id"))
        for candidate in pool.get("candidates") or []:
            key = (qid, str(candidate.get("product_id")))
            if key in result:
                raise ValueError(f"Duplicate frozen candidate pair: {key}")
            result[key] = dict(candidate)
    return result


def import_native_relevance_reviews(
    dataset: Path,
    *,
    judge_slot: str,
    submission: Path,
    resume: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    """Import and schema-check a native Judge A/B relevance submission."""
    if judge_slot not in {"A", "B"}:
        raise ValueError("judge_slot must be A or B")
    _require_native_dataset(dataset)
    if not submission.is_file():
        raise FileNotFoundError(f"Native relevance submission is missing: {submission}")
    tasks = _load_relevance_tasks(dataset)
    pools = _load_native_pools(dataset)
    candidates = _pool_candidate_map(pools)
    submitted = read_jsonl(submission)
    if not submitted:
        raise ValueError("Native relevance submission has no rows")
    descriptor = NativeProviderDescriptor(model=(model or UNKNOWN_MODEL).strip() or UNKNOWN_MODEL)
    imported: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in submitted:
        qid, pid = str(row.get("query_id") or ""), str(row.get("product_id") or "")
        if not qid or not pid:
            raise ValueError("Native relevance review is missing query_id or product_id")
        key = (qid, pid)
        if key in seen:
            raise ValueError(f"Duplicate native relevance review: {key}")
        seen.add(key)
        task = tasks.get(key)
        if task is None:
            raise ValueError(f"Native relevance review has unknown query/product pair: {key}")
        if key not in candidates:
            raise ValueError(f"Native relevance review product is not in the frozen pool: {key}")
        if row.get("task_fingerprint") != task.get("task_fingerprint"):
            raise ValueError(f"Stale or mismatched relevance task fingerprint: {key}")
        missing_fields = [field for field in RELEVANCE_SCHEMA_FIELDS if field not in row]
        if missing_fields:
            raise ValueError(f"Native relevance review lacks required evidence/judgment fields for {key}: {missing_fields}")
        normalized = _normalise_review_payload(row, provider=descriptor, input_fingerprint=str(task["task_fingerprint"]))
        flags, missing = deterministic_violations(
            (task.get("evidence") or {}).get("audited_intent") or {}, candidates[key]
        )
        # Preserve the agent's asserted flags separately, but record a
        # deterministic OR so later validation/adjudication cannot overlook a
        # confirmed catalog constraint violation.
        asserted = {field: normalized[field] for field in flags}
        for field in flags:
            normalized[field] = bool(normalized[field]) or flags[field]
        review = {
            "query_id": qid,
            "product_id": pid,
            "judge_slot": judge_slot,
            "status": "SUCCESS",
            "task_schema_version": task["task_schema_version"],
            "prompt_version": task["prompt_version"],
            "task_fingerprint": task["task_fingerprint"],
            "judge_input_fingerprint": task["task_fingerprint"],
            "evidence_fingerprint": task["evidence_fingerprint"],
            "dataset_fingerprint": task["dataset_fingerprint"],
            "catalog_fingerprint": task["catalog_fingerprint"],
            **normalized,
            # _normalise_review_payload is shared with the legacy HTTP path
            # and supplies its legacy prompt constant, so restore the packet's
            # native provenance after expanding it.
            "prompt_version": task["prompt_version"],
            "judge_asserted_violations": asserted,
            "deterministic_violations": flags,
            "deterministic_missing_evidence": missing,
            "judge_provider": descriptor.provider_id,
            "judge_model": descriptor.model,
            "label_source": "CODEX_NATIVE_JUDGE",
            "session_provenance": _native_session_provenance(judge_slot, descriptor.model),
            "submitted_output_fingerprint": fingerprint(row),
            "imported_at_utc": utc_now(),
        }
        review["review_fingerprint"] = fingerprint({key: value for key, value in review.items() if key != "imported_at_utc"})
        imported.append(review)
    if seen != set(tasks):
        raise ValueError(
            f"Native Judge {judge_slot} relevance output must cover every prepared pair; "
            f"missing={len(set(tasks) - seen)}, extra={len(seen - set(tasks))}"
        )
    path = dataset / f"judge_{judge_slot.lower()}_relevance.jsonl"
    _write_checkpoint(path, sorted(imported, key=lambda row: (row["query_id"], row["product_id"])), resume=resume)
    _refresh_native_manifest(
        dataset,
        completion_status="RELEVANCE_REVIEWS_IMPORTED",
        native_updates={f"judge_{judge_slot.lower()}_relevance_review_count": len(imported)},
    )
    return {"status": "COMPLETE", "judge_slot": judge_slot, "review_count": len(imported), "path": str(path)}


def _load_relevance_reviews(dataset: Path, judge_slot: str) -> dict[tuple[str, str], dict[str, Any]]:
    path = dataset / f"judge_{judge_slot.lower()}_relevance.jsonl"
    rows = read_jsonl(path)
    indexed = {(str(row.get("query_id")), str(row.get("product_id"))): row for row in rows}
    if not rows or len(indexed) != len(rows):
        raise ValueError(f"Judge {judge_slot} relevance reviews are missing or contain duplicate pairs")
    return indexed


def prepare_native_relevance_adjudication_tasks(dataset: Path, *, resume: bool = False) -> dict[str, Any]:
    """Write canonical-evidence packets only for genuine Judge A/B disagreements."""
    _require_native_dataset(dataset)
    tasks = _load_relevance_tasks(dataset)
    reviews_a, reviews_b = _load_relevance_reviews(dataset, "A"), _load_relevance_reviews(dataset, "B")
    if set(reviews_a) != set(tasks) or set(reviews_b) != set(tasks):
        raise ValueError("Both native relevance judges must cover every prepared pair before adjudication")
    pools = _load_native_pools(dataset)
    candidates = _pool_candidate_map(pools)
    rows: list[dict[str, Any]] = []
    for key in sorted(tasks):
        left, right = reviews_a[key], reviews_b[key]
        if left.get("relevance_grade") == right.get("relevance_grade"):
            continue
        task = tasks[key]
        base = {
            "task_type": "RELEVANCE_ADJUDICATION",
            "task_schema_version": RELEVANCE_ADJUDICATION_TASK_SCHEMA_VERSION,
            "prompt_version": NATIVE_PROMPT_VERSION,
            "query_id": key[0],
            "product_id": key[1],
            "dataset_fingerprint": task["dataset_fingerprint"],
            "catalog_fingerprint": task["catalog_fingerprint"],
            "evidence": task["evidence"],
            "evidence_fingerprint": task["evidence_fingerprint"],
            "relevance_task_fingerprint": task["task_fingerprint"],
            "deterministic_violations": deterministic_violations(
                (task.get("evidence") or {}).get("audited_intent") or {}, candidates[key]
            )[0],
            "judge_a": {
                name: left.get(name)
                for name in ("relevance_grade", "category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation", "missing_evidence", "relevant_evidence_references", "explanation", "confidence", "review_fingerprint")
            },
            "judge_b": {
                name: right.get(name)
                for name in ("relevance_grade", "category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation", "missing_evidence", "relevant_evidence_references", "explanation", "confidence", "review_fingerprint")
            },
            "required_output_fields": [
                "query_id", "product_id", "task_fingerprint", "resolution_status", "relevance_grade",
                "category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation",
                "missing_evidence", "rationale", "confidence",
            ],
        }
        _assert_blind_packet(base["evidence"])
        rows.append({**base, "task_fingerprint": fingerprint(base)})
    _write_checkpoint(relevance_adjudication_task_path(dataset), rows, resume=resume)
    _refresh_native_manifest(dataset, completion_status="RELEVANCE_ADJUDICATION_TASKS_PREPARED",
                             native_updates={"relevance_disagreement_count": len(rows)})
    return {"status": "COMPLETE", "disagreement_count": len(rows), "path": str(relevance_adjudication_task_path(dataset))}


def _normalise_native_adjudication(
    row: Mapping[str, Any],
    *,
    task: Mapping[str, Any],
    review_a: Mapping[str, Any],
    review_b: Mapping[str, Any],
    model: str,
) -> dict[str, Any]:
    key = (str(task["query_id"]), str(task["product_id"]))
    if row.get("task_fingerprint") != task.get("task_fingerprint"):
        raise ValueError(f"Stale or mismatched relevance adjudication task fingerprint: {key}")
    status = str(row.get("resolution_status") or "").upper()
    if status not in {"RESOLVED", "UNRESOLVED"}:
        raise ValueError(f"Native relevance adjudication has invalid resolution_status: {key}")
    rationale = str(row.get("rationale") or "").strip()
    if not rationale:
        raise ValueError(f"Native relevance adjudication lacks rationale: {key}")
    base: dict[str, Any] = {
        "query_id": key[0],
        "product_id": key[1],
        "task_fingerprint": task["task_fingerprint"],
        "relevance_task_fingerprint": task["relevance_task_fingerprint"],
        "evidence_fingerprint": task["evidence_fingerprint"],
        "dataset_fingerprint": task["dataset_fingerprint"],
        "catalog_fingerprint": task["catalog_fingerprint"],
        "task_schema_version": task["task_schema_version"],
        "prompt_version": task["prompt_version"],
        "resolution_status": status,
        "rationale": rationale,
        "confidence": _confidence(row.get("confidence")),
        "judge_a_grade": int(review_a["relevance_grade"]),
        "judge_b_grade": int(review_b["relevance_grade"]),
        "judge_a_review_fingerprint": review_a["review_fingerprint"],
        "judge_b_review_fingerprint": review_b["review_fingerprint"],
        "adjudicator_provider": CODEX_NATIVE_PROVIDER,
        "adjudicator_model": model,
        "adjudicator_provenance": {
            "execution_mode": "INTERACTIVE_CODEX_MAIN_AGENT",
            "model": model,
            "machine_adjudication": True,
            "external_api_called": False,
        },
        "submitted_output_fingerprint": fingerprint(row),
        "adjudicated_at_utc": utc_now(),
    }
    deterministic = task.get("deterministic_violations") or {}
    if status == "UNRESOLVED":
        return {
            **base,
            "final_grade": None,
            "label_source": None,
            **{field: bool(deterministic.get(field, False)) for field in deterministic},
            "missing_evidence": list(row.get("missing_evidence") or []),
            "reason": str(row.get("unresolved_reason") or "CODEX_NATIVE_ADJUDICATOR_UNRESOLVED"),
        }
    missing_fields = [field for field in RELEVANCE_SCHEMA_FIELDS if field not in row and field not in {"relevant_evidence_references", "explanation"}]
    if missing_fields:
        raise ValueError(f"Resolved native relevance adjudication lacks fields for {key}: {missing_fields}")
    grade = row.get("relevance_grade")
    if isinstance(grade, str) and grade.strip().isdigit():
        grade = int(grade)
    if grade not in VALID_GRADES:
        raise ValueError(f"Resolved native relevance adjudication has invalid grade for {key}")
    flags: dict[str, bool] = {}
    for field in ("category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation"):
        raw = row.get(field)
        if not isinstance(raw, bool):
            raise ValueError(f"Resolved native relevance adjudication has non-boolean {field}: {key}")
        flags[field] = raw or bool(deterministic.get(field, False))
    missing = row.get("missing_evidence")
    if isinstance(missing, str):
        missing = [missing]
    if not isinstance(missing, list):
        raise ValueError(f"Resolved native relevance adjudication has invalid missing_evidence: {key}")
    overridden = False
    if grade >= 2 and any(flags.values()):
        grade = 1
        overridden = True
        rationale += " Deterministic hard-constraint conflict capped final grade at 1."
    return {
        **base,
        "final_grade": grade,
        "label_source": "CODEX_NATIVE_ADJUDICATION",
        **flags,
        "missing_evidence": [str(item) for item in missing],
        "constraint_override": overridden,
    }


def finalise_native_relevance_adjudications(
    dataset: Path,
    *,
    submission: Path | None = None,
    resume: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    """Resolve exact agreements and import only actual native disagreement decisions."""
    _require_native_dataset(dataset)
    tasks = _load_relevance_tasks(dataset)
    reviews_a, reviews_b = _load_relevance_reviews(dataset, "A"), _load_relevance_reviews(dataset, "B")
    if set(reviews_a) != set(tasks) or set(reviews_b) != set(tasks):
        raise ValueError("Both native relevance judge artifacts must be complete before finalization")
    adjudication_tasks = {
        (str(row.get("query_id")), str(row.get("product_id"))): row
        for row in read_jsonl(relevance_adjudication_task_path(dataset))
    }
    if len(adjudication_tasks) != len(read_jsonl(relevance_adjudication_task_path(dataset))):
        raise ValueError("Duplicate native relevance adjudication tasks")
    submissions: dict[tuple[str, str], Mapping[str, Any]] = {}
    if submission is not None:
        if not submission.is_file():
            raise FileNotFoundError(f"Native relevance adjudication submission is missing: {submission}")
        for row in read_jsonl(submission):
            key = (str(row.get("query_id") or ""), str(row.get("product_id") or ""))
            if not all(key):
                raise ValueError("Native relevance adjudication is missing query_id or product_id")
            if key in submissions:
                raise ValueError(f"Duplicate native relevance adjudication: {key}")
            submissions[key] = row
    if set(submissions) - set(adjudication_tasks):
        raise ValueError(f"Native relevance adjudication includes non-disagreement pair(s): {sorted(set(submissions) - set(adjudication_tasks))}")
    native_model = (model or UNKNOWN_MODEL).strip() or UNKNOWN_MODEL
    decisions: list[dict[str, Any]] = []
    for key in sorted(tasks):
        review_a, review_b = reviews_a[key], reviews_b[key]
        deterministic = deterministic_violations(
            (tasks[key].get("evidence") or {}).get("audited_intent") or {},
            _pool_candidate_map(_load_native_pools(dataset))[key],
        )
        flags = {
            field: bool(deterministic[0][field]) or bool(review_a.get(field)) or bool(review_b.get(field))
            for field in deterministic[0]
        }
        common = {
            "query_id": key[0],
            "product_id": key[1],
            "relevance_task_fingerprint": tasks[key]["task_fingerprint"],
            "evidence_fingerprint": tasks[key]["evidence_fingerprint"],
            "dataset_fingerprint": tasks[key]["dataset_fingerprint"],
            "catalog_fingerprint": tasks[key]["catalog_fingerprint"],
            "prompt_version": tasks[key]["prompt_version"],
            "judge_a_grade": int(review_a["relevance_grade"]),
            "judge_b_grade": int(review_b["relevance_grade"]),
            "judge_a_review_fingerprint": review_a["review_fingerprint"],
            "judge_b_review_fingerprint": review_b["review_fingerprint"],
            **flags,
            "missing_evidence": sorted(set((deterministic[1] or []) + list(review_a.get("missing_evidence") or []) + list(review_b.get("missing_evidence") or []))),
            "adjudicated_at_utc": utc_now(),
        }
        if review_a["relevance_grade"] == review_b["relevance_grade"]:
            grade = int(review_a["relevance_grade"])
            overridden = False
            rationale = "Separate native judge contexts agreed; deterministic constraints were applied."
            if grade >= 2 and any(flags.values()):
                grade = 1
                overridden = True
                rationale += " Deterministic hard-constraint conflict capped final grade at 1."
            decision = {
                **common,
                "final_grade": grade,
                "resolution_status": "RESOLVED",
                "label_source": "CODEX_NATIVE_EXACT_AGREEMENT",
                "constraint_override": overridden,
                "rationale": rationale,
                "adjudicator_provider": None,
                "adjudicator_model": None,
            }
        elif key not in submissions:
            decision = {
                **common,
                "final_grade": None,
                "resolution_status": "UNRESOLVED",
                "label_source": None,
                "reason": "SUBSTANTIVE_CODEX_NATIVE_DISAGREEMENT_NO_ADJUDICATION",
                "constraint_override": False,
            }
        else:
            decision = _normalise_native_adjudication(
                submissions[key], task=adjudication_tasks[key], review_a=review_a, review_b=review_b, model=native_model
            )
            # Import output has the same authoritative deterministic flags as
            # the finalizer.  Preserve a clear combined set on the record.
            for field, value in flags.items():
                decision[field] = bool(decision.get(field)) or value
            if decision.get("final_grade") in {2, 3} and any(bool(decision.get(field)) for field in flags):
                decision["final_grade"] = 1
                decision["constraint_override"] = True
                decision["rationale"] = str(decision.get("rationale") or "") + " Deterministic hard-constraint conflict capped final grade at 1."
        decision["adjudication_fingerprint"] = fingerprint({key: value for key, value in decision.items() if key != "adjudicated_at_utc"})
        decisions.append(decision)
    path = dataset / "relevance_adjudications.jsonl"
    _write_checkpoint(path, decisions, resume=resume)
    qrels = qrels_from_adjudications(decisions)
    qrels_path = dataset / "qrels_silver.csv"
    if qrels_path.exists() and not resume:
        raise FileExistsError(f"{qrels_path} already exists. Use --resume only for an identical compatible checkpoint.")
    if qrels_path.exists() and resume:
        # CSV formatting itself is deterministic under the shared writer.
        from .silver import read_csv_rows
        if _checkpoint_fingerprint(read_csv_rows(qrels_path)) != _checkpoint_fingerprint(qrels):
            raise ValueError(f"Incompatible resume checkpoint: {qrels_path}")
    else:
        write_csv_rows(qrels_path, qrels, QREL_FIELDS)
    source = _load_unique_queries(dataset)
    audited = {str(row["query_id"]): row for row in audited_queries(source.values(), read_jsonl(dataset / "query_audit.jsonl"))}
    agreement = agreement_statistics(
        reviews_a.values(), reviews_b.values(), audited,
        _pool_candidate_map(_load_native_pools(dataset)),
    )
    disagreement_count = sum(item["judge_a_grade"] != item["judge_b_grade"] for item in decisions)
    resolved = [item for item in decisions if item.get("resolution_status") == "RESOLVED"]
    agreement.update({
        "annotation_method": CODEX_NATIVE_ANNOTATION_METHOD,
        "disagreement_count": disagreement_count,
        "constraint_violation_rate": (
            round(sum(any(bool(item.get(field)) for field in ("category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation")) for item in resolved) / len(resolved), 6)
            if resolved else None
        ),
        "unresolved_cases": [
            {"query_id": item["query_id"], "product_id": item["product_id"], "reason": item.get("reason", "UNRESOLVED")}
            for item in decisions if item.get("resolution_status") != "RESOLVED"
        ],
        "known_limitation": "Agreement reflects separate native executions, not independent model families or human verification.",
    })
    agreement_path = dataset / "agreement_report.json"
    if agreement_path.exists() and not resume:
        raise FileExistsError(f"{agreement_path} already exists. Use --resume only for an identical compatible checkpoint.")
    if agreement_path.exists() and resume:
        prior = json.loads(agreement_path.read_text(encoding="utf-8"))
        if _checkpoint_fingerprint(prior) != _checkpoint_fingerprint(agreement):
            raise ValueError(f"Incompatible resume checkpoint: {agreement_path}")
    else:
        agreement_path.write_text(json.dumps(agreement, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    unresolved = [item for item in decisions if item.get("resolution_status") != "RESOLVED"]
    _refresh_native_manifest(
        dataset,
        completion_status="ADJUDICATION_COMPLETE" if not unresolved else "ADJUDICATION_UNRESOLVED",
        unresolved_cases=unresolved,
        native_updates={
            "relevance_adjudication_count": len(decisions),
            "relevance_resolved_count": len(resolved),
            "relevance_unresolved_count": len(unresolved),
        },
    )
    return {
        "status": "COMPLETE" if not unresolved else "UNRESOLVED",
        "adjudications": len(decisions),
        "qrels": len(qrels),
        "unresolved": len(unresolved),
        "agreement": agreement,
    }


def _verify_native_snapshot(dataset: Path, manifest: Mapping[str, Any]) -> None:
    queries_path = dataset / "queries.jsonl"
    legacy_hashes = manifest.get("artifact_sha256") or {}
    expected_query_snapshot = manifest.get("queries_snapshot_sha256") or legacy_hashes.get("queries.jsonl")
    if not queries_path.is_file() or file_sha256(queries_path) != expected_query_snapshot:
        raise ValueError("Native dataset queries.jsonl no longer matches its pinned source-query fingerprint")
    catalog = PROJECT_ROOT / str(manifest.get("catalog_artifact") or "")
    if not catalog.is_file():
        raise FileNotFoundError(f"Pinned catalog is unavailable: {catalog}")
    if file_sha256(catalog) != manifest.get("catalog_sha256"):
        raise ValueError("Pinned catalog SHA-256 does not match native dataset manifest")


async def capture_native_candidate_pools(
    dataset: Path,
    *,
    methods: Sequence[str] = ("tfidf", "dense", "hybrid"),
    contribution_depth: int = 20,
    max_pairs: int = 90,
    allow_partial_methods: bool = False,
    resume: bool = False,
) -> dict[str, Any]:
    """Rerun real retrieval after a native audit and freeze a capped union."""
    manifest = _require_native_dataset(dataset)
    _verify_native_snapshot(dataset, manifest)
    audits = read_jsonl(dataset / "query_audit.jsonl")
    if not audits:
        raise ValueError("Complete native query audits are required before candidate capture")
    source = _load_unique_queries(dataset)
    eligible = [
        row for row in audited_queries(source.values(), audits)
        if row.get("silver_audit_status") == "COMPLETE"
    ]
    if not eligible:
        raise ValueError("No complete native query audits are eligible for candidate capture")
    catalog = PROJECT_ROOT / str(manifest["catalog_artifact"])
    pools, runs, blockers = await capture_multi_method_pools(
        eligible,
        catalog_path=catalog,
        catalog_sha256=str(manifest["catalog_sha256"]),
        methods=methods,
        contribution_depth=contribution_depth,
        allow_partial_methods=allow_partial_methods,
    )
    if not pools:
        _write_checkpoint(dataset / "capture_blockers.jsonl", blockers, resume=resume)
        _refresh_native_manifest(dataset, completion_status="CAPTURE_BLOCKED",
                                 native_updates={"capture_blocker_count": len(blockers)})
        return {"status": "BLOCKED", "frozen_pools": 0, "retrieval_runs": len(runs), "blockers": blockers}
    capped, cap_report = cap_native_candidate_pools(pools, max_pairs=max_pairs)
    _write_checkpoint(dataset / "candidate_pools.jsonl", capped, resume=resume)
    _write_checkpoint(dataset / "retrieval_runs.jsonl", runs, resume=resume)
    _write_checkpoint(dataset / "capture_blockers.jsonl", blockers, resume=resume)
    _refresh_native_manifest(
        dataset,
        completion_status="CANDIDATES_CAPTURED",
        native_updates={
            "capture_methods": list(methods),
            "capture_contribution_depth": contribution_depth,
            "candidate_pair_cap": cap_report,
            "capture_blocker_count": len(blockers),
        },
    )
    return {
        "status": "COMPLETE",
        "frozen_pools": len(capped),
        "retrieval_runs": len(runs),
        "blockers": blockers,
        "candidate_cap": cap_report,
        "eligible_query_ids": [str(row["query_id"]) for row in eligible],
    }
