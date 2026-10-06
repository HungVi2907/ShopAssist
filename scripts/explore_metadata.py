"""Profile Amazon Appliances metadata and explore its product taxonomy."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "parent_asin", "title", "main_category", "categories", "features",
    "description", "details", "price", "average_rating", "rating_number",
    "store",
)
FAMILY_PATTERNS = {
    "coffee_maker": re.compile(r"\b(?:coffee\s*(?:makers?|machines?|brewers?)|espresso\s+(?:machines?|makers?)|drip\s+coffee)\b", re.I),
    "blender": re.compile(r"\bblenders?\b", re.I),
    "air_fryer": re.compile(r"\bair\s+fryers?\b", re.I),
    "electric_kettle": re.compile(r"\bkettles?\b", re.I),
    "rice_cooker": re.compile(r"\b(?:rice\s+cookers?|rice\s+makers?)\b", re.I),
}
ACCESSORY = re.compile(
    r"\b(?:parts?|accessor(?:y|ies)|replacement|spare|filters?|blades?|"
    r"lids?|covers?|adapters?|attachments?)\b", re.I
)


def present(value: object) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[int((len(ordered) - 1) * fraction)], 2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/meta_Appliances.jsonl")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/interim")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    field_counts = Counter()
    field_types: dict[str, Counter] = defaultdict(Counter)
    main_categories = Counter()
    category_nodes = Counter()
    category_paths = Counter()
    category_depths = Counter()
    family_stats: dict[str, Counter] = defaultdict(Counter)
    family_samples: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    parent_asins = set()
    price_values = []
    rating_number_values = []

    with args.input.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            item = json.loads(line)
            total += 1
            for field in FIELDS:
                value = item.get(field)
                field_types[field][type(value).__name__] += 1
                if present(value):
                    field_counts[field] += 1

            parent_asins.add(item.get("parent_asin"))
            main_categories[str(item.get("main_category"))] += 1
            categories = item.get("categories") or []
            if not isinstance(categories, list):
                raise ValueError(f"categories is not a list on line {line_number}")
            categories = [str(value).strip() for value in categories if value]
            category_depths[len(categories)] += 1
            category_nodes.update(set(categories))
            category_paths[" > ".join(categories) if categories else "(empty)"] += 1

            price = item.get("price")
            if isinstance(price, (int, float)) and not isinstance(price, bool):
                price_values.append(price)
            rating_number = item.get("rating_number")
            if isinstance(rating_number, (int, float)) and not isinstance(rating_number, bool):
                rating_number_values.append(rating_number)

            title = str(item.get("title") or "")
            category_text = " > ".join(categories)
            accessory_category = bool(ACCESSORY.search(category_text))
            accessory_title = bool(ACCESSORY.search(title))
            for family, pattern in FAMILY_PATTERNS.items():
                title_match = bool(pattern.search(title))
                category_match = bool(pattern.search(category_text))
                if not (title_match or category_match):
                    continue
                stats = family_stats[family]
                stats["either"] += 1
                stats["title"] += title_match
                stats["category"] += category_match
                stats["both"] += title_match and category_match
                stats["accessory_category"] += accessory_category
                stats["accessory_title"] += accessory_title
                stats["without_accessory_signals"] += not (accessory_category or accessory_title)
                stats["priced"] += isinstance(price, (int, float)) and not isinstance(price, bool)
                stats["rating_number_ge_5"] += isinstance(rating_number, (int, float)) and rating_number >= 5
                bucket = "category_only" if category_match and not title_match else "title_match"
                samples = family_samples[family][bucket]
                if len(samples) < 8:
                    samples.append({
                        "parent_asin": item.get("parent_asin"),
                        "title": title,
                        "categories": categories,
                        "price": price,
                    })

    write_csv(
        args.output_dir / "category_analysis.csv",
        ["kind", "category", "count"],
        [(kind, value, count) for kind, counter in (
            ("node", category_nodes), ("path", category_paths),
            ("main_category", main_categories)
        ) for value, count in counter.most_common()],
    )
    profile = {
        "source": str(args.input.resolve()),
        "total_records": total,
        "unique_parent_asin": len(parent_asins),
        "field_presence": {field: {"count": field_counts[field], "pct": round(100 * field_counts[field] / total, 2)} for field in FIELDS},
        "field_types": {field: dict(counter) for field, counter in field_types.items()},
        "category_depths": dict(sorted(category_depths.items())),
        "numeric_summaries": {
            "price": {
                "min": min(price_values), "p10": percentile(price_values, 0.10),
                "median": percentile(price_values, 0.50),
                "p90": percentile(price_values, 0.90), "max": max(price_values),
            } if price_values else {},
            "rating_number": {
                "min": min(rating_number_values),
                "median": percentile(rating_number_values, 0.50),
                "max": max(rating_number_values),
                "ge_5": sum(value >= 5 for value in rating_number_values),
                "ge_10": sum(value >= 10 for value in rating_number_values),
            } if rating_number_values else {},
        },
        "family_signals": {family: dict(family_stats[family]) for family in FAMILY_PATTERNS},
        "family_samples": {family: dict(family_samples[family]) for family in FAMILY_PATTERNS},
    }
    (args.output_dir / "metadata_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Records: {total:,}; unique parent_asin: {len(parent_asins):,}")
    print(f"Taxonomy nodes: {len(category_nodes):,}; paths: {len(category_paths):,}")
    print("Exploratory family signals (includes accessories and overlaps):")
    for family in FAMILY_PATTERNS:
        print(f"  {family}: {family_stats[family]['either']:,}")
    print(f"Outputs: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
