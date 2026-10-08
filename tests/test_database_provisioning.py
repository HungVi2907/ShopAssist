"""Automated unit and integration tests for Phase 5.4 Supabase PostgreSQL + pgvector provisioning."""

from __future__ import annotations

import asyncio
from functools import wraps
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shopassist.core.config import mask_database_url, Settings
from shopassist.db.connection import (
    check_connection,
    ensure_windows_event_loop_policy,
    get_async_database_url,
    get_async_engine,
)
from shopassist.db.validation import (
    DEFERRED_PHASE_5_7_INDEXES,
    enable_pgvector,
    validate_constraints,
    validate_deferred_indexes,
    validate_products_table_schema,
    validate_updated_at_trigger,
    validate_vector_dimension,
)

ensure_windows_event_loop_policy()


def async_test(coro):
    """Decorator to execute async test functions cleanly without requiring pytest-asyncio plugin."""
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


# ==============================================================================
# 1. Config & Masking Tests (Unit)
# ==============================================================================

def test_supabase_db_url_required_when_missing():
    """Verify ValueError is raised when SUPABASE_DB_URL is unset."""
    with patch.dict("os.environ", {}, clear=True):
        with patch("shopassist.core.config.ENV_FILE_PATH") as mock_path:
            mock_path.exists.return_value = False
            empty_settings = Settings(_env_file=None, supabase_db_url=None)
            with pytest.raises(ValueError, match="SUPABASE_DB_URL is missing or empty"):
                empty_settings.get_raw_supabase_db_url()


def test_mask_database_url_masks_credentials_and_host():
    """Verify secret masking hides password, project ref, and pooler host."""
    raw_url = "postgresql://postgres.myprojectref123:SuperSecretP@ssw0rd!@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
    masked = mask_database_url(raw_url)

    assert "SuperSecretP@ssw0rd!" not in masked
    assert "myprojectref123" not in masked
    assert "aws-0-ap-southeast-1" not in masked
    assert masked.startswith("postgresql://postgres.***:***@***.pooler.supabase.com:5432/postgres")


def test_mask_database_url_none_or_empty():
    """Verify masking handles None or empty input safely."""
    assert mask_database_url(None) == "[NOT CONFIGURED]"
    assert mask_database_url("") == "[NOT CONFIGURED]"
    assert mask_database_url("   ") == "[NOT CONFIGURED]"


def test_get_async_database_url_conversion():
    """Verify standard postgresql:// URL is cleanly converted to async driver URL."""
    raw = "postgresql://user:pass@host:5432/db"
    async_url = get_async_database_url(raw)
    assert async_url.startswith("postgresql+psycopg_async://")
    assert "user:pass@host:5432/db" in async_url

    # Idempotent when already async
    assert get_async_database_url(async_url) == async_url


# ==============================================================================
# 2. Connection & Error Sanitization Tests (Unit)
# ==============================================================================

@async_test
async def test_check_connection_failure_handling():
    """Verify check_connection sanitizes error messages and suppresses credentials."""
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = Exception("FATAL: password authentication failed for user postgres.secretref")

    with pytest.raises(RuntimeError) as exc_info:
        await check_connection(mock_engine)

    err_msg = str(exc_info.value)
    assert "secretref" not in err_msg
    assert "Supabase connection test failed" in err_msg


# ==============================================================================
# 3. Schema & Catalog Audit Tests (Unit with Mocks)
# ==============================================================================

@async_test
async def test_enable_pgvector_missing_raises_error():
    """Verify enable_pgvector raises RuntimeError if pg_extension catalog returns no row."""
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = make_mock_result(fetchone_val=None)

    mock_engine = MagicMock()
    mock_engine.begin.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(RuntimeError, match="Failed to enable 'vector' extension"):
        await enable_pgvector(mock_engine)


