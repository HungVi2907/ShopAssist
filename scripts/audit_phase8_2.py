"""Recompute historical evidence and raw-response rule ablations without API calls."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from shopassist.llm.experiments.phase82.runner import atomic_write, digest
from shopassist.llm.experiments.phase82.rules import RULE_GROUPS, apply
from shopassist.llm.experiments.phase82.scoring import aggregate, paired_bootstrap, score
from shopassist.llm.refinement_rules import (apply_rule_based_refinement_v2, detect_price_boundary_semantics,
    extract_exclusions_from_text, resolve_negation_conflicts, clean_product_type_from_preferences,
    refine_hard_constraints_rules)
from shopassist.llm.schema_variants import RefinedQueryUnderstandingOutput
from shopassist.llm.schemas import QueryUnderstandingOutput

OUT = ROOT / "data/interim/phase8_2"


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf8"))


def legacy_key(config, query):
    payload = f"{config['model']}|{config['prompt_variant']}|{config['schema_version']}|{config['temperature']:.2f}|{query.strip()}"
    return hashlib.sha256(payload.encode()).hexdigest()


def historical_row(c):
    valid = c.get("is_valid", c.get("metrics", {}).get("is_valid", True))
    return {"test_id": c["test_id"], "query": c["query"], "expected": c["expected"], "actual": c["actual"],
            "is_valid": valid, "score": score(c["actual"], c["expected"], valid),
            "cache_status": "historical_unknown", "latency_ms": c.get("latency_ms", c.get("metrics", {}).get("latency_ms")),
            "token_usage": c.get("token_usage", c.get("metrics", {}).get("token_usage", {}))}


def main():
    timestamp = datetime.now(timezone.utc).isoformat()
    frozen_path = OUT / "baseline_sources/src__shopassist__llm__experiments__metrics.py"
    spec = importlib.util.spec_from_file_location("historical_metrics", frozen_path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    cache = load("data/interim/phase8_1/gemini_response_cache.json")
    baseline = load("data/interim/phase8_query_understanding_report.json")
    sets = {"baseline_50": {"E0": {"config": {"schema_version": "v1.0.0", "model": baseline.get("verified_model")},
                                        "per_case_results": baseline["per_case_evaluations"]}},
            "dev_15": load("data/interim/phase8_1/experiment_results.json"),
            "legacy_heldout_20": load("data/interim/phase8_1/experiment_results_heldout_20.json")}
    audits, failures, ablations = {}, [], []
    for split, experiments in sets.items():
        audits[split] = {}
        for exp, result in experiments.items():
            rows = [historical_row(c) for c in result["per_case_results"]]
            schema = RefinedQueryUnderstandingOutput if result["config"]["schema_version"] == "v2.0.0" else QueryUnderstandingOutput
            for row in rows:
                row.update(configuration=result["config"], dataset=split, dataset_version="historical version not recorded",
                           new_api_requests=0, audit_timestamp_utc=timestamp, retry_status="historical count unknown")
                try:
                    schema.model_validate(row["actual"])
                    row["stored_object_schema_revalidated"] = True
                except ValueError:
                    row["stored_object_schema_revalidated"] = False
                    row["is_valid"] = False
                    row["score"] = score(row["actual"],row["expected"],False)
            old_rows = [{**r, "metrics": old.evaluate_refined_case(r["actual"], r["expected"])} for r in rows]
            frozen_metrics = old.compute_experiment_metrics(old_rows)
            summary = aggregate(rows)
            invalid = []
            for r in rows:
                if not r["is_valid"]:
                    raw = cache.get(legacy_key(result["config"], r["query"]), {})
                    reason = raw.get("parsed_output", {}).get("clarification_reason", "")
                    invalid.append({"test_id": r["test_id"], "cause": "API_429_RETRY_EXHAUSTED" if "429" in reason else "UNCLASSIFIED",
                                    "json_syntax_validity": None, "schema_validity": None,
                                    "note": "No successful provider response; fallback object is not a schema-success observation."})
                s = r["score"]
                if not s["common_exact"] or s["full_v2_exact"] is False:
                    failures.append({"split": split, "experiment": exp, **r,
                                     "mismatch_fields": [k for k, v in s["field_matches"].items() if not v],
                                     "product_type_failure": s["product_type_match"] is False,
                                     "exclusion_failure": s["exclusion_exact"] is False,
                                     "boundary_failure": any(v is False for v in s["boundary_matches"].values())})
            tokens = [r["token_usage"].get("total_tokens", 0) for r in rows]
            latencies = [r["latency_ms"] for r in rows if r["latency_ms"]]
            audits[split][exp] = {"configuration": result["config"], "timestamp_utc": result.get("timestamp_utc"),
                                  "new_api_requests": 0, "cache_provenance": "unknown historical; raw cache replay audit only",
                                  "historical_frozen_recomputed": frozen_metrics, "standardized": summary,
                                  "historical_descriptive_only": {"median_stored_latency_ms": statistics.median(latencies) if latencies else None,
                                                                  "average_stored_tokens": statistics.mean(tokens)},
                                  "invalid_cases": invalid, "per_case_results": rows}
            if result["config"]["schema_version"] != "v2.0.0":
                continue
            raw_rows = []
            for r in rows:
                cached = cache.get(legacy_key(result["config"], r["query"]))
                if not cached or not cached.get("is_valid", True):
                    continue
                raw_rows.append((r, RefinedQueryUnderstandingOutput.model_validate_json(cached["raw_json"])))
            # All variants get exactly the same valid raw responses, excluding failures equally.
            configs = ["none", "historical", "historical_price", "historical_negation", "historical_product_type", "historical_brand", *RULE_GROUPS, "conservative_all"]
            variant_rows = {}
            for variant in configs:
                evaluated = []
                for r, raw in raw_rows:
                    if variant == "none":
                        final = raw.model_copy(deep=True)
                    elif variant == "historical":
                        final, _ = apply_rule_based_refinement_v2(raw.model_copy(deep=True), r["query"])
                    elif variant.startswith("historical_"):
                        final = raw.model_copy(deep=True)
                        if variant == "historical_price":
                            bounds = detect_price_boundary_semantics(r["query"])
                            final.hard_constraints.min_inclusive = bounds["min_inclusive"]
                            final.hard_constraints.max_inclusive = bounds["max_inclusive"]
                        elif variant == "historical_product_type":
                            final.soft_preferences, _ = clean_product_type_from_preferences(final.soft_preferences,final.product_type,final.semantic_query)
                        elif variant == "historical_negation":
                            existing = list(final.exclusions)
                            existing_values = {e.value for e in existing}
                            existing.extend(e for e in extract_exclusions_from_text(r["query"]) if e.value not in existing_values)
                            final.soft_preferences, final.exclusions, _ = resolve_negation_conflicts(final.soft_preferences,existing)
                        elif variant == "historical_brand":
                            constraints, _ = refine_hard_constraints_rules(final.hard_constraints, r["query"],is_clarification=final.needs_clarification)
                            final.hard_constraints.brand = constraints.brand
                            final.hard_constraints.category = constraints.category
                    else:
                        final, _ = apply(raw, r["query"], RULE_GROUPS if variant == "conservative_all" else (variant,))
                    evaluated.append({**r, "actual": final.model_dump(), "score": score(final.model_dump(), r["expected"]), "cache_status": "offline_replay"})
                variant_rows[variant] = evaluated
            base_by_id = {r["test_id"]: r for r in variant_rows["none"]}
            for variant, vr in variant_rows.items():
                corrected, introduced, changed = [], [], []
                for r in vr:
                    b = base_by_id[r["test_id"]]
                    if not b["score"]["full_v2_exact"] and r["score"]["full_v2_exact"]:
                        corrected.append(r["test_id"])
                    if b["score"]["full_v2_exact"] and not r["score"]["full_v2_exact"]:
                        introduced.append(r["test_id"])
                    if b["actual"] != r["actual"]:
                        changed.append(r["test_id"])
                ablations.append({"source_experiment": exp, "dataset": split, "variant": variant,
                                  "configuration": result["config"], "dataset_version": "historical version not recorded",
                                  "cache_status": "offline_replay", "retry_status": "no new calls; historical retries unknown",
                                  "token_usage": {"new_billed_tokens": 0}, "latency": "not inference measurement",
                                  "requests": 0, "timestamp_utc": timestamp, "status": "OFFLINE_REPLAY_EXECUTED",
                                  "valid_raw_cases": len(vr), "source_cases": len(rows), "excluded_api_failures": len(rows)-len(vr),
                                  "metrics": aggregate(vr), "corrected_full_em": corrected, "introduced_full_em": introduced,
                                  "changed_cases": changed, "per_case_results": vr})
    atomic_write(OUT / "baseline_audit.json", {"status": "EXECUTED_OFFLINE", "timestamp_utc": timestamp, "audits": audits})
    atomic_write(OUT / "failure_analysis.json", {"timestamp_utc": timestamp, "failures": failures,
                  "legacy_heldout_e5b_breakdown": dict(Counter(k for r in failures if r["split"] == "legacy_heldout_20" and r["experiment"] == "E5-B"
                         for k, v in [("soft", not r["score"]["soft_exact"]), ("product_type", r["product_type_failure"]),
                                      ("exclusion", r["exclusion_failure"]), ("brand", "brand" in r["mismatch_fields"]),
                                      ("clarification", "clarification" in r["mismatch_fields"]), ("boundary", r["boundary_failure"])] if v))})
    atomic_write(OUT / "rule_ablation_results.json", {"status": "EXECUTED_OFFLINE", "results": ablations})
    a = audits["legacy_heldout_20"]
    comparison = paired_bootstrap(a["E1-A"]["per_case_results"], a["E5-B"]["per_case_results"])
    atomic_write(OUT / "candidate_comparison.json", {"status": "HISTORICAL_REANALYSIS", "common_field_paired_bootstrap": comparison,
                 "selection": "NO_NEW_LIVE_CANDIDATE_ADOPTED", "production": "v1 original prompt retained",
                 "historical_e5b": "leading experimental control; not a proven production winner"})
    fixture_sets = {}
    for name in ("query_understanding_cases", "dev_evaluation_cases", "heldout_evaluation_cases"):
        fixture_sets[name] = load(f"tests/fixtures/{name}.json")["cases"]
    for split in ("dev", "validation", "heldout"):
        fixture_sets["phase82_"+split] = load(f"tests/fixtures/phase8_2/{split}.json")["cases"]
    integrity = {k: {"count": len(v), "duplicate_ids": len(v)-len({r["test_id"] for r in v}),
                     "duplicate_queries": len(v)-len({r["query"].strip().casefold() for r in v}), "cases_hash": digest(v)} for k,v in fixture_sets.items()}
    overlap = []
    for i, (a, rows) in enumerate(fixture_sets.items()):
        for b in list(fixture_sets)[i+1:]:
            common = {r["query"].strip().casefold() for r in rows} & {r["query"].strip().casefold() for r in fixture_sets[b]}
            if common:
                overlap.append({"left": a, "right": b, "exact_query_overlap": sorted(common)})
    atomic_write(OUT / "dataset_integrity.json", {"sets": integrity, "overlaps": overlap,
                 "independent_annotation_review": "PENDING", "fresh_heldout_predictions": "NOT RUN"})
    edge_rows = fixture_sets["phase82_dev"][:18]
    edge_results = {}
    for variant in ("historical", "conservative_all"):
        rows = []
        for c in edge_rows:
            raw = RefinedQueryUnderstandingOutput.model_validate(c["expected"])
            final, notes = (apply_rule_based_refinement_v2(raw, c["query"]) if variant == "historical" else apply(raw,c["query"]))
            rows.append({"test_id": c["test_id"], "query": c["query"], "expected": c["expected"], "actual": final.model_dump(),
                         "score": score(final.model_dump(),c["expected"]), "notes": notes, "cache_status": "synthetic_oracle_input"})
        edge_results[variant] = {"metrics": aggregate(rows), "per_case_results": rows}
    atomic_write(OUT / "robustness_evaluation_results.json", {"status": "OFFLINE_RULE_INVARIANCE_EXECUTED", "requests": 0,
                 "scope": "18 authored oracle inputs; not LLM extraction or generalization measurement", "results": edge_results,
                 "multilingual_live": "NOT_RUN", "adversarial_live": "NOT_RUN"})
    print(json.dumps({"baseline": audits["baseline_50"]["E0"]["standardized"],
                      "heldout": {k:v["standardized"] for k,v in audits["legacy_heldout_20"].items()},
                      "paired": comparison, "overlap_counts": [(r["left"],r["right"],len(r["exact_query_overlap"])) for r in overlap],
                      "rule_oracle": {k:v["metrics"]["full_v2_exact"] for k,v in edge_results.items()}},indent=2))


if __name__ == "__main__":
    main()
