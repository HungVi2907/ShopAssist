"""Shared Phase 4B audit loading and text normalization helpers."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path


DEFAULT_LABELS = Path("data/interim/phase4a_audit_sample_labeled.csv")
DEFAULT_CANDIDATES = Path("data/interim/home_kitchen_candidates.jsonl")
INVALID_LABELS = ("ACCESSORY", "MANUAL_DEVICE", "STOVETOP", "OTHER_NOISE")
LABELS = ("VALID_PRODUCT", *INVALID_LABELS, "AMBIGUOUS")


def normalize_text(value: str) -> str:
    """Lowercase Unicode text and replace punctuation/whitespace consistently."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def metadata_text(record: dict) -> str:
    fields = [record.get("title"), *(record.get("categories") or []),
              *(record.get("features") or []), *(record.get("description") or [])]
    details = record.get("details") or {}
    if isinstance(details, dict):
        for key, value in details.items():
            if isinstance(value, (str, int, float)):
                fields.extend((str(key), str(value)))
    return normalize_text(" ".join(value for value in fields if isinstance(value, str)))


def load_audit_records(labels_path: Path = DEFAULT_LABELS,
                       candidates_path: Path = DEFAULT_CANDIDATES) -> list[tuple[dict, dict]]:
    """Join labeled sample to full retained metadata by ASIN; never mutate source."""
    with labels_path.open(encoding="utf-8-sig", newline="") as stream:
        labels = list(csv.DictReader(stream))
    by_asin = {row["parent_asin"]: row for row in labels}
    if len(by_asin) != len(labels):
        raise ValueError("Duplicate ASIN in labeled sample")
    records = {}
    with candidates_path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            asin = record.get("parent_asin")
            if asin in by_asin:
                if asin in records:
                    raise ValueError(f"Duplicate candidate ASIN: {asin}")
                records[asin] = record
    missing = set(by_asin) - set(records)
    if missing:
        raise ValueError(f"Missing source metadata for {len(missing)} labeled ASINs")
    return [(row, records[row["parent_asin"]]) for row in labels]
