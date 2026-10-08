"""Automated unit and integration tests for Phase 5.7: PostgreSQL B-Tree & HNSW Index Construction."""

from __future__ import annotations

import asyncio
from functools import wraps
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shopassist.db.connection import ensure_windows_event_loop_policy, get_async_engine
from shopassist.db.indexing import (
    EXPECTED_INDEXES,
    IndexAuditItem,
    IndexAuditResult,
    IndexDefinition,
    IndexState,
    audit_indexes,
    execute_index_migration,
    export_index_report,
    parse_reloptions,
    validate_all_indexes,
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


def create_mock_catalog_row(
    index_name: str,
    access_method: str = "btree",
    is_valid: bool = True,
    is_ready: bool = True,
    is_primary: bool = False,
    rel_options: list[str] | None = None,
    index_def: str = "",
    indexed_columns: list[str] | None = None,
    opclasses: list[str] | None = None,
) -> MagicMock:
    """Create a mock row mapping for CATALOG_INDEX_QUERY."""
    mapping = {
        "index_name": index_name,
        "access_method": access_method,
        "is_valid": is_valid,
        "is_ready": is_ready,
        "is_primary": is_primary,
        "rel_options": rel_options,
        "index_def": index_def,
        "indexed_columns": indexed_columns or [index_name.replace("idx_products_", "")],
        "opclasses": opclasses or ["text_ops"],
    }
    row = MagicMock()
    row._mapping = mapping
    return row


# ==============================================================================
# 1. Index Specification & Constants Tests (Unit)
# ==============================================================================

def test_expected_indexes_count_and_keys():
    """Verify exactly 5 approved production indexes are defined."""
    assert len(EXPECTED_INDEXES) == 5
    assert set(EXPECTED_INDEXES.keys()) == {
        "idx_products_category",
        "idx_products_price",
        "idx_products_brand",
        "idx_products_category_price",
        "idx_products_embedding",
    }


def test_btree_index_definitions():
    """Verify B-Tree index specifications, single columns, and composite column ordering."""
    cat_idx = EXPECTED_INDEXES["idx_products_category"]
    assert cat_idx.access_method == "btree"
    assert cat_idx.columns == ["category"]

    price_idx = EXPECTED_INDEXES["idx_products_price"]
    assert price_idx.access_method == "btree"
    assert price_idx.columns == ["discounted_price"]

    brand_idx = EXPECTED_INDEXES["idx_products_brand"]
    assert brand_idx.access_method == "btree"
    assert brand_idx.columns == ["brand"]

    # Composite index strictly preserves (category, discounted_price) order
    comp_idx = EXPECTED_INDEXES["idx_products_category_price"]
    assert comp_idx.access_method == "btree"
    assert comp_idx.columns == ["category", "discounted_price"]


def test_hnsw_vector_index_definition():
    """Verify HNSW vector index specification, operator class, and storage parameters."""
    emb_idx = EXPECTED_INDEXES["idx_products_embedding"]
    assert emb_idx.access_method == "hnsw"
    assert emb_idx.columns == ["embedding"]
    assert emb_idx.opclasses == ["vector_cosine_ops"]
    assert emb_idx.options == {"m": "16", "ef_construction": "64"}


def test_parse_reloptions():
    """Verify parse_reloptions correctly parses PostgreSQL storage option arrays."""
    assert parse_reloptions(None) == {}
    assert parse_reloptions([]) == {}
    assert parse_reloptions(["m=16", "ef_construction=64"]) == {"m": "16", "ef_construction": "64"}
    assert parse_reloptions({"m": "16"}) == {"m": "16"}


# ==============================================================================
# 2. Index State Audit Scenarios Tests (Unit / Mock)
# ==============================================================================

@async_test
async def test_audit_scenario_a_indexes_absent():
    """Verify Scenario A is classified when only primary key exists in catalog."""
    mock_conn = AsyncMock()
    # Catalog contains only products_pkey
    mock_conn.execute.return_value = make_mock_result(
        rows=[create_mock_catalog_row("products_pkey", is_primary=True, indexed_columns=["product_id"])]
    )
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    audit = await audit_indexes(mock_engine)
    assert audit.state == IndexState.INDEXES_ABSENT
    assert audit.can_proceed is True
    assert audit.missing_count == 5
    assert audit.existing_matching_count == 0
    assert len(audit.missing_indexes) == 5


@async_test
async def test_audit_scenario_b_all_indexes_match():
    """Verify Scenario B is classified when all 5 indexes exist and match definitions."""
    mock_conn = AsyncMock()
    mock_rows = [
        create_mock_catalog_row("products_pkey", is_primary=True, indexed_columns=["product_id"]),
        create_mock_catalog_row("idx_products_category", indexed_columns=["category"]),
        create_mock_catalog_row("idx_products_price", indexed_columns=["discounted_price"], opclasses=["numeric_ops"]),
        create_mock_catalog_row("idx_products_brand", indexed_columns=["brand"]),
        create_mock_catalog_row(
            "idx_products_category_price",
            indexed_columns=["category", "discounted_price"],
            opclasses=["text_ops", "numeric_ops"],
        ),
        create_mock_catalog_row(
            "idx_products_embedding",
            access_method="hnsw",
            indexed_columns=["embedding"],
            opclasses=["vector_cosine_ops"],
            rel_options=["m=16", "ef_construction=64"],
        ),
    ]
    mock_conn.execute.return_value = make_mock_result(rows=mock_rows)
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    audit = await audit_indexes(mock_engine)
    assert audit.state == IndexState.ALL_INDEXES_EXIST_AND_MATCH
    assert audit.can_proceed is True
    assert audit.missing_count == 0
    assert audit.existing_matching_count == 5


@async_test
async def test_audit_scenario_c_partial_indexes_missing():
    """Verify Scenario C is classified when a subset of matching indexes exists."""
    mock_conn = AsyncMock()
    mock_rows = [
        create_mock_catalog_row("products_pkey", is_primary=True, indexed_columns=["product_id"]),
        create_mock_catalog_row("idx_products_category", indexed_columns=["category"]),
        create_mock_catalog_row("idx_products_price", indexed_columns=["discounted_price"], opclasses=["numeric_ops"]),
    ]
    mock_conn.execute.return_value = make_mock_result(rows=mock_rows)
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    audit = await audit_indexes(mock_engine)
    assert audit.state == IndexState.PARTIAL_INDEXES_MISSING
    assert audit.can_proceed is True
    assert audit.existing_matching_count == 2
    assert audit.missing_count == 3
    assert set(audit.missing_indexes) == {
        "idx_products_brand",
        "idx_products_category_price",
        "idx_products_embedding",
    }


@async_test
async def test_audit_scenario_d_reversed_composite_columns():
    """Verify Scenario D is detected when composite index columns are reversed."""
    mock_conn = AsyncMock()
    mock_rows = [
        # Reversed column order: [discounted_price, category] instead of [category, discounted_price]
        create_mock_catalog_row(
            "idx_products_category_price",
            indexed_columns=["discounted_price", "category"],
        ),
    ]
    mock_conn.execute.return_value = make_mock_result(rows=mock_rows)
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    audit = await audit_indexes(mock_engine)
    assert audit.state == IndexState.CONFLICTING_INDEX_DEFINITION
    assert audit.can_proceed is False
    assert audit.conflicting_count >= 1
    assert "Column list mismatch" in audit.items["idx_products_category_price"].discrepancy


@async_test
async def test_audit_scenario_d_wrong_hnsw_operator_class():
    """Verify Scenario D is detected when HNSW uses wrong operator class."""
    mock_conn = AsyncMock()
    mock_rows = [
        create_mock_catalog_row(
            "idx_products_embedding",
            access_method="hnsw",
            indexed_columns=["embedding"],
            opclasses=["vector_l2_ops"],  # Wrong: should be vector_cosine_ops
            rel_options=["m=16", "ef_construction=64"],
        ),
    ]
    mock_conn.execute.return_value = make_mock_result(rows=mock_rows)
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    audit = await audit_indexes(mock_engine)
    assert audit.state == IndexState.CONFLICTING_INDEX_DEFINITION
    assert audit.can_proceed is False
    assert "Operator class mismatch" in audit.items["idx_products_embedding"].discrepancy


@async_test
async def test_audit_scenario_d_wrong_hnsw_parameter():
    """Verify Scenario D is detected when HNSW parameter does not match m=16, ef_construction=64."""
    mock_conn = AsyncMock()
    mock_rows = [
        create_mock_catalog_row(
            "idx_products_embedding",
            access_method="hnsw",
            indexed_columns=["embedding"],
            opclasses=["vector_cosine_ops"],
            rel_options=["m=32", "ef_construction=128"],  # Wrong parameters
        ),
    ]
    mock_conn.execute.return_value = make_mock_result(rows=mock_rows)
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    audit = await audit_indexes(mock_engine)
    assert audit.state == IndexState.CONFLICTING_INDEX_DEFINITION
    assert audit.can_proceed is False
    assert "HNSW parameter" in audit.items["idx_products_embedding"].discrepancy


@async_test
async def test_audit_scenario_e_invalid_index():
    """Verify Scenario E is detected when an index is marked invalid in pg_index."""
    mock_conn = AsyncMock()
    mock_rows = [
        create_mock_catalog_row(
            "idx_products_category",
            is_valid=False,  # Marked invalid
            is_ready=False,
            indexed_columns=["category"],
        ),
    ]
    mock_conn.execute.return_value = make_mock_result(rows=mock_rows)
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    audit = await audit_indexes(mock_engine)
    assert audit.state == IndexState.INVALID_OR_INCOMPLETE_INDEX
    assert audit.can_proceed is False
    assert audit.invalid_count == 1
    assert "invalid or not ready" in audit.items["idx_products_category"].discrepancy


# ==============================================================================
# 3. Migration Execution & Validation Tests (Unit / Mock)
# ==============================================================================

@async_test
async def test_execute_index_migration_all():
    """Verify execute_index_migration executes DDL for all 5 indexes and commits."""
    mock_conn = AsyncMock()
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    res = await execute_index_migration(mock_engine)
    assert res["status"] == "PASS"
    assert len(res["created_indexes"]) == 5
    assert mock_conn.execute.call_count == 5
    assert mock_conn.commit.call_count == 5


@async_test
async def test_execute_index_migration_rejects_unapproved():
    """Verify execute_index_migration rejects unknown index names."""
    mock_engine = MagicMock()
    with pytest.raises(ValueError, match="Unapproved index name"):
        await execute_index_migration(mock_engine, ["unapproved_index_foo"])


@async_test
async def test_validate_all_indexes_failure_raises():
    """Verify validate_all_indexes raises ValueError if audit is not fully matching."""
    mock_conn = AsyncMock()
    # Missing all indexes
    mock_conn.execute.return_value = make_mock_result(rows=[])
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    with pytest.raises(ValueError, match="Index validation failed"):
        await validate_all_indexes(mock_engine)


# ==============================================================================
# 4. Report Generation Tests
# ==============================================================================

def test_export_index_report(tmp_path: Path):
    """Verify export_index_report saves JSON atomically with required keys."""
    report_dict = {
        "phase": "5.7",
        "overall_status": "PASS",
        "created_indexes": list(EXPECTED_INDEXES.keys()),
    }
    out_file = tmp_path / "phase5_7_test_report.json"
    result_path = export_index_report(report_dict, out_file)

    assert result_path.exists()
    loaded = json.loads(result_path.read_text(encoding="utf-8"))
    assert loaded["phase"] == "5.7"
    assert loaded["overall_status"] == "PASS"


# ==============================================================================
# 5. Live Supabase Pre-Migration Audit Integration Test
# ==============================================================================

@async_test
async def test_live_supabase_index_audit():
    """Non-destructive live integration test: connect and audit current index state."""
    try:
        engine = get_async_engine()
    except Exception as exc:
        pytest.skip(f"Supabase connection unavailable: {exc}")

    audit = await audit_indexes(engine)
    # Target state before or after migration should be clean valid state (A or B)
    assert audit.state in (IndexState.INDEXES_ABSENT, IndexState.ALL_INDEXES_EXIST_AND_MATCH)
    assert audit.can_proceed is True
    assert audit.conflicting_count == 0
    assert audit.invalid_count == 0
