"""Create the immutable Phase 13 pilot scaffold. No human labels are synthesized."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/evaluation/phase13/v1"
CATALOG = ROOT / "data/processed/products.parquet"

# Authored from the catalog domain and earlier Phase 11/12 examples, before viewing
# Phase 13 predictions. Category/type are planning metadata, not ground truth.
SEEDS = [
    ("running shoes for jogging", "Footwear", "USE_CASE", "en"),
    ("women red party wedges heel under 1500 INR rating 4.0+", "Footwear", "MULTI_CONSTRAINT", "en"),
    ("Tôi cần giày chạy bộ nam nhẹ, êm và thoáng cho người mới bắt đầu", "Footwear", "MIXED_HARD_SOFT", "vi"),
    ("brown leather boots for women with a zipper", "Footwear", "DIFFICULT_SEMANTIC", "en"),
    ("Show me phone cases for a Samsung Galaxy A-series handset", "Mobiles & Accessories", "SIMPLE_CONSTRAINT", "en"),
    ("I need a compact power bank for a day trip", "Mobiles & Accessories", "USE_CASE", "en"),
    ("Ốp điện thoại chống sốc, cầm không bị trơn", "Mobiles & Accessories", "SOFT_PREFERENCE", "vi"),
    ("car floor mats for a Suzuki Swift, not a Swift Dzire", "Automotive", "DIFFICULT_SEMANTIC", "en"),
    ("Show me car seat covers under 2000 INR", "Automotive", "SIMPLE_CONSTRAINT", "en"),
    ("Tôi cần bạt phủ xe chống nắng, dễ gấp gọn", "Automotive", "SOFT_PREFERENCE", "vi"),
    ("decorative wall stickers for a child's room", "Home Decor & Festive Needs", "USE_CASE", "en"),
    ("I want a festive lamp with a warm, subtle look", "Home Decor & Festive Needs", "SOFT_PREFERENCE", "en"),
    ("Rèm cửa cản sáng cho phòng ngủ, giá tối đa 1500 INR", "Home Furnishing", "MIXED_HARD_SOFT", "vi"),
    ("cotton bedsheets for a double bed", "Home Furnishing", "SIMPLE_CONSTRAINT", "en"),
    ("nonstick frying pan that is easy to clean", "Kitchen & Dining", "SOFT_PREFERENCE", "en"),
    ("Bình giữ nhiệt gọn nhẹ để mang đi làm", "Kitchen & Dining", "USE_CASE", "vi"),
    ("laptop for office work under 40000 INR", "Computers", "MIXED_HARD_SOFT", "en"),
    ("wireless keyboard for a small desk", "Computers", "USE_CASE", "en"),
    ("Đồng hồ đeo tay mặt số dễ đọc cho người lớn tuổi", "Watches", "USE_CASE", "vi"),
    ("men's analog watch priced between 1000 and 3000 INR", "Watches", "MULTI_CONSTRAINT", "en"),
    ("diaper bag with room for bottles and wipes", "Baby Care", "USE_CASE", "en"),
    ("Tôi muốn chăn em bé mềm và dễ giặt", "Baby Care", "SOFT_PREFERENCE", "vi"),
    ("waterproof backpack with a laptop compartment", "Bags, Wallets & Belts", "MIXED_HARD_SOFT", "en"),
    ("genuine leather men's wallet, not synthetic leather", "Bags, Wallets & Belts", "DIFFICULT_SEMANTIC", "en"),
    ("folding table for a small apartment", "Furniture", "USE_CASE", "en"),
    ("Ghế văn phòng ngồi lâu đỡ mỏi lưng", "Furniture", "SOFT_PREFERENCE", "vi"),
    ("yoga mat for a beginner practicing at home", "Sports & Fitness", "USE_CASE", "en"),
    ("lightweight badminton racket under 2000 INR", "Sports & Fitness", "MIXED_HARD_SOFT", "en"),
    ("cordless drill for assembling furniture", "Tools & Hardware", "USE_CASE", "en"),
    ("Bộ tua vít nhỏ gọn để sửa đồ trong nhà", "Tools & Hardware", "SOFT_PREFERENCE", "vi"),
    ("fountain pen with a fine nib", "Pens & Stationery", "SIMPLE_CONSTRAINT", "en"),
    ("notebook for daily study notes, easy to carry", "Pens & Stationery", "MIXED_HARD_SOFT", "en"),
    ("camera tripod for travel that folds small", "Cameras & Accessories", "MIXED_HARD_SOFT", "en"),
    ("I need a camera accessory for a beginner photographer", "Cameras & Accessories", "MISSING_ATTRIBUTE", "en"),
    ("energy-efficient LED bulb for a hallway", "Home Improvement", "USE_CASE", "en"),
    ("Đèn tường lắp ngoài hiên có chịu mưa không?", "Home Improvement", "MISSING_ATTRIBUTE", "vi"),
    ("Show me a laptop under 1 INR", "Computers", "NO_RESULT", "en"),
    ("I want a fountain pen below 1 INR", "Pens & Stationery", "NO_RESULT", "en"),
    ("I need running shoes under 100 USD", "Footwear", "CLARIFICATION_UNSUPPORTED", "en"),
    ("I need something nice for my home", "Home Decor & Festive Needs", "CLARIFICATION_UNSUPPORTED", "en"),
]

QUERY_TYPES = {"SIMPLE_CONSTRAINT", "MULTI_CONSTRAINT", "SOFT_PREFERENCE", "USE_CASE", "MIXED_HARD_SOFT", "DIFFICULT_SEMANTIC", "MISSING_ATTRIBUTE", "NO_RESULT", "CLARIFICATION_UNSUPPORTED"}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(out: Path = OUT) -> None:
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Dataset version already exists: {out}; make a new version instead")
    if len(SEEDS) != 40 or any(t not in QUERY_TYPES for _, _, t, _ in SEEDS):
        raise ValueError("Pilot must contain 40 valid query seeds")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for number, (query, category, query_type, language) in enumerate(SEEDS, 1):
        rows.append({
            "query_id": f"Q{number:04d}", "raw_query": query, "language": language,
            "query_type": query_type, "planning_category": category,
            "intent_group": f"G{number:04d}", "difficulty": "hard" if query_type in {"DIFFICULT_SEMANTIC", "MISSING_ATTRIBUTE", "NO_RESULT", "CLARIFICATION_UNSUPPORTED"} else "standard",
            "source": "phase11_or_phase12_example" if number in {1, 2, 3, 4, 8} else "phase13_author_draft",
            "expected_query_understanding": None, "price_boundary_semantics": None,
            "expected_status": None, "annotation_status": "UNREVIEWED_DRAFT",
        })
    (out / "queries.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    for name, fields in {
        "qrels.csv": ["query_id", "product_id", "reviewer_a_id", "reviewer_b_id", "reviewer_a_grade", "reviewer_b_grade", "adjudicated_grade", "category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation", "disagreement_reason"],
        "query_annotations.csv": ["query_id", "annotator_id", "semantic_query", "category", "brand", "min_price", "max_price", "min_rating", "currency", "min_operator", "max_operator", "soft_preferences_json", "needs_clarification", "clarification_reason", "expected_status", "comment"],
        "relevance_annotations.csv": ["query_id", "product_id", "annotator_id", "relevance_grade", "category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation", "comment"],
        "generation_claims.csv": ["claim_id", "query_id", "product_id", "claim", "evidence_ids_json", "evidence_text_json", "generation_snapshot", "reviewer_a_id", "reviewer_b_id", "adjudicator_id", "reviewer_a_support", "reviewer_b_support", "adjudicated_support", "reviewer_a_factual", "reviewer_b_factual", "adjudicated_factual", "reviewer_a_relevance", "reviewer_b_relevance", "adjudicated_relevance", "missing_information_handling", "disagreement_reason"],
    }.items():
        with (out / name).open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerow(fields)
    (out / "candidate_pools.jsonl").write_text("", encoding="utf-8")
    write_json(out / "splits.json", {"status": "NOT_FROZEN", "development": [], "held_out": [], "reason": "Independent annotations and adjudication are pending."})
    write_json(out / "dataset_manifest.json", {
        "dataset_version": "phase13-pilot-v1", "created_date": date.today().isoformat(),
        "catalog_artifact": "data/processed/products.parquet", "catalog_sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
        "catalog_product_count": 8405, "query_count": len(rows), "qrel_count": 0,
        "category_distribution": dict(sorted(Counter(r["planning_category"] for r in rows).items())),
        "query_type_distribution": dict(sorted(Counter(r["query_type"] for r in rows).items())),
        "language_distribution": dict(sorted(Counter(r["language"] for r in rows).items())),
        "split_counts": {"development": 0, "held_out": 0},
        "annotation_status": "UNREVIEWED_DRAFT", "reviewer_count": 0,
        "source_artifacts": ["data/interim/phase11/phase11_annotation_plan.md", "data/interim/phase11/phase11_reranking_cases.json", "docs/phase12_recommendation_evaluation.md"],
        "candidate_capture_status": "PENDING", "frozen": False,
    })


if __name__ == "__main__":
    build()
