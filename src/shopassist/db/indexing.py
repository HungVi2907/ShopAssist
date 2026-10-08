"""PostgreSQL B-Tree and HNSW index construction, catalog auditing, and query plan benchmarking.

Phase 5.7 of ShopAssist:
- Target table: public.products (Supabase Cloud PostgreSQL 17.11 + pgvector 0.8.2)
- Relational B-Tree indexes:
    1. idx_products_category (category)
    2. idx_products_price (discounted_price)
    3. idx_products_brand (brand)
    4. idx_products_category_price (category, discounted_price)
- Vector HNSW index:
    5. idx_products_embedding (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)
- Strict catalog state audit (Scenarios A through E)
- Query plan benchmarking with EXPLAIN (ANALYZE, BUFFERS)
- Post-migration catalog and data integrity verification
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from shopassist.core.config import (
    INDEX_MIGRATION_PATH,
    INTERIM_DATA_DIR,
    mask_database_url,
    settings,
)
from shopassist.db.connection import (
    check_connection,
    ensure_windows_event_loop_policy,
    get_async_engine,
)
from shopassist.db.validation import (
    validate_constraints,
    validate_products_table_schema,
    validate_updated_at_trigger,
    validate_vector_dimension,
)

ensure_windows_event_loop_policy()

logger = logging.getLogger(__name__)

DEFAULT_INDEX_REPORT_PATH: Path = INTERIM_DATA_DIR / "phase5_7_index_construction_report.json"
EXPECTED_CATALOG_SIZE: int = 8405
EXPECTED_EMBEDDING_DIM: int = 384
TARGET_TABLE: str = "public.products"


class IndexState(str, Enum):
    """Classification of database index state prior to or after migration."""

    INDEXES_ABSENT = "INDEXES_ABSENT"  # Scenario A: Only primary key exists, proceed with migration
    ALL_INDEXES_EXIST_AND_MATCH = "ALL_INDEXES_EXIST_AND_MATCH"  # Scenario B: All 5 indexes exist & match (no-op)
    PARTIAL_INDEXES_MISSING = "PARTIAL_INDEXES_MISSING"  # Scenario C: Valid subset exists, create missing
    CONFLICTING_INDEX_DEFINITION = "CONFLICTING_INDEX_DEFINITION"  # Scenario D: Unapproved or altered definition
    INVALID_OR_INCOMPLETE_INDEX = "INVALID_OR_INCOMPLETE_INDEX"  # Scenario E: Index marked invalid or not ready


@dataclass
class IndexDefinition:
    """Canonical specification for an approved production index."""

    name: str
    table: str
    access_method: str  # 'btree' or 'hnsw'
    columns: list[str]
    opclasses: list[str] | None = None
    options: dict[str, str] | None = None
    ddl: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Approved canonical specifications per database/migrations/002_create_product_indexes.sql
EXPECTED_INDEXES: dict[str, IndexDefinition] = {
    "idx_products_category": IndexDefinition(
        name="idx_products_category",
        table="products",
        access_method="btree",
        columns=["category"],
        opclasses=["text_ops"],
        options=None,
        ddl="CREATE INDEX IF NOT EXISTS idx_products_category ON public.products (category);",
    ),
    "idx_products_price": IndexDefinition(
        name="idx_products_price",
        table="products",
        access_method="btree",
        columns=["discounted_price"],
        opclasses=["numeric_ops"],
        options=None,
        ddl="CREATE INDEX IF NOT EXISTS idx_products_price ON public.products (discounted_price);",
    ),
    "idx_products_brand": IndexDefinition(
        name="idx_products_brand",
        table="products",
        access_method="btree",
        columns=["brand"],
        opclasses=["text_ops"],
        options=None,
        ddl="CREATE INDEX IF NOT EXISTS idx_products_brand ON public.products (brand);",
    ),
    "idx_products_category_price": IndexDefinition(
        name="idx_products_category_price",
        table="products",
        access_method="btree",
        columns=["category", "discounted_price"],
        opclasses=["text_ops", "numeric_ops"],
        options=None,
        ddl="CREATE INDEX IF NOT EXISTS idx_products_category_price ON public.products (category, discounted_price);",
    ),
    "idx_products_embedding": IndexDefinition(
        name="idx_products_embedding",
        table="products",
        access_method="hnsw",
        columns=["embedding"],
        opclasses=["vector_cosine_ops"],
        options={"m": "16", "ef_construction": "64"},
        ddl=(
            "CREATE INDEX IF NOT EXISTS idx_products_embedding ON public.products "
            "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);"
        ),
    ),
}


@dataclass
class IndexAuditItem:
    """Observed catalog properties for a specific index."""

    name: str
    exists: bool
    access_method: str | None = None
    indexed_columns: list[str] | None = None
    opclasses: list[str] | None = None
    options: dict[str, str] | None = None
    is_valid: bool | None = None
    is_ready: bool | None = None
    is_primary: bool | None = None
    index_def: str | None = None
    matches_expected: bool = False
    discrepancy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IndexAuditResult:
    """Comprehensive result of index catalog audit."""

    state: IndexState
    total_expected: int
    existing_matching_count: int
    missing_count: int
    conflicting_count: int
    invalid_count: int
    items: dict[str, IndexAuditItem] = field(default_factory=dict)
    missing_indexes: list[str] = field(default_factory=list)
    can_proceed: bool = True
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "total_expected": self.total_expected,
            "existing_matching_count": self.existing_matching_count,
            "missing_count": self.missing_count,
            "conflicting_count": self.conflicting_count,
            "invalid_count": self.invalid_count,
            "missing_indexes": self.missing_indexes,
            "can_proceed": self.can_proceed,
            "message": self.message,
            "items": {k: v.to_dict() for k, v in self.items.items()},
        }


def parse_reloptions(options_raw: Any) -> dict[str, str]:
    """Parse PostgreSQL pg_class.reloptions array into key-value dictionary."""
    if not options_raw:
        return {}
    if isinstance(options_raw, dict):
        return {str(k): str(v) for k, v in options_raw.items()}

    opts: dict[str, str] = {}
    for item in options_raw:
        if isinstance(item, str) and "=" in item:
            k, v = item.split("=", 1)
            opts[k.strip()] = v.strip()
    return opts


CATALOG_INDEX_QUERY = text("""
    SELECT 
        c.relname AS index_name,
        am.amname AS access_method,
        i.indisvalid AS is_valid,
        i.indisready AS is_ready,
        i.indisprimary AS is_primary,
        c.reloptions AS rel_options,
        pg_get_indexdef(c.oid) AS index_def,
        ARRAY(
            SELECT a.attname
            FROM unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
            ORDER BY k.ord
        ) AS indexed_columns,
        ARRAY(
            SELECT opc.opcname
            FROM unnest(i.indclass) WITH ORDINALITY AS c(opcid, ord)
            JOIN pg_opclass opc ON opc.oid = c.opcid
            ORDER BY c.ord
        ) AS opclasses
    FROM pg_index i
    JOIN pg_class c ON c.oid = i.indexrelid
    JOIN pg_class t ON t.oid = i.indrelid
    JOIN pg_am am ON am.oid = c.relam
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND t.relname = 'products';
""")


async def fetch_catalog_indexes(conn: AsyncConnection) -> dict[str, dict[str, Any]]:
    """Retrieve all current indexes on public.products directly from PostgreSQL catalogs."""
    res = await conn.execute(CATALOG_INDEX_QUERY)
    catalog_dict: dict[str, dict[str, Any]] = {}
    for row in res.fetchall():
        mapping = dict(row._mapping)
        name = mapping["index_name"]
        mapping["options"] = parse_reloptions(mapping.get("rel_options"))
        catalog_dict[name] = mapping
    return catalog_dict


async def audit_indexes(engine: AsyncEngine) -> IndexAuditResult:
    """Perform comprehensive catalog audit of public.products indexes.

    Evaluates:
    - Index existence in pg_class / pg_index.
    - Index validity (indisvalid) and readiness (indisready).
    - Access method match ('btree' / 'hnsw').
    - Indexed columns and column order match approved specification.
    - Vector operator class matches 'vector_cosine_ops'.
    - HNSW storage options match m=16, ef_construction=64.

    Returns:
        IndexAuditResult with state classification (Scenario A, B, C, D, or E).
    """
    logger.info("Auditing PostgreSQL system catalogs for public.products indexes...")
    async with engine.connect() as conn:
        catalog_indexes = await fetch_catalog_indexes(conn)

    audit_items: dict[str, IndexAuditItem] = {}
    missing_indexes: list[str] = []
    conflicting_indexes: list[str] = []
    invalid_indexes: list[str] = []
    matching_indexes: list[str] = []

    for name, expected in EXPECTED_INDEXES.items():
        if name not in catalog_indexes:
            missing_indexes.append(name)
            audit_items[name] = IndexAuditItem(
                name=name,
                exists=False,
                matches_expected=False,
                discrepancy="Index does not exist in catalog",
            )
            continue

        obs = catalog_indexes[name]
        is_valid = bool(obs.get("is_valid", False))
        is_ready = bool(obs.get("is_ready", False))
        access_method = str(obs.get("access_method", "")).lower()
        indexed_cols = list(obs.get("indexed_columns") or [])
        opclasses = list(obs.get("opclasses") or [])
        options = dict(obs.get("options") or {})
        index_def = str(obs.get("index_def") or "")

        discrepancies: list[str] = []

        # Check validity
        if not is_valid or not is_ready:
            discrepancies.append(f"Index is invalid or not ready (valid={is_valid}, ready={is_ready})")
            invalid_indexes.append(name)

        # Check access method
        if access_method != expected.access_method:
            discrepancies.append(
                f"Access method mismatch: expected '{expected.access_method}', got '{access_method}'"
            )

        # Check indexed columns and strict column order
        if indexed_cols != expected.columns:
            discrepancies.append(
                f"Column list mismatch: expected {expected.columns}, got {indexed_cols}"
            )

        # Check opclasses (specifically for vector)
        if expected.access_method == "hnsw":
            if "vector_cosine_ops" not in opclasses:
                discrepancies.append(
                    f"Operator class mismatch for HNSW: expected 'vector_cosine_ops', got {opclasses}"
                )
            # Check HNSW parameters
            exp_opts = expected.options or {}
            for opt_k, exp_v in exp_opts.items():
                act_v = options.get(opt_k)
                if act_v != exp_v:
                    discrepancies.append(
                        f"HNSW parameter '{opt_k}' mismatch: expected {exp_v}, got {act_v}"
                    )

        if discrepancies:
            conflicting_indexes.append(name)
            audit_items[name] = IndexAuditItem(
                name=name,
                exists=True,
                access_method=access_method,
                indexed_columns=indexed_cols,
                opclasses=opclasses,
                options=options,
                is_valid=is_valid,
                is_ready=is_ready,
                is_primary=bool(obs.get("is_primary")),
                index_def=index_def,
                matches_expected=False,
                discrepancy="; ".join(discrepancies),
            )
        else:
            matching_indexes.append(name)
            audit_items[name] = IndexAuditItem(
                name=name,
                exists=True,
                access_method=access_method,
                indexed_columns=indexed_cols,
                opclasses=opclasses,
                options=options,
                is_valid=is_valid,
                is_ready=is_ready,
                is_primary=bool(obs.get("is_primary")),
                index_def=index_def,
                matches_expected=True,
                discrepancy=None,
            )

    # Classify overall state
    total_exp = len(EXPECTED_INDEXES)
    if invalid_indexes:
        state = IndexState.INVALID_OR_INCOMPLETE_INDEX
        can_proceed = False
        message = f"Found {len(invalid_indexes)} invalid or incomplete indexes: {invalid_indexes} (Scenario E)."
    elif conflicting_indexes:
        state = IndexState.CONFLICTING_INDEX_DEFINITION
        can_proceed = False
        message = f"Found {len(conflicting_indexes)} indexes with conflicting definitions: {conflicting_indexes} (Scenario D)."
    elif len(matching_indexes) == total_exp:
        state = IndexState.ALL_INDEXES_EXIST_AND_MATCH
        can_proceed = True
        message = f"All {total_exp} approved production indexes already exist and match specifications (Scenario B)."
    elif len(missing_indexes) == total_exp:
        state = IndexState.INDEXES_ABSENT
        can_proceed = True
        message = f"All {total_exp} approved production indexes are absent. Ready for migration (Scenario A)."
    else:
        state = IndexState.PARTIAL_INDEXES_MISSING
        can_proceed = True
        message = (
            f"Found {len(matching_indexes)}/{total_exp} matching indexes. "
            f"Missing {len(missing_indexes)} indexes: {missing_indexes} (Scenario C)."
        )

    logger.info("Index audit state: %s — %s", state.value, message)

    return IndexAuditResult(
        state=state,
        total_expected=total_exp,
        existing_matching_count=len(matching_indexes),
        missing_count=len(missing_indexes),
        conflicting_count=len(conflicting_indexes),
        invalid_count=len(invalid_indexes),
        items=audit_items,
        missing_indexes=missing_indexes,
        can_proceed=can_proceed,
        message=message,
    )


async def execute_index_migration(
    engine: AsyncEngine,
    indexes_to_create: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Execute creation of approved indexes on public.products.

    Design:
    - Runs standard CREATE INDEX statements matching database/migrations/002_create_product_indexes.sql.
    - If indexes_to_create is specified, creates only those specific indexes.
    - Executes DDL sequentially and records per-index timing.

    Args:
        engine: AsyncEngine connected to Supabase PostgreSQL.
        indexes_to_create: Optional list of index names to create. Defaults to all 5.

    Returns:
        Dictionary with execution timings, created indexes, and status.
    """
    target_names = list(indexes_to_create) if indexes_to_create is not None else list(EXPECTED_INDEXES.keys())
    logger.info("Executing index creation for %d indexes: %s...", len(target_names), target_names)

    t_start = time.time()
    created_timings: dict[str, float] = {}

    async with engine.connect() as conn:
        for idx_name in target_names:
            if idx_name not in EXPECTED_INDEXES:
                raise ValueError(f"Unapproved index name requested: '{idx_name}'")

            idx_spec = EXPECTED_INDEXES[idx_name]
            logger.info("Creating index '%s' (%s on %s)...", idx_name, idx_spec.access_method, idx_spec.columns)
            t_idx_start = time.time()

            await conn.execute(text(idx_spec.ddl))
            await conn.commit()

            idx_elapsed = round(time.time() - t_idx_start, 3)
            created_timings[idx_name] = idx_elapsed
            logger.info("Index '%s' created successfully in %.3fs.", idx_name, idx_elapsed)

    total_elapsed = round(time.time() - t_start, 3)
    logger.info("Index migration completed in %.3f seconds.", total_elapsed)

    return {
        "status": "PASS",
        "created_indexes": target_names,
        "timings_seconds": created_timings,
        "total_elapsed_seconds": total_elapsed,
    }


