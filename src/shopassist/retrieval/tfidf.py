"""TF-IDF Baseline Product Retrieval Engine.

Phase 6 of ShopAssist:
- Fits a lexical TF-IDF vectorizer on canonical product retrieval_text.
- Constructs an L2-normalized sparse document-term matrix (SciPy CSR).
- Transforms natural-language queries into sparse TF-IDF vectors.
- Computes cosine similarity via sparse matrix-vector dot product.
- Ranks candidates with deterministic tie-breaking and Top-K retrieval.
- Handles empty queries and out-of-vocabulary (OOV) terms gracefully.
- Serializes and reloads artifacts from data/processed/tfidf/.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Sequence

import joblib
import numpy as np
import pandas as pd
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer

from shopassist.core.config import INTERIM_DATA_DIR, PROCESSED_DATA_DIR

logger = logging.getLogger(__name__)

CANONICAL_PRODUCTS_PATH: Path = PROCESSED_DATA_DIR / "products.parquet"
DEFAULT_TFIDF_ARTIFACT_DIR: Path = PROCESSED_DATA_DIR / "tfidf"
DEFAULT_TFIDF_REPORT_PATH: Path = INTERIM_DATA_DIR / "phase6_tfidf_baseline_report.json"
EXPECTED_CATALOG_SIZE: int = 8405


@dataclass
class TFIDFConfig:
    """Hyperparameter configuration for TF-IDF vectorizer."""

    ngram_range: tuple[int, int] = (1, 2)
    min_df: int | float = 2
    max_df: float = 0.8
    max_features: int | None = None
    sublinear_tf: bool = True
    use_idf: bool = True
    smooth_idf: bool = True
    norm: str = "l2"
    lowercase: bool = True
    token_pattern: str = r"(?u)\b\w+\b"

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        d = asdict(self)
        d["ngram_range"] = list(self.ngram_range)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TFIDFConfig:
        """Create configuration instance from dictionary."""
        kwargs = dict(data)
        if "ngram_range" in kwargs and isinstance(kwargs["ngram_range"], list):
            kwargs["ngram_range"] = tuple(kwargs["ngram_range"])
        return cls(**kwargs)


@dataclass
class SearchResult:
    """Individual retrieved product candidate."""

    rank: int
    product_id: str
    product_name: str
    category: str
    brand: str | None
    discounted_price: float
    tfidf_score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert search result to dictionary."""
        return {
            "rank": self.rank,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "category": self.category,
            "brand": self.brand,
            "discounted_price": round(float(self.discounted_price), 2),
            "tfidf_score": round(float(self.tfidf_score), 6),
            "metadata": self.metadata,
        }


