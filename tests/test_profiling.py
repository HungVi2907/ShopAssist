"""Unit tests for profiling modules using synthetic mock datasets."""

import pandas as pd
import pytest

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


@pytest.fixture
def mock_df() -> pd.DataFrame:
    """Create a small representative DataFrame for profiling tests."""
    return pd.DataFrame(
        {
            "uniq_id": ["u1", "u2", "u3", "u4"],
            "pid": ["p1", "p2", "p3", "p3"],  # p3 duplicated on purpose
            "product_name": ["Laptop A", "Laptop B", "Laptop A", "Headphones C"],
            "product_category_tree": [
                '["Computers >> Laptops >> Thin Laptops"]',
                '["Computers >> Laptops >> Gaming Laptops"]',
                '["Computers >> Laptops >> Thin Laptops"]',
                '["Audio >> Headphones"]',
            ],
            "retail_price": [1000.0, 1500.0, 1000.0, None],
            "discounted_price": [800.0, 1200.0, 800.0, None],
            "brand": ["Dell", "Asus", "dell", None],  # case variation + null
            "product_rating": ["4.5", "No rating available", "5", None],
            "overall_rating": ["4.5", "No rating available", "5", None],
            "description": [
                "Great lightweight laptop for daily office use.",
                "Powerful gaming laptop with high-refresh display.",
                "Great lightweight laptop for daily office use.",
                None,
            ],
            "product_specifications": [
                '{"product_specification"=>[{"key"=>"RAM", "value"=>"16GB"}]}',
                '{"product_specification"=>[{"key"=>"GPU", "value"=>"RTX 4060"}]}',
                '{"product_specification"=>[{"key"=>"RAM", "value"=>"16GB"}]}',
                None,
            ],
        }
    )


def test_profile_dataset_overview(mock_df: pd.DataFrame):
    overview = profile_dataset_overview(mock_df)
    assert overview["total_rows"] == 4
    assert overview["total_columns"] == 11
    assert "uniq_id" in overview["columns"]
    assert overview["columns"]["uniq_id"]["null_count"] == 0
    assert overview["columns"]["uniq_id"]["unique_count"] == 4


def test_profile_missing_values(mock_df: pd.DataFrame):
    mv = profile_missing_values(mock_df)
    # product_rating has 1 actual null and 1 semantic missing ("No rating available")
    assert mv["product_rating"]["actual_null_count"] == 1
    assert mv["product_rating"]["semantic_missing_count"] == 1
    assert mv["product_rating"]["effective_missing_count"] == 2
    assert mv["product_rating"]["effective_missing_percentage"] == 50.0

    # retail_price has 1 null
    assert mv["retail_price"]["actual_null_count"] == 1
    assert mv["retail_price"]["effective_missing_count"] == 1


def test_profile_identifiers(mock_df: pd.DataFrame):
    ids = profile_identifiers(mock_df)
    assert ids["uniq_id"]["is_unique_primary_key_candidate"] is True
    assert ids["pid"]["is_unique_primary_key_candidate"] is False  # p3 is duplicated
    assert ids["mapping_consistency"]["one_pid_to_multiple_uniq_count"] == 1


def test_profile_duplicates(mock_df: pd.DataFrame):
    dups = profile_duplicates(mock_df)
    assert dups["exact_duplicate_rows"] == 0
    assert dups["duplicate_uniq_id"] == 0
    assert dups["duplicate_pid"] == 1
    assert dups["duplicate_product_name"] == 1  # "Laptop A" appears twice


def test_profile_prices(mock_df: pd.DataFrame):
    prices = profile_prices(mock_df)
    assert prices["discounted_price"]["count"] == 3
    assert prices["discounted_price"]["min"] == 800.0
    assert prices["discounted_price"]["max"] == 1200.0
    assert prices["anomalies_and_comparisons"]["discount_exceeds_retail_count"] == 0
    assert prices["anomalies_and_comparisons"]["both_prices_missing_count"] == 1


def test_profile_ratings(mock_df: pd.DataFrame):
    ratings = profile_ratings(mock_df)
    pr = ratings["product_rating"]
    assert pr["numeric_rating_count"] == 2  # 4.5 and 5
    assert pr["no_rating_available_count"] == 1
    assert pr["actual_null_count"] == 1
    assert pr["numeric_stats"]["min"] == 4.5
    assert pr["numeric_stats"]["max"] == 5.0

    # Relationship between product_rating and overall_rating
    rel = ratings["relationship"]
    assert rel["exact_raw_string_match_count"] == 4
    assert rel["raw_string_mismatch_count"] == 0


def test_profile_brands(mock_df: pd.DataFrame):
    brands = profile_brands(mock_df)
    assert brands["missing_count"] == 1
    assert brands["unique_brand_count_raw"] == 3  # Dell, Asus, dell
    assert brands["unique_brand_count_normalized"] == 2  # dell, asus
    assert brands["case_variation_redundancy"] == 1


def test_profile_descriptions(mock_df: pd.DataFrame):
    desc = profile_descriptions(mock_df)
    assert desc["missing_count"] == 1
    assert desc["valid_text_count"] == 3
    assert desc["character_length_stats"]["min"] > 0
    assert desc["word_count_stats"]["median"] > 0


def test_profile_specifications(mock_df: pd.DataFrame):
    specs = profile_specifications(mock_df)
    assert specs["missing_count"] == 1
    assert specs["format_structure"]["ruby_arrow_syntax_count"] == 3
    assert specs["sample_parsing_audit"]["parseable_records_in_sample"] == 3


def test_profile_categories(mock_df: pd.DataFrame):
    cats = profile_categories(mock_df)
    assert cats["total_rows"] == 4
    assert cats["unique_level_1_count"] == 2  # Computers and Audio
    assert cats["depth_statistics"]["max_depth"] == 3


def test_profile_category_suitability(mock_df: pd.DataFrame):
    # Computers has 3 products, Audio has 1 product
    suitability = profile_category_suitability(mock_df, min_products=2)
    assert len(suitability) == 1
    comp_row = suitability[0]
    assert comp_row["discounted_price_coverage_pct"] == 100.0
    assert comp_row["retail_price_coverage_pct"] == 100.0


def test_profile_retrieval_readiness(mock_df: pd.DataFrame):
    rr = profile_retrieval_readiness(mock_df)
    assert rr["with_product_name_count"] == 4
    assert rr["with_description_count"] == 3
    assert rr["with_specifications_count"] == 3
    assert rr["with_all_three_count"] == 3
    assert rr["with_all_three_pct"] == 75.0
