"""Exhaustively scan Home_and_Kitchen metadata into a high-recall candidate set."""

from __future__ import annotations

import argparse
import concurrent.futures
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from typing import Any

from candidate_rules import FAMILY_TERMS, detect_candidate


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "interim"
SOURCE_URL = (
    "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/"
    "resolve/2b6d039ed471f2ba5fd2acb718bf33b0a7e5598e/"
    "raw/meta_categories/meta_Home_and_Kitchen.jsonl"
)
SOURCE_SIZE = 11_788_767_944
SOURCE_SHA256 = "691353084748d985180deb13dc8de59afe4969933ad3692ea06b80460510aa56"
FIELDS = (
    "parent_asin", "title", "main_category", "categories", "features",
    "description", "details", "price", "average_rating", "rating_number", "store",
)
QUALITY_FIELDS = ("price", "features", "description", "details", "categories")
FLAG_FIELDS = ("possible_accessory", "possible_manual_product", "possible_stovetop_kettle", "ambiguous_family")


def present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def fetch_range(curl: str, start: int, end: int, temporary_dir: Path) -> tuple[bytes, int]:
    failures = 0
    for attempt in range(4):
        with tempfile.TemporaryDirectory(dir=temporary_dir) as name:
            body = Path(name) / "body"
            headers = Path(name) / "headers"
            try:
                subprocess.run(
                    [curl, "--fail", "--location", "--silent", "--show-error",
                     "--connect-timeout", "30", "--max-time", "240",
                     "--range", f"{start}-{end}", "--dump-header", str(headers),
                     "--output", str(body), SOURCE_URL],
                    check=True, capture_output=True, timeout=250,
                )
                header_text = headers.read_text(encoding="latin-1").lower()
                statuses = re.findall(r"(?m)^http/\S+\s+(\d{3})\b", header_text)
                expected_range = f"content-range: bytes {start}-{end}/{SOURCE_SIZE}"
                if not statuses or statuses[-1] != "206":
                    raise ValueError(f"Expected HTTP 206 for bytes {start}-{end}; statuses={statuses}")
                if expected_range not in header_text:
                    raise ValueError(f"Unexpected Content-Range for bytes {start}-{end}; headers={header_text[-300:]}")
                data = body.read_bytes()
                if len(data) != end - start + 1:
                    raise ValueError(f"Truncated range {start}-{end}: {len(data)} bytes")
                return data, failures
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
                failures += 1
                if attempt == 3:
                    detail = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
                    raise RuntimeError(f"Failed range {start}-{end} after 4 attempts: {detail}") from exc
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def initial_stats() -> dict[str, Any]:
    return {
        "total_records_scanned": 0,
        "valid_records": 0,
        "total_candidates": 0,
        "invalid_records": 0,
        "parse_errors": 0,
        "network_errors": 0,
        "missing_parent_asin_count": 0,
        "duplicate_parent_asin_count": 0,
        "unexpected_field_types": {},
        "families": {family: {} for family in FAMILY_TERMS},
    }


def open_state(database: Path, partial_output: Path) -> tuple[sqlite3.Connection, int, bytes, dict[str, Any]]:
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("CREATE TABLE IF NOT EXISTS source_asins (asin TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS candidate_asins (asin TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS family_asins (family TEXT, asin TEXT, PRIMARY KEY (family, asin))")
    conn.execute("CREATE TABLE IF NOT EXISTS progress (id INTEGER PRIMARY KEY CHECK(id=1), offset INTEGER, output_size INTEGER, pending BLOB, stats TEXT)")
    row = conn.execute("SELECT offset, output_size, pending, stats FROM progress WHERE id=1").fetchone()
    if row is None:
        if partial_output.exists():
            raise RuntimeError(f"Partial output exists without checkpoint: {partial_output}")
        partial_output.touch()
        stats = initial_stats()
        conn.execute(
            "INSERT INTO progress VALUES (1, 0, 0, ?, ?)",
            (b"", json.dumps(stats)),
        )
        conn.commit()
        return conn, 0, b"", stats
    offset, output_size, pending, stats_json = row
    if not partial_output.exists() or partial_output.stat().st_size < output_size:
        raise RuntimeError("Checkpoint refers to missing or truncated candidate output")
    with partial_output.open("r+b") as stream:
        stream.truncate(output_size)
    return conn, offset, pending, json.loads(stats_json)


