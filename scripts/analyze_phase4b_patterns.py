"""Inspect label-associated n-grams and counterexamples without training a model."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from phase4b_common import DEFAULT_CANDIDATES, DEFAULT_LABELS, INVALID_LABELS, LABELS, load_audit_records, metadata_text, normalize_text


PROBES = (
    "replacement", "compatible with", "filter", "basket", "cup", "lid",
    "french press", "pour over", "moka", "manual", "cold brew",
    "stovetop", "whistling", "induction", "electric", "watt",
    "air fryer", "rice cooker", "rice warmer", "coffee maker", "blender",
)
GENERIC_TOKENS = {"a", "and", "appliances", "available", "brand", "by", "capacity", "color",
                  "count", "date", "description", "diameter", "dimensions", "dining", "feature",
                  "first", "for", "home", "in", "inch", "inches", "item", "kitchen", "manufacturer",
                  "material", "model", "number", "of", "ounces", "pounds", "product", "size",
                  "special", "style", "the", "to", "unit", "weight", "with", "x", "yes"}


def ngrams(tokens: list[str], size: int) -> set[str]:
    return {" ".join(tokens[index:index + size]) for index in range(len(tokens) - size + 1)}


def analyze(rows: list[tuple[dict, dict]]) -> dict:
    counts = Counter(label["audit_label"] for label, _ in rows)
    if set(counts) - set(LABELS):
        raise ValueError("Unknown audit labels")
    frequencies = {size: defaultdict(Counter) for size in (1, 2)}
    probes = {phrase: {label: {"count": 0, "examples": []} for label in LABELS} for phrase in PROBES}
    for label_row, record in rows:
        label = label_row["audit_label"]
        full_text = metadata_text(record)
        tokens = full_text.split()
        for size in (1, 2):
            for term in ngrams(tokens, size):
                frequencies[size][label][term] += 1
        padded = f" {full_text} "
        for phrase in PROBES:
            normalized = normalize_text(phrase)
            if f" {normalized} " in padded:
                cell = probes[phrase][label]
                cell["count"] += 1
                if len(cell["examples"]) < 3:
                    cell["examples"].append({"parent_asin": record["parent_asin"],
                                             "title": (record.get("title") or "")[:170]})

    def best_terms(label: str, size: int) -> list[dict]:
        reference_labels = INVALID_LABELS if label == "VALID_PRODUCT" else ("VALID_PRODUCT",)
        reference_total = sum(counts[reference] for reference in reference_labels)
        target_total = counts[label]
        ranked = []
        for term, support in frequencies[size][label].items():
            parts = term.split()
            if support < 3 or len(term) < 3 or any(part in GENERIC_TOKENS or part.isdigit() for part in parts):
                continue
            reference_support = sum(frequencies[size][reference][term] for reference in reference_labels)
            target_rate = (support + .5) / (target_total + 1)
            reference_rate = (reference_support + .5) / (reference_total + 1)
            ratio = target_rate / reference_rate
            if ratio <= 1.2:
                continue
            score = math.log2(ratio) * support
            ranked.append({"term": term, "target_count": support,
                           "reference_count": reference_support, "smoothed_rate_ratio": round(ratio, 3),
                           "score": round(score, 3)})
        return sorted(ranked, key=lambda item: (-item["score"], -item["target_count"], item["term"]))[:25]

    return {
        "method": "binary document frequency of normalized metadata unigrams/bigrams; generic metadata terms and numbers omitted; add-0.5 smoothed target/reference rate ratio; reference is VALID_PRODUCT except for VALID_PRODUCT where it is pooled invalid labels; score=target_count*log2(ratio)",
        "sample_count": len(rows), "label_counts": dict(counts),
        "top_discriminative": {label: {"unigrams": best_terms(label, 1), "bigrams": best_terms(label, 2)}
                               for label in LABELS if label != "AMBIGUOUS"},
        "probe_counts_and_counterexamples": probes,
    }


def render_markdown(profile: dict) -> str:
    lines = ["# Phase 4B — Pattern analysis", "",
             f"Input: {profile['sample_count']} Phase 4A labeled rows. Full retained metadata is joined only for those ASINs.",
             "Unigrams and bigrams are counted once per product; generic metadata terms and numbers are omitted. Ratios use add-0.5 smoothing. VALID_PRODUCT is compared with all four pooled invalid labels; each invalid label is compared with VALID_PRODUCT.",
             "These are exploratory associations from a stratified, risk-enriched sample, not population estimates or automatic rules.", ""]
    for label, sizes in profile["top_discriminative"].items():
        reference = "pooled invalid" if label == "VALID_PRODUCT" else "VALID_PRODUCT"
        lines.extend([f"## {label} vs {reference}", "",
                      "| N-gram | Term | Label rows | Reference rows | Smoothed ratio |",
                      "| --- | --- | ---: | ---: | ---: |"])
        for size, key in ((1, "unigrams"), (2, "bigrams")):
            for entry in sizes[key][:12]:
                lines.append(f"| {size} | {entry['term']} | {entry['target_count']} | {entry['reference_count']} | {entry['smoothed_rate_ratio']} |")
        lines.append("")
    lines.extend(["## Probe phrases and counterexamples", "",
                  "Counts below include any metadata field. A phrase with valid examples is unsafe as a stand-alone exclusion.", "",
                  "| Phrase | Valid | Accessory | Manual | Stovetop | Other |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for phrase, by_label in profile["probe_counts_and_counterexamples"].items():
        counts = [by_label[label]["count"] for label in ("VALID_PRODUCT", "ACCESSORY", "MANUAL_DEVICE", "STOVETOP", "OTHER_NOISE")]
        lines.append("| " + phrase + " | " + " | ".join(map(str, counts)) + " |")
    lines.extend(["", "### Unsafe single signals", ""])
    for phrase in ("filter", "basket", "cup", "manual", "induction", "replacement", "electric"):
        valid = profile["probe_counts_and_counterexamples"][phrase]["VALID_PRODUCT"]
        examples = valid["examples"][:2]
        sample = "; ".join(f"`{item['parent_asin']}` ({item['title']})" for item in examples)
        lines.append(f"- `{phrase}` occurs in {valid['count']} VALID_PRODUCT rows. Examples: {sample or 'none in this sample'}.")
    lines.extend(["", "## Family-specific interpretation", "",
                  "- Coffee: French press, pour-over and Moka often indicate manual brewing; powered espresso machines can mention manual controls or Moka.",
                  "- Blender: replacement jars/blades and whisk-like utensils are common; a full blender may include cups and blades.",
                  "- Air fryer: paper liners, pans and baskets are common; complete air fryers also mention baskets and accessories.",
                  "- Kettle: stovetop/whistling evidence requires checking for an integrated electric heater; `induction` alone is unsafe.",
                  "- Rice cooker: distinguish powered rice cooking from microwave pots, rice warmers and general hot pots.", "",
                  "Use the validation and error files to decide which combinations are safe. The six AMBIGUOUS labels are not training examples for KEEP or REMOVE.", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--json", type=Path, default=Path("data/interim/phase4b_pattern_analysis.json"))
    parser.add_argument("--md", type=Path, default=Path("data/interim/phase4b_pattern_analysis.md"))
    args = parser.parse_args()
    result = analyze(load_audit_records(args.labels, args.candidates))
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.md.write_text(render_markdown(result), encoding="utf-8")
    print(f"Analyzed {result['sample_count']} labeled rows")


if __name__ == "__main__":
    main()
