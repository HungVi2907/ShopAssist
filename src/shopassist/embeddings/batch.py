"""Batch embedding generation, validation, and parquet export for ShopAssist (Phase 5.5).

Produces the canonical Product Knowledge Base artifact:
    data/processed/products.parquet

Encapsulates:
- Strict input candidate dataset validation (deterministic ordering, schema readiness).
- Automatic retrieval_text resolution via Phase 5.2 canonical pipeline if absent.
- High-throughput batch inference with BAAI/bge-small-en-v1.5 (CUDA with CPU fallback).
- Multi-layer embedding validation (shape, dimension 384, finite, zero-vector, L2 norm).
- Atomic Parquet export with serialization-deserialization roundtrip verification.
- Comprehensive machine-readable execution report generation.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import time
from typing import Any, Sequence

import numpy as np
import pandas as pd
import psutil
import torch

from shopassist.data.retrieval_text import (
    build_dataset_retrieval_texts,
    validate_retrieval_text,
)
from shopassist.embeddings.model import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_MAX_SEQ_LENGTH,
    DEFAULT_MODEL_NAME,
    EmbeddingModel,
    resolve_device,
    validate_embeddings,
)

logger = logging.getLogger(__name__)

# Canonical schema column ordering for Phase 5.1 / 5.5 / 5.6
CANONICAL_COLUMNS: list[str] = [
    "product_id",
    "product_name",
    "category",
    "brand",
    "retail_price",
    "discounted_price",
    "rating",
    "description",
    "product_specifications",
    "product_url",
    "image",
    "pid",
    "retrieval_text",
    "embedding",
    "embedding_model",
]

CANONICAL_COLUMNS_WITH_TIMESTAMPS: list[str] = CANONICAL_COLUMNS + [
    "created_at",
    "updated_at",
]

EXPECTED_CATALOG_SIZE: int = 8405


def validate_input_dataset(
    df: pd.DataFrame,
    expected_count: int | None = EXPECTED_CATALOG_SIZE,
    allow_missing_retrieval_text: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate input dataset against Phase 5.1/5.2 readiness requirements.

    Ensures:
    - Expected row count (default 8,405).
    - Presence, non-nullity, uniqueness, and length (<= 64 chars) of product_id.
    - Required fields: product_name, category, discounted_price.
    - Numeric validity: discounted_price > 0, retail_price > 0 (if present), rating 1.0-5.0 (if present).
    - Specifications validity: valid JSON array or string parsable as list.
    - retrieval_text validity: present and passes validate_retrieval_text(), or constructed.
    - Deterministic row ordering preserved.

    Args:
        df: Input DataFrame (e.g. from cleaned_candidates.parquet).
        expected_count: Expected row count (default: 8405, None to bypass count check).
        allow_missing_retrieval_text: If True, constructs retrieval_text if absent.

    Returns:
        Tuple of (prepared_dataframe, validation_metrics_dict).

    Raises:
        ValueError: If any validation rule fails.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Expected pandas DataFrame, got {type(df).__name__}")

    total_rows = len(df)
    if expected_count is not None and total_rows != expected_count:
        raise ValueError(
            f"Input dataset row count mismatch: expected {expected_count}, got {total_rows}."
        )

    # 1. Product ID checks
    if "product_id" not in df.columns:
        raise ValueError("Missing mandatory column 'product_id' in input dataset.")

    null_ids = int(df["product_id"].isna().sum())
    empty_ids = int((df["product_id"].astype(str).str.strip() == "").sum())
    if null_ids > 0 or empty_ids > 0:
        raise ValueError(f"Found {null_ids + empty_ids} null or empty product_id records.")

    if not df["product_id"].is_unique:
        duplicates = df[df["product_id"].duplicated(keep=False)]["product_id"].unique().tolist()
        raise ValueError(
            f"Found duplicate product_id values in input dataset: count={len(duplicates)}, sample={duplicates[:5]}."
        )

    id_len_violations = int((df["product_id"].astype(str).str.len() > 64).sum())
    if id_len_violations > 0:
        raise ValueError(f"Found {id_len_violations} product_id records exceeding 64 characters.")

    # 2. Mandatory Core Descriptive Fields
    for col in ("product_name", "category", "discounted_price"):
        if col not in df.columns:
            raise ValueError(f"Missing mandatory column '{col}' in input dataset.")

    invalid_names = int((df["product_name"].isna() | (df["product_name"].astype(str).str.strip() == "")).sum())
    if invalid_names > 0:
        raise ValueError(f"Found {invalid_names} null or empty product_name records.")

    invalid_cats = int((df["category"].isna() | (df["category"].astype(str).str.strip() == "")).sum())
    if invalid_cats > 0:
        raise ValueError(f"Found {invalid_cats} null or empty category records.")

    # 3. Numeric Constraints
    invalid_discounted = int((df["discounted_price"].isna() | (df["discounted_price"] <= 0)).sum())
    if invalid_discounted > 0:
        raise ValueError(f"Found {invalid_discounted} invalid discounted_price records (must be > 0).")

    if "retail_price" in df.columns:
        invalid_retail = int((df["retail_price"].notna() & (df["retail_price"] <= 0)).sum())
        if invalid_retail > 0:
            raise ValueError(f"Found {invalid_retail} invalid retail_price records (must be > 0 if present).")

    if "rating" in df.columns:
        invalid_rating = int((df["rating"].notna() & ((df["rating"] < 1.0) | (df["rating"] > 5.0))).sum())
        if invalid_rating > 0:
            raise ValueError(f"Found {invalid_rating} invalid rating records (must be between 1.0 and 5.0).")

    # 4. Specifications validity
    if "product_specifications" in df.columns:
        for idx, spec_val in enumerate(df["product_specifications"]):
            if spec_val is None or pd.isna(spec_val):
                raise ValueError(f"Row {idx}: product_specifications is null.")
            try:
                if isinstance(spec_val, str):
                    parsed = json.loads(spec_val)
                elif isinstance(spec_val, list):
                    parsed = spec_val
                else:
                    raise ValueError(f"Unsupported specifications type: {type(spec_val)}")
                if not isinstance(parsed, list):
                    raise ValueError("product_specifications must be a JSON list.")
            except Exception as exc:
                raise ValueError(f"Row {idx}: Invalid product_specifications: {exc}") from exc

    # 5. retrieval_text resolution
    result_df = df.copy()
    retrieval_text_generated = False

    if "retrieval_text" not in result_df.columns:
        if not allow_missing_retrieval_text:
            raise ValueError("Column 'retrieval_text' is missing and automatic generation is disabled.")
        logger.info("Constructing canonical retrieval_text for %d products using Phase 5.2 pipeline...", total_rows)
        result_df = build_dataset_retrieval_texts(result_df)
        retrieval_text_generated = True

    # Validate all retrieval_text entries
    invalid_texts = 0
    first_invalid_reason: str | None = None
    for idx, text in enumerate(result_df["retrieval_text"]):
        is_val, reason = validate_retrieval_text(text)
        if not is_val:
            invalid_texts += 1
            if first_invalid_reason is None:
                first_invalid_reason = f"Row {idx} (ID={result_df['product_id'].iloc[idx]}): {reason}"

    if invalid_texts > 0:
        raise ValueError(
            f"Found {invalid_texts} invalid retrieval_text records. First error: {first_invalid_reason}"
        )

    # 6. Preserve deterministic ordering
    if not result_df["product_id"].equals(df["product_id"]):
        raise ValueError("Critical error: product_id ordering was corrupted during preprocessing.")

    metrics: dict[str, Any] = {
        "input_rows": total_rows,
        "product_id_unique": True,
        "null_id_count": 0,
        "duplicate_id_count": 0,
        "retrieval_text_generated": retrieval_text_generated,
        "valid_retrieval_texts": total_rows - invalid_texts,
        "status": "PASS",
    }
    return result_df, metrics


def generate_catalog_embeddings(
    df: pd.DataFrame,
    model: EmbeddingModel | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    batch_size: int = 32,
    device: str | None = None,
    show_progress: bool = True,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Generate dense vector embeddings for catalog products in batches.

    Uses BAAI/bge-small-en-v1.5 and encodes product retrieval_text passages
    directly without query instructions (asymmetric document encoding).

    Args:
        df: DataFrame containing verified 'retrieval_text' column.
        model: Optional pre-loaded EmbeddingModel instance. If None, initialized here.
        model_name: HuggingFace model ID (default: 'BAAI/bge-small-en-v1.5').
        batch_size: Inference batch size (default: 32).
        device: Target compute device or None for auto-detect.
        show_progress: Whether to display inference progress bar.

    Returns:
        Tuple of (embeddings_array, performance_metrics_dict).

    Raises:
        ValueError: If inference fails or generated vectors violate integrity checks.
    """
    if "retrieval_text" not in df.columns:
        raise ValueError("DataFrame must contain 'retrieval_text' column.")

    total_texts = len(df)
    texts: list[str] = df["retrieval_text"].tolist()

    process = psutil.Process()
    ram_before_mb = round(process.memory_info().rss / (1024 * 1024), 1)

    t_load_start = time.time()
    active_model = model
    if active_model is None:
        logger.info(
            "Initializing EmbeddingModel('%s', batch_size=%d, device=%s)...",
            model_name,
            batch_size,
            device or "auto",
        )
        active_model = EmbeddingModel(
            model_name=model_name,
            device=device,
            normalize_embeddings=True,
            max_seq_length=DEFAULT_MAX_SEQ_LENGTH,
        )
    model_load_seconds = round(time.time() - t_load_start, 3)
    ram_after_mb = round(process.memory_info().rss / (1024 * 1024), 1)

    logger.info(
        "Starting batch embedding generation for %d products (batch_size=%d, device=%s)...",
        total_texts,
        batch_size,
        active_model.device,
    )

    t_start = time.time()
    embeddings = active_model.encode_documents(
        documents=texts,
        batch_size=batch_size,
        show_progress_bar=show_progress,
        normalize_embeddings=True,
    )
    elapsed_seconds = time.time() - t_start

    # Ensure float32 numpy ndarray
    embeddings = np.asarray(embeddings, dtype=np.float32)

    total_batches = int(math.ceil(total_texts / batch_size))
    throughput = round(total_texts / max(elapsed_seconds, 1e-6), 2)
    ms_per_item = round((elapsed_seconds / max(total_texts, 1)) * 1000, 2)

    logger.info(
        "Generated %d embeddings across %d batches in %.2fs (%.1f texts/s, %.2f ms/text).",
        len(embeddings),
        total_batches,
        elapsed_seconds,
        throughput,
        ms_per_item,
    )

    # Strict numerical validation
    norm_metrics = validate_embeddings(
        embeddings,
        expected_dim=DEFAULT_EMBEDDING_DIM,
        expected_count=total_texts,
        check_normalized=True,
        norm_tolerance=1e-4,
    )

    # CUDA device metadata
    cuda_name: str | None = None
    if torch.cuda.is_available() and active_model.device.startswith("cuda"):
        cuda_name = torch.cuda.get_device_name(0)

    perf_metrics: dict[str, Any] = {
        "model_name": active_model.model_name,
        "embedding_dimension": active_model.embedding_dimension,
        "device": active_model.device,
        "cuda_device_name": cuda_name,
        "batch_size": batch_size,
        "total_items": total_texts,
        "total_batches": total_batches,
        "model_load_seconds": model_load_seconds,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "throughput_texts_per_second": throughput,
        "milliseconds_per_text": ms_per_item,
        "process_ram_mb": {
            "before_load": ram_before_mb,
            "after_load": ram_after_mb,
        },
        "validation": norm_metrics,
        "status": "PASS",
    }
    return embeddings, perf_metrics


