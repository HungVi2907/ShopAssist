"""Unit tests for Phase 4 dataset cleaning, normalization, specification parsing, and deduplication."""

import json
import pandas as pd
import pytest

from shopassist.data.cleaning import (
    build_brand_canonical_map,
    clean_candidate_dataset,
    clean_price,
    clean_text,
    deduplicate_candidates,
    extract_specs_dict,
    normalize_brand,
    normalize_rating,
    parse_specifications,
    specs_conflict,
)


class TestPriceCleaning:
    """Test suite for price cleaning and validation."""

    def test_valid_numeric_prices(self):
        assert clean_price(199.99) == 199.99
        assert clean_price("499") == 499.0
        assert clean_price("1490.50") == 1490.5

    def test_invalid_prices_rejected(self):
        assert clean_price(None) is None
        assert clean_price(float("nan")) is None
        assert clean_price(0) is None
        assert clean_price(0.0) is None
        assert clean_price(-15.0) is None
        assert clean_price("-99") is None
        assert clean_price("invalid") is None
        assert clean_price("") is None


class TestRatingNormalization:
    """Test suite for rating normalization."""

    def test_valid_ratings(self):
        assert normalize_rating("4.5") == 4.5
        assert normalize_rating("5") == 5.0
        assert normalize_rating(3.2) == 3.2
        assert normalize_rating("1.0") == 1.0

    def test_no_rating_available(self):
        assert normalize_rating("No rating available") is None
        assert normalize_rating("no rating available") is None
        assert normalize_rating(None) is None
        assert normalize_rating("") is None

    def test_fallback_to_overall_rating(self):
        assert normalize_rating("No rating available", "4.2") == 4.2
        assert normalize_rating(None, "3.8") == 3.8
        assert normalize_rating("No rating available", "No rating available") is None

    def test_out_of_range_rejected(self):
        assert normalize_rating("0.5") is None
        assert normalize_rating("5.5") is None
        assert normalize_rating("-1.0") is None


class TestBrandNormalization:
    """Test suite for brand cleaning and canonical casing."""

    def test_whitespace_and_nulls(self):
        assert normalize_brand("  Samsung  ") == "Samsung"
        assert normalize_brand("Apple   Inc  ") == "Apple Inc"
        assert normalize_brand(None) is None
        assert normalize_brand("") is None
        assert normalize_brand("None") is None
        assert normalize_brand("NaN") is None

    def test_canonical_casing_map(self):
        brands = ["D-Link", "D-LINK", "D-Link", "SHOPMANIA", "Shopmania", "SHOPMANIA"]
        canonical_map = build_brand_canonical_map(brands)

        # D-Link should be preferred (more frequent or mixed case)
        assert canonical_map["d-link"] == "D-Link"
        # SHOPMANIA is more frequent
        assert canonical_map["shopmania"] == "SHOPMANIA"

        assert normalize_brand("d-link", canonical_map) == "D-Link"
        assert normalize_brand("D-LINK", canonical_map) == "D-Link"


class TestTextCleaning:
    """Test suite for product_name and description cleaning."""

    def test_whitespace_and_control_chars(self):
        raw = "  Product \t Name \n With \x00 Weird \r\n Spaces  "
        cleaned = clean_text(raw)
        assert cleaned == "Product Name With Weird Spaces"

    def test_html_entities_and_tags(self):
        raw = "Comfortable &amp; stylish &lt;b&gt;cotton&lt;/b&gt; shoes.<br><p>Size 8.</p>"
        cleaned = clean_text(raw)
        assert cleaned == "Comfortable & stylish cotton shoes. Size 8."

    def test_preserves_technical_details(self):
        raw = "Intel Core i7-11800H, 16GB DDR4 RAM, 512GB NVMe SSD, 15.6\" FHD (1920x1080) 144Hz"
        cleaned = clean_text(raw)
        assert "Intel Core i7-11800H" in cleaned
        assert "16GB DDR4 RAM" in cleaned
        assert "15.6\" FHD" in cleaned

    def test_placeholders_mapped_to_none(self):
        assert clean_text("") is None
        assert clean_text("   ") is None
        assert clean_text("None") is None
        assert clean_text("nan") is None
        assert clean_text("null") is None


