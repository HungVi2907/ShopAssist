"""ShopAssist embeddings module for dense vector representation and model inference."""

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
]