def load_canonical_products(
    parquet_path: Path | str = CANONICAL_PRODUCTS_PATH,
    expected_count: int | None = EXPECTED_CATALOG_SIZE,
) -> pd.DataFrame:
    """Load and validate canonical product dataset from Parquet.

    Args:
        parquet_path: Path to products.parquet.
        expected_count: Optional expected row count validation.

    Returns:
        Validated pandas DataFrame.

    Raises:
        FileNotFoundError: If parquet_path does not exist.
        ValueError: If validation checks fail.
    """
    path = Path(parquet_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Canonical product dataset not found: {path}")

    df = pd.read_parquet(path)
    logger.info("Loaded canonical dataset from %s: shape %s", path, df.shape)

    required_cols = [
        "product_id",
        "product_name",
        "category",
        "brand",
        "discounted_price",
        "retrieval_text",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing required columns: {missing}")

    if expected_count is not None and len(df) != expected_count:
        raise ValueError(
            f"Expected {expected_count} products, found {len(df)} in {path}"
        )

    distinct_ids = df["product_id"].nunique()
    if distinct_ids != len(df):
        raise ValueError(
            f"Duplicate product IDs detected: {len(df) - distinct_ids} duplicates"
        )

    empty_texts = df["retrieval_text"].isna() | (df["retrieval_text"].str.strip() == "")
    if empty_texts.any():
        empty_count = int(empty_texts.sum())
        raise ValueError(f"Dataset contains {empty_count} empty or null retrieval_text entries")

    return df


class TFIDFIndex:
    """Lexical retrieval engine based on TF-IDF vectorization and sparse cosine similarity."""

    def __init__(self, config: TFIDFConfig | None = None) -> None:
        self.config = config or TFIDFConfig()
        self.vectorizer: TfidfVectorizer | None = None
        self.document_matrix: sp.csr_matrix | None = None
        self.metadata_df: pd.DataFrame | None = None
        self.product_ids: list[str] = []
        self._fit_time_seconds: float = 0.0

    @property
    def is_fitted(self) -> bool:
        """Check whether the vectorizer and document matrix are fitted."""
        return (
            self.vectorizer is not None
            and self.document_matrix is not None
            and self.metadata_df is not None
            and len(self.product_ids) > 0
        )

    def fit(
        self,
        df: pd.DataFrame,
        text_column: str = "retrieval_text",
    ) -> TFIDFIndex:
        """Fit the TF-IDF vectorizer on the given product DataFrame.

        Args:
            df: DataFrame containing products and text_column.
            text_column: Column name to vectorize (default: 'retrieval_text').

        Returns:
            self: The fitted TFIDFIndex instance.
        """
        logger.info("Fitting TF-IDF index on %d documents...", len(df))
        t_start = time.perf_counter()

        # Build clean metadata subset aligned to document rows
        metadata_cols = [
            "product_id",
            "product_name",
            "category",
            "brand",
            "discounted_price",
        ]
        optional_cols = ["retail_price", "rating", "pid"]
        for c in optional_cols:
            if c in df.columns:
                metadata_cols.append(c)

        self.metadata_df = df[metadata_cols].copy().reset_index(drop=True)
        self.product_ids = self.metadata_df["product_id"].astype(str).tolist()

        # Initialize scikit-learn TfidfVectorizer with configured parameters
        self.vectorizer = TfidfVectorizer(
            ngram_range=self.config.ngram_range,
            min_df=self.config.min_df,
            max_df=self.config.max_df,
            max_features=self.config.max_features,
            sublinear_tf=self.config.sublinear_tf,
            use_idf=self.config.use_idf,
            smooth_idf=self.config.smooth_idf,
            norm=self.config.norm,
            lowercase=self.config.lowercase,
            token_pattern=self.config.token_pattern,
        )

        texts = df[text_column].astype(str).tolist()
        matrix = self.vectorizer.fit_transform(texts)

        # Ensure CSR format for fast row slicing and dot products
        if not sp.isspmatrix_csr(matrix):
            matrix = matrix.tocsr()
        self.document_matrix = matrix

        self._fit_time_seconds = time.perf_counter() - t_start
        stats = self.get_statistics()
        logger.info(
            "TF-IDF index fitted in %.3fs: %d docs, %d vocab features, %.2f%% sparsity",
            self._fit_time_seconds,
            stats["total_documents"],
            stats["vocabulary_size"],
            stats["sparsity_pct"],
        )
        return self

    def transform_query(self, query: str) -> sp.csr_matrix:
        """Transform a natural-language query into a sparse TF-IDF vector.

        Args:
            query: Query string.

        Returns:
            Sparse 1 x V CSR matrix representing the query.

        Raises:
            RuntimeError: If index is not fitted.
            ValueError: If query is not a valid string.
        """
        if not self.is_fitted:
            raise RuntimeError("TFIDFIndex must be fitted before transforming queries.")

        if not isinstance(query, str):
            raise ValueError(f"Query must be a string, received: {type(query).__name__}")

        clean_q = query.strip()
        if not clean_q:
            # Return a zero sparse vector with correct dimension
            return sp.csr_matrix((1, len(self.vectorizer.vocabulary_)), dtype=np.float64)

        return self.vectorizer.transform([clean_q])

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Search the catalog using TF-IDF vectorization and cosine similarity.

        Zero-score policy:
            If a query is empty, whitespace-only, or contains exclusively
            out-of-vocabulary terms (i.e. zero term overlap with the corpus),
            the engine returns an empty list [] rather than returning arbitrary
            products with similarity 0.0.

        Deterministic tie-breaking:
            When candidate similarity scores are identical, candidates are
            broken deterministically by score DESC, then product_id ASC.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of top candidates to return (default: 5).

        Returns:
            List of SearchResult objects sorted by relevance.
        """
        if not self.is_fitted:
            raise RuntimeError("TFIDFIndex must be fitted before executing search.")

        if top_k <= 0:
            raise ValueError(f"top_k must be a positive integer, got: {top_k}")

        clean_q = str(query).strip() if query is not None else ""
        if not clean_q:
            return []

        # 1. Transform query
        q_vec = self.vectorizer.transform([clean_q])

        # If query vector has zero non-zero components, all terms were OOV
        if q_vec.nnz == 0:
            return []

        # 2. Compute Cosine Similarity via sparse dot product
        # Both document matrix and query vector are L2-normalized, so dot product = cosine similarity
        raw_scores = self.document_matrix.dot(q_vec.T).toarray().ravel()

        # 3. Filter positive scores
        positive_indices = np.flatnonzero(raw_scores > 0.0)
        if len(positive_indices) == 0:
            return []

        pos_scores = raw_scores[positive_indices]

        # 4. Rank candidates deterministically
        # Tie breaking: primary key (-score), secondary key (product_id)
        candidate_ids = [self.product_ids[idx] for idx in positive_indices]
        order = sorted(
            range(len(positive_indices)),
            key=lambda i: (-pos_scores[i], candidate_ids[i]),
        )

        selected_order = order[:top_k]
        results: list[SearchResult] = []

        for rank, ord_idx in enumerate(selected_order, start=1):
            doc_idx = int(positive_indices[ord_idx])
            row = self.metadata_df.iloc[doc_idx]
            score = float(pos_scores[ord_idx])

            extra_metadata = {}
            for col in ["retail_price", "rating", "pid"]:
                if col in row and pd.notna(row[col]):
                    extra_metadata[col] = row[col]

            results.append(
                SearchResult(
                    rank=rank,
                    product_id=str(row["product_id"]),
                    product_name=str(row["product_name"]),
                    category=str(row["category"]),
                    brand=str(row["brand"]) if pd.notna(row["brand"]) else None,
                    discounted_price=float(row["discounted_price"]),
                    tfidf_score=score,
                    metadata=extra_metadata,
                )
            )

        return results

    def get_statistics(self) -> dict[str, Any]:
        """Compute structural statistics of the fitted index."""
        if not self.is_fitted:
            return {
                "is_fitted": False,
                "total_documents": 0,
                "vocabulary_size": 0,
            }

        shape = self.document_matrix.shape
        nnz = int(self.document_matrix.nnz)
        total_cells = shape[0] * shape[1]
        sparsity_pct = (1.0 - (nnz / total_cells)) * 100.0 if total_cells > 0 else 0.0

        # Memory estimation: CSR data array + indices array + indptr array
        data_bytes = self.document_matrix.data.nbytes
        indices_bytes = self.document_matrix.indices.nbytes
        indptr_bytes = self.document_matrix.indptr.nbytes
        total_bytes = data_bytes + indices_bytes + indptr_bytes

        return {
            "is_fitted": True,
            "total_documents": int(shape[0]),
            "vocabulary_size": int(shape[1]),
            "matrix_shape": [int(shape[0]), int(shape[1])],
            "nonzero_elements": nnz,
            "sparsity_pct": round(sparsity_pct, 4),
            "memory_bytes_approx": total_bytes,
            "memory_mb_approx": round(total_bytes / (1024 * 1024), 2),
            "fit_time_seconds": round(self._fit_time_seconds, 4),
            "config": self.config.to_dict(),
        }

    def save(
        self,
        target_dir: Path | str = DEFAULT_TFIDF_ARTIFACT_DIR,
        manifest_extra: dict[str, Any] | None = None,
    ) -> Path:
        """Persist fitted vectorizer, sparse matrix, metadata, and manifest to disk.

        Args:
            target_dir: Directory where artifacts will be saved.
            manifest_extra: Optional extra fields to include in manifest.json.

        Returns:
            Resolved Path of the target directory.
        """
        if not self.is_fitted:
            raise RuntimeError("Cannot save an unfitted TFIDFIndex.")

        out_dir = Path(target_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        vectorizer_path = out_dir / "tfidf_vectorizer.joblib"
        matrix_path = out_dir / "tfidf_matrix.npz"
        metadata_path = out_dir / "product_metadata.parquet"
        manifest_path = out_dir / "tfidf_manifest.json"

        # 1. Save vectorizer
        joblib.dump(self.vectorizer, vectorizer_path, compress=3)

        # 2. Save sparse matrix
        sp.save_npz(matrix_path, self.document_matrix)

        # 3. Save aligned metadata DataFrame
        self.metadata_df.to_parquet(metadata_path, index=False)

        # 4. Generate manifest
        stats = self.get_statistics()
        manifest: dict[str, Any] = {
            "phase": "6.0",
            "artifact_type": "tfidf_baseline_index",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "statistics": stats,
            "files": {
                "vectorizer": vectorizer_path.name,
                "matrix": matrix_path.name,
                "metadata": metadata_path.name,
            },
        }
        if manifest_extra:
            manifest.update(manifest_extra)

        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("Saved TF-IDF artifacts to %s", out_dir)
        return out_dir

    @classmethod
    def load(cls, source_dir: Path | str = DEFAULT_TFIDF_ARTIFACT_DIR) -> TFIDFIndex:
        """Load a persisted TFIDFIndex from an artifact directory.

        Args:
            source_dir: Directory containing saved artifacts.

        Returns:
            Reconstructed, ready-to-use TFIDFIndex instance.
        """
        s_dir = Path(source_dir).resolve()
        if not s_dir.exists():
            raise FileNotFoundError(f"TF-IDF artifact directory does not exist: {s_dir}")

        vectorizer_path = s_dir / "tfidf_vectorizer.joblib"
        matrix_path = s_dir / "tfidf_matrix.npz"
        metadata_path = s_dir / "product_metadata.parquet"
        manifest_path = s_dir / "tfidf_manifest.json"

        for p in [vectorizer_path, matrix_path, metadata_path, manifest_path]:
            if not p.exists():
                raise FileNotFoundError(f"Missing required TF-IDF artifact: {p}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cfg_dict = manifest.get("statistics", {}).get("config", {})
        config = TFIDFConfig.from_dict(cfg_dict) if cfg_dict else TFIDFConfig()

        index = cls(config=config)
        index.vectorizer = joblib.load(vectorizer_path)
        index.document_matrix = sp.load_npz(matrix_path)
        if not sp.isspmatrix_csr(index.document_matrix):
            index.document_matrix = index.document_matrix.tocsr()

        index.metadata_df = pd.read_parquet(metadata_path)
        index.product_ids = index.metadata_df["product_id"].astype(str).tolist()

        # Validate dimensional alignment
        if index.document_matrix.shape[0] != len(index.product_ids):
            raise ValueError(
                f"Row mismatch: matrix has {index.document_matrix.shape[0]} rows, "
                f"but metadata has {len(index.product_ids)} items."
            )

        logger.info(
            "Loaded TFIDFIndex from %s: %d docs, %d vocab",
            s_dir,
            len(index.product_ids),
            len(index.vectorizer.vocabulary_),
        )
        return index


# ==============================================================================
# PIPELINE ORCHESTRATOR & BENCHMARKING
# ==============================================================================

def run_retrieval_scenarios(
    index: TFIDFIndex,
    scenarios: list[dict[str, str]] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Execute standard representative retrieval scenarios.

    Args:
        index: Fitted TFIDFIndex.
        scenarios: List of scenario dictionaries with 'scenario_id', 'description', 'query'.
        top_k: Number of candidates to retrieve.

    Returns:
        List of scenario execution results with returned candidates.
    """
    default_scenarios = [
        {
            "scenario_id": "SCENARIO_1_EXACT_KEYWORD",
            "description": "Exact keyword match for technical hardware accessories",
            "query": "wireless bluetooth keyboard",
        },
        {
            "scenario_id": "SCENARIO_2_TECHNICAL_TERMS",
            "description": "Multiple technical compound terms for portable electronics",
            "query": "portable usb storage device",
        },
        {
            "scenario_id": "SCENARIO_3_BRAND_SPECIFIC",
            "description": "Specific brand matching from catalog",
            "query": "Allure Auto",
        },
        {
            "scenario_id": "SCENARIO_4_CATEGORY_ORIENTED",
            "description": "Category-oriented search with product style",
            "query": "Footwear casual running shoes",
        },
        {
            "scenario_id": "SCENARIO_5_SYNONYM_MISMATCH",
            "description": "Colloquial synonym query testing lexical limitation",
            "query": "sneakers for jogging",
        },
        {
            "scenario_id": "SCENARIO_6_NATURAL_LANGUAGE_INTENT",
            "description": "Conversational shopper request with descriptive words",
            "query": "I need comfortable footwear for everyday walking",
        },
        {
            "scenario_id": "SCENARIO_7_NUMERIC_CONSTRAINT",
            "description": "Numeric budget constraint demonstrating lexical inability to filter",
            "query": "laptop under 500",
        },
        {
            "scenario_id": "SCENARIO_8_OUT_OF_VOCABULARY",
            "description": "Out-of-vocabulary query with zero catalog term overlap",
            "query": "zyxwvutsrqponmlkjihgfedcba nonexistentgibberish",
        },
    ]

    test_scenarios = scenarios or default_scenarios
    results = []

    for sc in test_scenarios:
        q = sc["query"]
        t0 = time.perf_counter()
        candidates = index.search(q, top_k=top_k)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        results.append({
            "scenario_id": sc["scenario_id"],
            "description": sc["description"],
            "query": q,
            "latency_ms": round(latency_ms, 3),
            "returned_count": len(candidates),
            "candidates": [c.to_dict() for c in candidates],
        })

    return results


def benchmark_tfidf_latency(
    index: TFIDFIndex,
    queries: Sequence[str] | None = None,
    num_iterations: int = 10,
    warmup_runs: int = 2,
    top_k: int = 5,
) -> dict[str, Any]:
    """Measure latency distribution across representative queries.

    Args:
        index: Fitted TFIDFIndex.
        queries: Queries to benchmark.
        num_iterations: Number of measured repetitions per query.
        warmup_runs: Unmeasured warm-up iterations.
        top_k: Top-K candidates.

    Returns:
        Latency summary statistics in milliseconds.
    """
    bench_queries = queries or [
        "wireless bluetooth keyboard",
        "portable usb storage device",
        "Allure Auto car mat",
        "running shoes",
        "digital watch leather strap",
        "kitchen dining container",
        "laptop under 500",
        "comfortable footwear for everyday walking",
    ]

    # Warm-up runs
    for _ in range(warmup_runs):
        for q in bench_queries:
            index.search(q, top_k=top_k)

    # Measured runs
    latencies: list[float] = []
    for _ in range(num_iterations):
        for q in bench_queries:
            t0 = time.perf_counter()
            index.search(q, top_k=top_k)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000.0)

    return {
        "num_queries": len(bench_queries),
        "iterations_per_query": num_iterations,
        "total_measured_calls": len(latencies),
        "mean_latency_ms": round(float(np.mean(latencies)), 3),
        "p50_latency_ms": round(float(np.percentile(latencies, 50)), 3),
        "p95_latency_ms": round(float(np.percentile(latencies, 95)), 3),
        "min_latency_ms": round(float(np.min(latencies)), 3),
        "max_latency_ms": round(float(np.max(latencies)), 3),
    }


def build_tfidf_baseline(
    parquet_path: Path | str = CANONICAL_PRODUCTS_PATH,
    artifact_dir: Path | str = DEFAULT_TFIDF_ARTIFACT_DIR,
    report_path: Path | str = DEFAULT_TFIDF_REPORT_PATH,
    config: TFIDFConfig | None = None,
) -> tuple[TFIDFIndex, dict[str, Any]]:
    """Execute complete Phase 6 build pipeline.

    1. Loads canonical products.parquet.
    2. Fits TFIDFIndex on retrieval_text.
    3. Persists artifacts to artifact_dir.
    4. Runs baseline retrieval experiments.
    5. Benchmarks latency distribution.
    6. Validates artifact reload reproducibility.
    7. Generates machine-readable report JSON.

    Returns:
        Tuple of (fitted_index, report_dict).
    """
    logger.info("=" * 74)
    logger.info("STARTING PHASE 6: TF-IDF BASELINE RETRIEVAL ENGINE BUILD")
    logger.info("=" * 74)

    t_pipeline_start = time.perf_counter()
    p_path = Path(parquet_path).resolve()
    a_dir = Path(artifact_dir).resolve()
    r_path = Path(report_path).resolve()

    # 1. Load canonical dataset
    t_load_0 = time.perf_counter()
    df = load_canonical_products(p_path)
    load_time_seconds = time.perf_counter() - t_load_0

    # 2. Fit TFIDFIndex
    index = TFIDFIndex(config=config)
    index.fit(df, text_column="retrieval_text")
    stats = index.get_statistics()

    # 3. Persist artifacts
    source_hash = hashlib.sha256(p_path.read_bytes()).hexdigest()
    index.save(
        target_dir=a_dir,
        manifest_extra={"source_dataset_sha256": source_hash, "source_dataset_path": str(p_path)},
    )

    # 4. Verify artifact reload reproducibility
    t_reload_0 = time.perf_counter()
    reloaded_index = TFIDFIndex.load(a_dir)
    reload_time_seconds = time.perf_counter() - t_reload_0

    # Check identical search outputs between memory and reloaded index
    test_q = "wireless bluetooth keyboard"
    orig_results = index.search(test_q, top_k=5)
    reloaded_results = reloaded_index.search(test_q, top_k=5)

    orig_tuples = [(r.product_id, round(r.tfidf_score, 5)) for r in orig_results]
    reloaded_tuples = [(r.product_id, round(r.tfidf_score, 5)) for r in reloaded_results]
    reload_verified = orig_tuples == reloaded_tuples

    if not reload_verified:
        logger.error("Artifact reload produced mismatched results! Orig: %s, Reloaded: %s", orig_tuples, reloaded_tuples)
    else:
        logger.info("Artifact reload reproducibility verified: 100%% identical rankings")

    # 5. Execute retrieval scenarios
    scenarios_output = run_retrieval_scenarios(reloaded_index, top_k=5)

    # 6. Benchmark latency
    benchmarks = benchmark_tfidf_latency(reloaded_index, num_iterations=15, top_k=5)

    total_pipeline_seconds = time.perf_counter() - t_pipeline_start

    # Assemble comprehensive report
    report: dict[str, Any] = {
        "phase": "6.0",
        "objective": "TF-IDF Baseline Lexical Product Retrieval Engine",
        "overall_status": "PASS" if reload_verified else "FAIL",
        "execution_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_dataset": {
            "path": str(p_path),
            "sha256": source_hash,
            "total_products": len(df),
            "categories_count": int(df["category"].nunique()),
            "load_time_seconds": round(load_time_seconds, 3),
        },
        "vectorizer_configuration": index.config.to_dict(),
        "corpus_statistics": {
            "total_documents": stats["total_documents"],
            "vocabulary_size": stats["vocabulary_size"],
            "matrix_shape": stats["matrix_shape"],
            "nonzero_elements": stats["nonzero_elements"],
            "sparsity_pct": stats["sparsity_pct"],
            "memory_mb_approx": stats["memory_mb_approx"],
            "fit_time_seconds": stats["fit_time_seconds"],
        },
        "artifact_persistence": {
            "directory": str(a_dir),
            "reload_verified": reload_verified,
            "reload_time_seconds": round(reload_time_seconds, 4),
        },
        "latency_benchmarks": benchmarks,
        "retrieval_scenarios": scenarios_output,
        "performance": {
            "total_pipeline_seconds": round(total_pipeline_seconds, 3),
        },
        "readiness_for_phase7": {
            "status": "READY",
            "role": "Baseline 1 established for lexical vs. dense semantic comparison",
        },
    }

    r_path.parent.mkdir(parents=True, exist_ok=True)
    temp_report = r_path.parent / f".tmp_{r_path.stem}_{os.getpid()}_{int(time.time())}.json"
    temp_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temp_report.replace(r_path)
    logger.info("Phase 6 execution report saved to %s", r_path)

    return reloaded_index, report
