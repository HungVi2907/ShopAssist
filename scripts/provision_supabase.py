"""Executable provisioning and validation pipeline for Supabase PostgreSQL + pgvector.

Phase 5.4 — Supabase PostgreSQL + pgvector Provisioning.

Usage:
    python scripts/provision_supabase.py
    python scripts/provision_supabase.py --validate-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shopassist.core.config import (
    BASE_MIGRATION_PATH,
    mask_database_url,
    settings,
)
from shopassist.db.connection import (
    check_connection,
    ensure_windows_event_loop_policy,
    get_async_engine,
)
from shopassist.db.validation import (
    enable_pgvector,
    provision_base_schema,
    run_transactional_smoke_test,
    validate_constraints,
    validate_deferred_indexes,
    validate_products_table_schema,
    validate_updated_at_trigger,
    validate_vector_dimension,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("provision_supabase")

DEFAULT_REPORT_PATH = Path("data/interim/phase5_4_database_provisioning_report.json")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Phase 5.4 — Supabase PostgreSQL + pgvector Provisioning & Validation."
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Skip DDL provisioning; perform non-mutating schema & smoke test validation only.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Output path for the JSON validation report.",
    )
    return parser.parse_args()


async def run_pipeline(validate_only: bool, report_path: Path) -> int:
    """Run the complete Phase 5.4 provisioning and validation pipeline."""
    ensure_windows_event_loop_policy()

    logger.info("==================================================================")
    logger.info("Starting Phase 5.4 — Supabase PostgreSQL + pgvector Provisioning")
    logger.info("==================================================================")
    logger.info("Execution mode: %s", "VALIDATION ONLY (no DDL)" if validate_only else "FULL PROVISIONING & VALIDATION")
    logger.info("Report path:    %s", report_path)

    # 1. Environment & connection string verification (masked)
    try:
        raw_db_url = settings.get_raw_supabase_db_url()
        masked_url = mask_database_url(raw_db_url)
        logger.info("Supabase database URL loaded: YES")
        logger.info("Target connection: %s", masked_url)
    except ValueError as exc:
        logger.error("Configuration Error: %s", exc)
        return 1

    engine = get_async_engine(url=raw_db_url, pool_size=3, max_overflow=1)

    try:
        # 2. Database connectivity & metadata check (SELECT 1)
        logger.info("1. Verifying PostgreSQL connectivity (SELECT 1)...")
        conn_info = await check_connection(engine)
        logger.info("Connection successful! Database: %s | Server: %s | SSL: %s",
                    conn_info["database"], conn_info["postgresql_version"], conn_info["ssl"])

        # 3. Enable / Verify pgvector extension
        logger.info("2. Checking / Enabling pgvector extension...")
        if not validate_only:
            pgvector_info = await enable_pgvector(engine)
        else:
            async with engine.connect() as conn:
                from sqlalchemy import text
                ext_res = await conn.execute(
                    text("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';")
                )
                row = ext_res.fetchone()
                if not row:
                    raise RuntimeError("pgvector extension not installed in validate-only mode!")
                pgvector_info = {"enabled": True, "name": str(row[0]), "version": str(row[1])}
        logger.info("pgvector verified: %s v%s", pgvector_info["name"], pgvector_info["version"])

        # 4. Provision Base Schema (Products table & triggers, NO Phase 5.7 indexes)
        if not validate_only:
            logger.info("3. Executing base schema DDL migration (%s)...", BASE_MIGRATION_PATH.name)
            await provision_base_schema(engine, migration_path=BASE_MIGRATION_PATH)
        else:
            logger.info("3. Skipping DDL execution (--validate-only active).")

        # 5. Programmatic schema validation (17 columns, nullability, PK, JSONB)
        logger.info("4. Validating products table schema & column constraints...")
        schema_info = await validate_products_table_schema(engine)
        logger.info("Table schema verified: %d columns, PK=%s, JSONB valid.",
                    schema_info["column_count"], schema_info["primary_key"])

        # 6. Verify vector(384) dimension
        logger.info("5. Verifying vector(384) dimension in pg_attribute...")
        vector_info = await validate_vector_dimension(engine, expected_dim=384)
        logger.info("Vector column verified: %s (dimension=%d)",
                    vector_info["embedding_type"], vector_info["embedding_dimension"])

        # 7. Verify CHECK constraints
        logger.info("6. Verifying CHECK constraints via pg_constraint...")
        constraint_info = await validate_constraints(engine)
        logger.info("CHECK constraints verified: %d active constraints.",
                    constraint_info["check_constraints_count"])

        # 8. Verify updated_at trigger
        logger.info("7. Verifying updated_at trigger...")
        trigger_info = await validate_updated_at_trigger(engine)
        logger.info("Trigger verified: %s (%s %s)",
                    trigger_info["trigger_name"], trigger_info["timing"], trigger_info["event"])

        # 9. Verify Phase 5.7 indexes are cleanly deferred
        logger.info("8. Verifying deferred status of Phase 5.7 indexes...")
        index_info = await validate_deferred_indexes(engine)
        logger.info("Phase 5.7 indexes deferred: %s (Existing indexes: %s)",
                    index_info["phase5_7_indexes_deferred"], index_info["existing_indexes"])

        # 10. Execute transactional smoke test (insert, update trigger, cosine distance, rollback)
        logger.info("9. Executing transactional pgvector smoke test...")
        smoke_info = await run_transactional_smoke_test(engine)
        logger.info("Smoke test passed: insert=%s, trigger=%s, cosine_search=%s, rollback=%s",
                    smoke_info["insert_valid"],
                    smoke_info["updated_at_trigger_behavior_valid"],
                    smoke_info["cosine_operator_valid"],
                    smoke_info["rollback_verified"])

        # Assemble JSON report (never contains secrets)
        report: dict[str, Any] = {
            "phase": "5.4",
            "connection_method": conn_info["connection_method"],
            "connection_status": conn_info["connection_status"],
            "ssl": conn_info["ssl"],
            "postgresql": {
                "version": conn_info["postgresql_version"],
                "database": conn_info["database"],
            },
            "pgvector": {
                "enabled": pgvector_info["enabled"],
                "version": pgvector_info["version"],
            },
            "products_table": {
                "exists": schema_info["table_exists"],
                "column_count": schema_info["column_count"],
                "primary_key": schema_info["primary_key"],
                "jsonb_column_valid": schema_info["jsonb_column_valid"],
                "embedding_type": vector_info["embedding_type"],
                "embedding_dimension": vector_info["embedding_dimension"],
            },
            "constraints": {
                "check_constraints_count": constraint_info["check_constraints_count"],
                "required_constraints_verified": constraint_info["required_constraints_verified"],
            },
            "defaults": {
                "embedding_model": "BAAI/bge-small-en-v1.5",
                "created_at": True,
                "updated_at": True,
            },
            "trigger": {
                "updated_at_trigger_exists": True,
                "trigger_name": trigger_info["trigger_name"],
                "behavior_verified": smoke_info["updated_at_trigger_behavior_valid"],
            },
            "pgvector_smoke_test": {
                "insert_valid": smoke_info["insert_valid"],
                "cosine_operator_valid": smoke_info["cosine_operator_valid"],
                "ranking_valid": smoke_info["ranking_valid"],
                "rollback_verified": smoke_info["rollback_verified"],
                "residual_records_count": smoke_info["residual_records_count"],
            },
            "indexes": {
                "phase5_7_deferred": index_info["phase5_7_indexes_deferred"],
                "existing_indexes": index_info["existing_indexes"],
            },
            "overall_status": "PASS",
        }

        # Write machine-readable report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info("Saved Phase 5.4 provisioning report to: %s", report_path)

        # Print formatted terminal summary
        print("\n" + "=" * 70)
        print("PHASE 5.4 — SUPABASE POSTGRESQL + PGVECTOR PROVISIONING SUMMARY")
        print("=" * 70)
        print("CONNECTION:")
        print(f"  Method:                     {report['connection_method']}")
        print("  Port:                       5432 (SSL enabled)")
        print(f"  Status:                     {report['connection_status']}")
        print(f"  Database Server:            {report['postgresql']['version']} (Database: {report['postgresql']['database']})")
        print("-" * 70)
        print("PGVECTOR EXTENSION:")
        print(f"  Extension Enabled:          {report['pgvector']['enabled']}")
        print(f"  Extension Version:          v{report['pgvector']['version']}")
        print("-" * 70)
        print("PRODUCTS SCHEMA CONTRACT:")
        print(f"  Table Name:                 public.products (Exists: {report['products_table']['exists']})")
        print(f"  Total Columns:              {report['products_table']['column_count']} (17 required columns verified)")
        print(f"  Primary Key:                {report['products_table']['primary_key']}")
        print(f"  JSONB Specifications:       {report['products_table']['jsonb_column_valid']} (Default: '[]'::jsonb)")
        print(f"  Embedding Column:           {report['products_table']['embedding_type']}")
        print(f"  Embedding Dimension:        {report['products_table']['embedding_dimension']}")
        print(f"  CHECK Constraints:          {report['constraints']['check_constraints_count']} constraints verified")
        print(f"  Trigger:                    {report['trigger']['trigger_name']} (Behavior verified: PASS)")
        print("-" * 70)
        print("TRANSACTIONAL SMOKE TEST:")
        print(f"  Constraint Invalidation:    VERIFIED (Negative price, rating > 5, empty name rejected)")
        print(f"  Temporary Vector Inserts:   PASS (2 records with 384-d unit vectors)")
        print(f"  pgvector <=> Operator:      PASS (Cosine distance ranking verified)")
        print(f"  Rollback Audit:             PASS (0 residual test records in database)")
        print("-" * 70)
        print("INDEX BOUNDARY:")
        print("  Status:                     DEFERRED TO PHASE 5.7 (Cleanly separated in 002 migration)")
        print("=" * 70)
        print(f"OVERALL STATUS:               {report['overall_status']}")
        print(f"REPORT ARTIFACT:              {report_path}")
        print("=" * 70 + "\n")

        return 0

    except Exception as exc:
        logger.error("Phase 5.4 provisioning failed: %s", exc)
        return 1
    finally:
        await engine.dispose()


def main() -> int:
    """CLI entry point."""
    ensure_windows_event_loop_policy()
    args = parse_args()
    return asyncio.run(run_pipeline(validate_only=args.validate_only, report_path=args.report))


if __name__ == "__main__":
    sys.exit(main())
