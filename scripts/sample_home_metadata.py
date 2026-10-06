"""Sample byte ranges across Home_and_Kitchen metadata without downloading all 11.8 GB."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from explore_metadata import ACCESSORY, FAMILY_PATTERNS, ROOT, present


SOURCE_URL = (
    "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/"
    "resolve/2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e/"
    "raw/meta_categories/meta_Home_and_Kitchen.jsonl"
)
FILE_SIZE = 11_788_767_944


def fetch_range(curl: str, start: int, size: int) -> bytes:
    end = start + size - 1
    with tempfile.TemporaryDirectory() as directory:
        body = Path(directory) / "body"
        headers = Path(directory) / "headers"
        subprocess.run(
            [curl, "--fail", "--location", "--retry", "3", "--silent", "--show-error",
             "--range", f"{start}-{end}", "--dump-header", str(headers),
             "--output", str(body), SOURCE_URL],
            check=True,
        )
        header_text = headers.read_text(encoding="latin-1").lower()
        expected_range = f"content-range: bytes {start}-{end}/{FILE_SIZE}"
        if "http/1.1 206" not in header_text and "http/2 206" not in header_text:
            raise ValueError("Server did not return HTTP 206 for range request")
        if expected_range not in header_text:
            raise ValueError(f"Unexpected Content-Range for {start}-{end}")
        data = body.read_bytes()
        if len(data) != size:
            raise ValueError(f"Expected {size} bytes, received {len(data)}")
        return data


def complete_lines(data: bytes, start: int) -> list[bytes]:
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]
    if not data.endswith(b"\n"):
        lines = lines[:-1]
    return [line for line in lines if line]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", type=int, default=24)
    parser.add_argument("--window-mib", type=int, default=4)
    parser.add_argument("--output", type=Path, default=ROOT / "data/interim/home_sample_profile.json")
    args = parser.parse_args()
    size = args.window_mib * 1024 * 1024
    if args.windows < 2 or size <= 0 or args.windows * size > FILE_SIZE:
        parser.error("Need at least two non-overlapping windows inside the source file")
    curl = shutil.which("curl.exe" if os.name == "nt" else "curl")
    if curl is None:
        raise RuntimeError("curl is required")

    total = 0
    field_presence = Counter()
    category_nodes = Counter()
    category_paths = Counter()
    family_stats: dict[str, Counter] = defaultdict(Counter)
    family_examples: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    starts = []
    for index in range(args.windows):
        start = round((index + 0.5) * FILE_SIZE / args.windows - size / 2)
        starts.append(start)
        data = fetch_range(curl, start, size)
        for raw_line in complete_lines(data, start):
            item = json.loads(raw_line)
            total += 1
            for field in ("parent_asin", "title", "categories", "features", "description", "details", "price", "rating_number"):
                field_presence[field] += present(item.get(field))
            categories = item.get("categories") or []
            if not isinstance(categories, list):
                continue
            categories = [str(value).strip() for value in categories if value]
            category_text = " > ".join(categories)
            category_nodes.update(set(categories))
            category_paths[category_text or "(empty)"] += 1
            title = str(item.get("title") or "")
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
                stats["without_accessory_signals"] += not (accessory_category or accessory_title)
                stats["priced"] += isinstance(item.get("price"), (int, float))
                bucket = "no_accessory_signal" if not (accessory_category or accessory_title) else "accessory_signal"
                examples = family_examples[family][bucket]
                if len(examples) < 12:
                    examples.append({"title": title, "categories": categories, "price": item.get("price"), "parent_asin": item.get("parent_asin")})
        print(f"Window {index + 1}/{args.windows}: {total:,} records so far", flush=True)

    result = {
        "source": SOURCE_URL,
        "source_size_bytes": FILE_SIZE,
        "sampling": "Systematic byte windows at stratum midpoints; partial edge lines excluded",
        "window_count": args.windows,
        "window_size_bytes": size,
        "window_starts": starts,
        "sampled_records": total,
        "field_presence": {key: {"count": value, "pct": round(100 * value / total, 2)} for key, value in field_presence.items()},
        "top_category_nodes": category_nodes.most_common(30),
        "top_category_paths": category_paths.most_common(30),
        "family_signals": {family: dict(family_stats[family]) for family in FAMILY_PATTERNS},
        "family_examples": {family: dict(family_examples[family]) for family in FAMILY_PATTERNS},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Sampled records: {total:,}; output: {args.output}")


if __name__ == "__main__":
    main()