async def validate_all_indexes(engine: AsyncEngine) -> dict[str, Any]:
    """Verify that all 5 approved indexes are present, valid, and match specifications.

    Raises:
        ValueError: If any index is missing, invalid, or violates approved specifications.
    """
    audit = await audit_indexes(engine)
    if audit.state != IndexState.ALL_INDEXES_EXIST_AND_MATCH:
        raise ValueError(
            f"Index validation failed: State is '{audit.state.value}'. "
            f"Details: {audit.message}"
        )

    # Confirm vector dimension on table remains 384
    dim_res = await validate_vector_dimension(engine, expected_dim=EXPECTED_EMBEDDING_DIM)

    return {
        "status": "PASS",
        "state": audit.state.value,
        "verified_indexes": list(audit.items.keys()),
        "vector_dimension": dim_res["embedding_dimension"],
    }


BENCHMARK_QUERIES = [
    {
        "query_type": "category_filter",
        "description": "Category equality filtering",
        "sql": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT product_id FROM public.products WHERE category = :category;",
        "params": {"category": "Footwear"},
    },
    {
        "query_type": "price_filter",
        "description": "Discounted price range filtering",
        "sql": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT product_id FROM public.products WHERE discounted_price <= :max_price;",
        "params": {"max_price": 500.0},
    },
    {
        "query_type": "brand_filter",
        "description": "Brand equality filtering",
        "sql": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT product_id FROM public.products WHERE brand = :brand;",
        "params": {"brand": "Alisha"},
    },
    {
        "query_type": "category_price_filter",
        "description": "Combined category and price composite filtering",
        "sql": (
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            "SELECT product_id FROM public.products "
            "WHERE category = :category AND discounted_price <= :max_price;"
        ),
        "params": {"category": "Footwear", "max_price": 500.0},
    },
    {
        "query_type": "hnsw_vector_similarity",
        "description": "HNSW vector cosine distance nearest-neighbor search",
        "sql": (
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            "SELECT product_id, embedding <=> CAST(:vec AS vector) AS distance "
            "FROM public.products "
            "ORDER BY embedding <=> CAST(:vec AS vector) "
            "LIMIT 10;"
        ),
        "params": {},  # Will be populated with first product embedding
    },
]


