"""Phase 10 hybrid candidate retrieval.

The service combines parameterized PostgreSQL/pgvector retrieval with the
existing Phase 6 TF-IDF index using reciprocal rank fusion (RRF). It consumes
the frozen Phase 8 v1 result and the typed Phase 9 representation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import logging
import math
import time
from typing import Any, Mapping

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from shopassist.db.ingestion import format_vector_literal
from shopassist.llm.schemas import QueryUnderstandingResult
from shopassist.preferences.schemas import (
    PreferenceRepresentationResult,
    RepresentationStatus,
)
from shopassist.preferences.normalization import normalize_preferences, normalize_semantic_query
from shopassist.preferences.safety import find_unsafe_negative_preferences
from shopassist.retrieval.semantic import DenseQueryEncoder, SemanticSearchConfig
from shopassist.retrieval.tfidf import TFIDFIndex

logger = logging.getLogger(__name__)


class HybridRetrievalStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_RESULTS = "NO_RESULTS"
    INVALID_INPUT = "INVALID_INPUT"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    UNSUPPORTED_INTENT = "UNSUPPORTED_INTENT"
    EMBEDDING_FAILURE = "EMBEDDING_FAILURE"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"


@dataclass(frozen=True)
class HybridRetrievalConfig:
    """Runtime limits and the shared Phase 7 embedding identity."""

    top_n: int = 20
    max_top_n: int = 100
    candidate_pool_multiplier: int = 3
    database_timeout_seconds: float = 10.0
    rrf_k: int = 60
    model_name: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 384

    def __post_init__(self) -> None:
        if self.max_top_n <= 0 or self.top_n <= 0 or self.top_n > self.max_top_n:
            raise ValueError("top_n and max_top_n must be positive and top_n cannot exceed max_top_n")
        if self.candidate_pool_multiplier <= 0 or self.rrf_k <= 0:
            raise ValueError("candidate_pool_multiplier and rrf_k must be positive")
        if self.embedding_dimension <= 0 or not self.model_name.strip():
            raise ValueError("Embedding model name and dimension must be configured")
        if not math.isfinite(self.database_timeout_seconds) or self.database_timeout_seconds <= 0:
            raise ValueError("database_timeout_seconds must be a positive finite number")


@dataclass(frozen=True)
class HardConstraintFilters:
    """Lossless SQL filter input; price operators must be explicit."""

    category: str | None = None
    brand: str | None = None
    min_rating: float | None = None
    min_price: float | None = None
    min_price_inclusive: bool | None = None
    max_price: float | None = None
    max_price_inclusive: bool | None = None


@dataclass(frozen=True)
class CandidateSource:
    rank: int
    score: float


@dataclass
class HybridCandidate:
    rank: int
    product_id: str
    product_name: str
    category: str
    brand: str | None
    discounted_price: float
    rating: float | None
    rrf_score: float
    sources: dict[str, CandidateSource] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "category": self.category,
            "brand": self.brand,
            "discounted_price": self.discounted_price,
            "rating": self.rating,
            "rrf_score": self.rrf_score,
            "sources": {
                name: {"rank": item.rank, "score": item.score}
                for name, item in self.sources.items()
            },
            "metadata": self.metadata,
        }


@dataclass
class HybridRetrievalResult:
    status: HybridRetrievalStatus
    candidates: list[HybridCandidate] = field(default_factory=list)
    applied_constraints: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    stage_latency_ms: dict[str, float] = field(default_factory=dict)
    filtered_catalog_size: int | None = None
    diagnostic_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "1.0.0",
            "status": self.status.value,
            "candidates": [item.to_dict() for item in self.candidates],
            "applied_constraints": self.applied_constraints,
            "warnings": list(self.warnings),
            "stage_latency_ms": dict(self.stage_latency_ms),
            "filtered_catalog_size": self.filtered_catalog_size,
            "diagnostic_reason": self.diagnostic_reason,
        }


def validate_query_vector(
    vector: Any,
    model_name: str | None,
    dimension: int | None,
    *,
    expected_model: str = "BAAI/bge-small-en-v1.5",
    expected_dimension: int = 384,
) -> np.ndarray:
    """Validate model identity and numerical vector properties before SQL use."""

    if model_name != expected_model:
        raise ValueError("Query embedding model does not match the product catalog")
    if dimension != expected_dimension:
        raise ValueError("Query embedding dimension metadata is incompatible")
    try:
        array = np.asarray(vector, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError("Query embedding is not a numeric vector") from exc
    if array.shape != (expected_dimension,):
        raise ValueError("Query embedding has an incompatible shape")
    if not np.all(np.isfinite(array)):
        raise ValueError("Query embedding contains non-finite values")
    norm = float(np.linalg.norm(array))
    if norm <= 1e-6:
        raise ValueError("Query embedding is zero")
    if abs(norm - 1.0) > 1e-4:
        raise ValueError("Query embedding is not unit normalized")
    return array


def compile_hard_constraint_filters(filters: HardConstraintFilters) -> tuple[str, dict[str, Any]]:
    """Compile supported filters into fixed SQL fragments and bound values.

    SQL identifiers/operators are selected from constants; user strings only
    enter the bound parameter map. Price bounds without explicit inclusivity are
    rejected because Phase 8 v1 does not preserve strict versus inclusive intent.
    """

    clauses: list[str] = []
    params: dict[str, Any] = {}
    if filters.category is not None:
        if not filters.category.strip():
            raise ValueError("Category filter cannot be blank")
        clauses.append("LOWER(category) = LOWER(:category)")
        params["category"] = filters.category.strip()
    if filters.brand is not None:
        if not filters.brand.strip():
            raise ValueError("Brand filter cannot be blank")
        clauses.append("LOWER(brand) = LOWER(:brand)")
        params["brand"] = filters.brand.strip()
    if filters.min_rating is not None:
        if not math.isfinite(filters.min_rating) or not 1 <= filters.min_rating <= 5:
            raise ValueError("Minimum rating must be finite and between 1 and 5")
        clauses.append("rating IS NOT NULL AND rating >= :min_rating")
        params["min_rating"] = float(filters.min_rating)
    for side, value, inclusive in (
        ("min", filters.min_price, filters.min_price_inclusive),
        ("max", filters.max_price, filters.max_price_inclusive),
    ):
        if value is None:
            if inclusive is not None:
                raise ValueError(f"{side}_price inclusivity was given without a bound")
            continue
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{side}_price must be a finite non-negative number")
        if not isinstance(inclusive, bool):
            raise ValueError(
                f"{side}_price boundary semantics are unknown; explicit inclusivity is required"
            )
        op = ">=" if side == "min" and inclusive else ">" if side == "min" else "<=" if inclusive else "<"
        clauses.append(f"discounted_price {op} :{side}_price")
        params[f"{side}_price"] = float(value)
    return (" AND ".join(clauses) if clauses else "TRUE"), params


def product_matches_filters(product: Mapping[str, Any], filters: HardConstraintFilters) -> bool:
    """Apply the same explicit filter semantics to local lexical candidates."""

    if filters.min_price is not None and filters.min_price_inclusive is None:
        raise ValueError("Minimum price boundary semantics are unknown")
    if filters.max_price is not None and filters.max_price_inclusive is None:
        raise ValueError("Maximum price boundary semantics are unknown")
    if filters.category is not None and str(product.get("category") or "").casefold() != filters.category.casefold():
        return False
    brand = product.get("brand")
    if filters.brand is not None and (brand is None or str(brand).casefold() != filters.brand.casefold()):
        return False
    if filters.min_rating is not None:
        rating = product.get("rating")
        if rating is None or float(rating) < filters.min_rating:
            return False
    price = product.get("discounted_price")
    if filters.min_price is not None:
        if price is None or (float(price) < filters.min_price if filters.min_price_inclusive else float(price) <= filters.min_price):
            return False
    if filters.max_price is not None:
        if price is None or (float(price) > filters.max_price if filters.max_price_inclusive else float(price) >= filters.max_price):
            return False
    return True


class HybridRetrievalService:
    """Run validated dense retrieval, filtered lexical retrieval, and RRF."""

    def __init__(
        self,
        engine: AsyncEngine,
        tfidf_index: TFIDFIndex,
        *,
        query_encoder: DenseQueryEncoder | None = None,
        config: HybridRetrievalConfig | None = None,
    ) -> None:
        self.engine = engine
        self.tfidf_index = tfidf_index
        self.query_encoder = query_encoder
        self.config = config or HybridRetrievalConfig()

    async def retrieve(
        self,
        query_result: QueryUnderstandingResult,
        preference_result: PreferenceRepresentationResult,
        *,
        top_n: int | None = None,
        price_boundary_semantics: Mapping[str, bool] | None = None,
    ) -> HybridRetrievalResult:
        """Retrieve candidates for a single Phase 8/9 query pair."""

        if price_boundary_semantics is not None and not isinstance(price_boundary_semantics, Mapping):
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.INVALID_INPUT,
                diagnostic_reason="price_boundary_semantics must be a mapping of verified operator flags",
            )
        if not isinstance(query_result, QueryUnderstandingResult) or not isinstance(
            preference_result, PreferenceRepresentationResult
        ):
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.INVALID_INPUT,
                diagnostic_reason="Expected typed Phase 8 and Phase 9 results",
            )
        if not query_result.is_valid:
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.INVALID_INPUT,
                diagnostic_reason="Phase 8 marked the query invalid",
            )
        if query_result.output.needs_clarification:
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.CLARIFICATION_REQUIRED,
                diagnostic_reason=query_result.output.clarification_reason or "Phase 8 requires clarification",
            )
        if (query_result.output.hard_constraints.currency or "INR").upper() != "INR":
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.UNSUPPORTED_INTENT,
                diagnostic_reason="Catalog prices are in INR; foreign currency filters are unsupported",
            )
        if find_unsafe_negative_preferences([query_result.query]):
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.UNSUPPORTED_INTENT,
                diagnostic_reason="The original query contains a negative or exclusion intent that Phase 8 v1 cannot represent safely",
            )
        if preference_result.status in (RepresentationStatus.INVALID_INPUT,):
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.INVALID_INPUT,
                diagnostic_reason="Phase 9 marked the query invalid",
            )
        if preference_result.status == RepresentationStatus.CLARIFICATION_REQUIRED:
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.CLARIFICATION_REQUIRED,
                diagnostic_reason="Phase 9 requires clarification",
            )
        if preference_result.status in (
            RepresentationStatus.UNSUPPORTED_INTENT,
            RepresentationStatus.EMBEDDING_FAILURE,
        ):
            status = (
                HybridRetrievalStatus.UNSUPPORTED_INTENT
                if preference_result.status == RepresentationStatus.UNSUPPORTED_INTENT
                else HybridRetrievalStatus.EMBEDDING_FAILURE
            )
            return HybridRetrievalResult(status=status, diagnostic_reason="Phase 9 did not provide a usable representation")

        try:
            expected_context = normalize_semantic_query(query_result.output.semantic_query)
            actual_context = normalize_semantic_query(preference_result.semantic_query)
            source_preferences = normalize_preferences(query_result.output.soft_preferences)
            represented_preferences = normalize_preferences(preference_result.normalized_preferences)
        except (TypeError, ValueError):
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.INVALID_INPUT,
                diagnostic_reason="Phase 8 or Phase 9 representation contains invalid text fields",
            )
        if expected_context != actual_context:
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.INVALID_INPUT,
                diagnostic_reason="Phase 8 and Phase 9 results do not describe the same semantic query",
            )
        if preference_result.status == RepresentationStatus.SUCCESS and (
            not preference_result.has_preferences
            or not source_preferences
            or source_preferences != represented_preferences
            or not preference_result.preference_query
            or preference_result.preference_embedding is None
        ):
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.INVALID_INPUT,
                diagnostic_reason="Phase 8 and Phase 9 preference data do not match",
            )
        if preference_result.status == RepresentationStatus.NO_PREFERENCES and (
            source_preferences
            or represented_preferences
            or preference_result.has_preferences
            or preference_result.preference_embedding is not None
        ):
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.INVALID_INPUT,
                diagnostic_reason="Phase 9 reports no preferences for a Phase 8 query that contains preferences",
            )

        constraints = query_result.output.hard_constraints
        # v1 has no flags that preserve strict/inclusive price operators. A
        # caller may pass separately verified semantics; never infer them here.
        if (
            constraints.min_price is not None
            and (price_boundary_semantics is None or "min_inclusive" not in price_boundary_semantics)
        ) or (
            constraints.max_price is not None
            and (price_boundary_semantics is None or "max_inclusive" not in price_boundary_semantics)
        ):
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.UNSUPPORTED_INTENT,
                diagnostic_reason=(
                    "Phase 8 v1 does not preserve strict versus inclusive price boundaries; "
                    "this price-filtered query requires clarification"
                ),
            )
        filters = HardConstraintFilters(
            category=constraints.category,
            brand=constraints.brand,
            min_rating=constraints.min_rating,
            min_price=constraints.min_price,
            min_price_inclusive=(price_boundary_semantics or {}).get("min_inclusive"),
            max_price=constraints.max_price,
            max_price_inclusive=(price_boundary_semantics or {}).get("max_inclusive"),
        )
        try:
            where_sql, params = compile_hard_constraint_filters(filters)
        except (TypeError, ValueError):
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.UNSUPPORTED_INTENT,
                diagnostic_reason="A Phase 8 hard constraint cannot be safely represented",
            )

        limit = self.config.top_n if top_n is None else top_n
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0 or limit > self.config.max_top_n:
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.INVALID_INPUT,
                diagnostic_reason=f"top_n must be an integer between 1 and {self.config.max_top_n}",
            )
        if not self.tfidf_index.is_fitted:
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.RETRIEVAL_FAILURE,
                diagnostic_reason="Phase 6 TF-IDF index is not fitted",
            )

        try:
            vector, dense_query, vector_source = await self._query_vector(preference_result)
        except Exception as exc:
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.EMBEDDING_FAILURE,
                diagnostic_reason=f"Query embedding failed ({type(exc).__name__})",
            )

        pool_size = min(limit * max(1, self.config.candidate_pool_multiplier), 8405)
        if not math.isfinite(self.config.database_timeout_seconds) or self.config.database_timeout_seconds <= 0:
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.INVALID_INPUT,
                diagnostic_reason="database_timeout_seconds must be a positive finite number",
            )
        count_sql = text(
            f"""
            SELECT COUNT(*)
            FROM public.products
            WHERE embedding_model = :embedding_model AND ({where_sql})
            """
        )
        sql = text(
            f"""
            SELECT product_id, product_name, category, brand, discounted_price, rating,
                   embedding <=> CAST(:query_vector AS vector) AS cosine_distance,
                   retail_price, product_specifications, description
            FROM public.products
            WHERE embedding_model = :embedding_model AND ({where_sql})
            ORDER BY embedding <=> CAST(:query_vector AS vector), product_id ASC
            LIMIT :fetch_limit
            """
        )
        dense_started = time.perf_counter()
        try:
            dense_rows, sql_filter_ms, dense_ms, filtered_catalog_size = await asyncio.wait_for(
                self._fetch_dense_rows(
                    count_sql,
                    sql,
                    {"embedding_model": self.config.model_name, **params},
                    {
                        **params,
                        "embedding_model": self.config.model_name,
                        "query_vector": format_vector_literal(vector),
                        "fetch_limit": pool_size,
                    },
                ),
                timeout=self.config.database_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("Phase 10 database retrieval failed: %s", type(exc).__name__)
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.RETRIEVAL_FAILURE,
                applied_constraints=self._constraint_provenance(filters),
                stage_latency_ms={"sql_filter_and_dense_ms": _elapsed_ms(dense_started)},
                diagnostic_reason=f"Database retrieval failed ({type(exc).__name__})",
            )

        lexical_query = preference_result.preference_query if preference_result.status == RepresentationStatus.SUCCESS else dense_query
        lexical_started = time.perf_counter()
        try:
            lexical_top_k = len(getattr(self.tfidf_index, "product_ids", [])) or pool_size
            lexical_rows = self.tfidf_index.search(lexical_query, top_k=lexical_top_k)
            lexical_rows = [
                row for row in lexical_rows
                if product_matches_filters(
                    {
                        "product_id": row.product_id,
                        "product_name": row.product_name,
                        "category": row.category,
                        "brand": row.brand,
                        "discounted_price": row.discounted_price,
                        "rating": row.metadata.get("rating"),
                    },
                    filters,
                )
            ]
        except Exception as exc:
            logger.warning("Phase 10 lexical retrieval failed: %s", type(exc).__name__)
            return HybridRetrievalResult(
                status=HybridRetrievalStatus.RETRIEVAL_FAILURE,
                applied_constraints=self._constraint_provenance(filters),
                stage_latency_ms={"sql_filter_ms": sql_filter_ms, "dense_retrieval_ms": dense_ms, "lexical_ms": _elapsed_ms(lexical_started)},
                diagnostic_reason=f"Lexical retrieval failed ({type(exc).__name__})",
            )
        lexical_ms = _elapsed_ms(lexical_started)

        fusion_started = time.perf_counter()
        fused: dict[str, HybridCandidate] = {}
        for rank, row in enumerate(dense_rows, start=1):
            product_id = str(row[0])
            candidate = self._candidate_from_dense_row(row)
            candidate.sources["dense"] = CandidateSource(rank=rank, score=1.0 - float(row[6]))
            candidate.rrf_score += 1.0 / (self.config.rrf_k + rank)
            fused[product_id] = candidate
        for rank, row in enumerate(lexical_rows, start=1):
            product_id = str(row.product_id)
            candidate = fused.get(product_id)
            if candidate is None:
                candidate = HybridCandidate(
                    rank=0,
                    product_id=product_id,
                    product_name=str(row.product_name),
                    category=str(row.category),
                    brand=str(row.brand) if row.brand is not None else None,
                    discounted_price=float(row.discounted_price),
                    rating=_optional_float(row.metadata.get("rating")),
                    rrf_score=0.0,
                    metadata=dict(row.metadata),
                )
                fused[product_id] = candidate
            candidate.sources["lexical"] = CandidateSource(rank=rank, score=float(row.tfidf_score))
            candidate.rrf_score += 1.0 / (self.config.rrf_k + rank)
        candidates = sorted(fused.values(), key=lambda item: (-item.rrf_score, item.product_id))[:limit]
        for rank, candidate in enumerate(candidates, start=1):
            candidate.rank = rank
            candidate.metadata.setdefault("query_vector_source", vector_source)
        fusion_ms = _elapsed_ms(fusion_started)
        status = HybridRetrievalStatus.SUCCESS if candidates else HybridRetrievalStatus.NO_RESULTS
        return HybridRetrievalResult(
            status=status,
            candidates=candidates,
            applied_constraints=self._constraint_provenance(filters),
            warnings=[],
            stage_latency_ms={
                "sql_filter_ms": sql_filter_ms,
                "dense_retrieval_ms": dense_ms,
                "lexical_ms": lexical_ms,
                "fusion_ms": fusion_ms,
            },
            filtered_catalog_size=filtered_catalog_size,
        )

    async def _query_vector(
        self, result: PreferenceRepresentationResult
    ) -> tuple[np.ndarray, str, str]:
        if result.status == RepresentationStatus.SUCCESS:
            vector = validate_query_vector(
                result.preference_embedding,
                result.embedding_model,
                result.embedding_dimension,
                expected_model=self.config.model_name,
                expected_dimension=self.config.embedding_dimension,
            )
            return vector, result.preference_query or result.semantic_query, "phase9_preference"
        if result.status != RepresentationStatus.NO_PREFERENCES:
            raise ValueError("Phase 9 status does not permit dense retrieval")
        if not result.semantic_query.strip():
            raise ValueError("No base semantic query is available")
        if self.query_encoder is None:
            self.query_encoder = DenseQueryEncoder(
                config=SemanticSearchConfig(
                    model_name=self.config.model_name,
                    embedding_dim=self.config.embedding_dimension,
                )
            )
        vector = await self.query_encoder.encode_query_async(result.semantic_query)
        vector = validate_query_vector(
            vector,
            self.config.model_name,
            self.config.embedding_dimension,
            expected_model=self.config.model_name,
            expected_dimension=self.config.embedding_dimension,
        )
        return vector, result.semantic_query, "phase7_base_query"

    async def _fetch_dense_rows(
        self,
        count_sql: Any,
        sql: Any,
        filter_params: dict[str, Any],
        dense_params: dict[str, Any],
    ) -> tuple[list[Any], float, float, int]:
        async with self.engine.connect() as conn:
            filter_started = time.perf_counter()
            count_result = await conn.execute(count_sql, filter_params)
            filtered_count = int(count_result.scalar())
            filter_ms = _elapsed_ms(filter_started)
            dense_started = time.perf_counter()
            db_result = await conn.execute(sql, dense_params)
            rows = list(db_result.fetchall())
            dense_ms = _elapsed_ms(dense_started)
            return rows, filter_ms, dense_ms, filtered_count

    @staticmethod
    def _candidate_from_dense_row(row: Any) -> HybridCandidate:
        distance = float(row[6])
        if not math.isfinite(distance):
            raise ValueError("Database returned non-finite cosine distance")
        return HybridCandidate(
            rank=0,
            product_id=str(row[0]),
            product_name=str(row[1]),
            category=str(row[2]),
            brand=str(row[3]) if row[3] is not None else None,
            discounted_price=float(row[4]),
            rating=_optional_float(row[5]),
            rrf_score=0.0,
            metadata={
                "cosine_distance": distance,
                "retail_price": _optional_float(row[7]),
                "product_specifications": row[8],
                "product_description": row[9],
            },
        )

    @staticmethod
    def _constraint_provenance(filters: HardConstraintFilters) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "category": filters.category,
                "brand": filters.brand,
                "min_rating": filters.min_rating,
                "rating_null_policy": "null ratings do not satisfy a minimum rating",
            }.items()
            if value is not None
        }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 4)
