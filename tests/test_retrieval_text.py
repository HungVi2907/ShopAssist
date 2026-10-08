"""Unit and integration tests for Phase 5.2 retrieval_text construction and validation."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from shopassist.data.retrieval_text import (
    DEFAULT_MAX_DESCRIPTION_CHARS,
    audit_retrieval_text_dataset,
    build_dataset_retrieval_texts,
    build_retrieval_text,
    clean_whitespace,
    format_specifications,
    is_placeholder,
    truncate_description,
    validate_retrieval_text,
)


@pytest.fixture
def sample_product_full() -> dict[str, Any]:
    """A complete product dictionary with all fields populated."""
    return {
        "product_id": "prod_001",
        "product_name": "Logitech K380 Multi-Device Bluetooth Keyboard",
        "category": "Computers",
        "brand": "Logitech",
        "retail_price": Decimal("2995.00"),
        "discounted_price": Decimal("2495.00"),
        "rating": 4.5,
        "description": "Compact and lightweight multi-device Bluetooth keyboard for computers, phones, and tablets.",
        "product_specifications": json.dumps([
            {"key": "Type", "value": "Wireless Keyboard"},
            {"key": "Connectivity", "value": "Bluetooth 3.0"},
            {"key": "Battery Type", "value": "AAA"},
        ]),
    }


# 1. Full product
def test_full_product(sample_product_full: dict[str, Any]) -> None:
    text = build_retrieval_text(sample_product_full)
    expected = (
        "Product: Logitech K380 Multi-Device Bluetooth Keyboard | "
        "Category: Computers | "
        "Brand: Logitech | "
        "Specifications: Type: Wireless Keyboard; Connectivity: Bluetooth 3.0; Battery Type: AAA | "
        "Description: Compact and lightweight multi-device Bluetooth keyboard for computers, phones, and tablets."
    )
    assert text == expected
    is_val, err = validate_retrieval_text(text)
    assert is_val is True
    assert err is None


# 2. Missing brand
@pytest.mark.parametrize("missing_brand_val", [None, "", "   ", "None", "null", "NaN", "NA", "N/A"])
def test_missing_brand(sample_product_full: dict[str, Any], missing_brand_val: Any) -> None:
    product = sample_product_full.copy()
    product["brand"] = missing_brand_val
    text = build_retrieval_text(product)

    assert "Brand:" not in text
    assert "None" not in text
    assert "null" not in text
    assert text.startswith("Product: Logitech K380 Multi-Device Bluetooth Keyboard | Category: Computers | Specifications:")
    is_val, err = validate_retrieval_text(text)
    assert is_val is True


# 3. Missing description
@pytest.mark.parametrize("missing_desc_val", [None, "", "   ", "None", "null", "NaN", "NA"])
def test_missing_description(sample_product_full: dict[str, Any], missing_desc_val: Any) -> None:
    product = sample_product_full.copy()
    product["description"] = missing_desc_val
    text = build_retrieval_text(product)

    assert "Description:" not in text
    assert text.endswith("Specifications: Type: Wireless Keyboard; Connectivity: Bluetooth 3.0; Battery Type: AAA")
    is_val, err = validate_retrieval_text(text)
    assert is_val is True


# 4. Empty specifications
@pytest.mark.parametrize("empty_specs_val", ["[]", [], "", None, "{}", "null"])
def test_empty_specifications(sample_product_full: dict[str, Any], empty_specs_val: Any) -> None:
    product = sample_product_full.copy()
    product["product_specifications"] = empty_specs_val
    text = build_retrieval_text(product)

    assert "Specifications:" not in text
    expected = (
        "Product: Logitech K380 Multi-Device Bluetooth Keyboard | "
        "Category: Computers | "
        "Brand: Logitech | "
        "Description: Compact and lightweight multi-device Bluetooth keyboard for computers, phones, and tablets."
    )
    assert text == expected
    is_val, err = validate_retrieval_text(text)
    assert is_val is True


# 5. Specifications containing null/NA
def test_specifications_with_null_and_na() -> None:
    specs = [
        {"key": "Color", "value": "Matte Black"},
        {"key": "Material", "value": "NA"},
        {"key": "Weight", "value": "None"},
        {"key": "Warranty", "value": "null"},
        {"key": "N/A", "value": "Something"},
        {"key": "EmptyVal", "value": "   "},
        {"key": "", "value": "ValidVal"},
        {"key": "Connectivity", "value": "Bluetooth 5.0"},
    ]
    formatted = format_specifications(specs)
    assert formatted == "Color: Matte Black; Connectivity: Bluetooth 5.0"

    # All invalid specs
    all_invalid = [{"key": "NA", "value": "NA"}, {"key": "None", "value": "null"}]
    assert format_specifications(all_invalid) == ""


# 6. Description > 1200 chars
def test_description_gt_1200_chars(sample_product_full: dict[str, Any]) -> None:
    long_desc = "Word " * 300  # 1500 chars
    product = sample_product_full.copy()
    product["description"] = long_desc
    text = build_retrieval_text(product, max_desc_chars=1200)

    # Extract description part
    desc_part = text.split(" | Description: ")[1]
    assert len(desc_part) <= 1200
    assert len(desc_part) > 1150
    assert not desc_part.endswith(" ")


# 7. Description truncate does not break word boundary
def test_description_truncate_preserves_word_boundary() -> None:
    text = "The quick brown fox jumps over the lazy dog"
    # Cut at limit 15: "The quick brown" has length 15
    res = truncate_description(text, max_chars=15)
    assert res == "The quick brown"

    # Cut at limit 13: falls in middle of "brown", should cut back to "The quick" (9 chars)
    res2 = truncate_description(text, max_chars=13)
    assert res2 == "The quick"
    assert not res2.endswith("bro")

    # Unbroken long string fallback
    unbroken = "Supercalifragilisticexpialidocious"
    res3 = truncate_description(unbroken, max_chars=10)
    assert res3 == "Supercalif"


# 8. Whitespace normalization
def test_whitespace_normalization() -> None:
    raw = "  Logitech   K380 \n\n Multi-Device \t\t Keyboard   "
    cleaned = clean_whitespace(raw)
    assert cleaned == "Logitech K380 Multi-Device Keyboard"

    product = {
        "product_name": "  Keyboard   Pro  ",
        "category": " Computers \n Accessories ",
        "brand": "\tLogitech\t",
        "product_specifications": [{"key": "  Color  ", "value": "  Deep \n Blue  "}],
        "description": "  Great \n\n typing   experience.  ",
    }
    text = build_retrieval_text(product)
    assert text == (
        "Product: Keyboard Pro | "
        "Category: Computers Accessories | "
        "Brand: Logitech | "
        "Specifications: Color: Deep Blue | "
        "Description: Great typing experience."
    )


# 9. Price and rating do not appear from template
def test_price_and_rating_excluded(sample_product_full: dict[str, Any]) -> None:
    text = build_retrieval_text(sample_product_full)
    assert "2495" not in text
    assert "2995" not in text
    assert "Price:" not in text
    assert "discounted_price" not in text
    assert "retail_price" not in text
    assert "Rating:" not in text
    assert "4.5" not in text


# 10. Output is deterministic
def test_output_deterministic(sample_product_full: dict[str, Any]) -> None:
    run1 = build_retrieval_text(sample_product_full)
    run2 = build_retrieval_text(sample_product_full)
    run3 = build_retrieval_text(sample_product_full)
    assert run1 == run2 == run3


# 11. retrieval_text is not empty when required fields are valid
def test_retrieval_text_not_empty_when_required_valid() -> None:
    minimal_product = {
        "product_name": "Minimalist Ceramic Mug",
        "category": "Kitchen & Dining",
    }
    text = build_retrieval_text(minimal_product)
    assert text == "Product: Minimalist Ceramic Mug | Category: Kitchen & Dining"
    is_val, err = validate_retrieval_text(text)
    assert is_val is True
    assert err is None


# 12. Missing required fields raise ValueError
@pytest.mark.parametrize("bad_name", [None, "", "   ", "NA", "null", "None"])
def test_missing_name_raises(bad_name: Any) -> None:
    with pytest.raises(ValueError, match="product_name"):
        build_retrieval_text({"product_name": bad_name, "category": "Computers"})


@pytest.mark.parametrize("bad_cat", [None, "", "   ", "NA", "null", "None"])
def test_missing_category_raises(bad_cat: Any) -> None:
    with pytest.raises(ValueError, match="category"):
        build_retrieval_text({"product_name": "Valid Name", "category": bad_cat})


# 13. Forbidden placeholder validation check
def test_validate_retrieval_text_detects_faulty_placeholders() -> None:
    # Obvious error strings
    bad_1 = "Product: Phone | Category: Mobiles | Brand: None"
    bad_2 = "Product: Phone | Category: Mobiles | Brand: nan"
    bad_3 = "Product: Phone | Category: Mobiles | Description: null"
    bad_4 = "Product: Phone | Category: Mobiles | Specifications: NA"

    assert validate_retrieval_text(bad_1)[0] is False
    assert validate_retrieval_text(bad_2)[0] is False
    assert validate_retrieval_text(bad_3)[0] is False
    assert validate_retrieval_text(bad_4)[0] is False

    # Valid string containing a word starting with 'nan' like 'Nanson'
    valid_nanson = "Product: Nanson Kadhai | Category: Kitchen & Dining | Brand: Nanson"
    assert validate_retrieval_text(valid_nanson)[0] is True


# 14. format_specifications handles robustly
def test_format_specifications_robustness() -> None:
    # Malformed JSON
    assert format_specifications("{bad json:") == ""
    # Non-list JSON
    assert format_specifications('{"key": "value"}') == ""
    # List of non-dicts
    assert format_specifications(["not", "a", "dict"]) == ""
    # Pydantic or object-like specification items
    class DummyItem:
        def __init__(self, key: str, value: str) -> None:
            self.key = key
            self.value = value

    items = [DummyItem("Color", "Red"), DummyItem("Size", "M")]
    assert format_specifications(items) == "Color: Red; Size: M"


# 15. Dataset-level integration test
def test_build_dataset_retrieval_texts_integration() -> None:
    records = [
        {
            "product_id": "p1",
            "product_name": "Prod 1",
            "category": "Cat 1",
            "brand": "Brand A",
            "description": "Desc 1",
            "product_specifications": '[{"key": "K1", "value": "V1"}]',
        },
        {
            "product_id": "p2",
            "product_name": "Prod 2",
            "category": "Cat 2",
            "brand": None,
            "description": None,
            "product_specifications": "[]",
        },
    ]
    df = pd.DataFrame(records)
    out_df = build_dataset_retrieval_texts(df)

    assert "retrieval_text" in out_df.columns
    assert len(out_df) == 2
    assert out_df["retrieval_text"].iloc[0] == "Product: Prod 1 | Category: Cat 1 | Brand: Brand A | Specifications: K1: V1 | Description: Desc 1"
    assert out_df["retrieval_text"].iloc[1] == "Product: Prod 2 | Category: Cat 2"

    report = audit_retrieval_text_dataset(out_df)
    assert report["input_rows"] == 2
    assert report["valid_retrieval_text_rows"] == 2
    assert report["invalid_retrieval_text_rows"] == 0
    assert report["missing_brand_count"] == 1
    assert report["missing_description_count"] == 1
    assert report["empty_specs_count"] == 1
    assert report["status"] == "PASS"
