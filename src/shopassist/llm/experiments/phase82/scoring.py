"""Independent, versioned scoring. Missing outputs never earn empty-set credit."""
from __future__ import annotations

import math
import random
import statistics
from typing import Any

POLICY_VERSION = "phase82-1.0"
HC_FIELDS = ("category", "brand", "min_price", "max_price", "min_rating", "currency")
# Supplementary, conservative equivalences; strict scores always remain available.
EQUIVALENCES = {"with lumbar support": "lumbar support", "good battery endurance": "long battery life",
                "good battery life": "long battery life", "with safety harness": "safety harness"}


def text(value: Any) -> Any:
    return " ".join(value.casefold().split()) if isinstance(value, str) else value


def phrases(values: list[str] | None, semantic: bool = False) -> set[str]:
    result = {text(v) for v in values or [] if isinstance(v, str) and v.strip()}
    return {EQUIVALENCES.get(v, v) for v in result} if semantic else result


def prf(predicted: set, expected: set) -> dict:
    tp, fp, fn = len(predicted & expected), len(predicted - expected), len(expected - predicted)
    precision = tp / (tp + fp) if tp + fp else float(not expected)
    recall = tp / (tp + fn) if tp + fn else float(not predicted)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
            "f1": 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 1.0}


def exclusions(values: list | None) -> set:
    return {(text(e.get("target_type", "attribute")), text(e.get("value"))) for e in values or []}


def score(actual: dict | None, expected: dict, valid: bool = True) -> dict:
    valid = bool(valid and actual is not None)
    actual = actual or {}
    ah, eh = actual.get("hard_constraints", {}), expected.get("hard_constraints", {})
    # Currency default is part of both contracts, but a failed call has no default credit.
    def atoms(h: dict, failed: bool = False) -> set:
        return {(k, text(h.get(k, "INR" if k == "currency" else None))) for k in HC_FIELDS
                if not failed and h.get(k, "INR" if k == "currency" else None) is not None}
    hard = prf(atoms(ah, not valid), atoms(eh))
    ap, ep = phrases(actual.get("soft_preferences")), phrases(expected.get("soft_preferences"))
    soft = prf(ap if valid else set(), ep)
    semantic_soft = prf(phrases(actual.get("soft_preferences"), True) if valid else set(),
                        phrases(expected.get("soft_preferences"), True))
    if not valid:
        # A service failure is not a correct empty extraction.
        soft.update(precision=0.0, recall=0.0, f1=0.0)
        semantic_soft.update(precision=0.0, recall=0.0, f1=0.0)
    fields = {k: valid and text(ah.get(k, "INR" if k == "currency" else None)) ==
              text(eh.get(k, "INR" if k == "currency" else None)) for k in HC_FIELDS}
    fields["clarification"] = valid and actual.get("needs_clarification", False) == expected.get("needs_clarification", False)
    hard_exact = valid and all(fields[k] for k in HC_FIELDS)
    soft_exact = valid and ap == ep
    common_exact = hard_exact and soft_exact and fields["clarification"]
    v2_annotated = "product_type" in expected and "exclusions" in expected and all(
        k in eh for k in ("min_inclusive", "max_inclusive"))
    pt = (valid and "product_type" in actual and text(actual["product_type"]) == text(expected["product_type"])) if "product_type" in expected else None
    boundary = {}
    for side in ("min", "max"):
        flag = side + "_inclusive"
        boundary[flag] = (valid and flag in ah and ah[flag] == eh[flag]) if flag in eh and eh.get(side + "_price") is not None else None
    ax, ex = exclusions(actual.get("exclusions")), exclusions(expected.get("exclusions"))
    excl = prf(ax if valid else set(), ex) if "exclusions" in expected else None
    if not valid and excl is not None:
        excl.update(precision=0.0, recall=0.0, f1=0.0)
    excl_exact = (valid and "exclusions" in actual and ax == ex) if "exclusions" in expected else None
    full = (common_exact and pt is True and excl_exact is True and
            all(v for v in boundary.values() if v is not None)) if v2_annotated else None
    sq = valid and text(actual.get("semantic_query")) == text(expected["semantic_query"]) if "semantic_query" in expected else None
    return {"valid": valid, "hard": hard, "soft": soft, "semantic_soft": semantic_soft,
            "field_matches": fields, "hard_exact": hard_exact, "soft_exact": soft_exact,
            "common_exact": common_exact, "full_v2_exact": full, "product_type_match": pt,
            "boundary_matches": boundary, "exclusions": excl, "exclusion_exact": excl_exact,
            "semantic_query_lexical_match": sq,
            "soft_fp": sorted(ap - ep), "soft_fn": sorted(ep - ap)}


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if not n:
        return None
    p, d = successes / n, 1 + z*z/n
    center = (p + z*z/(2*n))/d
    margin = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return [center-margin, center+margin]


