"""Build a reproducible manual audit sample from Phase 3B candidates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from candidate_rules import FAMILY_TERMS


FAMILIES = tuple(FAMILY_TERMS)
MATCH_SOURCES = ("title_only", "taxonomy_only", "both")
TARGET_GROUPS = ("multi_family", "manual_coffee", "stovetop_kettle", "accessory")
FIELD_LIMITS = {"categories": 500, "features": 1200, "description": 1200, "details": 1200,
                "match_details": 500, "matched_accessory_keywords": 300,
                "matched_manual_keywords": 300, "matched_stovetop_keywords": 300}
CSV_FIELDS = (
    "parent_asin", "candidate_family", "candidate_families", "match_source",
    "title", "categories", "features", "description", "details", "match_details",
    "matched_accessory_keywords", "matched_manual_keywords", "matched_stovetop_keywords",
    "price", "average_rating", "rating_number", "accessory_flag",
    "manual_flag", "stovetop_flag", "ambiguous_family", "audit_group",
    "audit_label", "audit_family", "audit_reason", "audit_notes",
)


def match_source(record: dict, family: str | None = None) -> str:
    """Use family-specific evidence where a single family is being audited."""
    evidence = (record.get("match_details", {}).get(family, {}).get("matched_by")
                if family else record.get("matched_by"))
    values = set(evidence or [])
    if values == {"title"}:
        return "title_only"
    if values == {"taxonomy"}:
        return "taxonomy_only"
    if values == {"title", "taxonomy"}:
        return "both"
    raise ValueError(f"Unexpected match evidence: {evidence!r}")


def rank(seed: int, asin: str) -> str:
    return hashlib.sha256(f"{seed}:{asin}".encode("utf-8")).hexdigest()


def compact(value: object, limit: int) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return serialized if len(serialized) <= limit else serialized[:limit] + "… [truncated]"


def csv_row(record: dict, group: str) -> dict:
    family = record.get("candidate_family")
    row = {
        "parent_asin": record["parent_asin"],
        "candidate_family": family or "",
        "candidate_families": json.dumps(record["candidate_families"], ensure_ascii=False),
        "match_source": match_source(record, family),
        "title": record.get("title") or "",
        "price": record.get("price") if record.get("price") is not None else "",
        "average_rating": record.get("average_rating") if record.get("average_rating") is not None else "",
        "rating_number": record.get("rating_number") if record.get("rating_number") is not None else "",
        "accessory_flag": str(bool(record.get("possible_accessory"))).lower(),
        "manual_flag": str(bool(record.get("possible_manual_product"))).lower(),
        "stovetop_flag": str(bool(record.get("possible_stovetop_kettle"))).lower(),
        "ambiguous_family": str(bool(record.get("ambiguous_family"))).lower(),
        "audit_group": group,
        "audit_label": "", "audit_family": "", "audit_reason": "", "audit_notes": "",
    }
    row.update({field: compact(record.get(field), limit) for field, limit in FIELD_LIMITS.items()})
    return row


def generate_sample(source: Path, sample_csv: Path, profile_json: Path,
                    profile_md: Path, seed: int = 20261006,
                    per_stratum: int = 20, per_target: int = 20) -> dict:
    if per_stratum < 1 or per_target < 0:
        raise ValueError("per_stratum must be positive and per_target nonnegative")
    source = source.resolve()
    candidates = []
    seen = set()
    source_hash = hashlib.sha256()
    with source.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            source_hash.update(raw)
            record = json.loads(raw)
            asin = record.get("parent_asin")
            if not isinstance(asin, str) or not asin:
                raise ValueError(f"Missing parent_asin on line {line_number}")
            if asin in seen:
                raise ValueError(f"Duplicate parent_asin in source: {asin}")
            seen.add(asin)
            candidates.append(record)

    strata = defaultdict(list)
    for record in candidates:
        family = record.get("candidate_family")
        if family is not None:
            if family not in FAMILIES:
                raise ValueError(f"Unexpected candidate family: {family}")
            strata[(family, match_source(record, family))].append(record)

    selected = []
    selected_asins = set()

    def add(record: dict, group: str) -> None:
        asin = record["parent_asin"]
        if asin not in selected_asins:
            selected.append((record, group))
            selected_asins.add(asin)

    source_strata_counts = {}
    primary_counts = {}
    for family in FAMILIES:
        for source_name in MATCH_SOURCES:
            key = f"{family}|{source_name}"
            pool = strata[(family, source_name)]
            source_strata_counts[key] = len(pool)
            for record in sorted(pool, key=lambda item: (rank(seed, item["parent_asin"]), item["parent_asin"]))[:per_stratum]:
                add(record, f"stratum:{key}")
            primary_counts[key] = min(per_stratum, len(pool))

    target_predicates = {
        "multi_family": lambda r: len(r.get("candidate_families", [])) > 1,
        "manual_coffee": lambda r: bool(r.get("possible_manual_product")),
        "stovetop_kettle": lambda r: bool(r.get("possible_stovetop_kettle")),
        "accessory": lambda r: bool(r.get("possible_accessory")),
    }
    target_counts = {}
    target_available = {}
    for group in TARGET_GROUPS:
        pool = [record for record in candidates if target_predicates[group](record)]
        target_available[group] = len(pool)
        available = [record for record in pool if record["parent_asin"] not in selected_asins]
        before = len(selected)
        for record in sorted(available, key=lambda item: (rank(seed, item["parent_asin"]), item["parent_asin"]))[:per_target]:
            add(record, f"targeted:{group}")
        target_counts[group] = len(selected) - before

    rows = [csv_row(record, group) for record, group in selected]
    for output in (sample_csv, profile_json, profile_md):
        output.parent.mkdir(parents=True, exist_ok=True)
    with sample_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    family_counts = Counter(row["candidate_family"] or "MULTI_FAMILY" for row in rows)
    source_counts = Counter(row["match_source"] for row in rows)
    sample_strata_counts = Counter(
        f"{row['candidate_family']}|{row['match_source']}" for row in rows if row["candidate_family"]
    )
    high_risk = {
        "accessory_flag": sum(row["accessory_flag"] == "true" for row in rows),
        "manual_flag": sum(row["manual_flag"] == "true" for row in rows),
        "stovetop_flag": sum(row["stovetop_flag"] == "true" for row in rows),
        "multi_family": sum(row["ambiguous_family"] == "true" for row in rows),
        "ambiguous": sum(row["ambiguous_family"] == "true" for row in rows),
    }
    profile = {
        "random_seed": seed,
        "source_candidate_count": len(candidates),
        "source_sha256": source_hash.hexdigest(),
        "sample_count": len(rows),
        "unique_sample_asins": len(selected_asins),
        "family_counts": dict(sorted(family_counts.items())),
        "match_source_counts": dict(sorted(source_counts.items())),
        "source_strata_counts": source_strata_counts,
        "primary_strata_counts": primary_counts,
        "sample_strata_counts": dict(sorted(sample_strata_counts.items())),
        "high_risk_counts": high_risk,
        "targeted_oversample_counts": target_counts,
        "targeted_source_available": target_available,
        "sampling_configuration": {"per_stratum": per_stratum, "per_target": per_target,
                                   "family_order": FAMILIES, "match_source_order": MATCH_SOURCES,
                                   "target_group_order": TARGET_GROUPS, "field_char_limits": FIELD_LIMITS},
        "source_candidate_path": str(source),
        "sample_csv_path": str(sample_csv.resolve()),
    }
    profile_json.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Phase 4A — Audit sampling profile", "",
        f"Source: `{source}` ({len(candidates):,} candidates; SHA-256 `{source_hash.hexdigest()}`).",
        f"Seed: `{seed}`. Sample: **{len(rows)}** unique `parent_asin` values.", "",
        "The sample balances family × match source for single-family candidates, then adds separate high-risk rows. "
        "It is designed to discover cleaning patterns, not to estimate overall error rates without weighting.", "",
        "## Primary strata", "", "| Family | Title only | Taxonomy only | Both |", "| --- | ---: | ---: | ---: |",
    ]
    for family in FAMILIES:
        lines.append("| " + family + " | " + " | ".join(str(primary_counts[f"{family}|{name}"]) for name in MATCH_SOURCES) + " |")
    lines += ["", "## Sample coverage", "", "Family counts (ambiguous rows are shown as MULTI_FAMILY): " + json.dumps(profile["family_counts"]),
              "Match-source counts: " + json.dumps(profile["match_source_counts"]),
              "High-risk flag counts (overlapping): " + json.dumps(high_risk),
              "Additional targeted rows: " + json.dumps(target_counts), "",
              "## Limits", "", "Flags are hints, not labels. Multi-family rows retain all matched families and have no assigned candidate family. "
              "Nested source fields are JSON serialized and truncated in the CSV for review; the original candidate JSONL is untouched. "
              "Missing price is retained. The sample is deliberately balanced and enriched for risks, so its proportions are not population rates. "
              "Phase 4A does not define final cleaning rules; manually label the CSV before Phase 4B.", ""]
    profile_md.write_text("\n".join(lines), encoding="utf-8")
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/interim/home_kitchen_candidates.jsonl"))
    parser.add_argument("--sample-csv", type=Path, default=Path("data/interim/phase4a_audit_sample.csv"))
    parser.add_argument("--profile-json", type=Path, default=Path("data/interim/phase4a_audit_profile.json"))
    parser.add_argument("--profile-md", type=Path, default=Path("data/interim/phase4a_audit_profile.md"))
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--per-stratum", type=int, default=20)
    parser.add_argument("--per-target", type=int, default=20)
    args = parser.parse_args()
    profile = generate_sample(args.source, args.sample_csv, args.profile_json, args.profile_md,
                              args.seed, args.per_stratum, args.per_target)
    print(f"Wrote {profile['sample_count']} rows to {args.sample_csv}")


if __name__ == "__main__":
    main()