def extract_plan_node_types(plan_node: dict[str, Any]) -> list[str]:
    """Recursively collect all node types from an EXPLAIN plan tree."""
    nodes = [plan_node.get("Node Type", "Unknown")]
    for child in plan_node.get("Plans", []):
        nodes.extend(extract_plan_node_types(child))
    return nodes


async def benchmark_query_plans(engine: AsyncEngine) -> list[dict[str, Any]]:
    """Execute EXPLAIN (ANALYZE, BUFFERS) queries against indexed table using real catalog values."""
    logger.info("Executing representative query plan benchmarks using EXPLAIN (ANALYZE, BUFFERS)...")
    results: list[dict[str, Any]] = []

    async with engine.connect() as conn:
        # Retrieve real embedding for vector benchmark
        emb_res = await conn.execute(text("SELECT embedding FROM public.products LIMIT 1;"))
        sample_vec_str = str(emb_res.scalar())

        for bench in BENCHMARK_QUERIES:
            q_type = bench["query_type"]
            params = dict(bench["params"])
            if q_type == "hnsw_vector_similarity":
                params["vec"] = sample_vec_str

            logger.info("Benchmarking query pattern: %s...", q_type)
            res = await conn.execute(text(bench["sql"]), params)
            plan_json = res.scalar()

            if isinstance(plan_json, list) and len(plan_json) > 0:
                top_plan = plan_json[0]
                plan_body = top_plan.get("Plan", {})
                node_types = extract_plan_node_types(plan_body)
                exec_time_ms = float(top_plan.get("Execution Time", 0.0))
                plan_time_ms = float(top_plan.get("Planning Time", 0.0))

                # Buffers info
                shared_hit = int(plan_body.get("Shared Hit Blocks", 0))
                shared_read = int(plan_body.get("Shared Read Blocks", 0))

                results.append({
                    "query_type": q_type,
                    "description": bench["description"],
                    "primary_node_type": plan_body.get("Node Type"),
                    "all_node_types": node_types,
                    "execution_time_ms": exec_time_ms,
                    "planning_time_ms": plan_time_ms,
                    "shared_hit_blocks": shared_hit,
                    "shared_read_blocks": shared_read,
                    "index_scans_used": [n for n in node_types if "Index" in n or "Bitmap" in n],
                })
            else:
                results.append({
                    "query_type": q_type,
                    "description": bench["description"],
                    "error": "Unexpected EXPLAIN format",
                })

    logger.info("Query plan benchmarks completed for %d query patterns.", len(results))
    return results


