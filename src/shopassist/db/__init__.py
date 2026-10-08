"""ShopAssist database connectivity, schema provisioning, and catalog validation module."""

from shopassist.db.connection import (
    check_connection,
    get_async_database_url,
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

__all__ = [
    "get_async_database_url",
    "get_async_engine",
    "check_connection",
    "enable_pgvector",
    "provision_base_schema",
    "validate_products_table_schema",
    "validate_vector_dimension",
    "validate_constraints",
    "validate_updated_at_trigger",
    "validate_deferred_indexes",
    "run_transactional_smoke_test",
]
