"""Adapter from Phase 9 to the shared Phase 7 query encoder."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

EXPECTED_EMBEDDING_DIM = 384
EXPECTED_MODEL_NAME = "BAAI/bge-small-en-v1.5"


def validate_preference_vector(vector: object, dimension: int = EXPECTED_EMBEDDING_DIM) -> list[float]:
    """Validate and serialize one normalized, finite, nonzero query vector."""
    array = np.asarray(vector, dtype=np.float32)
    if array.ndim != 1 or array.shape[0] != dimension:
        raise ValueError(f"preference vector must have shape ({dimension},)")
    if not np.isfinite(array).all():
        raise ValueError("preference vector contains NaN or infinity")
    norm = float(np.linalg.norm(array))
    if not math.isfinite(norm) or norm < 1e-8:
        raise ValueError("preference vector must have nonzero finite norm")
    if abs(norm - 1.0) > 1e-4:
        raise ValueError(f"preference vector must be unit-normalized (norm={norm:.6f})")
    return [float(item) for item in array]


class PreferenceQueryEncoder:
    """Use the same cached ``EmbeddingModel`` and BGE query instruction as Phase 7."""

    def __init__(self, dense_query_encoder: object | None = None) -> None:
        if dense_query_encoder is None:
            # Delayed import keeps normalization and contract use independent of
            # heavyweight torch/model initialization.
            from shopassist.retrieval.semantic import DenseQueryEncoder

            dense_query_encoder = DenseQueryEncoder()
        self._encoder = dense_query_encoder

    @property
    def model_name(self) -> str:
        return str(self._encoder.config.model_name)

    @property
    def embedding_dimension(self) -> int:
        return int(self._encoder.config.embedding_dim)

    @property
    def device(self) -> str:
        return str(self._encoder.model.device)

    def encode(self, query: str) -> list[float]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("preference query must be a non-empty string")
        vector = self._encoder.encode_query(query)
        return validate_preference_vector(vector, self.embedding_dimension)

    def encode_batch(self, queries: Sequence[str], batch_size: int = 32) -> list[list[float]]:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if not queries:
            return []
        if any(not isinstance(query, str) or not query.strip() for query in queries):
            raise ValueError("every preference query must be a non-empty string")
        # DenseQueryEncoder exposes the shared EmbeddingModel and configuration.
        # Encoding in one call avoids per-item dispatch while preserving Phase 7
        # instruction, normalization and model cache conventions.
        vectors = self._encoder.model.encode_queries(
            list(queries),
            instruction=self._encoder.config.query_instruction,
            batch_size=batch_size,
            normalize_embeddings=self._encoder.config.normalize_embeddings,
        )
        array = np.asarray(vectors, dtype=np.float32)
        if array.ndim != 2 or array.shape[0] != len(queries):
            raise ValueError("batch encoder returned an invalid vector shape")
        return [validate_preference_vector(row, self.embedding_dimension) for row in array]

    def validate_model_compatibility(self) -> None:
        if self.model_name != EXPECTED_MODEL_NAME:
            raise ValueError(f"incompatible embedding model: {self.model_name}")
        if self.embedding_dimension != EXPECTED_EMBEDDING_DIM:
            raise ValueError(f"incompatible embedding dimension: {self.embedding_dimension}")