async def validate_database_integrity_post_indexing(engine: AsyncEngine) -> dict[str, Any]:
    """Validate that index creation did not alter or corrupt product data or schema."""
    logger.info("Verifying database integrity following index creation...")
    async with engine.connect() as conn:
        # 1. Total row count & distinct product IDs
        res = await conn.execute(text("SELECT COUNT(*), COUNT(DISTINCT product_id) FROM public.products;"))
        rows, distinct_ids = res.fetchone()
        if int(rows) != EXPECTED_CATALOG_SIZE:
            raise ValueError(f"Integrity check failed: expected {EXPECTED_CATALOG_SIZE} rows, got {rows}")
        if int(distinct_ids) != EXPECTED_CATALOG_SIZE:
            raise ValueError(f"Integrity check failed: expected {EXPECTED_CATALOG_SIZE} distinct IDs, got {distinct_ids}")

        # 2. Null mandatory fields
        null_chk = await conn.execute(
            text(
                "SELECT COUNT(*) FROM public.products "
                "WHERE product_id IS NULL OR product_name IS NULL OR category IS NULL "
                "   OR discounted_price IS NULL OR product_specifications IS NULL "
                "   OR retrieval_text IS NULL OR embedding IS NULL OR embedding_model IS NULL;"
            )
        )
        if int(null_chk.scalar()) > 0:
            raise ValueError("Integrity check failed: detected null values in mandatory fields")

        # 3. Vector dimensions
        dim_chk = await conn.execute(
            text(f"SELECT COUNT(*) FROM public.products WHERE vector_dims(embedding) != {EXPECTED_EMBEDDING_DIM};")
        )
        if int(dim_chk.scalar()) > 0:
            raise ValueError(f"Integrity check failed: detected embeddings with dimension != {EXPECTED_EMBEDDING_DIM}")

        # 4. JSONB specifications
        spec_chk = await conn.execute(
            text("SELECT COUNT(*) FROM public.products WHERE jsonb_typeof(product_specifications) != 'array';")
        )
        if int(spec_chk.scalar()) > 0:
            raise ValueError("Integrity check failed: detected invalid JSONB specifications")

        # 5. Constraints & Triggers
        constraints_metrics = await validate_constraints(engine)
        trigger_metrics = await validate_updated_at_trigger(engine)
        schema_metrics = await validate_products_table_schema(engine)

    return {
        "status": "PASS",
        "row_count": int(rows),
        "distinct_ids": int(distinct_ids),
        "mandatory_fields_valid": True,
        "vector_dimensions_valid": True,
        "jsonb_specifications_valid": True,
        "constraints_valid": constraints_metrics["status"] == "PASS",
        "trigger_valid": trigger_metrics["status"] == "PASS",
        "primary_key_valid": schema_metrics["primary_key"] == "product_id",
    }


