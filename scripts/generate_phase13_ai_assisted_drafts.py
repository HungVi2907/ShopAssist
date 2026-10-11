"""Create clearly separated AI-assisted *draft* interpretations for Phase 13.

This utility is deliberately not part of the human-review assembly workflow.
It never changes ``queries.jsonl``, ``query_annotations.csv``, or readiness
state.  Its CSV is a review aid: a human must accept, amend, or reject every
row before making a real reviewer submission.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


DEFAULT_DATASET = Path("data/evaluation/phase13/v2")
DEFAULT_OUTPUT = DEFAULT_DATASET / "ai_assisted_drafts" / "ai_assisted_query_annotations.csv"


PRICE_RULES = (
    # order matters: ranges must be handled before one-sided bounds
    (re.compile(r"\bbetween\s+(\d+(?:\.\d+)?)\s+and\s+(\d+(?:\.\d+)?)\s+INR\b", re.I), "range"),
    (re.compile(r"\bfrom\s+(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)\s+INR\b", re.I), "range"),
    (re.compile(r"\b(?:under|below)\s+(\d+(?:\.\d+)?)\s+INR\b", re.I), "max_strict"),
    (re.compile(r"\b(?:up to|at most|maximum|max|no more than)\s+(\d+(?:\.\d+)?)\s+INR\b", re.I), "max_inclusive"),
)
RATING_RULES = (
    re.compile(r"\brating\s+(\d+(?:\.\d+)?)\+", re.I),
    re.compile(r"\brating\s+at least\s+(\d+(?:\.\d+)?)", re.I),
    re.compile(r"\brated\s+(\d+(?:\.\d+)?)\s+or higher", re.I),
)

# Product attributes, use cases, and exclusions are retrieval cues rather than
# fabricated catalog facts.  The short labels intentionally preserve the user
# wording so a reviewer can correct them quickly.
PREFERENCE_RULES = (
    (r"jogging", "for jogging"), (r"party", "party wear"),
    (r"lightweight|gọn nhẹ|nhẹ", "lightweight"), (r"easy to clean|dễ vệ sinh", "easy to clean"),
    (r"easy to carry|easy to carry|mang đi", "portable"), (r"non[- ]?slip|không trơn|chống trượt", "non-slip grip"),
    (r"waterproof|chống mưa|chịu được mưa", "water resistance"), (r"rain cover", "rain cover"),
    (r"warm, subtle|ánh sáng dịu|ánh sáng yếu", "soft lighting"), (r"minimalist|tối giản", "minimalist style"),
    (r"blackout|cản sáng", "blackout"), (r"easy to wash|dễ giặt", "easy to wash"),
    (r"soft|mềm|êm", "soft/comfortable"), (r"breathable|thoáng", "breathable"),
    (r"small desk|small apartment|căn hộ nhỏ|gọn", "space-saving"),
    (r"easy to read|dễ đọc|dễ xem giờ", "easy to read"), (r"long trips|travel|du lịch|mang lên máy bay", "travel use"),
    (r"laptop compartment|laptop", "laptop compatibility"), (r"genuine leather|full-grain leather|leather", "leather material"),
    (r"folding|gấp gọn|gấp ngắn", "foldable"), (r"back support|đỡ mỏi lưng", "back support"),
    (r"beginner|người mới", "beginner-friendly"), (r"easy to carry|dễ mang", "portable"),
    (r"easy to store|dễ cất", "easy to store"), (r"fine nib", "fine nib"),
    (r"easy to carry|dễ cầm", "portable"), (r"cushioned|lớp đệm", "protective cushioning"),
    (r"energy-efficient|tiết kiệm điện", "energy efficient"), (r"outdoor|ngoài hiên|sân vườn", "outdoor use"),
    (r"not synthetic|rather than|not a |not an |not Alto|not a Swift", "explicit compatibility/material exclusion"),
    (r"microphone", "microphone"), (r"charging case", "charging case"),
    (r"dashboard", "dashboard mounting"), (r"visor", "visor"),
    (r"zipper", "zipper closure"), (r"drawers", "storage drawers"),
    (r"warm white", "warm-white light"), (r"date display", "date display"),
    (r"with lid", "included lid"), (r"induction", "induction compatible"),
    (r"leak|rò nước", "leak resistant"), (r"quick dry|nhanh khô", "quick drying"),
    (r"long battery|sạc được nhiều lần", "high capacity"), (r"comfortable|không đau", "comfortable"),
    (r"quiet|gõ êm", "quiet operation"), (r"dim room", "low-light use"),
    (r"small hands|tay bé", "compact size"), (r"water resistance|washes hands", "water resistance"),
    (r"many compartments|nhiều ngăn", "multiple compartments"), (r"sweat|mồ hôi", "sweat-resistant grip"),
    (r"adjustable|thay đổi mức nặng", "adjustable resistance/weight"),
    (r"metric", "metric sizing"), (r"thick paper|giấy dày", "thick paper"),
    (r"does not bleed|không lem", "ink-resistant paper"), (r"4K", "4K recording compatible"),
)


def _number(value: str) -> str:
    return str(int(float(value))) if float(value).is_integer() else value


def price_fields(text: str) -> tuple[str, str, str, str]:
    """Return min/max price and their operators; blanks mean not specified."""
    for pattern, kind in PRICE_RULES:
        match = pattern.search(text)
        if not match:
            continue
        if kind == "range":
            return _number(match.group(1)), _number(match.group(2)), ">=", "<="
        if kind == "max_strict":
            return "", _number(match.group(1)), "", "<"
        return "", _number(match.group(1)), "", "<="
    return "", "", "", ""


def rating_field(text: str) -> str:
    for pattern in RATING_RULES:
        match = pattern.search(text)
        if match:
            return _number(match.group(1))
    return ""


def preference_suggestions(text: str) -> list[str]:
    found: list[str] = []
    for expression, label in PREFERENCE_RULES:
        if re.search(expression, text, flags=re.I) and label not in found:
            found.append(label)
    return found


def semantic_query(text: str) -> str:
    """Keep all user meaning while removing only filler; a human validates it."""
    value = re.sub(r"^(?:show me|i need|i want|find)\s+", "", text.strip(), flags=re.I)
    return value or text.strip()


def draft_row(query: dict[str, object]) -> dict[str, str]:
    raw = str(query["raw_query"])
    query_type = str(query["query_type"])
    category = str(query["planning_category"])
    min_price, max_price, min_operator, max_operator = price_fields(raw)
    status = "SUCCESS"
    needs_clarification = "false"
    clarification_reason = ""
    priority = "NORMAL"

    if query_type == "NO_RESULT":
        status = "NO_RESULTS"
        priority = "HIGH: verify against frozen catalog/Phase 10, not this draft"
    elif query_type == "CLARIFICATION_UNSUPPORTED":
        status = "UNSUPPORTED_INTENT"
        needs_clarification = "true"
        clarification_reason = "Request requires an unsupported external, remote, image, or service action."
        priority = "HIGH: confirm stop reason"
        if str(query["query_id"]) == "Q0040":
            category = ""
            status = "CLARIFICATION_REQUIRED"
            clarification_reason = "The requested home item is too vague to identify a supported product domain."
    elif query_type == "MISSING_ATTRIBUTE":
        priority = "HIGH: confirm whether catalog absence requires clarification or a retrieval result with an unknown attribute"

    currency = "USD" if re.search(r"\bUSD\b", raw, flags=re.I) else "INR"
    if currency == "USD":
        status = "UNSUPPORTED_INTENT"
        needs_clarification = "true"
        clarification_reason = "Catalog prices are INR; do not silently convert the explicit USD budget."
        priority = "HIGH: confirm foreign-currency stop behavior"

    return {
        "query_id": str(query["query_id"]),
        "record_type": "AI_ASSISTED_DRAFT_NOT_A_REVIEWER",
        "annotator_id": "AI_ASSISTED_DRAFT_NOT_A_REVIEWER",
        "semantic_query": semantic_query(raw),
        "category": category,
        "brand": "",
        "min_price": min_price,
        "max_price": max_price,
        "min_rating": rating_field(raw),
        "currency": currency,
        "min_operator": min_operator,
        "max_operator": max_operator,
        "soft_preferences_json": json.dumps(preference_suggestions(raw), ensure_ascii=False),
        "needs_clarification": needs_clarification,
        "clarification_reason": clarification_reason,
        "proposed_expected_status": status,
        "review_priority": priority,
        "rationale": "Machine-assisted preliminary interpretation derived from raw query and draft taxonomy; requires independent human review.",
        "source_query_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def generate(dataset: Path, output: Path) -> int:
    if output.name == "query_annotations.csv" or output.parent == dataset:
        raise ValueError("Refusing to write an AI draft into the canonical human-annotation location")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing draft file: {output}")
    queries = [json.loads(line) for line in (dataset / "queries.jsonl").read_text(encoding="utf-8").splitlines() if line]
    rows = [draft_row(query) for query in queries]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps({"ai_assisted_draft_rows": generate(args.dataset, args.out), "output": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