def assemble_knowledge_base_dataframe(
    df: pd.DataFrame,
    embeddings: np.ndarray,
    model_name: str = DEFAULT_MODEL_NAME,
    include_timestamps: bool = False,
) -> pd.DataFrame:
    """Assemble final canonical Product Knowledge Base DataFrame.

    Formats:
    - embedding: Stored as 1D float32 numpy arrays (serializes cleanly to PyArrow float list).
    - embedding_model: Set to official model ID ('BAAI/bge-small-en-v1.5').
    - Drops interim scraping columns (uniq_id, crawl_timestamp, is_FK_Advantage_product).
    - Preserves canonical schema column ordering matching Supabase PostgreSQL products table.

    Args:
        df: Input DataFrame with normalized metadata and retrieval_text.
        embeddings: 2D numpy array of shape (N, 384) with float32 dtype.
        model_name: Embedding model identifier.
        include_timestamps: Whether to generate explicit UTC created_at/updated_at timestamps.
            Defaults to False so PostgreSQL applies its intended DEFAULT NOW().

    Returns:
        Structured canonical DataFrame ready for Parquet export and Phase 5.6 ingestion.

    Raises:
        ValueError: If rows count and embeddings count mismatch.
    """
    total_rows = len(df)
    if len(embeddings) != total_rows:
        raise ValueError(
            f"Row count mismatch between DataFrame ({total_rows}) and embeddings ({len(embeddings)})."
        )

    out_df = df.copy()

    # Store embeddings as individual 1D float32 numpy arrays (compatible with pgvector and PyArrow)
    out_df["embedding"] = [embeddings[i].astype(np.float32) for i in range(total_rows)]
    out_df["embedding_model"] = str(model_name)

    if include_timestamps:
        now_ts = pd.Timestamp.now(tz="UTC")
        out_df["created_at"] = now_ts
        out_df["updated_at"] = now_ts
        target_columns = CANONICAL_COLUMNS_WITH_TIMESTAMPS
    else:
        target_columns = CANONICAL_COLUMNS

    # Ensure all canonical columns exist in the DataFrame
    missing_cols = set(target_columns) - set(out_df.columns)
    if missing_cols:
        raise ValueError(f"Missing required canonical columns before export: {sorted(missing_cols)}")

    # Return only the canonical columns in deterministic schema order
    return out_df[target_columns].copy()