def export_index_report(
    report_dict: dict[str, Any],
    output_path: Path | str = DEFAULT_INDEX_REPORT_PATH,
) -> Path:
    """Export machine-readable JSON execution report atomically."""
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.parent / f".tmp_{path.stem}_{os.getpid()}_{int(time.time())}.json"
    temp_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
    temp_path.replace(path)
    logger.info("Index construction report saved: %s", path)
    return path


async def run_phase5_7_pipeline(
    report_path: Path | str = DEFAULT_INDEX_REPORT_PATH,
    engine: AsyncEngine | None = None,
) -> tuple[dict[str, Any], IndexAuditResult]:
    """Orchestrate Phase 5.7 Index Construction pipeline end-to-end.

    Execution Flow:
    1. Pre-flight connectivity, version, and catalog size checks.
    2. Pre-migration index audit (Scenarios A through E).
    3. Migration execution (if Scenario A or C; skip if B; abort if D or E).
    4. Post-migration index validation.
    5. Query plan and performance benchmarking with EXPLAIN (ANALYZE, BUFFERS).
    6. Post-migration data integrity verification.
    7. Machine-readable JSON report export.

    Returns:
        Tuple of (report_dictionary, IndexAuditResult).
    """
    logger.info("=" * 70)
    logger.info("STARTING PHASE 5.7: POSTGRESQL B-TREE & HNSW INDEX CONSTRUCTION")
    logger.info("=" * 70)

    t_start = time.time()
    active_engine = engine or get_async_engine()
    masked_db_url = settings.get_masked_supabase_db_url()
    warnings: list[str] = []
    errors: list[str] = []

    # 1. Connection check
    logger.info("[Step 1/6] Verifying Supabase connection: %s", masked_db_url)
    conn_info = await check_connection(active_engine)
    logger.info("Connected to %s (%s)", conn_info["database"], conn_info.get("postgresql_version"))

    # Verify table row count before migration
    async with active_engine.connect() as conn:
        res = await conn.execute(text("SELECT count(*) FROM public.products;"))
        initial_row_count = int(res.scalar())
        if initial_row_count != EXPECTED_CATALOG_SIZE:
            err = f"Pre-migration check failed: expected {EXPECTED_CATALOG_SIZE} rows, got {initial_row_count}"
            errors.append(err)
            raise RuntimeError(err)

    # 2. Pre-migration index audit
    logger.info("[Step 2/6] Auditing database index state...")
    pre_audit = await audit_indexes(active_engine)

    migration_metrics: dict[str, Any] = {}
    if pre_audit.state == IndexState.INDEXES_ABSENT:
        logger.info("[Step 3/6] Executing approved index migration (Scenario A)...")
        migration_metrics = await execute_index_migration(active_engine)
    elif pre_audit.state == IndexState.PARTIAL_INDEXES_MISSING:
        logger.info(
            "[Step 3/6] Creating missing indexes: %s (Scenario C)...", pre_audit.missing_indexes
        )
        migration_metrics = await execute_index_migration(active_engine, pre_audit.missing_indexes)
    elif pre_audit.state == IndexState.ALL_INDEXES_EXIST_AND_MATCH:
        logger.info("[Step 3/6] All indexes already exist and match (Scenario B). Skipping DDL execution.")
        migration_metrics = {
            "status": "SKIPPED_ALREADY_EXISTS",
            "created_indexes": [],
            "timings_seconds": {},
            "total_elapsed_seconds": 0.0,
            "message": "All approved production indexes already exist and match specifications (Scenario B).",
        }
    elif pre_audit.state == IndexState.CONFLICTING_INDEX_DEFINITION:
        err = f"Halting: Conflicting index definitions detected (Scenario D): {pre_audit.message}"
        errors.append(err)
        raise RuntimeError(err)
    elif pre_audit.state == IndexState.INVALID_OR_INCOMPLETE_INDEX:
        err = f"Halting: Invalid or incomplete index detected (Scenario E): {pre_audit.message}"
        errors.append(err)
        raise RuntimeError(err)

    # 4. Post-migration index validation
    logger.info("[Step 4/6] Validating all production indexes in catalog...")
    post_index_metrics = await validate_all_indexes(active_engine)
    post_audit = await audit_indexes(active_engine)

    # 5. Query plan and performance benchmarking
    logger.info("[Step 5/6] Benchmarking query plans with EXPLAIN (ANALYZE, BUFFERS)...")
    benchmarks = await benchmark_query_plans(active_engine)

    # 6. Database integrity verification
    logger.info("[Step 6/6] Verifying database integrity post-indexing...")
    integrity_metrics = await validate_database_integrity_post_indexing(active_engine)

    total_pipeline_time = round(time.time() - t_start, 2)
    logger.info("Phase 5.7 pipeline completed successfully in %.2f seconds.", total_pipeline_time)

    # Assemble report
    report: dict[str, Any] = {
        "phase": "5.7",
        "objective": "PostgreSQL B-Tree & HNSW Index Construction",
        "overall_status": "PASS",
        "target_database": {
            "masked_url": masked_db_url,
            "table": TARGET_TABLE,
            "schema": "public",
            "connection": conn_info,
        },
        "pre_migration_state": {
            "catalog_rows": initial_row_count,
            "audit": pre_audit.to_dict(),
        },
        "migration_execution": migration_metrics,
        "post_migration_state": {
            "audit": post_audit.to_dict(),
            "validation": post_index_metrics,
        },
        "query_plan_benchmarks": benchmarks,
        "database_integrity": integrity_metrics,
        "phase5_8_readiness": {
            "ready_for_search_validation": True,
            "indexed_features": [
                "category (B-Tree)",
                "discounted_price (B-Tree)",
                "brand (B-Tree)",
                "category + discounted_price (Composite B-Tree)",
                "embedding (HNSW vector_cosine_ops, m=16, ef_construction=64)",
            ],
            "catalog_size": EXPECTED_CATALOG_SIZE,
        },
        "pipeline_performance": {
            "total_pipeline_elapsed_seconds": total_pipeline_time,
        },
        "warnings": warnings,
        "errors": errors,
    }

    export_index_report(report, report_path)
    return report, post_audit
