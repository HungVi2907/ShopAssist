"""Unit tests for Phase 3 Category Selection module."""

import pandas as pd
import pytest

from shopassist.data.category_selection import (
    evaluate_categories,
    extract_selected_candidates,
    get_selected_category_names,
)


@pytest.fixture
def mock_multi_category_df() -> pd.DataFrame:
    """Create mock DataFrame with products from both selected and rejected categories."""
    return pd.DataFrame(
        {
            "uniq_id": ["u1", "u2", "u3", "u4", "u5"],
            "pid": ["p1", "p2", "p3", "p4", "p5"],
            "product_name": [
                "Gaming Laptop X",
                "Alisha Cycling Shorts",
                "Gold Pearl Bangle",
                "Wired USB Mouse",
                "Leather Bellies Shoe",
            ],
            "product_category_tree": [
                '["Computers >> Laptops >> Gaming Laptops"]',
                '["Clothing >> Women\'s Clothing >> Shorts"]',
                '["Jewellery >> Bangles >> Gold Bangles"]',
                '["Computers >> Peripherals >> Mice"]',
                '["Footwear >> Women\'s Footwear >> Bellies"]',
            ],
            "discounted_price": [1200.0, 300.0, 500.0, 25.0, 45.0],
            "retail_price": [1500.0, 500.0, 800.0, 35.0, 60.0],
            "brand": ["Asus", "Alisha", "Karat", "Logitech", "Bata"],
            "description": ["High-performance gaming laptop.", "Cotton shorts.", "Pure gold bangle.", "Smooth optical mouse.", "Comfortable daily shoes."],
            "product_specifications": ['{"key"=>"RAM"}', '{"key"=>"Fabric"}', '{"key"=>"Metal"}', '{"key"=>"DPI"}', '{"key"=>"Material"}'],
            "product_rating": ["4.5", "No rating available", "4.0", "5.0", "No rating available"],
        }
    )


def test_get_selected_category_names():
    selected = get_selected_category_names()
    assert isinstance(selected, list)
    assert len(selected) == 16
    assert "Computers" in selected
    assert "Footwear" in selected
    assert "Mobiles & Accessories" in selected
    assert "Clothing" not in selected
    assert "Jewellery" not in selected
    assert "Beauty and Personal Care" not in selected


def test_evaluate_categories(mock_multi_category_df: pd.DataFrame):
    eval_results = evaluate_categories(mock_multi_category_df)

    assert "selected_categories" in eval_results
    assert "rejected_categories" in eval_results
    assert "comparison_table" in eval_results
    assert "summary" in eval_results

    selected_names = [s["category"] for s in eval_results["selected_categories"]]
    assert "Computers" in selected_names
    assert "Footwear" in selected_names
    assert "Clothing" not in selected_names
    assert "Jewellery" not in selected_names

    # In mock data: Computers (2) + Footwear (1) = 3 selected products
    assert eval_results["summary"]["total_selected_products"] == 3


def test_extract_selected_candidates_preserves_raw_data(mock_multi_category_df: pd.DataFrame):
    selected_set = {"Computers", "Footwear"}
    subset = extract_selected_candidates(mock_multi_category_df, selected_set)

    # Must contain 3 rows (2 Computers + 1 Footwear)
    assert len(subset) == 3
    assert set(subset["_level1_category"]) == {"Computers", "Footwear"}

    # Verify raw values are preserved exactly
    row_laptop = subset[subset["uniq_id"] == "u1"].iloc[0]
    assert row_laptop["product_name"] == "Gaming Laptop X"
    assert row_laptop["discounted_price"] == 1200.0
    assert row_laptop["brand"] == "Asus"
    assert row_laptop["description"] == "High-performance gaming laptop."

    # Verify rejected rows are absent
    assert "u2" not in subset["uniq_id"].values  # Clothing
    assert "u3" not in subset["uniq_id"].values  # Jewellery


def test_target_size_boundary_check():
    # Valid range
    summary_valid = {"total_selected_products": 8683}
    assert 5000 <= summary_valid["total_selected_products"] <= 15000

    # Below range
    summary_low = {"total_selected_products": 4500}
    assert not (5000 <= summary_low["total_selected_products"] <= 15000)

    # Above range
    summary_high = {"total_selected_products": 16000}
    assert not (5000 <= summary_high["total_selected_products"] <= 15000)