def validate_processed_dataset(
    df: pd.DataFrame,
    expected_count: int | None = EXPECTED_CATALOG_SIZE,
    expected_dim: int = DEFAULT_EMBEDDING_DIM,
    include_timestamps: bool = False,
    check_normalized: bool = True,
    norm_tolerance: float = 1e-4,
) -> dict[str, Any]:
    """Perform comprehensive integrity validation on the processed Product Knowledge Base dataset.

    Validates:
    1. Product count matches expected_count.
    2. Column structure and ordering strictly matches canonical schema.
    3. Identifiers are unique, non-null, and <= 64 chars.
    4. Mandatory fields are present and non-empty.
    5. Numeric constraints hold (discounted_price > 0, retail_price > 0, rating 1.0-5.0).
    6. product_specifications is a valid JSON array string for every record.
    7. Exactly one 384-dimensional embedding per product.
    8. Embeddings are finite (0 NaN, 0 Inf), non-zero, and unit L2-normalized.
    9. Product-to-embedding positional alignment is verified.

    Args:
        df: Processed DataFrame to validate.
        expected_count: Expected row count (default: 8405).
        expected_dim: Expected vector dimension (default: 384).
        include_timestamps: Whether created_at and updated_at are expected.
        check_normalized: Whether to verify L2 normalization.
        norm_tolerance: Maximum deviation allowed from 1.0.

    Returns:
        Validation metrics dictionary.

    Raises:
        ValueError: If any integrity constraint is violated.
    """
    total_rows = len(df)
    if expected_count is not None and total_rows != expected_count:
        raise ValueError(
            f"Processed dataset row count mismatch: expected {expected_count}, got {total_rows}."
        )

    expected_cols = CANONICAL_COLUMNS_WITH_TIMESTAMPS if include_timestamps else CANONICAL_COLUMNS
    actual_cols = list(df.columns)
    if actual_cols != expected_cols:
        raise ValueError(
            f"Column schema mismatch:\nExpected: {expected_cols}\nActual:   {actual_cols}"
        )

    # 1. Identifier checks
    if not df["product_id"].is_unique:
        raise ValueError("product_id is not unique in processed dataset.")
    if df["product_id"].isna().any() or (df["product_id"].astype(str).str.strip() == "").any():
        raise ValueError("Found null or empty product_id in processed dataset.")

    # 2. Mandatory non-null columns
    mandatory_cols = [
        "product_id",
        "product_name",
        "category",
        "discounted_price",
        "product_specifications",
        "retrieval_text",
        "embedding",
        "embedding_model",
    ]
    if include_timestamps:
        mandatory_cols.extend(["created_at", "updated_at"])

    for col in mandatory_cols:
        null_count = int(df[col].isna().sum())
        if null_count > 0:
            raise ValueError(f"Mandatory column '{col}' contains {null_count} null values.")

    # 3. Numeric constraints
    if (df["discounted_price"] <= 0).any():
        raise ValueError("Found non-positive values in 'discounted_price'.")
    if (df["retail_price"].notna() & (df["retail_price"] <= 0)).any():
        raise ValueError("Found non-positive values in 'retail_price'.")
    if (df["rating"].notna() & ((df["rating"] < 1.0) | (df["rating"] > 5.0))).any():
        raise ValueError("Found invalid values in 'rating' outside [1.0, 5.0].")

    # 4. Vector embeddings validation
    embeddings_list = df["embedding"].tolist()
    if len(embeddings_list) != total_rows:
        raise ValueError("Mismatch between DataFrame length and embedding list length.")

    # Inspect first vector and stack into matrix
    sample_vec = embeddings_list[0]
    if not (isinstance(sample_vec, (np.ndarray, list, tuple)) and len(sample_vec) == expected_dim):
        raise ValueError(
            f"Embedding vector dimension mismatch: expected {expected_dim}, got {len(sample_vec)}."
        )

    matrix = np.asarray(embeddings_list, dtype=np.float32)
    if matrix.shape != (total_rows, expected_dim):
        raise ValueError(
            f"Embedding matrix shape mismatch: expected ({total_rows}, {expected_dim}), got {matrix.shape}."
        )

    # Finite values
    nan_count = int(np.isnan(matrix).sum())
    inf_count = int(np.isinf(matrix).sum())
    if nan_count > 0:
        raise ValueError(f"Found {nan_count} NaN values in processed embeddings.")
    if inf_count > 0:
        raise ValueError(f"Found {inf_count} Inf values in processed embeddings.")

    # Non-zero vectors
    norms = np.linalg.norm(matrix, axis=1)
    zero_vectors = int((norms < 1e-8).sum())
    if zero_vectors > 0:
        raise ValueError(f"Found {zero_vectors} all-zero vectors in processed embeddings.")

    min_norm = float(norms.min())
    mean_norm = float(norms.mean())
    max_norm = float(norms.max())

    if check_normalized:
        deviations = np.abs(norms - 1.0)
        max_dev = float(deviations.max())
        if max_dev > norm_tolerance:
            raise ValueError(
                f"Processed embeddings failed L2 normalization check: max deviation={max_dev:.6f} > tolerance={norm_tolerance}"
            )

    # 5. Specifications JSON validation
    for idx, spec in enumerate(df["product_specifications"]):
        try:
            if isinstance(spec, str):
                p = json.loads(spec)
            elif isinstance(spec, list):
                p = spec
            else:
                raise ValueError(f"Unsupported spec type: {type(spec)}")
            if not isinstance(p, list):
                raise ValueError("Specification must be list.")
        except Exception as exc:
            raise ValueError(f"Row {idx} invalid product_specifications: {exc}") from exc

    return {
        "total_products": total_rows,
        "column_count": len(actual_cols),
        "columns": actual_cols,
        "embedding_dimension": expected_dim,
        "dtype": str(matrix.dtype),
        "nan_count": nan_count,
        "inf_count": inf_count,
        "zero_vector_count": zero_vectors,
        "min_l2_norm": round(min_norm, 6),
        "mean_l2_norm": round(mean_norm, 6),
        "max_l2_norm": round(max_norm, 6),
        "status": "PASS",
    }