class TestSpecificationParser:
    """Test suite for safe Ruby hash product specification parsing."""

    def test_valid_ruby_hash(self):
        raw = '{"product_specification"=>[{"key"=>"Color", "value"=>"Black"}, {"key"=>"Ideal For", "value"=>"Men"}]}'
        parsed = parse_specifications(raw)
        assert len(parsed) == 2
        assert parsed[0] == {"key": "Color", "value": "Black"}
        assert parsed[1] == {"key": "Ideal For", "value": "Men"}

    def test_nil_and_empty_specifications(self):
        assert parse_specifications(None) == []
        assert parse_specifications('{"product_specification"=>nil}') == []
        assert parse_specifications('{"product_specification"=>""}') == []
        assert parse_specifications("") == []

    def test_ruby_hash_with_nil_value(self):
        raw = '{"product_specification"=>[{"key"=>"Shade", "value"=>nil}]}'
        parsed = parse_specifications(raw)
        assert len(parsed) == 1
        assert parsed[0] == {"key": "Shade", "value": None}

    def test_escaped_quotes_and_unicode(self):
        raw = r'{"product_specification"=>[{"key"=>"Care Instructions", "value"=>"Do not expose to 100% moisture \"water\""}, {"key"=>"Dimensions", "value"=>"15 × 20 cm"}]}'
        parsed = parse_specifications(raw)
        assert len(parsed) == 2
        assert parsed[0]["value"] == 'Do not expose to 100% moisture "water"'
        assert parsed[1]["value"] == "15 × 20 cm"

    def test_specs_dict_and_conflict(self):
        s1 = {"color": "black", "size": "8"}
        s2 = {"color": "white", "size": "8"}
        s3 = {"color": "black", "size": "8", "material": "leather"}
        s4 = {"material": "leather"}

        assert specs_conflict(s1, s2) is True  # conflicting color
        assert specs_conflict(s1, s3) is False  # compatible attributes
        assert specs_conflict(s1, s4) is False  # no common keys


class TestDeduplication:
    """Test suite demonstrating true duplicates are removed while meaningful variants are preserved."""

    def test_true_duplicate_removed(self):
        # Two records with identical title, brand, category, price, and identical specs
        df = pd.DataFrame(
            [
                {
                    "uniq_id": "id1",
                    "product_name": "FabHomeDecor Double Sofa Bed",
                    "brand": "FabHomeDecor",
                    "category": "Furniture",
                    "discounted_price": 11999.0,
                    "description": "Short description",
                    "product_specifications_parsed": [{"key": "Color", "value": "Black"}, {"key": "Size", "value": "Double"}],
                },
                {
                    "uniq_id": "id2",
                    "product_name": "FabHomeDecor Double Sofa Bed",
                    "brand": "FabHomeDecor",
                    "category": "Furniture",
                    "discounted_price": 11999.0,
                    "description": "Comprehensive long description with care instructions and dimensions",
                    "product_specifications_parsed": [{"key": "Color", "value": "Black"}, {"key": "Size", "value": "Double"}],
                },
            ]
        )

        deduped, metrics = deduplicate_candidates(df)
        assert len(deduped) == 1
        assert metrics["dropped_rows"] == 1
        # Tie-breaker should preserve id2 with longer description
        assert deduped.iloc[0]["uniq_id"] == "id2"

    def test_meaningful_variant_preserved(self):
        # Same product name, brand, category, and price, but DIFFERENT color and size
        df = pd.DataFrame(
            [
                {
                    "uniq_id": "shoe_black_8",
                    "product_name": "Puma Running Shoes",
                    "brand": "Puma",
                    "category": "Footwear",
                    "discounted_price": 1999.0,
                    "description": "Puma lightweight running shoes",
                    "product_specifications_parsed": [{"key": "Color", "value": "Black"}, {"key": "Size", "value": "8"}],
                },
                {
                    "uniq_id": "shoe_red_9",
                    "product_name": "Puma Running Shoes",
                    "brand": "Puma",
                    "category": "Footwear",
                    "discounted_price": 1999.0,
                    "description": "Puma lightweight running shoes",
                    "product_specifications_parsed": [{"key": "Color", "value": "Red"}, {"key": "Size", "value": "9"}],
                },
                {
                    "uniq_id": "case_iphone6",
                    "product_name": "Spigen Rugged Armor Case",
                    "brand": "Spigen",
                    "category": "Mobiles & Accessories",
                    "discounted_price": 899.0,
                    "description": "Durable protective phone case",
                    "product_specifications_parsed": [{"key": "Compatible Model", "value": "Apple iPhone 6"}],
                },
                {
                    "uniq_id": "case_iphone6s",
                    "product_name": "Spigen Rugged Armor Case",
                    "brand": "Spigen",
                    "category": "Mobiles & Accessories",
                    "discounted_price": 899.0,
                    "description": "Durable protective phone case",
                    "product_specifications_parsed": [{"key": "Compatible Model", "value": "Apple iPhone 6s"}],
                },
            ]
        )

        deduped, metrics = deduplicate_candidates(df)
        # All 4 variants should be preserved!
        assert len(deduped) == 4
        assert metrics["dropped_rows"] == 0


