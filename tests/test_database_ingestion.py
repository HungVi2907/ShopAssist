"""Automated unit and integration tests for Phase 5.6: Database Loading / Ingestion."""

from __future__ import annotations

import asyncio
from functools import wraps
import json
import math
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from shopassist.core.config import mask_database_url
from shopassist.db.connection import ensure_windows_event_loop_policy, get_async_engine
from shopassist.db.ingestion import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_SOURCE_PARQUET_PATH,
    EXPECTED_CATALOG_SIZE,
    EXPECTED_EMBEDDING_DIM,
    EXPECTED_EMBEDDING_MODEL,
    DatabaseAuditResult,
    DatabaseState,
    audit_database_state,
    export_ingestion_report,
    format_product_record,
    format_product_specifications,
    format_vector_literal,
    ingest_products,
    validate_post_ingestion,
    validate_source_parquet,
)

ensure_windows_event_loop_policy()


def async_test(coro):
    """Decorator to execute async test functions cleanly without pytest-asyncio plugin."""
    @wraps(coro)
    def wrapper(*args, **kwargs):
        ensure_windows_event_loop_policy()
        return asyncio.run(coro(*args, **kwargs))
    return wrapper


_UNSET = object()


def make_mock_result(
    rows: list | None = None,
    scalar_val: any = _UNSET,
    fetchone_val: any = _UNSET,
) -> MagicMock:
    """Create a synchronous SQLAlchemy Result mock for conn.execute()."""
    res = MagicMock()
    if rows is not None:
        res.fetchall.return_value = rows
    if scalar_val is not _UNSET:
        res.scalar.return_value = scalar_val
    if fetchone_val is not _UNSET:
        res.fetchone.return_value = fetchone_val
    return res


# Sample test row fixture
def create_sample_row(
    product_id: str = "TEST_001",
    retail_price: float | None = 1000.0,
    discounted_price: float = 800.0,
    rating: float | None = 4.2,
    specs: str | list = '[{"key": "Color", "value": "Blue"}]',
    embedding: list[float] | None = None,
) -> dict:
    if embedding is None:
        # 384-dimensional unit vector
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0
        embedding = v.tolist()

    return {
        "product_id": product_id,
        "product_name": "Test Product Sample",
        "category": "Clothing >> Men >> Shirts",
        "brand": "SampleBrand",
        "retail_price": retail_price,
        "discounted_price": discounted_price,
        "rating": rating,
        "description": "High quality cotton shirt.",
        "product_specifications": specs,
        "product_url": "https://example.com/p/TEST_001",
        "image": "https://example.com/img/TEST_001.jpg",
        "pid": "PID12345",
        "retrieval_text": "SampleBrand Test Product Sample. Category: Clothing >> Men >> Shirts.",
        "embedding": embedding,
        "embedding_model": EXPECTED_EMBEDDING_MODEL,
    }


# ==============================================================================
# 1. Parquet Validation Tests
# ==============================================================================

def test_validate_source_parquet_real_file():
    """Verify validate_source_parquet successfully validates the Phase 5.5 artifact."""
    if not DEFAULT_SOURCE_PARQUET_PATH.exists():
        pytest.skip(f"Source file not present at {DEFAULT_SOURCE_PARQUET_PATH}")

    df, metrics = validate_source_parquet(DEFAULT_SOURCE_PARQUET_PATH)
    assert len(df) == EXPECTED_CATALOG_SIZE
    assert metrics["total_products"] == EXPECTED_CATALOG_SIZE
    assert metrics["embedding_dimension"] == EXPECTED_EMBEDDING_DIM
    assert metrics["status"] == "PASS"


def test_validate_source_parquet_missing_file():
    """Verify FileNotFoundError is raised for non-existent Parquet path."""
    with pytest.raises(FileNotFoundError, match="not found at"):
        validate_source_parquet("data/non_existent_products.parquet")


# ==============================================================================
# 2. Data Formatting & Type Conversion Tests
# ==============================================================================

def test_format_vector_literal():
    """Verify vector formatting produces valid pgvector literal '[v1,v2,...]'."""
    vec = [0.12345678, -0.98765432, 0.0]
    formatted = format_vector_literal(vec)
    assert formatted.startswith("[") and formatted.endswith("]")
    elements = formatted[1:-1].split(",")
    assert len(elements) == 3
    assert float(elements[0]) == pytest.approx(0.12345678)
    assert float(elements[1]) == pytest.approx(-0.98765432)


def test_format_product_specifications_valid_json_string():
    """Verify JSON string specifications are normalized to canonical JSON."""
    raw = '[{"key": "Material", "value": "Cotton"}]'
    out = format_product_specifications(raw)
    assert json.loads(out) == [{"key": "Material", "value": "Cotton"}]


def test_format_product_specifications_python_list():
    """Verify Python list specifications are converted to JSON array string."""
    raw = [{"key": "Size", "value": "M"}]
    out = format_product_specifications(raw)
    assert out == '[{"key": "Size", "value": "M"}]'


