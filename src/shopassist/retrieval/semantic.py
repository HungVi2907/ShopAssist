"""Dense Semantic Search Retrieval Engine for ShopAssist (Phase 7).

Baseline 2: Dense Semantic Retrieval using BAAI/bge-small-en-v1.5 embeddings
and Supabase PostgreSQL + pgvector HNSW index search.

Features:
- Natural-language query validation and preprocessing.
- 384-dimensional query embedding generation with BGE asymmetric query instruction.
- L2-normalized query embeddings compatible with existing database vectors.
- Parameterized pgvector cosine distance (<=>) retrieval.
- Primary ordering by raw distance operator for optimal HNSW index scan eligibility.
- In-memory deterministic tie-breaking on (cosine_distance, product_id).
- Safe zero-score policy for empty or whitespace-only queries.
- Exact linear scan retrieval option for ANN quality evaluation (Recall@K).
- Asynchronous SQLAlchemy engine integration with non-blocking thread execution for embeddings.
- Comparative evaluation against Phase 6 TF-IDF lexical baseline.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import json
import logging
import math
import os
from pathlib import Path
import time
from typing import Any, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from shopassist.core.config import INTERIM_DATA_DIR, PROCESSED_DATA_DIR, settings
from shopassist.db.connection import (
    ensure_windows_event_loop_policy,
    get_async_engine,
)
from shopassist.db.ingestion import format_vector_literal
from shopassist.embeddings.model import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_MODEL_NAME,
    DEFAULT_QUERY_INSTRUCTION,
    EmbeddingModel,
    resolve_device,
    validate_embeddings,
)

ensure_windows_event_loop_policy()

logger = logging.getLogger(__name__)

DEFAULT_REPORT_PATH: Path = INTERIM_DATA_DIR / "phase7_semantic_search_report.json"
CANONICAL_PRODUCTS_PATH: Path = PROCESSED_DATA_DIR / "products.parquet"
EXPECTED_CATALOG_SIZE: int = 8405
MAX_SAFE_TOP_K: int = 100


# ==============================================================================
# Domain Data Models & Configuration
# ==============================================================================

@dataclass
class SemanticSearchConfig:
    """Configuration for dense semantic search retrieval engine."""

    model_name: str = DEFAULT_MODEL_NAME
    embedding_dim: int = DEFAULT_EMBEDDING_DIM
    query_instruction: str | None = DEFAULT_QUERY_INSTRUCTION
    default_top_k: int = 5
    max_top_k: int = MAX_SAFE_TOP_K
    device: str | None = None
    normalize_embeddings: bool = True
    candidate_pool_multiplier: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SemanticSearchConfig:
        """Create configuration instance from dictionary."""
        return cls(**data)


@dataclass
class SemanticSearchResult:
    """Structured product candidate retrieved via dense semantic search."""

    rank: int
    product_id: str
    product_name: str
    category: str
    brand: str | None
    discounted_price: float
    cosine_distance: float
    semantic_score: float
    retail_price: float | None = None
    rating: float | None = None
    product_specifications: Any = None
    product_description: str | None = None
    embedding_model: str = DEFAULT_MODEL_NAME
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert search result to dictionary."""
        return {
            "rank": self.rank,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "category": self.category,
            "brand": self.brand,
            "discounted_price": self.discounted_price,
            "retail_price": self.retail_price,
            "rating": self.rating,
            "cosine_distance": round(self.cosine_distance, 6),
            "semantic_score": round(self.semantic_score, 6),
            "product_specifications": self.product_specifications,
            "product_description": self.product_description,
            "embedding_model": self.embedding_model,
            "metadata": self.metadata,
        }


# ==============================================================================
# Dense Query Encoder
# ==============================================================================

