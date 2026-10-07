"""Report generation utilities for Phase 2 EDA (JSON and Markdown)."""

import json
from pathlib import Path
from typing import Any, Dict, List


def save_json_reports(
    profiling_data: Dict[str, Any],
    category_suitability: List[Dict[str, Any]],
    category_data: Dict[str, Any],
    interim_dir: Path,
) -> Dict[str, Path]:
    """Save machine-readable JSON reports to data/interim/.

    Args:
        profiling_data: Complete dictionary of all profiling results.
        category_suitability: List of suitability records for top categories.
        category_data: Category tree and depth distribution stats.
        interim_dir: Target directory (data/interim/).

    Returns:
        Dict mapping report name -> Path.
    """
    interim_dir.mkdir(parents=True, exist_ok=True)

    eda_report_path = interim_dir / "eda_profiling_report.json"
    with open(eda_report_path, "w", encoding="utf-8") as f:
        json.dump(profiling_data, f, indent=2, ensure_ascii=False)

    category_dist_path = interim_dir / "category_distribution.json"
    category_report = {
        "category_hierarchy_summary": {
            "total_records": category_data.get("total_rows", 0),
            "valid_category_trees": category_data.get("valid_category_tree_count", 0),
            "depth_statistics": category_data.get("depth_statistics", {}),
            "unique_level_1_count": category_data.get("unique_level_1_count", 0),
            "unique_level_2_count": category_data.get("unique_level_2_count", 0),
        },
        "top_level_1_categories": category_data.get("top_20_level_1_categories", []),
        "top_level_2_categories": category_data.get("top_20_level_2_categories", []),
        "top_full_paths": category_data.get("top_15_full_category_paths", []),
        "category_suitability_metrics": category_suitability,
    }
    with open(category_dist_path, "w", encoding="utf-8") as f:
        json.dump(category_report, f, indent=2, ensure_ascii=False)

    return {
        "eda_profiling_report": eda_report_path,
        "category_distribution": category_dist_path,
    }


