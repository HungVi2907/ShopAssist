"""Offline tests for Phase 10 hybrid retrieval contracts and fusion."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from shopassist.llm.schemas import (
    HardConstraints,
    QueryUnderstandingOutput,
    QueryUnderstandingResult,
)
from shopassist.preferences.schemas import (
    PreferenceRepresentationResult,
    RepresentationStatus,
)
from shopassist.retrieval.hybrid import (
    HardConstraintFilters,
    HybridRetrievalConfig,
    HybridRetrievalService,
    HybridRetrievalStatus,
    compile_hard_constraint_filters,
    product_matches_filters,
    validate_query_vector,
)


def async_test(fn):
    def wrapped(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return wrapped


def phase8(*, preferences=None, query="running shoes", **constraints) -> QueryUnderstandingResult:
    return QueryUnderstandingResult(
        query=query,
        output=QueryUnderstandingOutput(
            semantic_query="running shoes",
            hard_constraints=HardConstraints(**constraints),
            soft_preferences=["comfortable"] if preferences is None else preferences,
        ),
    )


def phase9(status=RepresentationStatus.SUCCESS, vector=None, model="BAAI/bge-small-en-v1.5", dim=384):
    return PreferenceRepresentationResult(
        semantic_query="running shoes",
        normalized_preferences=["comfortable"] if status == RepresentationStatus.SUCCESS else [],
        preference_query="comfortable — running shoes" if status == RepresentationStatus.SUCCESS else None,
        preference_embedding=(vector if vector is not None else [1.0] + [0.0] * 383)
        if status == RepresentationStatus.SUCCESS else None,
        embedding_model=model if status == RepresentationStatus.SUCCESS else None,
        embedding_dimension=dim if status == RepresentationStatus.SUCCESS else None,
        has_preferences=status == RepresentationStatus.SUCCESS,
        status=status,
    )


class FakeTFIDF:
    is_fitted = True

    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []

    def search(self, query, top_k):
        self.queries.append((query, top_k))
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None

    async def execute(self, query, params):
        self.query = str(query)
        self.params = params
        if "COUNT(*)" in self.query:
            return SimpleNamespace(scalar=lambda: len(self.rows))
        return SimpleNamespace(fetchall=lambda: self.rows)


class FakeEngine:
    def __init__(self, rows):
        self.connection = FakeConnection(rows)

    @asynccontextmanager
    async def connect(self):
        yield self.connection


class FakeEncoder:
    async def encode_query_async(self, query):
        return np.asarray([1.0] + [0.0] * 383, dtype=np.float32)


def lexical_row(product_id, category="Footwear", brand="Nike", price=100.0, rating=4.5, score=0.8):
    return SimpleNamespace(
        product_id=product_id,
        product_name=f"Shoe {product_id}",
        category=category,
        brand=brand,
        discounted_price=price,
        tfidf_score=score,
        metadata={"rating": rating},
    )


def dense_row(product_id, distance=0.1, category="Footwear", brand="Nike", price=100.0, rating=4.5):
    return (
        product_id, f"Shoe {product_id}", category, brand, price, rating,
        distance, 120.0, [], "Description",
    )


def test_sql_filters_are_parameterized_and_rating_null_is_rejected():
    where, params = compile_hard_constraint_filters(
        HardConstraintFilters(category="Footwear'; DROP TABLE products;--", brand="Nike", min_rating=4)
    )
    assert "DROP TABLE" not in where
    assert params["category"] == "Footwear'; DROP TABLE products;--"
    assert params["brand"] == "Nike"
    assert "rating IS NOT NULL AND rating >= :min_rating" in where


@pytest.mark.parametrize(
    "filters,operator",
    [
        (HardConstraintFilters(min_price=100, min_price_inclusive=True), ">="),
        (HardConstraintFilters(min_price=100, min_price_inclusive=False), ">"),
        (HardConstraintFilters(max_price=100, max_price_inclusive=True), "<="),
        (HardConstraintFilters(max_price=100, max_price_inclusive=False), "<"),
    ],
)
def test_explicit_price_boundaries_compile_and_equality_semantics(filters, operator):
    where, params = compile_hard_constraint_filters(filters)
    assert operator in where
    assert params["min_price" if filters.min_price is not None else "max_price"] == 100
    product = {"discounted_price": 100.0}
    assert product_matches_filters(product, filters) is (operator in (">=", "<="))


def test_unknown_phase8_v1_price_boundary_is_rejected():
    with pytest.raises(ValueError, match="explicit inclusivity"):
        compile_hard_constraint_filters(HardConstraintFilters(max_price=100))


def test_filter_nulls_category_brand_and_rating():
    filters = HardConstraintFilters(category="Footwear", brand="Nike", min_rating=4)
    assert product_matches_filters(
        {"category": "footwear", "brand": "NIKE", "rating": 4.0}, filters
    )
    assert not product_matches_filters(
        {"category": "Footwear", "brand": "Nike", "rating": None}, filters
    )
    assert not product_matches_filters(
        {"category": "Footwear", "brand": "Adidas", "rating": 5}, filters
    )


@pytest.mark.parametrize(
    "vector,model,dim",
    [([0.0] * 384, "BAAI/bge-small-en-v1.5", 384), ([float("nan")] + [0.0] * 383, "BAAI/bge-small-en-v1.5", 384), ([1.0] * 383, "BAAI/bge-small-en-v1.5", 383), ([1.0] + [0.0] * 383, "other-model", 384), ([2.0] + [0.0] * 383, "BAAI/bge-small-en-v1.5", 384)],
)
def test_bad_query_vectors_are_rejected(vector, model, dim):
    with pytest.raises(ValueError):
        validate_query_vector(vector, model, dim)


@async_test
async def test_non_success_phase9_status_stops_before_database_query():
    engine = FakeEngine([])
    service = HybridRetrievalService(engine, FakeTFIDF(), query_encoder=FakeEncoder())
    result = await service.retrieve(phase8(), phase9(RepresentationStatus.UNSUPPORTED_INTENT))
    assert result.status == HybridRetrievalStatus.UNSUPPORTED_INTENT
    assert engine.connection.query is None


@async_test
async def test_clarification_and_invalid_phase8_results_stop_before_database_query():
    engine = FakeEngine([])
    service = HybridRetrievalService(engine, FakeTFIDF(), query_encoder=FakeEncoder())
    unclear = phase8()
    unclear.output.needs_clarification = True
    invalid = phase8()
    invalid.is_valid = False
    clarification_result = await service.retrieve(unclear, phase9())
    invalid_result = await service.retrieve(invalid, phase9())
    assert clarification_result.status == HybridRetrievalStatus.CLARIFICATION_REQUIRED
    assert invalid_result.status == HybridRetrievalStatus.INVALID_INPUT
    assert engine.connection.query is None


@async_test
async def test_foreign_currency_and_price_without_boundary_stop_safely():
    service = HybridRetrievalService(FakeEngine([]), FakeTFIDF(), query_encoder=FakeEncoder())
    currency_result = await service.retrieve(phase8(currency="USD"), phase9())
    price_result = await service.retrieve(phase8(max_price=100), phase9())
    assert currency_result.status == HybridRetrievalStatus.UNSUPPORTED_INTENT
    assert price_result.status == HybridRetrievalStatus.UNSUPPORTED_INTENT


@async_test
async def test_exclusion_in_original_query_stops_even_if_phase8_dropped_it():
    engine = FakeEngine([])
    service = HybridRetrievalService(engine, FakeTFIDF(), query_encoder=FakeEncoder())
    result = await service.retrieve(phase8(query="running shoes without leather"), phase9())
    assert result.status == HybridRetrievalStatus.UNSUPPORTED_INTENT
    assert engine.connection.query is None


@async_test
async def test_hybrid_fuses_deduplicates_and_preserves_provenance():
    engine = FakeEngine([dense_row("A"), dense_row("B", distance=0.2)])
    lexical = FakeTFIDF([lexical_row("B", score=0.9), lexical_row("C", score=0.7)])
    service = HybridRetrievalService(
        engine,
        lexical,
        config=HybridRetrievalConfig(top_n=3, candidate_pool_multiplier=2),
    )
    result = await service.retrieve(phase8(category="Footwear", brand="Nike", min_rating=4), phase9())
    assert result.status == HybridRetrievalStatus.SUCCESS
    assert [candidate.product_id for candidate in result.candidates] == ["B", "A", "C"]
    assert set(result.candidates[0].sources) == {"dense", "lexical"}
    assert result.candidates[0].rank == 1
    assert result.applied_constraints["category"] == "Footwear"
    assert "Nike" not in engine.connection.query
    assert engine.connection.params["brand"] == "Nike"
    assert "rating IS NOT NULL" in engine.connection.query
    assert lexical.queries[0][0] == "comfortable — running shoes"
    assert set(result.stage_latency_ms) == {"sql_filter_ms", "dense_retrieval_ms", "lexical_ms", "fusion_ms"}
    assert result.filtered_catalog_size == 2
    assert result.to_dict()["contract_version"] == "1.0.0"


@async_test
async def test_lexical_results_are_filtered_and_empty_results_are_explicit():
    service = HybridRetrievalService(
        FakeEngine([]),
        FakeTFIDF([lexical_row("wrong", brand="Adidas")]),
        config=HybridRetrievalConfig(top_n=4),
    )
    result = await service.retrieve(phase8(brand="Nike"), phase9())
    assert result.status == HybridRetrievalStatus.NO_RESULTS
    assert result.candidates == []


@async_test
async def test_no_preferences_uses_phase7_base_encoder():
    engine = FakeEngine([dense_row("A")])
    lexical = FakeTFIDF()
    service = HybridRetrievalService(engine, lexical, query_encoder=FakeEncoder())
    result = await service.retrieve(phase8(preferences=[]), phase9(RepresentationStatus.NO_PREFERENCES))
    assert result.status == HybridRetrievalStatus.SUCCESS
    assert result.candidates[0].metadata["query_vector_source"] == "phase7_base_query"
    assert lexical.queries[0][0] == "running shoes"
    assert engine.connection.params["embedding_model"] == "BAAI/bge-small-en-v1.5"


@async_test
async def test_database_failure_returns_sanitized_status():
    class FailingConnection(FakeConnection):
        async def execute(self, query, params):
            raise RuntimeError("secret host and password must not be echoed")

    class FailingEngine:
        @asynccontextmanager
        async def connect(self):
            yield FailingConnection([])

    service = HybridRetrievalService(FailingEngine(), FakeTFIDF(), query_encoder=FakeEncoder())
    result = await service.retrieve(phase8(), phase9())
    assert result.status == HybridRetrievalStatus.RETRIEVAL_FAILURE
    assert "secret" not in result.diagnostic_reason
    assert "RuntimeError" in result.diagnostic_reason


@async_test
async def test_database_timeout_returns_retrieval_failure():
    class SlowConnection(FakeConnection):
        async def execute(self, query, params):
            await asyncio.sleep(0.02)
            if "COUNT(*)" in str(query):
                return SimpleNamespace(scalar=lambda: len(self.rows))
            return SimpleNamespace(fetchall=lambda: [])

    class SlowEngine:
        @asynccontextmanager
        async def connect(self):
            yield SlowConnection([])

    service = HybridRetrievalService(
        SlowEngine(),
        FakeTFIDF(),
        query_encoder=FakeEncoder(),
        config=HybridRetrievalConfig(database_timeout_seconds=0.001),
    )
    result = await service.retrieve(phase8(), phase9())
    assert result.status == HybridRetrievalStatus.RETRIEVAL_FAILURE
    assert "TimeoutError" in result.diagnostic_reason

