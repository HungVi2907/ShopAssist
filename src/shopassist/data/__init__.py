"""Data loading, validation, profiling, reporting, and category selection module."""

from shopassist.data.category_parser import (
    extract_category_level,
    get_category_depth,
    parse_category_tree,
)
from shopassist.data.category_selection import (
    CATEGORY_EVALUATION_SPECS,
    evaluate_categories,
    extract_selected_candidates,
    get_selected_category_names,
)
from shopassist.data.cleaning import (
    build_brand_canonical_map,
    clean_candidate_dataset,
    clean_price,
    clean_text,
    deduplicate_candidates,
    normalize_brand,
    normalize_rating,
    parse_specifications,
    specs_conflict,
)
from shopassist.data.loader import load_raw_dataset
from shopassist.data.schema import (
    CleanedCandidateRecord,
    ProductKnowledgeBaseRecord,
    SpecificationItem,
    save_schema_readiness_report,
    validate_cleaned_dataset_readiness,
)
from shopassist.data.profiling import (
    profile_brands,
    profile_categories,
    profile_category_suitability,
    profile_dataset_overview,
    profile_descriptions,
    profile_duplicates,
    profile_identifiers,
    profile_missing_values,
    profile_prices,
    profile_ratings,
    profile_retrieval_readiness,
    profile_specifications,
)
from shopassist.data.reporting import (
    generate_markdown_report,
    save_json_reports,
)
from shopassist.data.retrieval_text import (
    DEFAULT_MAX_DESCRIPTION_CHARS,
    audit_retrieval_text_dataset,
    build_dataset_retrieval_texts,
    build_retrieval_text,
    format_specifications,
    truncate_description,
    validate_retrieval_text,
)
from shopassist.data.validation import (
    check_candidate_fields,
    check_duplicate_columns,
    inspect_raw_schema,
    validate_dataframe,
    validate_raw_file,
)

__all__ = [

    "load_raw_dataset",
    "validate_raw_file",
    "validate_dataframe",
    "check_duplicate_columns",
    "check_candidate_fields",
    "inspect_raw_schema",
    "parse_category_tree",
    "get_category_depth",
    "extract_category_level",
    "profile_dataset_overview",
    "profile_missing_values",
    "profile_identifiers",
    "profile_duplicates",
    "profile_prices",
    "profile_ratings",
    "profile_brands",
    "profile_descriptions",
    "profile_specifications",
    "profile_categories",
    "profile_category_suitability",
    "profile_retrieval_readiness",
    "save_json_reports",
    "generate_markdown_report",
    "CATEGORY_EVALUATION_SPECS",
    "evaluate_categories",
    "extract_selected_candidates",
    "get_selected_category_names",
    "clean_price",
    "normalize_rating",
    "build_brand_canonical_map",
    "normalize_brand",
    "clean_text",
    "parse_specifications",
    "extract_specs_dict",
    "specs_conflict",
    "deduplicate_candidates",
    "clean_candidate_dataset",
    "SpecificationItem",
    "CleanedCandidateRecord",
    "ProductKnowledgeBaseRecord",
    "validate_cleaned_dataset_readiness",
    "save_schema_readiness_report",
    "DEFAULT_MAX_DESCRIPTION_CHARS",
    "format_specifications",
    "truncate_description",
    "build_retrieval_text",
    "validate_retrieval_text",
    "build_dataset_retrieval_texts",
    "audit_retrieval_text_dataset",
]