class DenseQueryEncoder:
    """Production query embedding encoder wrapping BAAI/bge-small-en-v1.5.

    Manages model initialization, caching, input validation, and thread-safe
    asynchronous execution.
    """

    _cached_model: EmbeddingModel | None = None

    def __init__(
        self,
        config: SemanticSearchConfig | None = None,
        model: EmbeddingModel | None = None,
    ) -> None:
        """Initialize query encoder with optional config and model instance.

        Args:
            config: Semantic search configuration.
            model: Optional pre-loaded EmbeddingModel instance. If omitted,
                   a shared cached instance will be reused or created.
        """
        self.config = config or SemanticSearchConfig()
        if model is not None:
            self._model = model
        else:
            self._model = self._get_or_create_model(
                model_name=self.config.model_name,
                device=self.config.device,
                normalize_embeddings=self.config.normalize_embeddings,
            )

    @classmethod
    def _get_or_create_model(
        cls,
        model_name: str = DEFAULT_MODEL_NAME,
        device: str | None = None,
        normalize_embeddings: bool = True,
    ) -> EmbeddingModel:
        """Retrieve existing cached EmbeddingModel or instantiate a new one."""
        resolved_dev = resolve_device(device)
        if (
            cls._cached_model is not None
            and cls._cached_model.model_name == model_name
            and cls._cached_model.device == resolved_dev
            and cls._cached_model.normalize_embeddings == normalize_embeddings
        ):
            logger.debug("Reusing cached EmbeddingModel instance (%s on %s)", model_name, resolved_dev)
            return cls._cached_model

        logger.info("Initializing new EmbeddingModel instance (%s on %s)...", model_name, resolved_dev)
        cls._cached_model = EmbeddingModel(
            model_name=model_name,
            device=resolved_dev,
            normalize_embeddings=normalize_embeddings,
        )
        return cls._cached_model

    @property
    def model(self) -> EmbeddingModel:
        """Underlying EmbeddingModel instance."""
        return self._model

    @property
    def embedding_dimension(self) -> int:
        """Embedding dimension (384)."""
        return self._model.embedding_dimension

    def validate_query(self, query: Any) -> str:
        """Validate search query input type and format.

        Args:
            query: Input search query.

        Returns:
            Stripped query string.

        Raises:
            TypeError: If query is not a string.
        """
        if not isinstance(query, str):
            raise TypeError(f"Query must be a string, got {type(query).__name__}")
        return query.strip()

    def encode_query(
        self,
        query: str,
        instruction: str | None = ...,  # type: ignore[assignment]
    ) -> np.ndarray:
        """Encode query string into 384-dimensional unit L2 normalized vector.

        Args:
            query: User search query.
            instruction: Optional instruction prefix. If ellipsis, defaults
                         to self.config.query_instruction.

        Returns:
            1D float32 numpy array of shape (384,).

        Raises:
            ValueError: If query is empty or embedding validation fails.
        """
        clean_q = self.validate_query(query)
        if not clean_q:
            raise ValueError("Query cannot be empty or whitespace-only.")

        inst = self.config.query_instruction if instruction is ... else instruction

        # Encode using EmbeddingModel with instruction prefix
        emb = self._model.encode_queries(
            queries=clean_q,
            instruction=inst,
            normalize_embeddings=self.config.normalize_embeddings,
        )

        vec = np.asarray(emb, dtype=np.float32)

        # Validate embedding integrity
        if vec.shape != (self.config.embedding_dim,):
            raise ValueError(
                f"Generated query vector has invalid shape {vec.shape}, expected ({self.config.embedding_dim},)"
            )
        if not np.all(np.isfinite(vec)):
            raise ValueError("Generated query vector contains NaN or infinite values.")
        norm = float(np.linalg.norm(vec))
        if norm < 1e-6:
            raise ValueError("Generated query vector is an all-zero vector.")
        if self.config.normalize_embeddings and abs(norm - 1.0) > 1e-4:
            raise ValueError(f"Generated query vector is not unit L2 normalized (norm={norm:.6f}).")

        return vec

    async def encode_query_async(
        self,
        query: str,
        instruction: str | None = ...,  # type: ignore[assignment]
    ) -> np.ndarray:
        """Asynchronously encode query string in worker thread to prevent event loop blocking.

        Args:
            query: User search query.
            instruction: Optional instruction prefix.

        Returns:
            1D float32 numpy array of shape (384,).
        """
        return await asyncio.to_thread(self.encode_query, query, instruction)


# ==============================================================================
# Dense Semantic Search Engine
# ==============================================================================