class TestCleanCandidateDatasetPipeline:
    """End-to-end cleaning pipeline tests on synthetic fixtures."""

    def test_pipeline_filters_invalid_and_assembles_schema(self):
        raw_df = pd.DataFrame(
            [
                # Valid product
                {
                    "uniq_id": "uid_valid_1",
                    "product_name": "Logitech Wireless Mouse M185",
                    "_level1_category": "Computers",
                    "brand": "logitech",
                    "retail_price": "995.0",
                    "discounted_price": "749.0",
                    "product_rating": "4.3",
                    "overall_rating": "4.3",
                    "description": "Plug and play wireless mouse with 2.4GHz USB nano receiver.",
                    "product_specifications": '{"product_specification"=>[{"key"=>"Color", "value"=>"Grey"}]}',
                    "product_url": "http://www.flipkart.com/mouse/p/123",
                    "pid": "MOU123",
                    "image": '["http://img.com/1.jpg"]',
                    "crawl_timestamp": "2016-01-01",
                    "is_FK_Advantage_product": False,
                },
                # Missing operational price -> should be dropped
                {
                    "uniq_id": "uid_no_price",
                    "product_name": "Unknown Product",
                    "_level1_category": "Computers",
                    "brand": "Generic",
                    "retail_price": None,
                    "discounted_price": None,
                    "product_rating": "No rating available",
                    "overall_rating": "No rating available",
                    "description": "Some description",
                    "product_specifications": None,
                    "product_url": "http://www.flipkart.com/p/456",
                    "pid": "MOU456",
                },
                # Negative price -> should be dropped
                {
                    "uniq_id": "uid_neg_price",
                    "product_name": "Glitch Product",
                    "_level1_category": "Computers",
                    "brand": "Generic",
                    "retail_price": "100",
                    "discounted_price": "-50",
                    "product_rating": "3.0",
                    "overall_rating": "3.0",
                    "description": "Glitch",
                    "product_specifications": None,
                    "product_url": "http://www.flipkart.com/p/789",
                    "pid": "MOU789",
                },
            ]
        )

        cleaned_df, report = clean_candidate_dataset(raw_df, selected_categories=["Computers"])

        assert len(cleaned_df) == 1
        assert report["removed"]["invalid_price"] == 2
        assert cleaned_df.iloc[0]["product_id"] == "uid_valid_1"
        assert cleaned_df.iloc[0]["brand"] == "logitech"
        assert cleaned_df.iloc[0]["discounted_price"] == 749.0
        assert cleaned_df.iloc[0]["rating"] == 4.3
        # Check specifications format is valid JSON string
        specs_json = json.loads(cleaned_df.iloc[0]["product_specifications"])
        assert isinstance(specs_json, list)
        assert specs_json[0]["key"] == "Color"
