"""ShopAssist embeddings module for dense vector representation and model inference."""

from shopassist.embeddings.batch import (
    CANONICAL_COLUMNS,
    CANONICAL_COLUMNS_WITH_TIMESTAMPS,
    EXPECTED_CATALOG_SIZE,
    assemble_knowledge_base_dataframe,
    export_products_parquet,
    generate_catalog_embeddings,
    run_phase5_5_pipeline,
    validate_input_dataset,
    validate_processed_dataset,
    verify_semantic_retrieval_sanity,
)
from shopassist.embeddings.model import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_MAX_SEQ_LENGTH,
    DEFAULT_MODEL_NAME,
    DEFAULT_QUERY_INSTRUCTION,
    EmbeddingModel,
    resolve_device,
    validate_embeddings,
)

__all__ = [
    "EmbeddingModel",
    "resolve_device",
    "validate_embeddings",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_MAX_SEQ_LENGTH",
    "DEFAULT_QUERY_INSTRUCTION",
    "CANONICAL_COLUMNS",
    "CANONICAL_COLUMNS_WITH_TIMESTAMPS",
    "EXPECTED_CATALOG_SIZE",
    "validate_input_dataset",
    "generate_catalog_embeddings",
    "assemble_knowledge_base_dataframe",
    "validate_processed_dataset",
    "export_products_parquet",
    "verify_semantic_retrieval_sanity",
    "run_phase5_5_pipeline",
]