class SemanticSearchEngine:
    """Production Dense Semantic Search Retrieval Engine for ShopAssist.

    Performs vector similarity search against Supabase PostgreSQL `public.products`
    using pgvector cosine distance `<=>` and B-Tree/HNSW indexes.
    """

    def __init__(
        self,
        engine: AsyncEngine | None = None,
        encoder: DenseQueryEncoder | None = None,
        config: SemanticSearchConfig | None = None,
    ) -> None:
        """Initialize semantic search engine.

        Args:
            engine: SQLAlchemy AsyncEngine for Supabase PostgreSQL. If None,
                    a new engine is created via `get_async_engine()`.
            encoder: DenseQueryEncoder instance. If None, created from config.
            config: SemanticSearchConfig. If None, uses default configuration.
        """
        self.config = config or SemanticSearchConfig()
        self._owns_engine = engine is None
        self.engine = engine or get_async_engine()
        self.encoder = encoder or DenseQueryEncoder(config=self.config)

    def validate_top_k(self, top_k: Any) -> int:
        """Validate top_k parameter bounds.

        Args:
            top_k: Number of results requested.

        Returns:
            Validated integer top_k.

        Raises:
            TypeError: If top_k is not an integer.
            ValueError: If top_k <= 0 or exceeds max_top_k.
        """
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            raise TypeError(f"top_k must be an integer, got {type(top_k).__name__}")
        if top_k <= 0:
            raise ValueError(f"top_k must be a positive integer, got {top_k}")
        if top_k > self.config.max_top_k:
            raise ValueError(
                f"top_k={top_k} exceeds maximum allowed limit of {self.config.max_top_k}"
            )
        return top_k

    async def search(
        self,
        query: str,
        top_k: int = 5,
        instruction: str | None = ...,  # type: ignore[assignment]
        candidate_pool_multiplier: int | None = None,
    ) -> list[SemanticSearchResult]:
        """Perform dense semantic search for a user query.

        Args:
            query: Natural language product search query.
            top_k: Number of product candidates to return (default: 5).
            instruction: Optional BGE instruction prefix override.
            candidate_pool_multiplier: Optional factor to retrieve a larger candidate
                                       pool before deterministic in-memory tie-breaking.

        Returns:
            List of SemanticSearchResult objects ordered by rank.
        """
        clean_q = self.encoder.validate_query(query)
        # Safe zero-score policy: empty or whitespace queries return empty results
        if not clean_q:
            logger.info("Empty query received; returning empty result list.")
            return []

        validated_k = self.validate_top_k(top_k)

        # 1. Asynchronously encode query into 384-d normalized vector
        q_vec = await self.encoder.encode_query_async(clean_q, instruction=instruction)
        q_vec_str = format_vector_literal(q_vec)

        # 2. Determine candidate pool size for pure HNSW search
        multiplier = candidate_pool_multiplier or self.config.candidate_pool_multiplier
        fetch_limit = min(max(validated_k * multiplier, validated_k), EXPECTED_CATALOG_SIZE)

        # 3. Primary query using pure distance ordering for optimal HNSW index scan eligibility
        sql_query = text(
            """
            SELECT
                product_id,
                product_name,
                category,
                brand,
                discounted_price,
                retail_price,
                rating,
                product_specifications,
                description,
                embedding <=> CAST(:query_vector AS vector) AS cosine_distance
            FROM public.products
            ORDER BY embedding <=> CAST(:query_vector AS vector)
            LIMIT :fetch_limit;
            """
        )

        async with self.engine.connect() as conn:
            result = await conn.execute(sql_query, {"query_vector": q_vec_str, "fetch_limit": fetch_limit})
            rows = result.fetchall()

        if not rows:
            return []

        # 4. Map rows into candidate objects
        candidates: list[SemanticSearchResult] = []
        for row in rows:
            p_id = str(row[0])
            p_name = str(row[1])
            cat = str(row[2])
            brand = str(row[3]) if row[3] is not None else None
            disc_price = float(row[4]) if row[4] is not None else 0.0
            ret_price = float(row[5]) if row[5] is not None else None
            rating_val = float(row[6]) if row[6] is not None else None
            specs = row[7]
            desc = str(row[8]) if row[8] is not None else None
            dist = float(row[9])
            # Cosine similarity score: 1.0 - cosine_distance
            # For normalized vectors, distance is in [0, 2], score in [-1, 1], typically [0, 1] for positive similarity
            score = round(1.0 - dist, 6)

            candidates.append(
                SemanticSearchResult(
                    rank=0,  # assigned after final tie-breaking
                    product_id=p_id,
                    product_name=p_name,
                    category=cat,
                    brand=brand,
                    discounted_price=disc_price,
                    retail_price=ret_price,
                    rating=rating_val,
                    product_specifications=specs,
                    product_description=desc,
                    cosine_distance=round(dist, 6),
                    semantic_score=score,
                    embedding_model=self.config.model_name,
                )
            )

        # 5. Deterministic tie-breaking in Python: (cosine_distance ASC, product_id ASC)
        candidates.sort(key=lambda r: (r.cosine_distance, r.product_id))

        # 6. Slicing Top-K and assigning 1-indexed ranks
        top_results = candidates[:validated_k]
        for idx, item in enumerate(top_results, start=1):
            item.rank = idx

        return top_results

    async def search_exact(
        self,
        query: str,
        top_k: int = 5,
        instruction: str | None = ...,  # type: ignore[assignment]
    ) -> list[SemanticSearchResult]:
        """Perform exact linear scan vector retrieval by disabling index scans in transaction.

        Used for ANN Recall@K validation against the exact nearest-neighbor ground truth.

        Args:
            query: Natural language query.
            top_k: Number of candidates to return.
            instruction: Optional instruction prefix override.

        Returns:
            List of SemanticSearchResult objects from exact exhaustive scan.
        """
        clean_q = self.encoder.validate_query(query)
        if not clean_q:
            return []

        validated_k = self.validate_top_k(top_k)
        q_vec = await self.encoder.encode_query_async(clean_q, instruction=instruction)
        q_vec_str = format_vector_literal(q_vec)

        sql_query = text(
            """
            SELECT
                product_id,
                product_name,
                category,
                brand,
                discounted_price,
                retail_price,
                rating,
                product_specifications,
                description,
                embedding <=> CAST(:query_vector AS vector) AS cosine_distance
            FROM public.products
            ORDER BY embedding <=> CAST(:query_vector AS vector)
            LIMIT :k;
            """
        )

        async with self.engine.connect() as conn:
            async with conn.begin():
                # Disable index scan and bitmap scan within transaction for exact linear scan
                await conn.execute(text("SET LOCAL enable_indexscan = off;"))
                await conn.execute(text("SET LOCAL enable_bitmapscan = off;"))
                result = await conn.execute(sql_query, {"query_vector": q_vec_str, "k": validated_k})
                rows = result.fetchall()

        candidates: list[SemanticSearchResult] = []
        for row in rows:
            dist = float(row[9])
            candidates.append(
                SemanticSearchResult(
                    rank=0,
                    product_id=str(row[0]),
                    product_name=str(row[1]),
                    category=str(row[2]),
                    brand=str(row[3]) if row[3] is not None else None,
                    discounted_price=float(row[4]) if row[4] is not None else 0.0,
                    retail_price=float(row[5]) if row[5] is not None else None,
                    rating=float(row[6]) if row[6] is not None else None,
                    product_specifications=row[7],
                    product_description=str(row[8]) if row[8] is not None else None,
                    cosine_distance=round(dist, 6),
                    semantic_score=round(1.0 - dist, 6),
                    embedding_model=self.config.model_name,
                )
            )

        candidates.sort(key=lambda r: (r.cosine_distance, r.product_id))
        top_results = candidates[:validated_k]
        for idx, item in enumerate(top_results, start=1):
            item.rank = idx
        return top_results

    async def explain_search(
        self,
        query: str,
        top_k: int = 5,
        instruction: str | None = ...,  # type: ignore[assignment]
        format_json: bool = False,
    ) -> str | list[dict[str, Any]]:
        """Retrieve PostgreSQL execution plan (EXPLAIN ANALYZE BUFFERS) for semantic query.

        Args:
            query: Natural language query.
            top_k: Number of candidates requested.
            instruction: Optional instruction prefix override.
            format_json: Whether to return plan as parsed JSON list or text string.

        Returns:
            Plan as string or parsed JSON list.
        """
        clean_q = self.encoder.validate_query(query)
        q_vec = await self.encoder.encode_query_async(clean_q, instruction=instruction)
        q_vec_str = format_vector_literal(q_vec)

        fmt_clause = "FORMAT JSON," if format_json else ""
        explain_sql = text(
            f"""
            EXPLAIN (ANALYZE, BUFFERS, {fmt_clause} COSTS, TIMING)
            SELECT product_id, embedding <=> CAST(:query_vector AS vector) AS cosine_distance
            FROM public.products
            ORDER BY embedding <=> CAST(:query_vector AS vector)
            LIMIT :k;
            """
        )

        async with self.engine.connect() as conn:
            res = await conn.execute(explain_sql, {"query_vector": q_vec_str, "k": top_k})
            rows = res.fetchall()

        if format_json:
            raw_json = rows[0][0]
            if isinstance(raw_json, str):
                return json.loads(raw_json)
            return raw_json
        return "\n".join(r[0] for r in rows)

    async def evaluate_ann_recall(
        self,
        queries: Sequence[str],
        ks: Sequence[int] = (5, 10, 20),
        instruction: str | None = ...,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Evaluate HNSW ANN Recall@K against exact linear scan across queries.

        Args:
            queries: Sequence of natural language queries.
            ks: Sequence of Top-K cutoffs (e.g. 5, 10, 20).
            instruction: Optional query instruction.

        Returns:
            Dictionary containing average recalls, per-query recalls, and timings.
        """
        recalls_by_k: dict[int, list[float]] = {k: [] for k in ks}
        query_details: list[dict[str, Any]] = []

        for q in queries:
            q_detail: dict[str, Any] = {"query": q, "recalls": {}}
            for k in ks:
                # Approximate HNSW search
                ann_res = await self.search(q, top_k=k, instruction=instruction)
                ann_ids = [r.product_id for r in ann_res]

                # Exact linear scan search
                exact_res = await self.search_exact(q, top_k=k, instruction=instruction)
                exact_ids = [r.product_id for r in exact_res]

                # Intersection fraction
                intersection = set(ann_ids).intersection(set(exact_ids))
                recall = len(intersection) / float(k) if k > 0 else 1.0
                recalls_by_k[k].append(recall)
                q_detail["recalls"][f"K={k}"] = round(recall, 4)

            query_details.append(q_detail)

        summary: dict[str, Any] = {
            "num_queries": len(queries),
            "ks": list(ks),
            "average_recall": {f"Recall@{k}": round(float(np.mean(recalls_by_k[k])), 4) for k in ks},
            "min_recall": {f"Recall@{k}": round(float(np.min(recalls_by_k[k])), 4) for k in ks},
            "query_details": query_details,
        }
        return summary

    async def verify_catalog_integrity(self) -> dict[str, Any]:
        """Verify product catalog count and embedding integrity in public.products."""
        async with self.engine.connect() as conn:
            cnt_res = await conn.execute(text("SELECT COUNT(*) FROM public.products;"))
            total_rows = int(cnt_res.scalar())

            dim_res = await conn.execute(
                text("SELECT COUNT(*) FROM public.products WHERE vector_dims(embedding) = :dim;"),
                {"dim": self.config.embedding_dim},
            )
            matching_dim_rows = int(dim_res.scalar())

            null_emb_res = await conn.execute(
                text("SELECT COUNT(*) FROM public.products WHERE embedding IS NULL;")
            )
            null_emb_rows = int(null_emb_res.scalar())

        is_intact = (
            total_rows == EXPECTED_CATALOG_SIZE
            and matching_dim_rows == EXPECTED_CATALOG_SIZE
            and null_emb_rows == 0
        )
        return {
            "is_intact": is_intact,
            "total_rows": total_rows,
            "expected_rows": EXPECTED_CATALOG_SIZE,
            "matching_dim_rows": matching_dim_rows,
            "null_emb_rows": null_emb_rows,
        }

    async def close(self) -> None:
        """Dispose database engine if managed internally."""
        if self._owns_engine and self.engine is not None:
            await self.engine.dispose()
            logger.info("SemanticSearchEngine database engine disposed.")


# ==============================================================================
# Benchmarking & Comparative Evaluation Utilities
# ==============================================================================

async def benchmark_semantic_retrieval(
    engine: SemanticSearchEngine,
    queries: Sequence[str],
    top_k: int = 5,
    num_iterations: int = 20,
    warmup_iterations: int = 5,
) -> dict[str, Any]:
    """Measure embedding inference, database search, and end-to-end latency quantiles.

    Args:
        engine: SemanticSearchEngine instance.
        queries: Sequence of benchmark queries.
        top_k: Top-K cutoff.
        num_iterations: Measured iteration count per query.
        warmup_iterations: Unmeasured warmup iterations.

    Returns:
        Dictionary of latency statistics (mean, P50, P95, min, max in milliseconds).
    """
    logger.info("Executing %d warmup iterations...", warmup_iterations)
    for i in range(warmup_iterations):
        q = queries[i % len(queries)]
        await engine.search(q, top_k=top_k)

    embedding_latencies_ms: list[float] = []
    database_latencies_ms: list[float] = []
    end_to_end_latencies_ms: list[float] = []

    logger.info("Benchmarking latency over %d iterations across %d queries...", num_iterations, len(queries))
    for it in range(num_iterations):
        q = queries[it % len(queries)]

        t_start = time.perf_counter()

        # Measure embedding generation
        t_emb_0 = time.perf_counter()
        q_vec = await engine.encoder.encode_query_async(q)
        t_emb_1 = time.perf_counter()
        emb_ms = (t_emb_1 - t_emb_0) * 1000.0
        embedding_latencies_ms.append(emb_ms)

        # Measure database query execution
        q_vec_str = format_vector_literal(q_vec)
        t_db_0 = time.perf_counter()
        sql_query = text(
            """
            SELECT
                product_id,
                product_name,
                category,
                brand,
                discounted_price,
                retail_price,
                rating,
                product_specifications,
                description,
                embedding <=> CAST(:query_vector AS vector) AS cosine_distance
            FROM public.products
            ORDER BY embedding <=> CAST(:query_vector AS vector)
            LIMIT :k;
            """
        )
        async with engine.engine.connect() as conn:
            res = await conn.execute(sql_query, {"query_vector": q_vec_str, "k": top_k})
            _ = res.fetchall()
        t_db_1 = time.perf_counter()
        db_ms = (t_db_1 - t_db_0) * 1000.0
        database_latencies_ms.append(db_ms)

        t_end = time.perf_counter()
        e2e_ms = (t_end - t_start) * 1000.0
        end_to_end_latencies_ms.append(e2e_ms)

    def _stats(arr: list[float]) -> dict[str, float]:
        return {
            "mean_ms": round(float(np.mean(arr)), 3),
            "p50_ms": round(float(np.percentile(arr, 50)), 3),
            "p95_ms": round(float(np.percentile(arr, 95)), 3),
            "min_ms": round(float(np.min(arr)), 3),
            "max_ms": round(float(np.max(arr)), 3),
        }

    return {
        "num_queries": len(queries),
        "num_iterations": num_iterations,
        "warmup_iterations": warmup_iterations,
        "top_k": top_k,
        "embedding_latency": _stats(embedding_latencies_ms),
        "database_latency": _stats(database_latencies_ms),
        "end_to_end_latency": _stats(end_to_end_latencies_ms),
    }


def compute_result_overlap(
    results_a: Sequence[Any],
    results_b: Sequence[Any],
    top_k: int = 5,
) -> float:
    """Calculate Jaccard-like Overlap@K between two ranked result sets based on product_id.

    Args:
        results_a: First result list (e.g. TF-IDF).
        results_b: Second result list (e.g. Dense Semantic).
        top_k: Cutoff depth.

    Returns:
        Fraction of overlapping product IDs in range [0.0, 1.0].
    """
    ids_a = {getattr(r, "product_id", r.get("product_id") if isinstance(r, dict) else str(r)) for r in results_a[:top_k]}
    ids_b = {getattr(r, "product_id", r.get("product_id") if isinstance(r, dict) else str(r)) for r in results_b[:top_k]}
    if not ids_a and not ids_b:
        return 1.0
    return round(len(ids_a.intersection(ids_b)) / float(top_k), 4)
