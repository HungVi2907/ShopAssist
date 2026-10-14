"""Unit tests for PriceBoundaryAdapter (Phase 15)."""

from __future__ import annotations

import pytest

from shopassist.api.price_adapter import PriceBoundaryAdapter


def test_no_price_constraints():
    res = PriceBoundaryAdapter.resolve("Puma shoes", min_price=None, max_price=None)
    assert res.is_resolved is True
    assert res.semantics == {}


@pytest.mark.parametrize(
    "query,expected_max_inclusive",
    [
        ("shoes under 3000", False),
        ("shoes below 2000 INR", False),
        ("laptop less than 50000", False),
        ("running shoes cheaper than 1500", False),
        ("shoes < 3000", False),
        ("giày chạy bộ dưới 2000", False),
        ("tai nghe thấp hơn 1000", False),
        ("áo thun nhỏ hơn 500", False),
        ("shoes up to 3000", True),
        ("laptop at most 40000", True),
        ("phone maximum 20000", True),
        ("shoes not exceeding 2500", True),
        ("shoes within 3000", True),
        ("shoes <= 3000", True),
        ("giày tối đa 2000", True),
        ("tai nghe không quá 1500", True),
        ("điện thoại nhiều nhất 10000", True),
        ("giày 2000 đổ lại", True),
        ("giày 2000 trở xuống", True),
    ],
)
def test_max_price_operator_resolution(query: str, expected_max_inclusive: bool):
    res = PriceBoundaryAdapter.resolve(query, min_price=None, max_price=3000.0)
    assert res.is_resolved is True
    assert res.semantics.get("max_inclusive") == expected_max_inclusive


@pytest.mark.parametrize(
    "query,expected_min_inclusive",
    [
        ("shoes above 1000", False),
        ("laptop over 20000", False),
        ("shoes more than 1500", False),
        ("shoes higher than 2000", False),
        ("shoes > 1000", False),
        ("giày trên 1000", False),
        ("tai nghe cao hơn 500", False),
        ("laptop lớn hơn 15000", False),
        ("shoes at least 1000", True),
        ("laptop minimum 20000", True),
        ("shoes from 1500", True),
        ("shoes >= 1000", True),
        ("giày tối thiểu 1000", True),
        ("tai nghe ít nhất 500", True),
        ("giày từ 1000", True),
        ("giày 1000 đổ lên", True),
        ("giày 1000 trở lên", True),
    ],
)
def test_min_price_operator_resolution(query: str, expected_min_inclusive: bool):
    res = PriceBoundaryAdapter.resolve(query, min_price=1000.0, max_price=None)
    assert res.is_resolved is True
    assert res.semantics.get("min_inclusive") == expected_min_inclusive


@pytest.mark.parametrize(
    "query",
    [
        "shoes between 1000 and 3000",
        "laptop from 20000 to 40000",
        "giày từ 1000 đến 3000",
        "giày từ 1000 tới 3000",
        "shoes 1000 - 3000 inr",
        "shoes 1000 to 3000",
    ],
)
def test_explicit_inclusive_range(query: str):
    res = PriceBoundaryAdapter.resolve(query, min_price=1000.0, max_price=3000.0)
    assert res.is_resolved is True
    assert res.semantics.get("min_inclusive") is True
    assert res.semantics.get("max_inclusive") is True


@pytest.mark.parametrize(
    "query",
    [
        "shoes around 2000",
        "shoes about 1500",
        "shoes approx 2500",
        "shoes approximately 3000",
        "shoes with budget 2000",
        "giày khoảng 2000",
        "giày tầm 2000",
        "giày ngân sách 2000",
    ],
)
def test_ambiguous_price_expressions_rejected(query: str):
    res = PriceBoundaryAdapter.resolve(query, min_price=None, max_price=2000.0)
    assert res.is_resolved is False
    assert res.unresolved_reason is not None
    assert "ambiguous" in res.unresolved_reason.lower() or "approximate" in res.unresolved_reason.lower()


def test_missing_operator_fails_closed():
    # If the user says "Puma running shoes 3000 INR" without any operator ("under", "at least", etc.)
    res = PriceBoundaryAdapter.resolve("Puma running shoes 3000 INR", min_price=None, max_price=3000.0)
    assert res.is_resolved is False
    assert res.unresolved_reason is not None