def process_record(raw_line: bytes, stats: dict[str, Any], source_ids: list[tuple[str]], candidate_ids: list[tuple[str]], family_ids: list[tuple[str, str]], output) -> None:
    stats["total_records_scanned"] += 1
    try:
        item = json.loads(raw_line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        stats["invalid_records"] += 1
        stats["parse_errors"] += 1
        return
    if not isinstance(item, dict):
        stats["invalid_records"] += 1
        return
    stats["valid_records"] += 1
    asin = item.get("parent_asin")
    if isinstance(asin, str) and asin:
        source_ids.append((asin,))
    else:
        stats["missing_parent_asin_count"] += 1
    for field, expected_type in (("title", str), ("categories", list), ("features", list), ("description", list), ("details", dict)):
        value = item.get(field)
        if value is not None and not isinstance(value, expected_type):
            type_counts = stats["unexpected_field_types"]
            type_counts[field] = type_counts.get(field, 0) + 1

    match = detect_candidate(item)
    if match is None:
        return
    stats["total_candidates"] += 1
    if isinstance(asin, str) and asin:
        candidate_ids.append((asin,))
    candidate = {field: item.get(field) for field in FIELDS}
    candidate.update(match)
    candidate["source"] = "Home_and_Kitchen"
    output.write(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n")

    for family in match["candidate_families"]:
        family_stats = stats["families"][family]
        family_stats["raw_candidates"] = family_stats.get("raw_candidates", 0) + 1
        if isinstance(asin, str) and asin:
            family_ids.append((family, asin))
        flag_keys = {
            "possible_accessory": "possible_accessories",
            "possible_manual_product": "possible_manual_products",
            "possible_stovetop_kettle": "possible_stovetop_kettles",
            "ambiguous_family": "ambiguous_family",
        }
        for flag in FLAG_FIELDS:
            if match[flag]:
                key = flag_keys[flag]
                family_stats[key] = family_stats.get(key, 0) + 1
        for field in QUALITY_FIELDS:
            if present(item.get(field)):
                key = "has_" + field
                family_stats[key] = family_stats.get(key, 0) + 1
        reasons = match["match_details"][family]["matched_by"]
        key = "both" if len(reasons) == 2 else ("title_only" if reasons == ["title"] else "taxonomy_only")
        family_stats[key] = family_stats.get(key, 0) + 1


def commit_chunk(conn: sqlite3.Connection, offset: int, pending: bytes, stats: dict[str, Any], output, source_ids: list[tuple[str]], candidate_ids: list[tuple[str]], family_ids: list[tuple[str, str]]) -> None:
    output.flush()
    os.fsync(output.fileno())
    with conn:
        before = conn.total_changes
        conn.executemany("INSERT OR IGNORE INTO source_asins VALUES (?)", source_ids)
        after = conn.total_changes
        stats["duplicate_parent_asin_count"] += len(source_ids) - (after - before)
        conn.executemany("INSERT OR IGNORE INTO candidate_asins VALUES (?)", candidate_ids)
        conn.executemany("INSERT OR IGNORE INTO family_asins VALUES (?, ?)", family_ids)
        conn.execute(
            "UPDATE progress SET offset=?, output_size=?, pending=?, stats=? WHERE id=1",
            (offset, os.fstat(output.fileno()).st_size, pending, json.dumps(stats, separators=(",", ":"))),
        )


def split_complete_lines(pending: bytes, data: bytes, final: bool) -> tuple[list[bytes], bytes]:
    lines = (pending + data).split(b"\n")
    remainder = lines.pop()
    if final and remainder:
        lines.append(remainder)
        remainder = b""
    return lines, remainder


def finalize(conn: sqlite3.Connection, stats: dict[str, Any], output_dir: Path, partial_output: Path) -> None:
    stats["source"] = SOURCE_URL
    stats["source_size_bytes"] = SOURCE_SIZE
    stats["source_published_sha256"] = SOURCE_SHA256
    stats["scan_complete"] = True
    stats["unique_parent_asin"] = conn.execute("SELECT COUNT(*) FROM candidate_asins").fetchone()[0]
    stats["source_unique_parent_asin"] = conn.execute("SELECT COUNT(*) FROM source_asins").fetchone()[0]
    for family, family_stats in stats["families"].items():
        count = family_stats.get("raw_candidates", 0)
        family_stats.setdefault("raw_candidates", 0)
        family_stats["unique_parent_asin"] = conn.execute("SELECT COUNT(*) FROM family_asins WHERE family=?", (family,)).fetchone()[0]
        for flag, output_key in (("possible_accessory", "possible_accessories"), ("possible_manual_product", "possible_manual_products"), ("possible_stovetop_kettle", "possible_stovetop_kettles")):
            family_stats.setdefault(output_key, 0)
        family_stats.setdefault("ambiguous_family", 0)
        for field in QUALITY_FIELDS:
            key = "has_" + field
            family_stats.setdefault(key, 0)
            family_stats[key + "_rate"] = round(family_stats[key] / count, 4) if count else 0.0
        for key in ("title_only", "taxonomy_only", "both"):
            family_stats.setdefault(key, 0)

    profile_path = output_dir / "home_kitchen_full_profile.json"
    profile_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Home_and_Kitchen full metadata scan", "",
        f"Scanned lines: **{stats['total_records_scanned']:,}**; valid records: **{stats['valid_records']:,}**; candidate records: **{stats['total_candidates']:,}**; unique candidate `parent_asin`: **{stats['unique_parent_asin']:,}**.",
        f"Invalid records: {stats['invalid_records']:,}; parse errors: {stats['parse_errors']:,}; recoverable network errors: {stats['network_errors']:,}; duplicate source `parent_asin`: {stats['duplicate_parent_asin_count']:,}.",
        "", "| Family | Candidates | Unique ASIN | Accessory flag | Manual flag | Stovetop flag | Ambiguous | Price | Features | Description | Details | Categories |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family, value in stats["families"].items():
        lines.append("| " + " | ".join([
            family, f"{value['raw_candidates']:,}", f"{value['unique_parent_asin']:,}",
            f"{value['possible_accessories']:,}", f"{value['possible_manual_products']:,}",
            f"{value['possible_stovetop_kettles']:,}", f"{value['ambiguous_family']:,}",
            *[f"{value['has_' + field + '_rate']:.1%}" for field in QUALITY_FIELDS],
        ]) + " |")
    lines.extend([
        "", "## Potential issues", "",
        "- Flags identify possible accessories, manual coffee products, and stovetop kettles; they do not remove candidates.",
        "- `taxonomy_only` matches require manual review because category paths can be noisy.",
        "- Records with multiple family matches retain every matched family and have `candidate_family: null`.",
        "- Missing prices are measured, not filtered.",
        "", "## Phase 4 recommendation", "",
        "Audit flagged examples and taxonomy-only matches by family before final cleaning. Define explicit rules for powered coffee makers and electric kettles, then measure clean product counts and price coverage. No reviews, embeddings, or recommendation components were processed in this scan.", "",
    ])
    (output_dir / "home_kitchen_full_profile.md").write_text("\n".join(lines), encoding="utf-8")
    os.replace(partial_output, output_dir / "home_kitchen_candidates.jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunk-mib", type=int, default=32)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    chunk_size = args.chunk_mib * 1024 * 1024
    if chunk_size <= 0 or args.workers <= 0:
        parser.error("chunk-mib and workers must be positive")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final_output = output_dir / "home_kitchen_candidates.jsonl"
    if final_output.exists() and (output_dir / "home_kitchen_full_profile.json").exists():
        print(f"Full scan already complete: {final_output}")
        return
    curl = shutil.which("curl.exe" if os.name == "nt" else "curl")
    if curl is None:
        raise RuntimeError("curl is required for HTTP range requests")

    partial_output = output_dir / "home_kitchen_candidates.jsonl.part"
    conn, offset, pending, stats = open_state(output_dir / "home_kitchen_scan_state.sqlite", partial_output)
    if offset % chunk_size != 0 and offset != SOURCE_SIZE:
        raise RuntimeError("Resume requires the same --chunk-mib value")
    chunk_count = (SOURCE_SIZE + chunk_size - 1) // chunk_size
    next_index = offset // chunk_size
    last_log = stats["total_records_scanned"] // 100_000
    try:
        with partial_output.open("a", encoding="utf-8", newline="") as output:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures: dict[int, concurrent.futures.Future] = {}
                next_submit = next_index
                while next_index < chunk_count:
                    while next_submit < chunk_count and len(futures) < args.workers:
                        start = next_submit * chunk_size
                        end = min(SOURCE_SIZE, start + chunk_size) - 1
                        futures[next_submit] = pool.submit(fetch_range, curl, start, end, output_dir)
                        next_submit += 1
                    try:
                        data, failures = futures.pop(next_index).result()
                    except RuntimeError:
                        stats["network_errors"] += 4
                        with conn:
                            conn.execute("UPDATE progress SET stats=? WHERE id=1", (json.dumps(stats, separators=(",", ":")),))
                        raise
                    stats["network_errors"] += failures
                    lines, pending = split_complete_lines(pending, data, next_index == chunk_count - 1)
                    source_ids: list[tuple[str]] = []
                    candidate_ids: list[tuple[str]] = []
                    family_ids: list[tuple[str, str]] = []
                    for raw_line in lines:
                        if raw_line:
                            process_record(raw_line, stats, source_ids, candidate_ids, family_ids, output)
                    offset = min(SOURCE_SIZE, (next_index + 1) * chunk_size)
                    commit_chunk(conn, offset, pending, stats, output, source_ids, candidate_ids, family_ids)
                    if stats["total_records_scanned"] // 100_000 > last_log or offset == SOURCE_SIZE:
                        last_log = stats["total_records_scanned"] // 100_000
                        counts = " ".join(f"{family}={stats['families'][family].get('raw_candidates', 0):,}" for family in FAMILY_TERMS)
                        print(f"records scanned: {stats['total_records_scanned']:,}; candidates: {stats['total_candidates']:,}; bytes: {offset / SOURCE_SIZE:.1%}; {counts}", flush=True)
                    next_index += 1
        finalize(conn, stats, output_dir, partial_output)
        print(f"Full scan complete: {stats['total_records_scanned']:,} records; {stats['total_candidates']:,} candidates", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