@async_test
async def test_validate_products_table_missing_table_raises():
    """Verify validate_products_table_schema raises error if table does not exist."""
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = make_mock_result(scalar_val=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(RuntimeError, match="does not exist in database"):
        await validate_products_table_schema(mock_engine)


@async_test
async def test_validate_products_table_missing_columns_raises():
    """Verify validate_products_table_schema detects missing required columns."""
    mock_conn = AsyncMock()
    # 1st call for table exists check -> scalar True
    # 2nd call for columns fetchall -> partial columns
    mock_res_exists = make_mock_result(scalar_val=True)
    mock_res_cols = make_mock_result(rows=[
        ("product_id", "character varying", "varchar", "NO", None),
        ("product_name", "text", "text", "NO", None),
    ])
    mock_conn.execute.side_effect = [mock_res_exists, mock_res_cols]

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(ValueError, match="Missing required columns in products table"):
        await validate_products_table_schema(mock_engine)


@async_test
async def test_validate_vector_dimension_success_and_failure():
    """Verify vector dimension checks vector(384) and rejects invalid dimensions."""
    mock_conn = AsyncMock()
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    # Success case: vector(384)
    mock_conn.execute.return_value = make_mock_result(fetchone_val=("vector(384)",))
    res = await validate_vector_dimension(mock_engine, expected_dim=384)
    assert res["status"] == "PASS"
    assert res["embedding_dimension"] == 384

    # Failure case: vector(512)
    mock_conn.execute.return_value = make_mock_result(fetchone_val=("vector(512)",))
    with pytest.raises(ValueError, match="Vector dimension mismatch"):
        await validate_vector_dimension(mock_engine, expected_dim=384)

    # Failure case: un-dimensioned vector or wrong type
    mock_conn.execute.return_value = make_mock_result(fetchone_val=("USER-DEFINED",))
    with pytest.raises(ValueError, match="not a dimensioned vector"):
        await validate_vector_dimension(mock_engine, expected_dim=384)


@async_test
async def test_validate_constraints_detects_missing_check():
    """Verify validate_constraints raises ValueError when required CHECK constraints are absent."""
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = make_mock_result(rows=[])

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(ValueError, match="Missing required CHECK constraints"):
        await validate_constraints(mock_engine)


@async_test
async def test_validate_updated_at_trigger_missing_raises():
    """Verify validate_updated_at_trigger raises RuntimeError if trigger function is missing."""
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = make_mock_result(scalar_val=None)

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(RuntimeError, match="update_products_updated_at.*not found"):
        await validate_updated_at_trigger(mock_engine)


@async_test
async def test_validate_deferred_indexes_detects_phase5_7_indexes():
    """Verify validate_deferred_indexes identifies if Phase 5.7 indexes were accidentally created."""
    mock_conn = AsyncMock()
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    # Case 1: Only primary key index exists (deferred = True)
    mock_conn.execute.return_value = make_mock_result(rows=[("products_pkey",)])
    res1 = await validate_deferred_indexes(mock_engine)
    assert res1["phase5_7_indexes_deferred"] is True

    # Case 2: HNSW index prematurely exists (deferred = False)
    mock_conn.execute.return_value = make_mock_result(rows=[
        ("products_pkey",),
        ("idx_products_embedding",),
    ])
    res2 = await validate_deferred_indexes(mock_engine)
    assert res2["phase5_7_indexes_deferred"] is False


# ==============================================================================
# 4. Phase 5.4 Report Integrity Test (Unit)
# ==============================================================================

def test_phase5_4_report_schema_and_integrity():
    """Verify generated JSON provisioning report exists and adheres to contract schema."""
    report_file = Path("data/interim/phase5_4_database_provisioning_report.json")
    assert report_file.exists(), "Phase 5.4 report JSON file must exist"

    with open(report_file, "r", encoding="utf-8") as f:
        report = json.load(f)

    # Core required fields
    assert report["phase"] == "5.4"
    assert report["connection_method"] == "Supavisor Session Pooler"
    assert report["connection_status"] == "PASS"
    assert report["ssl"] is True
    assert report["overall_status"] == "PASS"

    # PostgreSQL metadata
    assert "PostgreSQL" in report["postgresql"]["version"]
    assert report["postgresql"]["database"] == "postgres"

    # pgvector extension
    assert report["pgvector"]["enabled"] is True
    assert report["pgvector"]["version"] == "0.8.2"

    # Products table contract
    assert report["products_table"]["exists"] is True
    assert report["products_table"]["column_count"] == 17
    assert report["products_table"]["primary_key"] == "product_id"
    assert report["products_table"]["jsonb_column_valid"] is True
    assert report["products_table"]["embedding_type"] == "vector(384)"
    assert report["products_table"]["embedding_dimension"] == 384

    # Constraints & defaults
    assert report["constraints"]["check_constraints_count"] >= 6
    assert report["constraints"]["required_constraints_verified"] is True
    assert report["defaults"]["embedding_model"] == "BAAI/bge-small-en-v1.5"

    # Trigger & Smoke Test
    assert report["trigger"]["updated_at_trigger_exists"] is True
    assert report["trigger"]["behavior_verified"] is True
    assert report["pgvector_smoke_test"]["insert_valid"] is True
    assert report["pgvector_smoke_test"]["cosine_operator_valid"] is True
    assert report["pgvector_smoke_test"]["ranking_valid"] is True
    assert report["pgvector_smoke_test"]["rollback_verified"] is True
    assert report["pgvector_smoke_test"]["residual_records_count"] == 0

    # Index boundary
    assert report["indexes"]["phase5_7_deferred"] is True

    # Security: report must NEVER contain secret patterns
    report_raw_str = json.dumps(report)
    assert "password" not in report_raw_str.lower()
    assert "postgres://" not in report_raw_str
    assert "postgresql://" not in report_raw_str


# ==============================================================================
# 5. Live Supabase Integration Test (Marked Integration)
# ==============================================================================

@pytest.mark.integration
@async_test
async def test_live_supabase_provisioning_integration():
    """Verify live connectivity and provisioned schema on Supabase PostgreSQL."""
    engine = get_async_engine(pool_size=2, max_overflow=0)
    try:
        # 1. Connectivity
        conn_res = await check_connection(engine)
        assert conn_res["connection_status"] == "PASS"
        assert conn_res["connection_method"] == "Supavisor Session Pooler"
        assert conn_res["ssl"] is True

        # 2. Table schema
        schema_res = await validate_products_table_schema(engine)
        assert schema_res["table_exists"] is True
        assert schema_res["column_count"] == 17
        assert schema_res["primary_key"] == "product_id"

        # 3. Vector dimension
        dim_res = await validate_vector_dimension(engine, expected_dim=384)
        assert dim_res["embedding_dimension"] == 384

        # 4. Deferred indexes
        idx_res = await validate_deferred_indexes(engine)
        assert idx_res["phase5_7_indexes_deferred"] is True

    finally:
        await engine.dispose()
