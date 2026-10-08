"""Database loading, batch ingestion pipeline, state auditing, and post-ingestion validation.

Phase 5.6 of ShopAssist:
- Ingestion target: public.products (Supabase PostgreSQL + pgvector)
- Source artifact: data/processed/products.parquet (8,405 products, 15 columns)
- Safe, parameterized batch insertion inside a single atomic transaction
- Strict idempotency: handles EMPTY_TABLE, ALREADY_POPULATED, PARTIALLY_POPULATED, CONFLICTING_DATA
- Multi-dimensional post-ingestion validation (row count, unique IDs, JSONB, vector dimension, cosine distance)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
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
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from shopassist.core.config import (
    INTERIM_DATA_DIR,
    PROCESSED_DATA_DIR,
    mask_database_url,
    settings,
)
from shopassist.db.connection import (
    check_connection,
    ensure_windows_event_loop_policy,
    get_async_engine,
)
from shopassist.db.validation import (
    DEFERRED_PHASE_5_7_INDEXES,
    enable_pgvector,
    validate_constraints,
    validate_deferred_indexes,
    validate_products_table_schema,
    validate_vector_dimension,
)
from shopassist.embeddings.batch import (
    CANONICAL_COLUMNS,
    EXPECTED_CATALOG_SIZE,
    validate_processed_dataset,
)

ensure_windows_event_loop_policy()

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE: int = 250
EXPECTED_EMBEDDING_DIM: int = 384
EXPECTED_EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
TARGET_TABLE: str = "public.products"
DEFAULT_SOURCE_PARQUET_PATH: Path = PROCESSED_DATA_DIR / "products.parquet"
DEFAULT_REPORT_PATH: Path = INTERIM_DATA_DIR / "phase5_6_database_ingestion_report.json"


class DatabaseState(str, Enum):
    """Classification of target table state before ingestion."""

    EMPTY_TABLE = "EMPTY_TABLE"  # Scenario A: Ready for clean ingestion
    ALREADY_POPULATED = "ALREADY_POPULATED"  # Scenario B: Fully matches approved source, no-op
    PARTIALLY_POPULATED = "PARTIALLY_POPULATED"  # Scenario C: Row count mismatch, unsafe to proceed
    CONFLICTING_DATA = "CONFLICTING_DATA"  # Scenario D: ID or content collision, unsafe to proceed


@dataclass
class DatabaseAuditResult:
    """Detailed audit of target database state prior to write operations."""

    state: DatabaseState
    current_row_count: int
    current_distinct_ids: int
    source_row_count: int
    matching_ids_count: int
    missing_ids_count: int
    unexpected_ids_count: int
    message: str
    can_proceed_with_insert: bool
    is_already_populated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "current_row_count": self.current_row_count,
            "current_distinct_ids": self.current_distinct_ids,
            "source_row_count": self.source_row_count,
            "matching_ids_count": self.matching_ids_count,
            "missing_ids_count": self.missing_ids_count,
            "unexpected_ids_count": self.unexpected_ids_count,
            "message": self.message,
            "can_proceed_with_insert": self.can_proceed_with_insert,
            "is_already_populated": self.is_already_populated,
        }


@dataclass
class BatchIngestionMetrics:
    """Metrics recorded during batch execution."""

    status: str
    total_records: int
    inserted_records: int
    batch_size: int
    num_batches: int
    elapsed_seconds: float
    throughput_rows_per_sec: float
    transaction_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PostIngestionValidationMetrics:
    """Metrics recorded during post-ingestion verification."""

    status: str
    total_rows: int
    distinct_product_ids: int
    null_mandatory_fields_count: int
    invalid_vector_dims_count: int
    invalid_specs_json_count: int
    null_timestamps_count: int
    sample_spot_check_count: int
    sample_spot_check_matched: int
    vector_smoke_test_passed: bool
    vector_smoke_test_query_id: str
    vector_smoke_test_top_match_id: str
    vector_smoke_test_distance: float
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_source_parquet(
    parquet_path: Path | str,
    expected_count: int = EXPECTED_CATALOG_SIZE,
    expected_dim: int = EXPECTED_EMBEDDING_DIM,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate source Parquet artifact integrity against Phase 5.1/5.5 schema requirements.

    Ensures:
    - Exactly 15 canonical columns exist in proper order.
    - Exactly expected_count rows exist (default 8,405).
    - All product_id values are unique, non-null, and non-empty.
    - Mandatory columns contain zero nulls.
    - Numerical prices and ratings satisfy database constraints.
    - Embedding vectors have dimension 384, contain finite floats, and are L2 normalized.
    - Product specifications are valid JSON arrays.

    Args:
        parquet_path: Path to products.parquet.
        expected_count: Expected row count (default: 8,405).
        expected_dim: Expected embedding dimension (default: 384).

    Returns:
        Tuple of (loaded DataFrame, validation metrics dictionary).

    Raises:
        FileNotFoundError: If the source Parquet file does not exist.
        ValueError: If any integrity or schema check fails.
    """
    path = Path(parquet_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Source Parquet artifact not found at {path}")

    logger.info("Loading source Parquet artifact for validation: %s", path)
    df = pd.read_parquet(path)

    metrics = validate_processed_dataset(
        df=df,
        expected_count=expected_count,
        expected_dim=expected_dim,
        include_timestamps=False,
        check_normalized=True,
    )
    metrics["source_path"] = str(path)
    metrics["file_size_mb"] = round(path.stat().st_size / (1024 * 1024), 2)
    logger.info(
        "Source Parquet validated successfully: %d products, %d columns, %.2f MB",
        len(df),
        len(df.columns),
        metrics["file_size_mb"],
    )
    return df, metrics


def format_vector_literal(vec: np.ndarray | Sequence[float]) -> str:
    """Format an embedding vector into a pgvector string literal '[v1,v2,...]'."""
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


def format_product_specifications(spec: Any) -> str:
    """Normalize product_specifications to a valid JSON array string."""
    if isinstance(spec, str):
        # Verify it parses as JSON and is a list
        parsed = json.loads(spec)
        if not isinstance(parsed, list):
            raise ValueError(f"product_specifications must be a JSON array, got {type(parsed).__name__}")
        return json.dumps(parsed)
    elif isinstance(spec, list):
        return json.dumps(spec)
    elif pd.isna(spec):
        return "[]"
    else:
        raise ValueError(f"Unsupported product_specifications type: {type(spec).__name__}")


def format_product_record(row: Any) -> dict[str, Any]:
    """Convert a Parquet product row into a PostgreSQL-compatible parameter dictionary.

    Handles:
    - NaN to None conversion for nullable fields (brand, retail_price, rating, description, etc.).
    - Decimal/float formatting for discounted_price and retail_price.
    - JSONB serialization for product_specifications.
    - Vector literal string formatting for embedding.
    - String stripping for text fields.
    """
    if isinstance(row, dict):
        d = row
    elif hasattr(row, "_asdict"):
        d = row._asdict()
    elif isinstance(row, pd.Series):
        d = row.to_dict()
    else:
        # Fallback for itertuples namedtuple
        d = row._asdict() if hasattr(row, "_asdict") else dict(zip(CANONICAL_COLUMNS, row))

    # Mandatory fields
    product_id = str(d["product_id"]).strip()
    product_name = str(d["product_name"]).strip()
    category = str(d["category"]).strip()
    discounted_price = float(d["discounted_price"])
    retrieval_text = str(d["retrieval_text"])
    embedding_model = str(d["embedding_model"]).strip()

    # Nullable fields
    brand = None if pd.isna(d.get("brand")) or not str(d.get("brand")).strip() else str(d.get("brand")).strip()
    retail_price = None if pd.isna(d.get("retail_price")) else float(d.get("retail_price"))
    rating = None if pd.isna(d.get("rating")) else float(d.get("rating"))
    description = (
        None if pd.isna(d.get("description")) or not str(d.get("description")).strip()
        else str(d.get("description")).strip()
    )
    product_url = (
        None if pd.isna(d.get("product_url")) or not str(d.get("product_url")).strip()
        else str(d.get("product_url")).strip()
    )
    image = None if pd.isna(d.get("image")) or not str(d.get("image")).strip() else str(d.get("image")).strip()
    pid = None if pd.isna(d.get("pid")) or not str(d.get("pid")).strip() else str(d.get("pid")).strip()

    # Serializations
    specs_json = format_product_specifications(d.get("product_specifications"))
    emb = d["embedding"]
    embedding_str = format_vector_literal(emb)

    return {
        "product_id": product_id,
        "product_name": product_name,
        "category": category,
        "brand": brand,
        "retail_price": retail_price,
        "discounted_price": discounted_price,
        "rating": rating,
        "description": description,
        "product_specifications": specs_json,
        "product_url": product_url,
        "image": image,
        "pid": pid,
        "retrieval_text": retrieval_text,
        "embedding": embedding_str,
        "embedding_model": embedding_model,
    }


async def audit_database_state(
    engine: AsyncEngine,
    source_df: pd.DataFrame,
    spot_check_count: int = 20,
) -> DatabaseAuditResult:
    """Inspect and classify the current state of public.products before any write operation.

    Classifies table into:
    - EMPTY_TABLE (Scenario A): row count == 0. Safe to proceed with ingestion.
    - ALREADY_POPULATED (Scenario B): row count matches source (8,405), all product IDs match,
      and spot-checked sample records match source data. Safe no-op.
    - PARTIALLY_POPULATED (Scenario C): row count is between 0 and 8,405, or > 8,405. Unsafe to proceed.
    - CONFLICTING_DATA (Scenario D): row count matches or exceeds source, but product IDs or
      sample contents do not match source artifact. Unsafe to proceed.

    Args:
        engine: AsyncEngine connection to Supabase.
        source_df: Verified source DataFrame.
        spot_check_count: Number of records to spot check for Scenario B validation.

    Returns:
        DatabaseAuditResult containing the state classification and audit metrics.
    """
    logger.info("Auditing target table 'public.products' state before write operations...")
    source_product_ids = set(source_df["product_id"].astype(str).tolist())
    source_count = len(source_product_ids)

    async with engine.connect() as conn:
        # 1. Query row count and distinct ID count
        res = await conn.execute(
            text("SELECT COUNT(*), COUNT(DISTINCT product_id) FROM public.products;")
        )
        row = res.fetchone()
        current_rows, current_distinct_ids = int(row[0]), int(row[1])

        logger.info(
            "Current public.products status: %d rows, %d distinct product_ids",
            current_rows,
            current_distinct_ids,
        )

        # Scenario A: Clean empty table
        if current_rows == 0:
            return DatabaseAuditResult(
                state=DatabaseState.EMPTY_TABLE,
                current_row_count=0,
                current_distinct_ids=0,
                source_row_count=source_count,
                matching_ids_count=0,
                missing_ids_count=source_count,
                unexpected_ids_count=0,
                message="Target table 'public.products' is empty. Ready for initial ingestion (Scenario A).",
                can_proceed_with_insert=True,
                is_already_populated=False,
            )

        # Retrieve all existing product IDs from the database
        id_res = await conn.execute(text("SELECT product_id FROM public.products;"))
        db_product_ids = set(r[0] for r in id_res.fetchall())

        matching_ids = source_product_ids.intersection(db_product_ids)
        missing_ids = source_product_ids - db_product_ids
        unexpected_ids = db_product_ids - source_product_ids

        # Scenario B candidate: Exactly matching row counts and ID set
        if current_rows == source_count and len(missing_ids) == 0 and len(unexpected_ids) == 0:
            logger.info("Row count and ID set match source. Conducting content spot check...")
            # Sample spot_check_count product IDs from source
            sample_ids = list(source_df["product_id"].iloc[:spot_check_count].astype(str))
            stmt = text(
                "SELECT product_id, product_name, category, discounted_price, embedding_model "
                "FROM public.products WHERE product_id = ANY(:ids);"
            )

            sample_res = await conn.execute(stmt, {"ids": sample_ids})
            db_sample_dict = {r[0]: r for r in sample_res.fetchall()}

            all_match = True
            for _, s_row in source_df.iloc[:spot_check_count].iterrows():
                pid = str(s_row["product_id"])
                if pid not in db_sample_dict:
                    all_match = False
                    break
                db_r = db_sample_dict[pid]
                # Compare critical fields
                if (
                    db_r[1] != str(s_row["product_name"])
                    or db_r[2] != str(s_row["category"])
                    or float(db_r[3]) != float(s_row["discounted_price"])
                    or db_r[4] != str(s_row["embedding_model"])
                ):
                    all_match = False
                    break

            if all_match:
                return DatabaseAuditResult(
                    state=DatabaseState.ALREADY_POPULATED,
                    current_row_count=current_rows,
                    current_distinct_ids=current_distinct_ids,
                    source_row_count=source_count,
                    matching_ids_count=len(matching_ids),
                    missing_ids_count=0,
                    unexpected_ids_count=0,
                    message=(
                        f"Target table 'public.products' is already fully populated with all "
                        f"{source_count} approved records. Content verified (Scenario B)."
                    ),
                    can_proceed_with_insert=False,
                    is_already_populated=True,
                )
            else:
                return DatabaseAuditResult(
                    state=DatabaseState.CONFLICTING_DATA,
                    current_row_count=current_rows,
                    current_distinct_ids=current_distinct_ids,
                    source_row_count=source_count,
                    matching_ids_count=len(matching_ids),
                    missing_ids_count=len(missing_ids),
                    unexpected_ids_count=len(unexpected_ids),
                    message=(
                        "Target table has 8,405 rows but content differs from approved Parquet source (Scenario D)."
                    ),
                    can_proceed_with_insert=False,
                    is_already_populated=False,
                )

        # Scenario C: Partially populated
        if current_rows < source_count or (len(missing_ids) > 0 and len(matching_ids) > 0):
            return DatabaseAuditResult(
                state=DatabaseState.PARTIALLY_POPULATED,
                current_row_count=current_rows,
                current_distinct_ids=current_distinct_ids,
                source_row_count=source_count,
                matching_ids_count=len(matching_ids),
                missing_ids_count=len(missing_ids),
                unexpected_ids_count=len(unexpected_ids),
                message=(
                    f"Target table is partially populated ({current_rows}/{source_count} rows, "
                    f"{len(missing_ids)} missing IDs). Ingestion halted to prevent inconsistent state (Scenario C)."
                ),
                can_proceed_with_insert=False,
                is_already_populated=False,
            )

        # Scenario D: Conflicting data
        return DatabaseAuditResult(
            state=DatabaseState.CONFLICTING_DATA,
            current_row_count=current_rows,
            current_distinct_ids=current_distinct_ids,
            source_row_count=source_count,
            matching_ids_count=len(matching_ids),
            missing_ids_count=len(missing_ids),
            unexpected_ids_count=len(unexpected_ids),
            message=(
                f"Target table contains {current_rows} rows with {len(unexpected_ids)} unexpected product IDs "
                f"not in source (Scenario D). Ingestion halted."
            ),
            can_proceed_with_insert=False,
            is_already_populated=False,
        )


INSERT_PRODUCTS_SQL = text("""
    INSERT INTO public.products (
        product_id,
        product_name,
        category,
        brand,
        retail_price,
        discounted_price,
        rating,
        description,
        product_specifications,
        product_url,
        image,
        pid,
        retrieval_text,
        embedding,
        embedding_model
    ) VALUES (
        :product_id,
        :product_name,
        :category,
        :brand,
        :retail_price,
        :discounted_price,
        :rating,
        :description,
        CAST(:product_specifications AS jsonb),
        :product_url,
        :image,
        :pid,
        :retrieval_text,
        CAST(:embedding AS vector),
        :embedding_model
    );
""")


async def ingest_products(
    engine: AsyncEngine,
    df: pd.DataFrame,
    batch_size: int = DEFAULT_BATCH_SIZE,
    show_progress: bool = True,
) -> BatchIngestionMetrics:
    """Execute parameterized batch ingestion into public.products inside a single atomic transaction.

    Design & Safety:
    - All batches are executed within a single transaction (`conn.begin()`).
    - If any batch fails, the entire transaction is rolled back, leaving the database clean.
    - PostgreSQL populates `created_at` and `updated_at` via defaults and triggers.
    - Parameters are bound safely with explicit type casts (`CAST(:embedding AS vector)`, `CAST(:specs AS jsonb)`).
    - Progress is logged periodically with batch counts and throughput.

    Args:
        engine: AsyncEngine connection to Supabase.
        df: Verified source DataFrame containing all 8,405 products.
        batch_size: Number of records per batch execution (default: 250).
        show_progress: Whether to log progress after batches.

    Returns:
        BatchIngestionMetrics with timing, counts, and throughput.

    Raises:
        RuntimeError: If any batch execution or transaction commit fails.
    """
    total_records = len(df)
    num_batches = math.ceil(total_records / batch_size)

    logger.info(
        "Starting atomic batch ingestion of %d products into '%s' (%d batches of size %d)...",
        total_records,
        TARGET_TABLE,
        num_batches,
        batch_size,
    )

    t_start = time.time()
    inserted_count = 0

    try:
        async with engine.connect() as conn:
            async with conn.begin():
                for batch_idx in range(num_batches):
                    start_i = batch_idx * batch_size
                    end_i = min(start_i + batch_size, total_records)
                    chunk_df = df.iloc[start_i:end_i]

                    # Convert chunk to list of parameter dictionaries
                    chunk_params = [format_product_record(row) for _, row in chunk_df.iterrows()]

                    # Execute batch insert via executemany
                    await conn.execute(INSERT_PRODUCTS_SQL, chunk_params)
                    inserted_count += len(chunk_params)

                    if show_progress and ((batch_idx + 1) % 5 == 0 or (batch_idx + 1) == num_batches):
                        elapsed = time.time() - t_start
                        rate = inserted_count / elapsed if elapsed > 0 else 0
                        pct = (inserted_count / total_records) * 100
                        logger.info(
                            "Batch %d/%d committed: %d/%d products (%.1f%%, %.1f rows/sec)",
                            batch_idx + 1,
                            num_batches,
                            inserted_count,
                            total_records,
                            pct,
                            rate,
                        )

        total_elapsed = time.time() - t_start
        throughput = total_records / total_elapsed if total_elapsed > 0 else 0.0

        logger.info(
            "Batch ingestion completed and committed successfully in %.2f seconds (%.1f rows/sec).",
            total_elapsed,
            throughput,
        )

        return BatchIngestionMetrics(
            status="PASS",
            total_records=total_records,
            inserted_records=inserted_count,
            batch_size=batch_size,
            num_batches=num_batches,
            elapsed_seconds=round(total_elapsed, 3),
            throughput_rows_per_sec=round(throughput, 2),
            transaction_status="COMMITTED",
        )

    except Exception as exc:
        total_elapsed = time.time() - t_start
        logger.error(
            "Batch ingestion failed after %.2f seconds at record %d/%d. Transaction rolled back cleanly. Error: %s",
            total_elapsed,
            inserted_count,
            total_records,
            str(exc).split("\n")[0],
        )
        raise RuntimeError(
            f"Atomic ingestion failed during batch execution: {str(exc).split(os.linesep)[0]}"
        ) from exc


async def validate_post_ingestion(
    engine: AsyncEngine,
    source_df: pd.DataFrame,
    sample_size: int = 50,
    tolerance: float = 1e-4,
) -> PostIngestionValidationMetrics:
    """Perform post-ingestion validation on public.products.

    Verifies:
    1. Exact row count: SELECT COUNT(*) == len(source_df) (8,405).
    2. Unique product IDs: SELECT COUNT(DISTINCT product_id) == len(source_df).
    3. Zero nulls in mandatory fields.
    4. All stored embeddings have vector_dims == 384.
    5. All product_specifications have jsonb_typeof == 'array'.
    6. All records have non-null created_at and updated_at populated by PostgreSQL.
    7. Content spot check: sample_size representative records compared against Parquet source
       (including float32 numerical vector tolerance check).
    8. Vector operation smoke test: lightweight pgvector cosine distance (<=>) query.

    Args:
        engine: AsyncEngine connection.
        source_df: Source DataFrame for ground truth comparison.
        sample_size: Number of records to verify via content spot check.
        tolerance: Maximum allowed L2 distance deviation for stored embeddings.

    Returns:
        PostIngestionValidationMetrics.

    Raises:
        ValueError: If any post-ingestion check fails.
    """
    logger.info("Running post-ingestion validation checks on '%s'...", TARGET_TABLE)
    expected_count = len(source_df)

    async with engine.connect() as conn:
        # 1. Total row count & distinct product IDs
        res = await conn.execute(
            text("SELECT COUNT(*), COUNT(DISTINCT product_id) FROM public.products;")
        )
        row = res.fetchone()
        actual_rows, distinct_ids = int(row[0]), int(row[1])

        if actual_rows != expected_count:
            raise ValueError(
                f"Post-ingestion row count mismatch: expected {expected_count}, got {actual_rows}"
            )
        if distinct_ids != expected_count:
            raise ValueError(
                f"Post-ingestion distinct ID mismatch: expected {expected_count}, got {distinct_ids}"
            )

        # 2. Null mandatory fields check
        null_chk = await conn.execute(
            text(
                "SELECT COUNT(*) FROM public.products "
                "WHERE product_id IS NULL "
                "   OR product_name IS NULL "
                "   OR category IS NULL "
                "   OR discounted_price IS NULL "
                "   OR product_specifications IS NULL "
                "   OR retrieval_text IS NULL "
                "   OR embedding IS NULL "
                "   OR embedding_model IS NULL;"
            )
        )
        null_count = int(null_chk.scalar())
        if null_count > 0:
            raise ValueError(f"Found {null_count} rows with null mandatory fields in public.products!")

        # 3. Vector dimension check
        dim_chk = await conn.execute(
            text(f"SELECT COUNT(*) FROM public.products WHERE vector_dims(embedding) != {EXPECTED_EMBEDDING_DIM};")
        )
        dim_mismatches = int(dim_chk.scalar())
        if dim_mismatches > 0:
            raise ValueError(
                f"Found {dim_mismatches} rows with embedding dimension != {EXPECTED_EMBEDDING_DIM}!"
            )

        # 4. JSONB array check
        spec_chk = await conn.execute(
            text("SELECT COUNT(*) FROM public.products WHERE jsonb_typeof(product_specifications) != 'array';")
        )
        spec_mismatches = int(spec_chk.scalar())
        if spec_mismatches > 0:
            raise ValueError(
                f"Found {spec_mismatches} rows where product_specifications is not a JSONB array!"
            )

        # 5. Default timestamps check
        ts_chk = await conn.execute(
            text("SELECT COUNT(*) FROM public.products WHERE created_at IS NULL OR updated_at IS NULL;")
        )
        null_ts_count = int(ts_chk.scalar())
        if null_ts_count > 0:
            raise ValueError(f"Found {null_ts_count} rows where created_at or updated_at was not populated!")

        # 6. Content spot check: select up to sample_size representative records
        n_rows = len(source_df)
        if n_rows <= sample_size:
            sample_indices = list(range(n_rows))
        else:
            mid = n_rows // 2
            cand = (
                list(range(0, min(15, n_rows)))
                + list(range(max(0, mid - 7), min(n_rows, mid + 8)))
                + list(range(max(0, n_rows - 15), n_rows))
                + [idx for idx in [100, 500, 1200, 3400, 6000] if idx < n_rows]
            )
            sample_indices = sorted(list(set(cand)))[:sample_size]

        sample_df = source_df.iloc[sample_indices]
        sample_ids = list(sample_df["product_id"].astype(str).tolist())

        stmt = text(
            "SELECT product_id, product_name, category, brand, retail_price, discounted_price, "
            "       rating, retrieval_text, embedding_model, embedding "
            "FROM public.products WHERE product_id = ANY(:ids);"
        )
        sample_res = await conn.execute(stmt, {"ids": sample_ids})
        db_records = {r[0]: r for r in sample_res.fetchall()}

        matched_spot_checks = 0
        for _, s_row in sample_df.iterrows():
            pid = str(s_row["product_id"])
            if pid not in db_records:
                raise ValueError(f"Spot-checked product_id '{pid}' was not found in database!")

            db_r = db_records[pid]
            # Metadata comparisons
            assert db_r[1] == str(s_row["product_name"]), f"Name mismatch for {pid}"
            assert db_r[2] == str(s_row["category"]), f"Category mismatch for {pid}"
            assert math.isclose(float(db_r[5]), float(s_row["discounted_price"]), rel_tol=1e-2), f"Price mismatch for {pid}"
            assert db_r[7] == str(s_row["retrieval_text"]), f"Retrieval text mismatch for {pid}"
            assert db_r[8] == str(s_row["embedding_model"]), f"Model mismatch for {pid}"

            # Numerical embedding comparison
            db_emb_raw = db_r[9]
            # pgvector embedding returned as string '[v1,v2,...]' or numpy-compatible string
            if isinstance(db_emb_raw, str):
                db_vec = np.array(json.loads(db_emb_raw), dtype=np.float32)
            else:
                db_vec = np.array(db_emb_raw, dtype=np.float32)

            source_vec = np.array(s_row["embedding"], dtype=np.float32)
            l2_diff = float(np.linalg.norm(db_vec - source_vec))
            if l2_diff > tolerance:
                raise ValueError(
                    f"Embedding numerical drift for product_id '{pid}': L2 diff={l2_diff:.6e} > {tolerance}"
                )

            matched_spot_checks += 1

        logger.info(
            "Spot check completed: %d/%d sample records matched source data perfectly.",
            matched_spot_checks,
            len(sample_indices),
        )

        # 7. Vector cosine distance smoke test
        first_row = source_df.iloc[0]
        query_id = str(first_row["product_id"])
        query_vec = first_row["embedding"]
        query_vec_str = format_vector_literal(query_vec)

        smoke_res = await conn.execute(
            text(
                "SELECT product_id, product_name, embedding <=> CAST(:vec AS vector) AS distance "
                "FROM public.products "
                "ORDER BY embedding <=> CAST(:vec AS vector) "
                "LIMIT 5;"
            ).bindparams(vec=query_vec_str)
        )
        smoke_rows = smoke_res.fetchall()
        top_match_id = smoke_rows[0][0]
        top_distance = float(smoke_rows[0][2])

        if top_match_id != query_id:
            raise ValueError(
                f"Vector smoke test failed: top match is '{top_match_id}', expected '{query_id}'"
            )
        if top_distance > tolerance:
            raise ValueError(
                f"Vector smoke test self-distance too high: {top_distance:.6e} > {tolerance}"
            )

        logger.info(
            "Vector cosine distance smoke test passed: query product '%s' matched with distance %.6e",
            query_id,
            top_distance,
        )

        return PostIngestionValidationMetrics(
            status="PASS",
            total_rows=actual_rows,
            distinct_product_ids=distinct_ids,
            null_mandatory_fields_count=null_count,
            invalid_vector_dims_count=dim_mismatches,
            invalid_specs_json_count=spec_mismatches,
            null_timestamps_count=null_ts_count,
            sample_spot_check_count=len(sample_indices),
            sample_spot_check_matched=matched_spot_checks,
            vector_smoke_test_passed=True,
            vector_smoke_test_query_id=query_id,
            vector_smoke_test_top_match_id=top_match_id,
            vector_smoke_test_distance=round(top_distance, 8),
            details={
                "top_5_smoke_matches": [
                    {"product_id": r[0], "product_name": r[1][:50], "cosine_distance": round(float(r[2]), 6)}
                    for r in smoke_rows
                ]
            },
        )


def export_ingestion_report(
    report_dict: dict[str, Any],
    output_path: Path | str = DEFAULT_REPORT_PATH,
) -> Path:
    """Export machine-readable JSON execution report atomically."""
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.parent / f".tmp_{path.stem}_{os.getpid()}_{int(time.time())}.json"
    temp_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
    temp_path.replace(path)
    logger.info("Ingestion report saved: %s", path)
    return path


async def run_phase5_6_pipeline(
    source_parquet_path: Path | str = DEFAULT_SOURCE_PARQUET_PATH,
    report_path: Path | str = DEFAULT_REPORT_PATH,
    batch_size: int = DEFAULT_BATCH_SIZE,
    engine: AsyncEngine | None = None,
) -> tuple[dict[str, Any], PostIngestionValidationMetrics]:
    """Orchestrate Phase 5.6 Database Loading / Ingestion pipeline end-to-end.

    Execution Flow:
    1. Database Connectivity & Credential Masking
    2. PostgreSQL Schema Verification (public schema, products table, vector(384), check constraints)
    3. Input Dataset Validation (Phase 5.5 Parquet artifact)
    4. Target Database State Audit (Scenario A, B, C, D)
    5. Ingestion Execution (Atomic parameterized batch INSERT)
    6. Post-Ingestion Verification (Counts, JSONB, vector dimension, spot check, cosine distance)
    7. Machine-Readable JSON Report Export

    Args:
        source_parquet_path: Path to products.parquet.
        report_path: Path for output JSON report.
        batch_size: Ingestion batch size (default 250).
        engine: Optional pre-configured AsyncEngine.

    Returns:
        Tuple of (report_dict, PostIngestionValidationMetrics).

    Raises:
        RuntimeError: If database is in an unsafe state or ingestion fails.
    """
    logger.info("=" * 70)
    logger.info("STARTING PHASE 5.6: DATABASE LOADING / INGESTION")
    logger.info("=" * 70)

    t_start = time.time()
    active_engine = engine or get_async_engine()
    masked_db_url = settings.get_masked_supabase_db_url()
    warnings: list[str] = []
    errors: list[str] = []

    # 1. Connection check
    logger.info("[Step 1/6] Verifying Supabase connection: %s", masked_db_url)
    conn_info = await check_connection(active_engine)
    logger.info("Supabase connection verified: %s", conn_info.get("postgresql_version") or conn_info.get("database"))

    # 2. Schema verification
    logger.info("[Step 2/6] Verifying target table schema and vector dimension...")
    schema_metrics = await validate_products_table_schema(active_engine)
    vector_metrics = await validate_vector_dimension(active_engine, expected_dim=EXPECTED_EMBEDDING_DIM)
    constraints_metrics = await validate_constraints(active_engine)
    deferred_idx_metrics = await validate_deferred_indexes(active_engine)

    # 3. Source Parquet validation
    logger.info("[Step 3/6] Validating source Parquet artifact: %s", source_parquet_path)
    source_df, source_metrics = validate_source_parquet(source_parquet_path)

    # 4. Target database state audit
    logger.info("[Step 4/6] Auditing target database state...")
    audit_res = await audit_database_state(active_engine, source_df)
    logger.info("Database state classification: %s (%s)", audit_res.state.value, audit_res.message)

    # 5. Handle Ingestion Scenarios
    ingestion_metrics: BatchIngestionMetrics
    if audit_res.state == DatabaseState.EMPTY_TABLE:
        logger.info("[Step 5/6] Executing atomic batch ingestion (Scenario A)...")
        ingestion_metrics = await ingest_products(
            engine=active_engine,
            df=source_df,
            batch_size=batch_size,
        )
    elif audit_res.state == DatabaseState.ALREADY_POPULATED:
        logger.info("[Step 5/6] Table already populated with approved dataset (Scenario B). Skipping insert.")
        ingestion_metrics = BatchIngestionMetrics(
            status="SKIPPED_ALREADY_POPULATED",
            total_records=len(source_df),
            inserted_records=0,
            batch_size=batch_size,
            num_batches=0,
            elapsed_seconds=0.0,
            throughput_rows_per_sec=0.0,
            transaction_status="NO_OP_ALREADY_POPULATED",
        )
    elif audit_res.state == DatabaseState.PARTIALLY_POPULATED:
        err = f"Halting: Target table is partially populated ({audit_res.current_row_count} rows). Manual intervention required."
        errors.append(err)
        raise RuntimeError(err)
    elif audit_res.state == DatabaseState.CONFLICTING_DATA:
        err = f"Halting: Target table contains data conflicting with source Parquet. Ingestion aborted."
        errors.append(err)
        raise RuntimeError(err)
    else:
        err = f"Unknown database state: {audit_res.state}"
        errors.append(err)
        raise RuntimeError(err)

    # 6. Post-ingestion validation
    logger.info("[Step 6/6] Executing post-ingestion verification...")
    post_metrics = await validate_post_ingestion(active_engine, source_df)

    total_pipeline_time = round(time.time() - t_start, 2)
    logger.info("Phase 5.6 pipeline completed successfully in %.2f seconds.", total_pipeline_time)

    # Assemble report
    report: dict[str, Any] = {
        "phase": "5.6",
        "objective": "Database Loading / Ingestion",
        "overall_status": "PASS",
        "source_parquet": {
            "path": str(source_parquet_path),
            "rows": len(source_df),
            "columns": list(source_df.columns),
            "validation": source_metrics,
        },
        "target_database": {
            "masked_url": masked_db_url,
            "table": TARGET_TABLE,
            "schema": "public",
            "connection": conn_info,
            "schema_validation": schema_metrics,
            "vector_validation": vector_metrics,
            "constraints_validation": constraints_metrics,
            "deferred_indexes": deferred_idx_metrics,
        },
        "pre_ingestion_audit": audit_res.to_dict(),
        "ingestion_execution": ingestion_metrics.to_dict(),
        "post_ingestion_validation": post_metrics.to_dict(),
        "phase5_7_readiness": {
            "ready_for_index_construction": True,
            "expected_indexes": DEFERRED_PHASE_5_7_INDEXES,
            "catalog_size": len(source_df),
        },
        "pipeline_performance": {
            "total_pipeline_elapsed_seconds": total_pipeline_time,
            "batch_size": batch_size,
        },
        "warnings": warnings,
        "errors": errors,
    }

    export_ingestion_report(report, report_path)
    return report, post_metrics