def test_format_product_specifications_nan_or_none():
    """Verify NaN or None specifications default to empty array '[]'."""
    assert format_product_specifications(None) == "[]"
    assert format_product_specifications(float("nan")) == "[]"


def test_format_product_specifications_invalid_type_raises():
    """Verify non-array JSON specification raises ValueError."""
    with pytest.raises(ValueError, match="must be a JSON array"):
        format_product_specifications('{"key": "value"}')


def test_format_product_record_nan_handling():
    """Verify NaN values in nullable fields are properly converted to SQL NULL (None)."""
    row = create_sample_row(retail_price=np.nan, rating=float("nan"))
    row["brand"] = float("nan")
    row["description"] = None
    row["image"] = "   "  # whitespace should become None

    record = format_product_record(row)
    assert record["retail_price"] is None
    assert record["rating"] is None
    assert record["brand"] is None
    assert record["description"] is None
    assert record["image"] is None
    assert record["discounted_price"] == 800.0
    assert record["product_id"] == "TEST_001"
    assert record["embedding"].startswith("[")


# ==============================================================================
# 3. Database State Classification Tests (Unit / Mock)
# ==============================================================================

@async_test
async def test_audit_database_state_empty_table_scenario_a():
    """Verify empty target table is classified as Scenario A (EMPTY_TABLE)."""
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = make_mock_result(fetchone_val=(0, 0))

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    df = pd.DataFrame([create_sample_row("ID_1"), create_sample_row("ID_2")])

    audit = await audit_database_state(mock_engine, df)
    assert audit.state == DatabaseState.EMPTY_TABLE
    assert audit.can_proceed_with_insert is True
    assert audit.is_already_populated is False
    assert audit.current_row_count == 0


@async_test
async def test_audit_database_state_already_populated_scenario_b():
    """Verify fully matching target table is classified as Scenario B (ALREADY_POPULATED)."""
    row1 = create_sample_row("ID_1")
    row2 = create_sample_row("ID_2")
    df = pd.DataFrame([row1, row2])

    mock_conn = AsyncMock()
    # 1. Row count check
    count_res = make_mock_result(fetchone_val=(2, 2))
    # 2. Product IDs check
    id_res = make_mock_result(rows=[("ID_1",), ("ID_2",)])
    # 3. Spot check query
    spot_res = make_mock_result(
        rows=[
            ("ID_1", row1["product_name"], row1["category"], row1["discounted_price"], row1["embedding_model"]),
            ("ID_2", row2["product_name"], row2["category"], row2["discounted_price"], row2["embedding_model"]),
        ]
    )
    mock_conn.execute.side_effect = [count_res, id_res, spot_res]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    audit = await audit_database_state(mock_engine, df)
    assert audit.state == DatabaseState.ALREADY_POPULATED
    assert audit.can_proceed_with_insert is False
    assert audit.is_already_populated is True
    assert audit.matching_ids_count == 2


@async_test
async def test_audit_database_state_partially_populated_scenario_c():
    """Verify partially populated target table is classified as Scenario C (PARTIALLY_POPULATED)."""
    df = pd.DataFrame([create_sample_row("ID_1"), create_sample_row("ID_2"), create_sample_row("ID_3")])

    mock_conn = AsyncMock()
    count_res = make_mock_result(fetchone_val=(1, 1))
    id_res = make_mock_result(rows=[("ID_1",)])
    mock_conn.execute.side_effect = [count_res, id_res]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    audit = await audit_database_state(mock_engine, df)
    assert audit.state == DatabaseState.PARTIALLY_POPULATED
    assert audit.can_proceed_with_insert is False
    assert audit.current_row_count == 1
    assert audit.missing_ids_count == 2


@async_test
async def test_audit_database_state_conflicting_data_scenario_d():
    """Verify target table with unrecognized IDs is classified as Scenario D (CONFLICTING_DATA)."""
    df = pd.DataFrame([create_sample_row("ID_1"), create_sample_row("ID_2")])

    mock_conn = AsyncMock()
    count_res = make_mock_result(fetchone_val=(2, 2))
    # Different product IDs in DB
    id_res = make_mock_result(rows=[("UNKNOWN_X",), ("UNKNOWN_Y",)])
    mock_conn.execute.side_effect = [count_res, id_res]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    audit = await audit_database_state(mock_engine, df)
    assert audit.state == DatabaseState.CONFLICTING_DATA
    assert audit.can_proceed_with_insert is False
    assert audit.unexpected_ids_count == 2


# ==============================================================================
# 4. Ingestion Execution & Rollback Handling Tests (Unit / Mock)
# ==============================================================================

