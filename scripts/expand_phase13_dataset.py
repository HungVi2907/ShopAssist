"""Create a traceable 200-query draft v2 from the immutable Phase 13 pilot.

The new text is authored for catalog domains. Types and categories are planning
metadata only; no generated interpretation or no-result label is ground truth.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.validate_phase13_dataset import ROOT, read_jsonl, validate
except ModuleNotFoundError:
    from validate_phase13_dataset import ROOT, read_jsonl, validate


TYPES = ("SIMPLE_CONSTRAINT", "MULTI_CONSTRAINT", "SOFT_PREFERENCE", "USE_CASE",
         "MIXED_HARD_SOFT", "DIFFICULT_SEMANTIC", "MISSING_ATTRIBUTE", "NO_RESULT",
         "CLARIFICATION_UNSUPPORTED", "MULTI_CONSTRAINT")

# Ten distinct shopping intents per category. The language prefix is removed
# before writing raw_query. Prices and absent attributes remain unverified.
NEW_QUERIES: dict[str, tuple[str, ...]] = {
    "Footwear": (
        "flat sandals with ankle straps", "women's walking shoes under 2500 INR with rating at least 4",
        "vi:Giày đi học nhẹ và không làm đau gót chân", "shoes for a restaurant worker standing all day",
        "vi:Giày thể thao nam dưới 2000 INR, đế bám tốt khi trời mưa",
        "trail shoes for wet rocks rather than a treadmill", "Is the insole removable in these walking shoes?",
        "women's boots below 1 INR", "Find the exact shoes from my photo",
        "men's formal lace-up shoes, black, from 1500 to 3000 INR inclusive"),
    "Mobiles & Accessories": (
        "USB-C charging cable for a phone", "screen protector for iPhone 13 up to 500 INR rated 4 or higher",
        "vi:Pin dự phòng nhỏ gọn, sạc được nhiều lần", "charger for commuting with only one wall outlet",
        "vi:Ốp Samsung A54 dưới 800 INR, mỏng và dễ cầm",
        "charger for an older micro-USB phone, not a USB-C handset", "Does this power bank support pass-through charging?",
        "phone case below 1 INR", "Repair my phone remotely before recommending accessories",
        "wireless earbuds with microphone and charging case under 2500 INR"),
    "Automotive": (
        "rear-view mirror for a car", "car phone holder under 1000 INR with dashboard mounting",
        "vi:Bọc vô lăng không trơn tay khi lái lâu", "organizer for a family car on long trips",
        "vi:Máy hút bụi ô tô dưới 3000 INR, dễ vệ sinh bộ lọc",
        "seat covers for Maruti Alto, not Alto K10", "Will this wiper fit the 2018 hatchback trim?",
        "car floor mat below 1 INR", "Book a mechanic to install this tomorrow",
        "bike helmet with visor under 2000 INR rated at least 4"),
    "Home Decor & Festive Needs": (
        "ceramic flower vase", "wall clock under 1500 INR in a wooden finish",
        "vi:Đèn trang trí ánh sáng dịu cho góc đọc sách", "festive decorations for a small rented room",
        "vi:Tranh treo tường dưới 2000 INR, phong cách tối giản",
        "diwali lights safe for an indoor shelf rather than an outdoor gate", "Does this wall decal peel off without damaging paint?",
        "decorative lamp below 1 INR", "Show how this vase looks in my room using a live camera",
        "set of two cushion covers in blue under 1200 INR"),
    "Home Furnishing": (
        "single-bed cotton sheet", "blackout curtains for a 6-foot window under 2500 INR",
        "vi:Khăn tắm mềm, thấm nước tốt và nhanh khô", "bedding for a guest room used only occasionally",
        "vi:Chăn mỏng mùa hè dưới 1800 INR, dễ giặt máy",
        "queen-size fitted sheet rather than a flat sheet", "What is the thread count of this bedsheet?",
        "pillow cover below 1 INR", "Arrange a home visit to measure my windows",
        "two cotton pillowcases in white below 1000 INR"),
    "Kitchen & Dining": (
        "stainless steel saucepan", "induction-compatible frying pan under 3000 INR with lid",
        "vi:Hộp đựng thức ăn kín, không bị rò nước", "lunch container for soup during a train commute",
        "vi:Bình nước thép dưới 1200 INR, giữ lạnh lâu",
        "pan for induction cooktop rather than gas-only cookware", "Is this food container explicitly BPA-free?",
        "dinner plate below 1 INR", "Cook dinner for me and deliver it tonight",
        "six-piece dinner set, ceramic, under 2500 INR"),
    "Computers": (
        "wired optical mouse", "laptop stand under 2000 INR that fits 15-inch laptops",
        "vi:Bàn phím gõ êm để làm việc ban đêm", "webcam for video lessons in a dim room",
        "vi:Chuột không dây dưới 1500 INR, nhỏ gọn cho tay bé",
        "USB-C hub with HDMI for a laptop, not a USB-A-only adapter", "Does this monitor support a 100 Hz refresh rate?",
        "laptop under 1 INR", "Install an operating system on my laptop now",
        "27-inch monitor with HDMI under 15000 INR"),
    "Watches": (
        "women's digital watch", "men's analog watch with leather strap at most 2500 INR",
        "vi:Đồng hồ dễ xem giờ trong ánh sáng yếu", "watch for a nurse who washes hands often",
        "vi:Đồng hồ trẻ em dưới 1000 INR, dây mềm và nhẹ",
        "automatic mechanical watch rather than battery quartz", "What is the rated water resistance depth of this watch?",
        "wristwatch below 1 INR", "Set the time on a watch I already own remotely",
        "silver-tone watch with date display under 3000 INR"),
    "Baby Care": (
        "baby feeding bottle", "diapers size M under 1000 INR in a multipack",
        "vi:Khăn em bé mềm, không gây kích ứng da", "portable changing mat for travel with a newborn",
        "vi:Túi đựng đồ em bé dưới 2500 INR, nhiều ngăn dễ tìm",
        "bottle sterilizer rather than a bottle warmer", "Is the fabric certified for newborn skin contact?",
        "baby blanket below 1 INR", "Diagnose my baby's rash from a photo",
        "baby stroller with canopy up to 12000 INR"),
    "Bags, Wallets & Belts": (
        "canvas tote bag", "women's shoulder bag under 2000 INR with zipper",
        "vi:Balo đi làm nhẹ, quai đeo không đau vai", "wallet for carrying many cards while traveling",
        "vi:Túi đeo chéo dưới 1500 INR, chống mưa nhẹ",
        "full-grain leather belt rather than faux-leather look", "Does this backpack fit a 17-inch laptop?",
        "men's wallet below 1 INR", "Repair the zip on my existing backpack",
        "black leather belt size 34 under 1200 INR"),
    "Furniture": (
        "wooden bedside table", "study desk under 6000 INR with two drawers",
        "vi:Ghế gấp gọn cho căn hộ nhỏ", "shoe rack for a narrow apartment hallway",
        "vi:Bàn làm việc dưới 5000 INR, đủ chỗ cho màn hình lớn",
        "solid wood shelf rather than particle board", "How much weight can this folding chair support?",
        "office chair below 1 INR", "Assemble my wardrobe at home this afternoon",
        "two-seater sofa in grey under 20000 INR"),
    "Sports & Fitness": (
        "resistance bands", "badminton shoes under 2500 INR in size 9",
        "vi:Thảm tập không trơn khi đổ mồ hôi", "home exercise equipment for a small apartment",
        "vi:Tạ tay dưới 2000 INR, dễ thay đổi mức nặng",
        "yoga block made of cork rather than foam", "What is the maximum user weight of this treadmill?",
        "cricket bat below 1 INR", "Become my live personal trainer for an hour",
        "football size 5 with pump under 1500 INR"),
    "Tools & Hardware": (
        "adjustable wrench", "cordless screwdriver under 4000 INR with battery included",
        "vi:Bộ dụng cụ sửa nhà gọn, dễ cất trong ngăn kéo", "level tool for hanging pictures straight",
        "vi:Kìm cắt dây dưới 1000 INR, tay cầm chống trượt",
        "drill bit for masonry walls rather than wood", "Does this extension cable have a grounded plug?",
        "hammer below 1 INR", "Send an electrician to my house right now",
        "set of hex keys in metric sizes for no more than 800 INR"),
    "Pens & Stationery": (
        "spiral ruled notebook", "gel pens pack of ten under 500 INR in blue ink",
        "vi:Sổ ghi chép giấy dày, viết bút mực không lem", "planner for tracking weekly school assignments",
        "vi:Bút chì kim dưới 300 INR, cầm lâu không mỏi",
        "archival ink pen rather than washable marker", "Is this notebook paper acid-free?",
        "eraser below 1 INR", "Grade my handwritten homework automatically",
        "A4 sketchbook with at least 100 pages under 1000 INR"),
    "Cameras & Accessories": (
        "camera lens cleaning kit", "tripod under 3000 INR for a mirrorless camera",
        "vi:Túi máy ảnh nhẹ, có lớp đệm bảo vệ", "memory card for recording long 4K travel videos",
        "vi:Chân máy dưới 2500 INR, gấp ngắn để mang lên máy bay",
        "battery for Canon EOS 200D rather than EOS R", "Does this SD card sustain V30 write speed?",
        "camera strap below 1 INR", "Edit my wedding photos overnight",
        "camera backpack with rain cover under 4000 INR"),
    "Home Improvement": (
        "LED ceiling light", "bathroom tap under 2500 INR in stainless steel",
        "vi:Bóng đèn tiết kiệm điện cho hành lang", "door seal to reduce street noise in a rented flat",
        "vi:Đèn sân vườn dưới 3000 INR, chịu được mưa",
        "wall plug for hollow drywall rather than concrete", "Is this paint rated for outdoor use?",
        "light switch below 1 INR", "Renovate my kitchen for me this weekend",
        "set of four LED bulbs, warm white, under 1200 INR"),
}


def expand(source: Path, out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite dataset version: {out}")
    pilot = read_jsonl(source / "queries.jsonl")
    if len(pilot) != 40 or [q["query_id"] for q in pilot] != [f"Q{i:04d}" for i in range(1, 41)]:
        raise ValueError("Expected the intact 40-query pilot with historical IDs")
    taxonomy = json.loads((ROOT / "data/interim/selected_categories.json").read_text(encoding="utf-8"))
    approved = {row["category"] for row in taxonomy["selected_categories"] if row["selection_status"] == "SELECT"}
    if set(NEW_QUERIES) != approved or any(len(items) != len(TYPES) for items in NEW_QUERIES.values()):
        raise ValueError("Expected ten new intents for each of 16 approved categories")
    rows = list(pilot)
    for category, items in NEW_QUERIES.items():
        for query_type, authored in zip(TYPES, items):
            number = len(rows) + 1
            is_vi = authored.startswith("vi:")
            rows.append({"query_id": f"Q{number:04d}", "raw_query": authored[3:] if is_vi else authored,
                         "language": "vi" if is_vi else "en", "query_type": query_type,
                         "planning_category": category, "intent_group": f"G{number:04d}",
                         "difficulty": "hard" if query_type in {"DIFFICULT_SEMANTIC", "MISSING_ATTRIBUTE", "NO_RESULT", "CLARIFICATION_UNSUPPORTED"} else "standard",
                         "source": "phase13_catalog_domain_authored_draft", "expected_query_understanding": None,
                         "price_boundary_semantics": None, "expected_status": None,
                         "annotation_status": "UNREVIEWED_DRAFT"})
    if len(rows) != 200 or len({q["raw_query"].casefold() for q in rows}) != 200:
        raise ValueError("Expansion must contain 200 distinct query texts")
    out.mkdir(parents=True)
    for name in ("candidate_pools.jsonl", "qrels.csv", "query_annotations.csv", "relevance_annotations.csv", "generation_claims.csv"):
        shutil.copy2(source / name, out / name)
    claim_path = out / "generation_claims.csv"
    with claim_path.open(encoding="utf-8-sig", newline="") as handle:
        claim_fields = next(csv.reader(handle))
    with claim_path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerow(claim_fields + ["provider", "model_version", "prompt_configuration", "product_metadata_json", "source_result_sha256"])
    (out / "queries.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    (out / "splits.json").write_text(json.dumps({"status": "NOT_FROZEN", "development": [], "held_out": [],
        "reason": "Independent annotation, candidate capture and adjudication are pending."}, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads((source / "dataset_manifest.json").read_text(encoding="utf-8"))
    manifest.update({"dataset_version": "phase13-draft-v2", "source_version": manifest["dataset_version"],
        "source_dataset_relpath": str(source.resolve().relative_to(ROOT)).replace("\\", "/"),
        "source_query_sha256": hashlib.sha256((source / "queries.jsonl").read_bytes()).hexdigest(),
        "created_utc": datetime.now(timezone.utc).isoformat(), "query_count": len(rows),
        "category_distribution": dict(sorted(Counter(q["planning_category"] for q in rows).items())),
        "query_type_distribution": dict(sorted(Counter(q["query_type"] for q in rows).items())),
        "language_distribution": dict(sorted(Counter(q["language"] for q in rows).items())),
        "draft_generation_method": "160 category-specific authored queries; type/category are planning metadata",
        "draft_warning": "No interpretations, no-result outcomes, relevance, or generation labels verified",
        "artifact_sha256": {name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in
                            ("queries.jsonl", "candidate_pools.jsonl", "qrels.csv", "query_annotations.csv",
                             "relevance_annotations.csv", "generation_claims.csv")}})
    (out / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = validate(out)
    (out / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        raise ValueError(f"Expanded version has validation errors: {report['errors']}")
    return {"queries": len(rows), "categories": len(manifest["category_distribution"]),
            "query_types": len(manifest["query_type_distribution"]), "language": manifest["language_distribution"],
            "near_duplicates": len(report["statistics"]["near_duplicate_pairs"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "data/evaluation/phase13/v1")
    parser.add_argument("--out", type=Path, default=ROOT / "data/evaluation/phase13/v2")
    args = parser.parse_args()
    print(json.dumps(expand(args.source, args.out)))


if __name__ == "__main__":
    main()