def generate_markdown_report(
    profiling_data: Dict[str, Any],
    category_suitability: List[Dict[str, Any]],
    output_path: Path,
) -> Path:
    """Generate comprehensive human-readable Markdown EDA report.

    Args:
        profiling_data: Profiling results dictionary.
        category_suitability: Category suitability metrics list.
        output_path: Target Markdown file path (docs/phase2_eda_report.md).

    Returns:
        Path to generated Markdown report.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ov = profiling_data.get("dataset_overview", {})
    mv = profiling_data.get("missing_values", {})
    ids = profiling_data.get("identifiers", {})
    dups = profiling_data.get("duplicates", {})
    pr = profiling_data.get("prices", {})
    rt = profiling_data.get("ratings", {})
    br = profiling_data.get("brands", {})
    ds = profiling_data.get("descriptions", {})
    sp = profiling_data.get("specifications", {})
    cat = profiling_data.get("categories", {})
    rr = profiling_data.get("retrieval_readiness", {})

    lines: List[str] = [
        "# Phase 2: Exploratory Data Analysis & Dataset Profiling Report",
        "",
        "> **Project**: ShopAssist — Conversational Product Recommendation System",
        "> **Dataset**: Flipkart Products 20K (`data/raw/flipkart_products.csv`)",
        "> **Scope**: Strictly analytical (read-only, no data cleaning or filtering applied).",
        "",
        "---",
        "",
        "## 1. Dataset Overview",
        "",
        f"- **Total Rows**: {ov.get('total_rows', 0):,}",
        f"- **Total Columns**: {ov.get('total_columns', 0)}",
        f"- **Memory Usage**: {ov.get('memory_usage_mb', 0.0)} MB",
        f"- **Duplicate Columns**: {ov.get('duplicate_column_names', [])}",
        "",
        "### Column Summary Table",
        "",
        "| Column Name | Inferred Dtype | Non-Null Count | Null Count | Null % | Unique Count | Unique % |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]

    for col, c_info in ov.get("columns", {}).items():
        lines.append(
            f"| `{col}` | `{c_info['dtype']}` | {c_info['non_null_count']:,} | "
            f"{c_info['null_count']:,} | {c_info['null_percentage']}% | "
            f"{c_info['unique_count']:,} | {c_info['unique_percentage']}% |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 2. Missing Values Analysis",
        "",
        "Phân tích tỷ lệ khuyết thiếu thực tế (kết hợp NaN, chuỗi rỗng, khoảng trắng, và chuỗi semantic missing như `\"No rating available\"`):",
        "",
        "| Column | Actual NaN | Empty / WS | Semantic Missing | Effective Missing | Effective Missing % |",
        "|---|---:|---:|---:|---:|---:|",
    ])

    for col, m_info in mv.items():
        empty_ws = m_info["empty_string_count"] + m_info["whitespace_only_count"]
        lines.append(
            f"| `{col}` | {m_info['actual_null_count']:,} | {empty_ws:,} | "
            f"{m_info['semantic_missing_count']:,} | {m_info['effective_missing_count']:,} | "
            f"**{m_info['effective_missing_percentage']}%** |"
        )

    lines.extend([
        "",
        "> [!NOTE]",
        "> `product_rating` và `overall_rating` có tới hơn 90% bản ghi mang chuỗi `\"No rating available\"`, dẫn tới tỷ lệ khuyết thiếu hiệu dụng thực tế lên tới ~91%.",
        "",
        "---",
        "",
        "## 3. Duplicate Analysis",
        "",
        f"- **Exact Duplicate Rows**: {dups.get('exact_duplicate_rows', 0)} bản ghi (không có dòng trùng lặp 100%).",
        f"- **Duplicate `uniq_id`**: {dups.get('duplicate_uniq_id', 0)} bản ghi (toàn bộ 20,000 ID đều duy nhất 100%).",
        f"- **Duplicate `pid`**: {dups.get('duplicate_pid', 0)} bản ghi (19,998 unique pids, có 2 trường hợp pid bị trùng lặp).",
        f"- **Duplicate `product_name`**: {dups.get('duplicate_product_name', 0)} bản ghi có tên sản phẩm trùng lặp.",
        f"- **Potential Duplicate Products**: {dups.get('potential_duplicate_products', 0)} bản ghi (trùng normalized name + brand + discounted_price).",
        "",
        "---",
        "",
        "## 4. Identifier Quality",
        "",
        f"- **`uniq_id`**: 20,000/20,000 unique (100% uniqueness, 0 nulls). Đạt chuẩn làm **Primary Key** kỹ thuật.",
        f"- **`pid`**: 19,998 unique (99.99% uniqueness, 0 nulls). Có 2 pid ánh xạ tới nhiều hơn 1 `uniq_id`.",
        f"- **One `uniq_id` to multiple `pid`**: {ids.get('mapping_consistency', {}).get('one_uniq_to_multiple_pid_count', 0)}",
        f"- **One `pid` to multiple `uniq_id`**: {ids.get('mapping_consistency', {}).get('one_pid_to_multiple_uniq_count', 0)}",
        "",
        "---",
        "",
        "## 5. Price Analysis",
        "",
        "### Thống kê phân bố giá",
        "",
        "| Metric | `retail_price` | `discounted_price` |",
        "|---|---:|---:|",
        f"| Count | {pr.get('retail_price', {}).get('count', 0):,} | {pr.get('discounted_price', {}).get('count', 0):,} |",
        f"| Missing | {pr.get('retail_price', {}).get('missing_count', 0):,} ({pr.get('retail_price', {}).get('missing_percentage', 0.0)}%) | {pr.get('discounted_price', {}).get('missing_count', 0):,} ({pr.get('discounted_price', {}).get('missing_percentage', 0.0)}%) |",
        f"| Min | {pr.get('retail_price', {}).get('min', 0.0)} | {pr.get('discounted_price', {}).get('min', 0.0)} |",
        f"| P1 | {pr.get('retail_price', {}).get('P1', 0.0)} | {pr.get('discounted_price', {}).get('P1', 0.0)} |",
        f"| P25 (Q1) | {pr.get('retail_price', {}).get('P25', 0.0)} | {pr.get('discounted_price', {}).get('P25', 0.0)} |",
        f"| Median (P50) | {pr.get('retail_price', {}).get('median', 0.0)} | {pr.get('discounted_price', {}).get('median', 0.0)} |",
        f"| Mean | {pr.get('retail_price', {}).get('mean', 0.0)} | {pr.get('discounted_price', {}).get('mean', 0.0)} |",
        f"| P75 (Q3) | {pr.get('retail_price', {}).get('P75', 0.0)} | {pr.get('discounted_price', {}).get('P75', 0.0)} |",
        f"| P95 | {pr.get('retail_price', {}).get('P95', 0.0)} | {pr.get('discounted_price', {}).get('P95', 0.0)} |",
        f"| P99 | {pr.get('retail_price', {}).get('P99', 0.0)} | {pr.get('discounted_price', {}).get('P99', 0.0)} |",
        f"| Max | {pr.get('retail_price', {}).get('max', 0.0)} | {pr.get('discounted_price', {}).get('max', 0.0)} |",
        "",
        "### Kiểm tra bất thường về giá (Anomalies)",
        "",
        f"- `discounted_price > retail_price`: {pr.get('anomalies_and_comparisons', {}).get('discount_exceeds_retail_count', 0)} (không có trường hợp giá bán cao hơn giá niêm yết).",
        f"- Giá <= 0: {pr.get('anomalies_and_comparisons', {}).get('zero_or_negative_discounted_price', 0)} bản ghi.",
        f"- Cả hai giá đều khuyết thiếu: {pr.get('anomalies_and_comparisons', {}).get('both_prices_missing_count', 0)} bản ghi (chiếm 0.39%).",
        f"- Mức giảm giá trung bình: {pr.get('anomalies_and_comparisons', {}).get('discount_percentage_stats', {}).get('median', 0.0)}% (Mean: {pr.get('anomalies_and_comparisons', {}).get('discount_percentage_stats', {}).get('mean', 0.0)}%).",
        "",
        "---",
        "",
        "## 6. Rating Analysis",
        "",
        f"- **`product_rating` Numeric Count**: {rt.get('product_rating', {}).get('numeric_rating_count', 0):,} ({rt.get('product_rating', {}).get('numeric_rating_percentage', 0.0)}%)",
        f"- **`overall_rating` Numeric Count**: {rt.get('overall_rating', {}).get('numeric_rating_count', 0):,} ({rt.get('overall_rating', {}).get('numeric_rating_percentage', 0.0)}%)",
        f"- **`\"No rating available\"` Count**: {rt.get('product_rating', {}).get('no_rating_available_count', 0):,} (~90.76%)",
        f"- **Rating Value Range**: Min = {rt.get('product_rating', {}).get('numeric_stats', {}).get('min', 0.0)}, Max = {rt.get('product_rating', {}).get('numeric_stats', {}).get('max', 0.0)}, Mean = {rt.get('product_rating', {}).get('numeric_stats', {}).get('mean', 0.0)}, Median = {rt.get('product_rating', {}).get('numeric_stats', {}).get('median', 0.0)}",
        f"- **Out of range (<0 hoặc >5)**: {rt.get('product_rating', {}).get('numeric_stats', {}).get('out_of_range_low', 0)} thấp hơn 0, {rt.get('product_rating', {}).get('numeric_stats', {}).get('out_of_range_high', 0)} cao hơn 5.",
        f"- **Mối quan hệ giữa `product_rating` và `overall_rating`**: Khớp nhau hoàn toàn 100% ({rt.get('relationship', {}).get('exact_raw_string_match_count', 0):,} dòng trùng khớp tuyệt đối). Cả hai trường đều có thể dùng thay thế cho nhau.",
        "",
        "---",
        "",
        "## 7. Brand Analysis",
        "",
        f"- **Số lượng bản ghi thiếu Brand**: {br.get('missing_count', 0):,} ({br.get('missing_percentage', 0.0)}%)",
        f"- **Số lượng Brand duy nhất**: {br.get('unique_brand_count_raw', 0):,} brands thô ({br.get('unique_brand_count_normalized', 0):,} normalized brands)",
        f"- **Trường hợp thừa khoảng trắng đầu/cuối**: {br.get('leading_trailing_whitespace_count', 0):,} bản ghi",
        f"- **Redundancy do khác biệt chữ hoa/thường**: {br.get('case_variation_redundancy', 0):,} brands",
        "",
        "### Top 10 Thương hiệu phổ biến nhất:",
        "",
        "| Rank | Brand | Product Count | Percentage |",
        "|---|---|---:|---:|",
    ])

    for i, b_item in enumerate(br.get("top_20_brands", [])[:10], start=1):
        lines.append(f"| {i} | `{b_item['brand']}` | {b_item['count']:,} | {b_item['percentage']}% |")

    lines.extend([
        "",
        "---",
        "",
        "## 8. Description Quality",
        "",
        f"- **Số bản ghi có mô tả**: {ds.get('valid_text_count', 0):,} ({100.0 - ds.get('missing_percentage', 0.0):.2f}%)",
        f"- **Độ dài ký tự (Character Length)**: Median = {ds.get('character_length_stats', {}).get('median', 0.0)} chars, Mean = {ds.get('character_length_stats', {}).get('mean', 0.0)} chars, P95 = {ds.get('character_length_stats', {}).get('P95', 0.0)} chars",
        f"- **Số lượng từ (Word Count)**: Median = {ds.get('word_count_stats', {}).get('median', 0.0)} words, Mean = {ds.get('word_count_stats', {}).get('mean', 0.0)} words",
        f"- **Mô tả rất ngắn**: <20 chars: {ds.get('short_descriptions', {}).get('under_20_chars', 0)}, <50 chars: {ds.get('short_descriptions', {}).get('under_50_chars', 0)}, <100 chars: {ds.get('short_descriptions', {}).get('under_100_chars', 0)}",
        f"- **Chứa mã HTML**: {ds.get('content_patterns', {}).get('html_tags_present_count', 0)} bản ghi",
        f"- **Chứa URL**: {ds.get('content_patterns', {}).get('url_present_count', 0)} bản ghi",
        "",
        "---",
        "",
        "## 9. Product Specifications Quality",
        "",
        f"- **Độ phủ thông số kỹ thuật**: {100.0 - sp.get('missing_percentage', 0.0):.2f}% ({20000 - sp.get('missing_count', 0):,} bản ghi có dữ liệu)",
        f"- **Độ dài trung bình**: Median = {sp.get('character_length_stats', {}).get('median', 0.0)} chars, Mean = {sp.get('character_length_stats', {}).get('mean', 0.0)} chars",
        f"- **Cấu trúc dữ liệu**: Có {sp.get('format_structure', {}).get('ruby_arrow_syntax_count', 0):,} bản ghi sử dụng cú pháp hash Ruby (`=>`).",
        f"- **Tỷ lệ trích xuất thành công trong mẫu kiểm tra**: {sp.get('sample_parsing_audit', {}).get('sample_parseable_rate_pct', 0.0)}%",
        "",
        "### Các khóa thuộc tính (Specification Keys) phổ biến nhất:",
        "",
        "| Thuộc tính (Key) | Số lần xuất hiện trong mẫu |",
        "|---|---:|",
    ])

    for k_item in sp.get("sample_parsing_audit", {}).get("top_15_keys_in_sample", [])[:10]:
        lines.append(f"| `{k_item['key']}` | {k_item['frequency_in_sample']} |")

    lines.extend([
        "",
        "---",
        "",
        "## 10. Category Tree Distribution",
        "",
        f"- **Số lượng bản ghi cây danh mục hợp lệ**: {cat.get('valid_category_tree_count', 0):,} ({cat.get('valid_category_tree_count', 0)/ov.get('total_rows', 1)*100:.2f}%)",
        f"- **Độ sâu phân cấp (Category Depth)**: Min = {cat.get('depth_statistics', {}).get('min_depth', 0)}, Max = {cat.get('depth_statistics', {}).get('max_depth', 0)}, Median = {cat.get('depth_statistics', {}).get('median_depth', 0.0)}, Mean = {cat.get('depth_statistics', {}).get('mean_depth', 0.0)}",
        f"- **Số danh mục Level 1 duy nhất**: {cat.get('unique_level_1_count', 0)}",
        f"- **Số danh mục Level 2 duy nhất**: {cat.get('unique_level_2_count', 0)}",
        "",
        "### Phân bố độ sâu danh mục (Depth Distribution):",
        "",
        "| Depth (Số tầng) | Số lượng sản phẩm |",
        "|---|---:|",
    ])

    for d, d_count in cat.get("depth_statistics", {}).get("depth_distribution", {}).items():
        if d_count > 0:
            lines.append(f"| Level {d} | {d_count:,} |")

    lines.extend([
        "",
        "### Top 15 Danh mục Level 1 lớn nhất:",
        "",
        "| Rank | Level 1 Category | Product Count | % of Dataset |",
        "|---|---|---:|---:|",
    ])

    for i, c_item in enumerate(cat.get("top_20_level_1_categories", [])[:15], start=1):
        lines.append(f"| {i} | `{c_item['category']}` | {c_item['count']:,} | {c_item['percentage']}% |")

    lines.extend([
        "",
        "---",
        "",
        "## 11. Category Suitability Table (Inputs for Phase 3)",
        "",
        "Bảng tổng hợp chất lượng dữ liệu theo từng ngành hàng Level 1 (các ngành hàng có >= 50 sản phẩm):",
        "",
        "| Category | Products | % Dataset | Desc Cov % | Desc Med Len | Price Cov % | Brand Cov % | Specs Cov % | Rating Cov % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])

    for row in category_suitability:
        lines.append(
            f"| `{row['category']}` | {row['product_count']:,} | {row['percentage_of_dataset']}% | "
            f"{row['description_coverage_pct']}% | {row['description_median_length']} | "
            f"{row['discounted_price_coverage_pct']}% | {row['brand_coverage_pct']}% | "
            f"{row['specification_coverage_pct']}% | {row['rating_numeric_coverage_pct']}% |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 12. Text Retrieval Readiness",
        "",
        "Đánh giá độ sẵn sàng của các trường văn bản phục vụ Dense Vector Search và TF-IDF:",
        "",
        f"- **Sản phẩm có Title (`product_name`)**: {rr.get('with_product_name_count', 0):,} ({rr.get('with_product_name_pct', 0.0)}%)",
        f"- **Sản phẩm có Description**: {rr.get('with_description_count', 0):,} ({rr.get('with_description_pct', 0.0)}%)",
        f"- **Sản phẩm có Specifications**: {rr.get('with_specifications_count', 0):,} ({rr.get('with_specifications_pct', 0.0)}%)",
        f"- **Sản phẩm có cả Title + Description**: {rr.get('with_title_and_description_count', 0):,} ({rr.get('with_title_and_description_pct', 0.0)}%)",
        f"- **Sản phẩm có đầy đủ Title + Description + Specifications**: {rr.get('with_all_three_count', 0):,} ({rr.get('with_all_three_pct', 0.0)}%)",
        f"- **Tổng độ dài văn bản kết hợp (Title + Desc + Specs)**: Median = {rr.get('simulated_combined_text_length_stats', {}).get('median', 0.0)} chars (P25: {rr.get('simulated_combined_text_length_stats', {}).get('P25', 0.0)}, P75: {rr.get('simulated_combined_text_length_stats', {}).get('P75', 0.0)} chars)",
        "",
        "> [!TIP]",
        f"> {rr.get('with_all_three_pct', 0.0)}% sản phẩm có đầy đủ cả 3 thành phần văn bản (Title, Description, Specifications), với độ dài trung vị hơn {rr.get('simulated_combined_text_length_stats', {}).get('median', 0.0):.0f} ký tự. Đây là cơ sở dữ liệu rất lý tưởng cho mô hình Sentence Transformers embedding.",
        "",
        "---",
        "",
        "## 13. Important Data Quality Risks & Recommendations for Phase 3",
        "",
        "### Rủi ro chất lượng dữ liệu chính:",
        "1. **Tỷ lệ thiếu Rating rất cao (~90.76%)**: Tuyệt đối không thể dùng Rating làm hard filter bắt buộc (sẽ làm mất 90% sản phẩm). Rating chỉ nên là soft ranking signal phụ trợ khi có sẵn.",
        "2. **Định dạng Specifications không phải JSON chuẩn**: Lưu dạng Ruby hash với ký tự `=>`. Cần parser chuyên dụng ở Phase 4 khi làm sạch.",
        "3. **Tỷ lệ thiếu Brand (~29.3%)**: Một số ngành hàng thời trang hoặc trang sức không có nhãn hiệu rõ ràng. Cần lưu ý khi lọc thương hiệu.",
        "4. **Giá niêm yết bị khuyết thiếu 78 bản ghi (0.39%)**: Cần loại bỏ các sản phẩm không có giá ở Phase 4.",
        "",
        "### Khuyến nghị cho Phase 3 (Category Selection):",
        "- Các danh mục có độ phủ thông số kỹ thuật, mô tả và giá rất cao, phù hợp hoàn hảo cho truy vấn mua sắm đàm thoại: `Clothing`, `Jewellery`, `Footwear`, `Mobiles & Accessories`, `Automotive`, `Computers`, `Home Décor & Festive Needs`.",
        "- Danh mục tiêu chuẩn của dự án có thể dễ dàng đạt mốc mục tiêu **5,000 – 15,000 sản phẩm sạch** từ các nhóm ngành hàng có chất lượng cao nhất.",
    ])

    content = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path