@async_test
async def test_ingest_products_success():
    """Verify batch insertion completes across batches inside transaction."""
    rows = [create_sample_row(f"ID_{i}") for i in range(5)]
    df = pd.DataFrame(rows)

    mock_conn = AsyncMock()
    mock_trans = MagicMock()
    mock_trans.__aenter__ = AsyncMock(return_value=mock_trans)
    mock_trans.__aexit__ = AsyncMock(return_value=None)
    mock_conn.begin = MagicMock(return_value=mock_trans)

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    metrics = await ingest_products(mock_engine, df, batch_size=2, show_progress=False)
    assert metrics.status == "PASS"
    assert metrics.total_records == 5
    assert metrics.inserted_records == 5
    assert metrics.num_batches == 3
    assert metrics.transaction_status == "COMMITTED"
    assert mock_conn.execute.call_count == 3


@async_test
async def test_ingest_products_failure_rolls_back():
    """Verify intermediate failure raises RuntimeError and triggers transaction rollback."""
    rows = [create_sample_row(f"ID_{i}") for i in range(5)]
    df = pd.DataFrame(rows)

    mock_conn = AsyncMock()
    mock_trans = MagicMock()
    mock_trans.__aenter__ = AsyncMock(return_value=mock_trans)
    mock_trans.__aexit__ = AsyncMock(return_value=None)
    mock_conn.begin = MagicMock(return_value=mock_trans)

    # Fail on second batch
    mock_conn.execute.side_effect = [None, Exception("connection terminated unexpectedly")]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(RuntimeError, match="Atomic ingestion failed during batch execution"):
        await ingest_products(mock_engine, df, batch_size=2, show_progress=False)


# ==============================================================================
# 5. Post-Ingestion Validation Tests (Unit / Mock)
# ==============================================================================

@async_test
async def test_validate_post_ingestion_success():
    """Verify validate_post_ingestion passes when all DB integrity checks hold."""
    row = create_sample_row("ID_1")
    df = pd.DataFrame([row])

    mock_conn = AsyncMock()
    # 1. Count
    r1 = make_mock_result(fetchone_val=(1, 1))
    # 2. Null mandatory
    r2 = make_mock_result(scalar_val=0)
    # 3. Vector dims
    r3 = make_mock_result(scalar_val=0)
    # 4. Specs JSON
    r4 = make_mock_result(scalar_val=0)
    # 5. Timestamps
    r5 = make_mock_result(scalar_val=0)
    # 6. Spot check
    r6 = make_mock_result(
        rows=[
            (
                "ID_1",
                row["product_name"],
                row["category"],
                row["brand"],
                row["retail_price"],
                row["discounted_price"],
                row["rating"],
                row["retrieval_text"],
                row["embedding_model"],
                json.dumps(row["embedding"]),
            )
        ]
    )
    # 7. Smoke test
    r7 = make_mock_result(rows=[("ID_1", row["product_name"], 0.0000001)])

    mock_conn.execute.side_effect = [r1, r2, r3, r4, r5, r6, r7]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    metrics = await validate_post_ingestion(mock_engine, df, sample_size=1)
    assert metrics.status == "PASS"
    assert metrics.total_rows == 1
    assert metrics.distinct_product_ids == 1
    assert metrics.vector_smoke_test_passed is True
    assert metrics.sample_spot_check_matched == 1


@async_test
async def test_validate_post_ingestion_row_count_mismatch():
    """Verify validate_post_ingestion raises ValueError on row count mismatch."""
    df = pd.DataFrame([create_sample_row("ID_1")])

    mock_conn = AsyncMock()
    mock_conn.execute.return_value = make_mock_result(fetchone_val=(0, 0))
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(ValueError, match="Post-ingestion row count mismatch"):
        await validate_post_ingestion(mock_engine, df)


# ==============================================================================
# 6. Report Export Tests
# ==============================================================================

def test_export_ingestion_report(tmp_path: Path):
    """Verify export_ingestion_report writes valid JSON atomically."""
    report_data = {
        "phase": "5.6",
        "overall_status": "PASS",
        "catalog_size": 8405,
    }
    out_file = tmp_path / "test_report.json"
    result_path = export_ingestion_report(report_data, out_file)

    assert result_path.exists()
    content = json.loads(result_path.read_text(encoding="utf-8"))
    assert content["phase"] == "5.6"
    assert content["overall_status"] == "PASS"


# ==============================================================================
# 7. Live Supabase Connection & Audit Integration Test
# ==============================================================================

@async_test
async def test_live_supabase_state_audit():
    """Non-destructive live integration test: connect and audit target database state."""
    try:
        engine = get_async_engine()
    except Exception as exc:
        pytest.skip(f"Supabase credentials unavailable: {exc}")

    if not DEFAULT_SOURCE_PARQUET_PATH.exists():
        pytest.skip("Source Parquet artifact not found.")

    df = pd.read_parquet(DEFAULT_SOURCE_PARQUET_PATH)
    audit = await audit_database_state(engine, df)

    assert audit.state in (DatabaseState.EMPTY_TABLE, DatabaseState.ALREADY_POPULATED)
    assert audit.source_row_count == EXPECTED_CATALOG_SIZE
