"""Automated unit and integration tests for Phase 5.4 Supabase PostgreSQL + pgvector provisioning."""

from __future__ import annotations

import asyncio
from functools import wraps
import json
from pathlib import Path
from traceback import format_exception
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shopassist.core.config import mask_database_url, settings, Settings
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

_TEST_DSN = "postgresql://postgres.secretref:driver-password@offline.invalid:5432/postgres"


@pytest.mark.parametrize("dsn", [None, _TEST_DSN], ids=["missing-dsn", "configured-dsn"])
@async_test
async def test_check_connection_failure_handling(dsn, monkeypatch, caplog):
    """Verify check_connection sanitizes error messages and suppresses credentials."""
    monkeypatch.setattr(settings, "supabase_db_url", dsn)
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = OSError(f"FATAL: connection failed for {_TEST_DSN}")

    with pytest.raises(RuntimeError, match=r"^Supabase connection test failed\.$") as exc_info:
        await check_connection(mock_engine)

    assert "Supabase connection test failed." in caplog.text
    traceback_text = "".join(format_exception(exc_info.value))
    for secret in ("secretref", "driver-password"):
        assert secret not in traceback_text
        assert secret not in caplog.text
    mock_engine.connect.assert_called_once_with()


@async_test
async def test_check_connection_without_engine_preserves_missing_dsn_error(monkeypatch):
    monkeypatch.setattr(settings, "supabase_db_url", None)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    with patch("shopassist.core.config.ENV_FILE_PATH") as env_file, patch(
        "shopassist.db.connection.create_async_engine"
    ) as create_engine:
        env_file.exists.return_value = False
        with pytest.raises(ValueError, match="SUPABASE_DB_URL is missing or empty"):
            await check_connection()
    create_engine.assert_not_called()


@pytest.mark.parametrize("entry_point", ["factory", "connection-check"])
@async_test
async def test_engine_initialization_failure_is_sanitized(entry_point, monkeypatch, caplog):
    monkeypatch.setattr(settings, "supabase_db_url", _TEST_DSN)
    with patch("shopassist.db.connection.create_async_engine", side_effect=OSError(_TEST_DSN)) as create_engine:
        with pytest.raises(RuntimeError, match=r"^Supabase database engine initialization failed\.$") as exc_info:
            if entry_point == "factory":
                get_async_engine()
            else:
                await check_connection()
    create_engine.assert_called_once()
    assert "Failed to initialize Supabase async database engine." in caplog.text
    traceback_text = "".join(format_exception(exc_info.value))
    for secret in ("secretref", "driver-password"):
        assert secret not in traceback_text
        assert secret not in caplog.text


def test_get_async_engine_hides_invalid_port_value():
    malformed_url = "postgresql://offline.invalid:driver-password/postgres"
    with patch("shopassist.db.connection.create_async_engine") as create_engine:
        with pytest.raises(ValueError, match=r"^Invalid Supabase database URL\.$") as exc_info:
            get_async_engine(url=malformed_url)
    create_engine.assert_not_called()
    assert "driver-password" not in "".join(format_exception(exc_info.value))


@async_test
async def test_temporary_engine_cleanup_failure_is_sanitized(monkeypatch, caplog):
    monkeypatch.setattr(settings, "supabase_db_url", _TEST_DSN)
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = OSError(_TEST_DSN)
    mock_engine.dispose = AsyncMock(side_effect=OSError(_TEST_DSN))
    with patch("shopassist.db.connection.create_async_engine", return_value=mock_engine) as create_engine:
        with pytest.raises(RuntimeError, match=r"^Supabase database engine cleanup failed\.$") as exc_info:
            await check_connection()

    create_engine.assert_called_once_with(
        _TEST_DSN.replace("postgresql://", "postgresql+psycopg_async://", 1),
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    mock_engine.dispose.assert_awaited_once_with()
    assert "Failed to dispose of the temporary Supabase database engine." in caplog.text
    traceback_text = "".join(format_exception(exc_info.value))
    for secret in ("secretref", "driver-password"):
        assert secret not in traceback_text
        assert secret not in caplog.text


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

        # 4. Indexes check
        idx_res = await validate_deferred_indexes(engine)
        assert idx_res["status"] == "PASS"
        assert "products_pkey" in idx_res["existing_indexes"]

    finally:
        await engine.dispose()
