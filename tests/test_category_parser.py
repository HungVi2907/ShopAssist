"""Unit tests for category tree parser."""

import pytest
from shopassist.data.category_parser import (
    extract_category_level,
    get_category_depth,
    parse_category_tree,
)


def test_parse_category_tree_standard():
    raw = '["Clothing >> Women\'s Clothing >> Lingerie, Sleep & Swimwear >> Shorts"]'
    levels = parse_category_tree(raw)
    assert levels == ["Clothing", "Women's Clothing", "Lingerie, Sleep & Swimwear", "Shorts"]
    assert get_category_depth(raw) == 4
    assert extract_category_level(raw, 1) == "Clothing"
    assert extract_category_level(raw, 2) == "Women's Clothing"
    assert extract_category_level(raw, 4) == "Shorts"
    assert extract_category_level(raw, 5) is None


def test_parse_category_tree_single_level():
    raw = '["Clothing"]'
    levels = parse_category_tree(raw)
    assert levels == ["Clothing"]
    assert get_category_depth(raw) == 1
    assert extract_category_level(raw, 1) == "Clothing"


def test_parse_category_tree_empty_and_invalid():
    assert parse_category_tree(None) == []
    assert parse_category_tree("") == []
    assert parse_category_tree("   ") == []
    assert parse_category_tree("[]") == []
    assert parse_category_tree('[""]') == []
    assert get_category_depth(None) == 0
    assert extract_category_level("", 1) is None


def test_parse_category_tree_raw_string_without_brackets():
    raw = "Electronics >> Audio >> Headphones"
    levels = parse_category_tree(raw)
    assert levels == ["Electronics", "Audio", "Headphones"]
    assert get_category_depth(raw) == 3