def aggregate(rows: list[dict]) -> dict:
    scores = [r["score"] for r in rows]
    n = len(scores)
    ids = [r["test_id"] for r in rows if "test_id" in r]
    repeated = len(ids) != len(set(ids))
    def rate(key: str) -> dict:
        vals = [s[key] for s in scores if s[key] is not None]
        return {"count": sum(vals), "denominator": len(vals), "rate": sum(vals)/len(vals) if vals else None,
                "wilson95": wilson(sum(vals), len(vals)) if not repeated else None}
    def micro(group: str) -> dict:
        vals = [s[group] for s in scores if s[group] is not None]
        tp, fp, fn = (sum(v[k] for v in vals) for k in ("tp", "fp", "fn"))
        return {"tp": tp, "fp": fp, "fn": fn, "f1": 2*tp/(2*tp+fp+fn) if tp+fp+fn else None}
    def mean(group: str, key: str = "f1") -> float | None:
        vals = [s[group][key] for s in scores if s[group] is not None]
        return statistics.mean(vals) if vals else None
    result = {"policy": POLICY_VERSION, "cases": n, "unique_queries": len(set(ids)) if ids else None,
              "uncertainty_note": "Repeated queries: record rates are descriptive; resample query clusters" if repeated else "Wilson intervals over query records",
              "schema_validity": rate("valid"),
              "common_exact": rate("common_exact"), "full_v2_exact": rate("full_v2_exact"),
              "hard_exact": rate("hard_exact"), "soft_exact": rate("soft_exact"),
              "product_type_accuracy": rate("product_type_match"), "exclusion_accuracy": rate("exclusion_exact"),
              "semantic_query_lexical_accuracy": rate("semantic_query_lexical_match"),
              "hard_micro": micro("hard"), "soft_micro": micro("soft"), "exclusion_micro": micro("exclusions"),
              "soft_macro_f1": mean("soft"), "soft_macro_precision": mean("soft", "precision"),
              "soft_macro_recall": mean("soft", "recall"), "semantic_soft_macro_f1": mean("semantic_soft"),
              "exclusion_macro_f1": mean("exclusions"),
              "field_accuracy": {k: sum(s["field_matches"][k] for s in scores)/n if n else None
                                 for k in (*HC_FIELDS, "clarification")}}
    live = [r for r in rows if r.get("cache_status") == "live"]
    cached = [r for r in rows if r.get("cache_status") == "hit"]
    def latency(items: list, key: str) -> dict:
        values = sorted(r[key] for r in items if r.get(key) is not None)
        return {"n": len(values), "median_ms": statistics.median(values) if values else None,
                "p95_ms": values[min(len(values)-1, math.ceil(.95*len(values))-1)] if values else None}
    result["performance"] = {"live_end_to_end": latency(live, "end_to_end_ms"),
                             "cache_lookup": latency(cached, "cache_lookup_ms"),
                             "historical_api_latency": "not comparable: origin/retry provenance incomplete"}
    result["boundary_accuracy"] = {}
    for flag in ("min_inclusive", "max_inclusive"):
        vals = [s["boundary_matches"][flag] for s in scores if s["boundary_matches"][flag] is not None]
        result["boundary_accuracy"][flag] = {"count": sum(vals), "denominator": len(vals),
                                             "rate": sum(vals)/len(vals) if vals else None,
                                             "wilson95": wilson(sum(vals),len(vals)) if not repeated else None}
    result["hallucinated_hard_constraints"] = {"false_positive_atoms": result["hard_micro"]["fp"],
        "query_rate": sum(s["hard"]["fp"] > 0 for s in scores)/n if n else None,
        "note": "Reference-relative false positives, including wrong values; not a universal hallucination detector"}
    usages = [r.get("token_usage", {}) for r in live]
    total = sum(u.get("total_tokens", 0) for u in usages)
    result["live_tokens"] = {"observed": total, "observed_per_call": total/len(live) if live else None,
                             "input_observed": sum(u.get("prompt_tokens",0) for u in usages),
                             "output_observed": sum(u.get("candidates_tokens",0) for u in usages),
                             "calls_with_observed_usage": sum(bool(u) for u in usages),
                             "unknown_attempts": sum(r.get("unknown_usage_attempts",0) for r in live),
                             "per_valid": total/sum(r["score"]["valid"] for r in live) if any(r["score"]["valid"] for r in live) else None,
                             "per_common_exact": total/sum(r["score"]["common_exact"] for r in live) if any(r["score"]["common_exact"] for r in live) else None}
    return result


def consistency(rows: list[dict]) -> dict:
    """Pairwise exact extraction agreement, grouped by query; failed calls disagree."""
    groups = {}
    for row in rows:
        groups.setdefault(row["test_id"], []).append(row)
    agreements = pairs = 0
    per_query = []
    for test_id, samples in sorted(groups.items()):
        wins = count = 0
        for i, left in enumerate(samples):
            for right in samples[i+1:]:
                count += 1
                wins += bool(left["is_valid"] and right["is_valid"] and left["actual"] == right["actual"])
        agreements += wins
        pairs += count
        per_query.append({"test_id": test_id, "samples": len(samples), "pairs": count,
                          "agreements": wins, "rate": wins/count if count else None})
    return {"agreements": agreements, "pairs": pairs, "rate": agreements/pairs if pairs else None,
            "unit": "within-query response pairs; agreement is not correctness", "per_query": per_query}


def paired_bootstrap(left: list[dict], right: list[dict], key: str = "common_exact", repetitions: int = 2000, seed: int = 82) -> dict:
    a, b = {r["test_id"]: r["score"][key] for r in left}, {r["test_id"]: r["score"][key] for r in right}
    if a.keys() != b.keys() or not a:
        raise ValueError("Paired comparisons require identical nonempty case IDs")
    if any(v is None for v in [*a.values(), *b.values()]):
        raise ValueError("Metric is not annotated on both sides")
    deltas = [float(b[k])-float(a[k]) for k in sorted(a)]
    rng = random.Random(seed)
    estimates = sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(repetitions))
    return {"effect": statistics.mean(deltas), "percentile95": [estimates[int(.025*repetitions)], estimates[int(.975*repetitions)-1]],
            "seed": seed, "repetitions": repetitions, "wins": sum(d>0 for d in deltas), "losses": sum(d<0 for d in deltas),
            "ties": sum(d==0 for d in deltas), "unit": "query; not repeated requests"}
