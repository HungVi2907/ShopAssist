"""Plan grouped, stratified Phase 13 splits without changing a dataset version."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.validate_phase13_dataset import read_jsonl, read_csv, near_duplicates, validate
except ModuleNotFoundError:  # direct script execution
    from validate_phase13_dataset import read_jsonl, read_csv, near_duplicates, validate


def _components(queries: list[dict]) -> list[list[dict]]:
    """Keep declared paraphrases and flagged lexical near-duplicates together."""
    ids = {q["query_id"]: q for q in queries}
    parent = {qid: qid for qid in ids}

    def root(qid: str) -> str:
        while parent[qid] != qid:
            parent[qid] = parent[parent[qid]]
            qid = parent[qid]
        return qid

    def union(left: str, right: str) -> None:
        a, b = root(left), root(right)
        parent[max(a, b)] = min(a, b)

    by_group: dict[str, str] = {}
    for q in queries:
        group = q["intent_group"]
        if group in by_group:
            union(q["query_id"], by_group[group])
        else:
            by_group[group] = q["query_id"]
    for pair in near_duplicates(queries):
        union(pair["left"], pair["right"])
    grouped: dict[str, list[dict]] = defaultdict(list)
    for q in queries:
        grouped[root(q["query_id"])].append(q)
    return [sorted(group, key=lambda q: q["query_id"]) for group in grouped.values()]


def plan(queries: list[dict], *, seed: int = 13, held_out_fraction: float = 0.3) -> dict:
    if not queries or not 0 < held_out_fraction < 1:
        raise ValueError("A nonempty query set and a fraction between zero and one are required")
    components = _components(queries)
    if len(components) < 2:
        raise ValueError("At least two independent intent components are needed")
    target_count = round(len(queries) * held_out_fraction)
    attrs = ("planning_category", "query_type", "language", "difficulty", "constraint_pattern")
    def value(query: dict, key: str) -> str:
        if key != "constraint_pattern":
            return str(query.get(key))
        understanding = query.get("expected_query_understanding") or {}
        hard = understanding.get("hard_constraints") or {}
        bounds = query.get("price_boundary_semantics") or {}
        parts = [field for field in ("category", "brand", "min_price", "max_price", "min_rating") if hard.get(field) is not None]
        parts += [f"strict_{field}" for field in ("min_operator", "max_operator") if bounds.get(field) in {"<", ">"}]
        if understanding.get("soft_preferences"):
            parts.append("soft")
        if query.get("expected_status") in {"NO_RESULTS", "CLARIFICATION_REQUIRED", "UNSUPPORTED_INTENT"}:
            parts.append(query["expected_status"])
        return "+".join(parts) or "none"
    totals = {key: Counter(value(q, key) for q in queries) for key in attrs}
    targets = {key: {value: count * held_out_fraction for value, count in totals[key].items()} for key in attrs}
    held_out: list[dict] = []
    counts = {key: Counter() for key in attrs}
    # Larger groups first; a seeded hash gives stable tie-breaking without
    # depending on Python's randomized hash function or input row order.
    components.sort(key=lambda group: (-len(group), hashlib.sha256(f"{seed}:{group[0]['query_id']}".encode()).hexdigest()))

    def score(next_count: int, next_counts: dict[str, Counter]) -> float:
        size_error = abs(next_count - target_count) * 5
        stratum_error = sum(
            abs(next_counts[key][value] - target) * (2 if key in {"planning_category", "query_type"} else 1)
            for key in attrs for value, target in targets[key].items()
        )
        return size_error + stratum_error

    for group in components:
        candidate_counts = {key: counts[key] + Counter(value(q, key) for q in group) for key in attrs}
        take = score(len(held_out) + len(group), candidate_counts) < score(len(held_out), counts)
        if take and len(held_out) + len(group) < len(queries):
            held_out.extend(group)
            counts = candidate_counts
    if not held_out:
        held_out = components[0]
    held_ids = {q["query_id"] for q in held_out}
    development = sorted(q["query_id"] for q in queries if q["query_id"] not in held_ids)
    test = sorted(held_ids)
    if not development or not test:
        raise ValueError("Unable to create two nonempty splits without leakage")
    return {
        "status": "PROPOSED", "split_version": "phase13-grouped-stratified-v1",
        "random_seed": seed, "held_out_fraction_target": held_out_fraction,
        "development": development, "held_out": test,
        "intent_groups": {q["query_id"]: q["intent_group"] for q in queries},
        "strata": {part: {key: dict(Counter(value(q, key) for q in queries if q["query_id"] in members)) for key in attrs}
                   for part, members in (("development", set(development)), ("held_out", set(test)))},
    }


def freeze(dataset: Path, split: dict) -> dict:
    """Promote a proposed split only after every human and data gate passes."""
    report = validate(dataset)
    if report["status"] != "PASS":
        raise ValueError("Dataset validation has critical errors")
    if split.get("status") != "PROPOSED":
        raise ValueError("Only a proposed split can be frozen")
    required_gates = ("query_count", "category_coverage", "query_type_coverage", "interpretations_adjudicated",
                      "candidate_pools_frozen", "no_results_verified", "relevance_complete",
                      "claims_adjudicated", "adjudication_trail", "generation_case_coverage",
                      "claim_challenge_coverage", "dataset_hashes")
    failed = [name for name in required_gates if not report["readiness_gates"][name]]
    if failed:
        raise ValueError(f"Dataset is ineligible for split freeze: {failed}")
    queries = read_jsonl(dataset / "queries.jsonl")
    pools = read_jsonl(dataset / "candidate_pools.jsonl")
    qrels = read_csv(dataset / "qrels.csv")
    claims = read_csv(dataset / "generation_claims.csv")
    if len(queries) < 200 or not all(q.get("annotation_status") == "ADJUDICATED" and q.get("expected_query_understanding") for q in queries):
        raise ValueError("At least 200 adjudicated query interpretations are required")
    eligible = {q["query_id"] for q in queries if q["expected_status"] in {"SUCCESS", "NO_RESULTS"}}
    if not eligible <= {p["query_id"] for p in pools} or not qrels or not claims:
        raise ValueError("Candidate pools, qrels, and generated claim cases are incomplete")
    if not all(r.get("adjudicated_grade") for r in qrels) or not all(c.get("adjudicated_support") and c.get("adjudicated_factual") and c.get("adjudicated_relevance") for c in claims):
        raise ValueError("Human relevance or claim adjudication is incomplete")
    if set(split["development"]) | set(split["held_out"]) != {q["query_id"] for q in queries}:
        raise ValueError("Proposed split does not cover this dataset")
    if set(split["development"]) & set(split["held_out"]):
        raise ValueError("Proposed split overlaps")
    grouped = {frozenset(q["query_id"] for q in group) for group in _components(queries)}
    dev, test = set(split["development"]), set(split["held_out"])
    if any(group & dev and group & test for group in grouped):
        raise ValueError("Intent or near-duplicate leakage across split")
    manifest = json.loads((dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
    names = (*manifest["artifact_sha256"], "dataset_manifest.json")
    frozen = dict(split)
    frozen["status"] = "FROZEN"
    frozen["split_timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    frozen["dataset_hashes"] = {name: hashlib.sha256((dataset / name).read_bytes()).hexdigest() for name in names}
    return frozen


def freeze_version(dataset: Path, out: Path, split: dict) -> dict:
    """Create a new immutable release version containing the frozen split."""
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite dataset version: {out}")
    frozen = freeze(dataset, split)
    source_manifest = json.loads((dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True)
    for name in (*source_manifest["artifact_sha256"], "catalog_draft_audit.json"):
        if (dataset / name).is_file():
            shutil.copy2(dataset / name, out / name)
    manifest = dict(source_manifest)
    manifest.update({"dataset_version": f"phase13-{out.name}", "source_version": source_manifest["dataset_version"],
                     "source_dataset_relpath": str(dataset.resolve().relative_to(Path(__file__).resolve().parents[1])).replace("\\", "/"),
                     "created_utc": datetime.now(timezone.utc).isoformat(), "frozen": True,
                     "split_counts": {"development": len(frozen["development"]), "held_out": len(frozen["held_out"])},
                     "source_file_sha256": {name: hashlib.sha256((dataset / name).read_bytes()).hexdigest()
                                            for name in source_manifest["artifact_sha256"]}})
    (out / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    frozen["dataset_hashes"] = {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                                for name in (*manifest["artifact_sha256"], "dataset_manifest.json")}
    (out / "splits.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate(out)
    (out / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        raise ValueError(f"Frozen version validation failed: {report['errors']}")
    return {"version": out.name, "development": len(frozen["development"]),
            "held_out": len(frozen["held_out"]), "phase14_ready": report["phase14_ready"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="New split manifest file; source dataset remains unchanged")
    parser.add_argument("--release-out", type=Path, help="New dataset version containing the frozen split")
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--held-out-fraction", type=float, default=0.3)
    parser.add_argument("--freeze", action="store_true", help="Require all reviewed benchmark gates")
    args = parser.parse_args()
    if bool(args.out) == bool(args.release_out):
        parser.error("choose exactly one of --out or --release-out")
    if args.release_out and not args.freeze:
        parser.error("--release-out requires --freeze")
    if args.out and args.out.exists():
        raise FileExistsError(f"Refusing to overwrite split manifest: {args.out}")
    split = plan(read_jsonl(args.dataset / "queries.jsonl"), seed=args.seed, held_out_fraction=args.held_out_fraction)
    if args.release_out:
        print(json.dumps(freeze_version(args.dataset, args.release_out, split)))
        return
    if args.freeze:
        split = freeze(args.dataset, split)
    args.out.write_text(json.dumps(split, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{split['status']}: development={len(split['development'])}, held_out={len(split['held_out'])}")


if __name__ == "__main__":
    main()