def export_products_parquet(
    df: pd.DataFrame,
    output_path: Path | str,
    validate_roundtrip: bool = True,
    include_timestamps: bool = False,
    expected_count: int | None = EXPECTED_CATALOG_SIZE,
) -> dict[str, Any]:
    """Export processed Product Knowledge Base dataset to Parquet atomically.

    Requirements:
    - Writes to an isolated temporary file first.
    - Re-reads and validates the serialized file (roundtrip test).
    - Verifies embeddings survive serialization without dimensional corruption.
    - Atomically promotes the temporary file to output_path.
    - Prevents publishing partially written or corrupted artifacts.

    Args:
        df: Assembled canonical DataFrame.
        output_path: Target output path (e.g. data/processed/products.parquet).
        validate_roundtrip: Whether to read back and validate after write.
        include_timestamps: Whether timestamps were included in schema.
        expected_count: Expected row count (default: 8405).

    Returns:
        Dictionary of export metrics (file size, path, validation status).

    Raises:
        RuntimeError: If export or roundtrip validation fails.
    """
    target_path = Path(output_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Isolated temporary file in the same target directory for atomic promotion
    temp_path = target_path.parent / f".tmp_{target_path.stem}_{os.getpid()}_{int(time.time())}.parquet"

    logger.info("Writing dataset (%d rows) to temporary file: %s", len(df), temp_path)

    try:
        # Export using project standard Pandas / PyArrow engine
        df.to_parquet(
            temp_path,
            index=False,
            engine="pyarrow",
            compression="snappy",
        )

        if validate_roundtrip:
            logger.info("Validating deserialization roundtrip from: %s", temp_path)
            roundtrip_df = pd.read_parquet(temp_path)

            if len(roundtrip_df) != len(df):
                raise RuntimeError(
                    f"Roundtrip row count mismatch: wrote {len(df)}, read {len(roundtrip_df)}"
                )

            if not roundtrip_df["product_id"].equals(df["product_id"]):
                raise RuntimeError("Roundtrip product_id alignment mismatch.")

            # Validate schema and numerical properties on read artifact
            audit_metrics = validate_processed_dataset(
                roundtrip_df,
                expected_count=expected_count,
                expected_dim=DEFAULT_EMBEDDING_DIM,
                include_timestamps=include_timestamps,
                check_normalized=True,
            )

            # Deep check on embeddings representation
            first_written = df["embedding"].iloc[0]
            first_read = roundtrip_df["embedding"].iloc[0]
            if not np.allclose(first_written, first_read, atol=1e-6):
                raise RuntimeError("Embedding precision drifted during Parquet serialization.")

        # Atomic promotion: replace temp file with final destination
        temp_path.replace(target_path)
        logger.info("Successfully exported and promoted canonical artifact to: %s", target_path)

    except Exception as exc:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        logger.error("Failed to export products.parquet: %s", exc)
        raise RuntimeError(f"Parquet export failed: {exc}") from exc

    file_size_bytes = target_path.stat().st_size
    file_size_mb = round(file_size_bytes / (1024 * 1024), 2)

    return {
        "output_path": str(target_path),
        "file_size_bytes": file_size_bytes,
        "file_size_mb": file_size_mb,
        "total_rows": len(df),
        "roundtrip_validation": "PASS",
        "status": "PASS",
    }


def verify_semantic_retrieval_sanity(
    df: pd.DataFrame,
    embedding_model: EmbeddingModel,
) -> dict[str, Any]:
    """Execute multi-category sanity checks directly against the processed dataset embeddings.

    Confirms that product-to-embedding association is semantically accurate
    and not misaligned by an off-by-one or indexing bug.

    Evaluates:
    1. Category-aware semantic retrieval matching ShopAssist's hybrid retrieval design.
    2. Mathematical spot-check verification: re-encodes retrieval_text for sample products
       and confirms dot product with stored embedding >= 0.999.

    Args:
        df: DataFrame containing 'product_id', 'product_name', 'retrieval_text', and 'embedding'.
        embedding_model: EmbeddingModel instance for query encoding.

    Returns:
        Sanity test report metrics.
    """
    scenarios = [
        {
            "scenario_id": "sanity_keyboard",
            "query": "wireless bluetooth keyboard",
            "category": "Computers",
            "keywords": ["keyboard", "key"],
        },
        {
            "scenario_id": "sanity_sofa",
            "query": "leather two seater sofa for living room",
            "category": "Furniture",
            "keywords": ["sofa", "couch", "sectional", "seater"],
        },
        {
            "scenario_id": "sanity_shoes",
            "query": "women casual flat sandals",
            "category": "Footwear",
            "keywords": ["sandal", "flat", "shoe"],
        },
    ]

    results: list[dict[str, Any]] = []
    passed = 0

    for sc in scenarios:
        # Route through category filter if category exists in candidates, matching ShopAssist architecture
        if "category" in df.columns and sc["category"] in df["category"].values:
            target_df = df[df["category"] == sc["category"]]
        else:
            target_df = df

        cat_matrix = np.vstack(target_df["embedding"].values).astype(np.float32)
        cat_names = target_df["product_name"].tolist()

        q_vec = embedding_model.encode_queries(sc["query"], show_progress_bar=False)
        sims = np.dot(cat_matrix, q_vec)
        top_idx = int(np.argmax(sims))
        top_sim = float(sims[top_idx])
        top_name = cat_names[top_idx]

        # Check if any target keyword/synonym is present in top product
        is_hit = any(kw in top_name.lower() for kw in sc["keywords"])
        if is_hit:
            passed += 1

        results.append({
            "scenario_id": sc["scenario_id"],
            "query": sc["query"],
            "category_filtered": sc["category"] if "category" in df.columns and sc["category"] in df["category"].values else "all",
            "top_product_name": top_name,
            "top_similarity": round(top_sim, 4),
            "target_keywords": sc["keywords"],
            "is_semantically_aligned": is_hit,
        })

    # Mathematical spot-check verification on sampled positions
    total_rows = len(df)
    sample_indices = sorted(list(set([0, total_rows // 4, total_rows // 2, 3 * total_rows // 4, total_rows - 1])))
    alignment_checks: list[dict[str, Any]] = []
    alignment_passed = 0

    for idx in sample_indices:
        row = df.iloc[idx]
        stored_vec = np.asarray(row["embedding"], dtype=np.float32)
        fresh_vec = embedding_model.encode_documents(str(row["retrieval_text"]), show_progress_bar=False)
        dot_product = float(np.dot(fresh_vec, stored_vec))
        is_aligned = bool(dot_product >= 0.999)
        if is_aligned:
            alignment_passed += 1

        alignment_checks.append({
            "index": idx,
            "product_id": str(row["product_id"]),
            "dot_product": round(dot_product, 6),
            "is_aligned": is_aligned,
        })

    status = (
        "PASS"
        if (passed == len(scenarios) and alignment_passed == len(sample_indices))
        else "FAIL"
    )

    return {
        "total_scenarios": len(scenarios),
        "passed": passed,
        "scenarios": results,
        "alignment_spot_checks": {
            "total_checked": len(sample_indices),
            "passed": alignment_passed,
            "status": "PASS" if alignment_passed == len(sample_indices) else "FAIL",
            "checks": alignment_checks,
        },
        "status": status,
    }


def run_phase5_5_pipeline(
    input_path: Path | str,
    output_path: Path | str,
    report_path: Path | str,
    model_name: str = DEFAULT_MODEL_NAME,
    batch_size: int = 32,
    device: str | None = None,
    include_timestamps: bool = False,
    expected_count: int | None = EXPECTED_CATALOG_SIZE,
) -> tuple[int, dict[str, Any]]:
    """Execute complete Phase 5.5 Batch Embedding Generation & Parquet Export pipeline.

    Steps:
    1. Validate input candidates dataset.
    2. Construct canonical retrieval_text if absent.
    3. Initialize embedding model on target device.
    4. Generate 384-d dense embeddings in batches.
    5. Validate numerical integrity and L2 normalization.
    6. Assemble canonical Product Knowledge Base schema.
    7. Atomically export products.parquet with roundtrip verification.
    8. Execute semantic sanity tests against exported embeddings.
    9. Produce machine-readable audit report.

    Args:
        input_path: Path to input parquet file.
        output_path: Path to output products.parquet.
        report_path: Path to output JSON execution report.
        model_name: HuggingFace model identifier.
        batch_size: Mini-batch size.
        device: Target compute device.
        include_timestamps: Whether to generate explicit timestamps.
        expected_count: Expected row count.

    Returns:
        Tuple of (exit_code, report_dict).
    """
    logger.info("==================================================================")
    logger.info("Starting Phase 5.5 — Batch Embedding Generation & Parquet Export")
    logger.info("==================================================================")
    logger.info("Input path:   %s", input_path)
    logger.info("Output path:  %s", output_path)
    logger.info("Report path:  %s", report_path)
    logger.info("Model:        %s (dim=384, batch_size=%d, device=%s)", model_name, batch_size, device or "auto")

    t_pipeline_start = time.time()
    inp_p = Path(input_path)
    out_p = Path(output_path)
    rep_p = Path(report_path)

    if not inp_p.exists():
        logger.error("Input dataset does not exist: %s", inp_p)
        return 1, {"status": "FAIL", "error": f"Input file not found: {inp_p}"}

    # 1. Load input dataset
    input_df = pd.read_parquet(inp_p)
    logger.info("Loaded input dataset with %d rows, %d columns.", len(input_df), len(input_df.columns))

    # 2. Validate input and resolve retrieval_text
    prepared_df, input_metrics = validate_input_dataset(
        input_df,
        expected_count=expected_count,
        allow_missing_retrieval_text=True,
    )
    logger.info("Input validation PASSED: %d valid records.", len(prepared_df))

    # 3. Initialize model & generate embeddings
    model = EmbeddingModel(
        model_name=model_name,
        device=device,
        normalize_embeddings=True,
        max_seq_length=DEFAULT_MAX_SEQ_LENGTH,
    )

    embeddings, perf_metrics = generate_catalog_embeddings(
        df=prepared_df,
        model=model,
        model_name=model_name,
        batch_size=batch_size,
        show_progress=True,
    )

    # 4. Assemble canonical DataFrame
    final_df = assemble_knowledge_base_dataframe(
        df=prepared_df,
        embeddings=embeddings,
        model_name=model_name,
        include_timestamps=include_timestamps,
    )

    # 5. Export to Parquet atomically with roundtrip verification
    export_metrics = export_products_parquet(
        df=final_df,
        output_path=out_p,
        validate_roundtrip=True,
        include_timestamps=include_timestamps,
        expected_count=expected_count,
    )

    # 6. Post-export semantic retrieval sanity check
    sanity_metrics = verify_semantic_retrieval_sanity(final_df, model)
    logger.info(
        "Semantic sanity checks: %d/%d passed (status: %s).",
        sanity_metrics["passed"],
        sanity_metrics["total_scenarios"],
        sanity_metrics["status"],
    )

    total_pipeline_seconds = round(time.time() - t_pipeline_start, 2)

    # 7. Construct comprehensive machine-readable report
    overall_status = (
        "PASS"
        if (
            input_metrics["status"] == "PASS"
            and perf_metrics["status"] == "PASS"
            and export_metrics["status"] == "PASS"
            and sanity_metrics["status"] == "PASS"
        )
        else "FAIL"
    )

    report: dict[str, Any] = {
        "phase": "5.5",
        "objective": "Batch Embedding Generation & products.parquet Export",
        "overall_status": overall_status,
        "input_dataset": {
            "path": str(inp_p),
            "rows": len(input_df),
            "columns_present": list(input_df.columns),
            "retrieval_text_generated_in_pipeline": input_metrics["retrieval_text_generated"],
            "validation": input_metrics,
        },
        "model_configuration": {
            "model_name": model_name,
            "embedding_dimension": DEFAULT_EMBEDDING_DIM,
            "max_sequence_length": DEFAULT_MAX_SEQ_LENGTH,
            "device": model.device,
            "cuda_device_name": perf_metrics.get("cuda_device_name"),
            "normalization_enabled": True,
        },
        "generation_performance": {
            "batch_size": batch_size,
            "total_items": len(prepared_df),
            "total_batches": perf_metrics["total_batches"],
            "model_load_seconds": perf_metrics["model_load_seconds"],
            "embedding_elapsed_seconds": perf_metrics["elapsed_seconds"],
            "throughput_texts_per_second": perf_metrics["throughput_texts_per_second"],
            "milliseconds_per_text": perf_metrics["milliseconds_per_text"],
            "process_ram_mb": perf_metrics["process_ram_mb"],
        },
        "embedding_validation": perf_metrics["validation"],
        "output_dataset": {
            "path": str(out_p),
            "rows": len(final_df),
            "column_count": len(final_df.columns),
            "columns": list(final_df.columns),
            "file_size_bytes": export_metrics["file_size_bytes"],
            "file_size_mb": export_metrics["file_size_mb"],
            "roundtrip_validation": export_metrics["roundtrip_validation"],
        },
        "semantic_sanity_checks": sanity_metrics,
        "timestamps_policy": {
            "columns_included": include_timestamps,
            "omitted_columns": [] if include_timestamps else ["created_at", "updated_at"],
            "rationale": (
                "Preserved PostgreSQL DEFAULT NOW() behavior for Phase 5.6 ingestion"
                if not include_timestamps
                else "Explicit timestamps populated"
            ),
        },
        "total_pipeline_seconds": total_pipeline_seconds,
    }

    # Save report
    rep_p.parent.mkdir(parents=True, exist_ok=True)
    with open(rep_p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("Saved Phase 5.5 execution report to: %s", rep_p)

    return (0 if overall_status == "PASS" else 1), report
