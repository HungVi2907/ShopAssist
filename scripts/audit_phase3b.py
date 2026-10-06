"""Verify Phase 3B candidates and add an evidence-based coverage summary."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim"
PROFILE = INTERIM / "home_kitchen_full_profile.json"
CANDIDATES = INTERIM / "home_kitchen_candidates.jsonl"
SUMMARY = INTERIM / "home_kitchen_full_profile.md"


def main() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    if not profile.get("scan_complete"):
        raise RuntimeError("Full scan is not complete")
    counts: dict[str, Counter] = defaultdict(Counter)
    examples: dict[str, list[dict]] = defaultdict(list)
    asins = set()
    lines = 0
    ambiguous = 0
    with CANDIDATES.open(encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            lines += 1
            asin = item.get("parent_asin")
            if asin:
                asins.add(asin)
            ambiguous += bool(item.get("ambiguous_family"))
            no_flags = not (
                item.get("possible_accessory") or item.get("possible_manual_product")
                or item.get("possible_stovetop_kettle")
            )
            for family in item["candidate_families"]:
                value = counts[family]
                value["candidate_records"] += 1
                if no_flags:
                    value["no_obvious_exclusion_flags"] += 1
                if no_flags and not item.get("ambiguous_family"):
                    value["no_flags_single_family"] += 1
                    if item.get("price") is not None:
                        value["no_flags_single_family_with_price"] += 1
                if item["match_details"][family]["matched_by"] == ["taxonomy"]:
                    value["taxonomy_only"] += 1
                    if len(examples[family]) < 5:
                        examples[family].append({
                            "parent_asin": asin, "title": item.get("title"),
                            "categories": item.get("categories"),
                        })
    if lines != profile["total_candidates"] or len(asins) != profile["unique_parent_asin"]:
        raise ValueError("Candidate JSONL does not match the full scan profile")
    for family, value in counts.items():
        if value["candidate_records"] != profile["families"][family]["raw_candidates"]:
            raise ValueError(f"Family count mismatch: {family}")

    profile["candidate_audit"] = {
        "jsonl_lines_verified": lines,
        "unique_parent_asin_verified": len(asins),
        "ambiguous_candidate_records": ambiguous,
        "families": {family: dict(counts[family]) for family in profile["families"]},
        "taxonomy_only_examples": examples,
        "note": "No-flag counts are heuristic upper bounds, not clean product counts.",
    }
    PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows = []
    for family, stats in profile["families"].items():
        audit = counts[family]
        rows.append(
            f"| {family} | {stats['raw_candidates']:,} | {stats['unique_parent_asin']:,} | "
            f"{stats['possible_accessories']:,} | {stats['possible_manual_products']:,} | "
            f"{stats['possible_stovetop_kettles']:,} | {stats['ambiguous_family']:,} | "
            f"{stats['has_price_rate']:.1%} | {stats['has_features_rate']:.1%} | "
            f"{stats['has_description_rate']:.1%} | {stats['has_details_rate']:.1%} | "
            f"{stats['has_categories_rate']:.1%} | {audit['no_flags_single_family']:,} | "
            f"{audit['no_flags_single_family_with_price']:,} |"
        )
    no_flags_total = sum(value["no_flags_single_family"] for value in counts.values())
    no_flags_price_total = sum(value["no_flags_single_family_with_price"] for value in counts.values())
    text = "\n".join([
        "# Phase 3B — Full Home_and_Kitchen metadata scan", "",
        f"Nguồn JSONL đã quét hết **{profile['source_size_bytes']:,} byte** bằng HTTP range có kiểm tra `Content-Range`.",
        "Nguồn được ghim theo commit và kích thước tệp; SHA-256 công bố của toàn tệp chưa được đối chiếu vì tệp 11,8 GB không được lưu cục bộ.",
        f"**{profile['total_records_scanned']:,}** dòng được quét; **{profile['valid_records']:,}** bản ghi hợp lệ; **{lines:,}** candidate JSONL; **{len(asins):,}** candidate ASIN duy nhất.",
        f"Nguồn có **{profile['duplicate_parent_asin_count']:,}** ASIN trùng, **{profile['invalid_records']:,}** bản ghi lỗi, **{profile['parse_errors']:,}** lỗi parse và **{profile['network_errors']:,}** lần tải range thất bại đã được thử lại hoặc khôi phục.",
        "", "| Family | Candidate | Unique ASIN | Accessory flag | Manual flag | Stovetop flag | Ambiguous | Price | Features | Description | Details | Categories | Không cờ, 1 family | Có giá trong nhóm đó |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *rows,
        "", "## Potential issues", "",
        f"- **{ambiguous:,}** candidate match hơn một family; `candidate_family` được đặt `null` và toàn bộ match nằm trong `candidate_families`.",
        "- Với candidate nhiều family, mỗi family đều được tính vào bảng; vì vậy cờ `manual` hoặc `stovetop` có thể xuất hiện ở family khác khi cùng một record match cả hai.",
        "- Cờ phụ kiện rất thường gặp, đặc biệt ở coffee maker và air fryer. Từ như `cup`, `basket`, `filter` cũng có thể nằm trong title của máy hoàn chỉnh, nên cờ này chỉ dùng để audit.",
        "- Coffee maker gồm French press, Moka pot và pour-over; cần quyết định phạm vi máy chạy điện trước khi làm sạch.",
        "- Kettle được bắt rộng theo từ `kettle`, nên gồm cả ấm stovetop và whistling; cần xác nhận tín hiệu chạy điện trong Phase 4.",
        "- `taxonomy_only` có thể chứa sản phẩm gắn sai category; cần lấy mẫu kiểm tra, nhất là các đường dẫn không có từ khóa trong title.",
        "- Quét nguồn là đầy đủ, nhưng recall của candidate vẫn phụ thuộc bộ từ khóa; tên như `Airfryer` viết liền hoặc tên thương mại không có từ chỉ family có thể bị sót nếu taxonomy cũng thiếu/sai.",
        "- `rice_cooker` có ít candidate nhất; giá chỉ hiện diện trong một phần ba candidate của nhóm.",
        "", "## Recommendation for Phase 4", "",
        f"Có **{no_flags_total:,}** candidate một family không mang ba cờ loại trừ rõ ràng; **{no_flags_price_total:,}** trong số đó có giá. Đây là chỉ báo quy mô để lập kế hoạch, **không phải số sản phẩm sạch**: cờ có thể báo sai và còn sản phẩm nhiễu trong taxonomy.",
        "Ưu tiên audit mẫu theo từng family và nguồn match (`title_only`, `taxonomy_only`, `both`), sau đó viết quy tắc loại phụ kiện, đồ pha cà phê thủ công và ấm stovetop. Đo lại phân bố family và tỷ lệ có giá sau cleaning. Chỉ 4.181 candidate một family không cờ có giá, thấp hơn mốc 5.000; nếu giá là điều kiện bắt buộc của dataset, cần chiến lược bổ sung hoặc chấp nhận tập nhỏ hơn. Nguồn Home_and_Kitchen có đủ candidate để tiếp tục; chưa có bằng chứng cần bổ sung Appliances ở bước này. Chỉ có thể xác nhận mục tiêu 5.000–15.000 sản phẩm sau Phase 4.",
        "", "Phase này không tải review, tạo embedding, dùng LLM, hay làm final cleaning.", "",
    ])
    SUMMARY.write_text(text, encoding="utf-8")
    print(f"Verified {lines:,} candidate lines and {len(asins):,} unique ASINs")
    print(f"No-flag single-family candidates: {no_flags_total:,}; with price: {no_flags_price_total:,}")


if __name__ == "__main__":
    main()
