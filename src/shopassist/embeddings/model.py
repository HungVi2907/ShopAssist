"""Embedding model wrapper and validation module for ShopAssist (Phase 5.3).

Encapsulates loading, inference, query/document encoding, and quality checks
for the official embedding model: `BAAI/bge-small-en-v1.5`.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
DEFAULT_EMBEDDING_DIM: int = 384
DEFAULT_MAX_SEQ_LENGTH: int = 512
DEFAULT_QUERY_INSTRUCTION: str = "Represent this sentence for searching relevant passages: "


def resolve_device(device: str | None = None) -> str:
    """Resolve compute device following priority: explicitly provided -> CUDA -> MPS -> CPU.

    Args:
        device: Optional explicit device string ('cuda', 'cpu', 'cuda:0', etc.).

    Returns:
        Resolved device string.
    """
    if device is not None:
        target = str(device).strip().lower()
        if target.startswith("cuda") and not torch.cuda.is_available():
            logger.warning("CUDA requested but not available. Falling back to CPU.")
            return "cpu"
        return target

    if torch.cuda.is_available():
        resolved = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        resolved = "mps"
    else:
        resolved = "cpu"

    logger.info("Auto-detected embedding device: %s", resolved)
    return resolved


def validate_embeddings(
    embeddings: np.ndarray,
    expected_dim: int = DEFAULT_EMBEDDING_DIM,
    expected_count: int | None = None,
    check_normalized: bool = True,
    norm_tolerance: float = 1e-4,
) -> dict[str, Any]:
    """Validate numerical properties of an embeddings array.

    Verifies:
    - Array shape: (N, expected_dim)
    - Finite values: no NaN, no +Inf, no -Inf
    - Non-trivial: no all-zero vectors
    - L2 normalization: norms ≈ 1.0 (if check_normalized is True)
    - Proper dtype (float32)

    Args:
        embeddings: 2D numpy array of shape (N, dim).
        expected_dim: Expected vector dimension (default: 384).
        expected_count: Optional expected row count N.
        check_normalized: Whether to check L2 norms are near 1.0.
        norm_tolerance: Maximum deviation from 1.0 allowed for normalized vectors.

    Returns:
        Dictionary of validation metrics.

    Raises:
        ValueError: If shape, dimension, or numerical integrity checks fail.
    """
    if not isinstance(embeddings, np.ndarray):
        raise TypeError(f"Embeddings must be np.ndarray, got {type(embeddings).__name__}")

    if embeddings.ndim != 2:
        raise ValueError(f"Embeddings array must be 2D with shape (N, dim), got ndim={embeddings.ndim}")

    num_vectors, dim = embeddings.shape

    if dim != expected_dim:
        raise ValueError(
            f"Embedding dimension mismatch: expected {expected_dim}, got {dim}"
        )

    if expected_count is not None and num_vectors != expected_count:
        raise ValueError(
            f"Vector count mismatch: expected {expected_count}, got {num_vectors}"
        )

    # Empty array case
    if num_vectors == 0:
        return {
            "num_vectors": 0,
            "dimension": dim,
            "dtype": str(embeddings.dtype),
            "nan_count": 0,
            "inf_count": 0,
            "zero_vector_count": 0,
            "status": "PASS",
        }

    # Finite values check
    nan_count = int(np.isnan(embeddings).sum())
    inf_count = int(np.isinf(embeddings).sum())
    if nan_count > 0:
        raise ValueError(f"Found {nan_count} NaN values in embeddings array")
    if inf_count > 0:
        raise ValueError(f"Found {inf_count} Inf values in embeddings array")

    # Zero vector check
    norms = np.linalg.norm(embeddings, axis=1)
    zero_vectors = int((norms < 1e-8).sum())
    if zero_vectors > 0:
        raise ValueError(f"Found {zero_vectors} all-zero vectors in embeddings array")

    min_norm = float(norms.min())
    max_norm = float(norms.max())
    mean_norm = float(norms.mean())

    if check_normalized:
        deviations = np.abs(norms - 1.0)
        max_dev = float(deviations.max())
        if max_dev > norm_tolerance:
            raise ValueError(
                f"Embeddings failed L2 normalization check: max deviation={max_dev:.6f} > tolerance={norm_tolerance}"
            )

    return {
        "num_vectors": num_vectors,
        "dimension": dim,
        "dtype": str(embeddings.dtype),
        "nan_count": nan_count,
        "inf_count": inf_count,
        "zero_vector_count": zero_vectors,
        "min_l2_norm": round(min_norm, 6),
        "mean_l2_norm": round(mean_norm, 6),
        "max_l2_norm": round(max_norm, 6),
        "status": "PASS",
    }


class EmbeddingModel:
    """Production wrapper for BAAI/bge-small-en-v1.5 embedding inference.

    Features:
    - Encapsulates SentenceTransformer model loading and device configuration.
    - Explicit dimension validation (ensures 384 dimensions).
    - Asymmetric retrieval support:
      - `encode_documents`: Raw product retrieval text without instruction.
      - `encode_queries`: User search queries prepended with recommended instruction.
    - Fast batch token length measurement via native tokenizer.
    - Cosine similarity computation over normalized vectors.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        device: str | None = None,
        normalize_embeddings: bool = True,
        max_seq_length: int = DEFAULT_MAX_SEQ_LENGTH,
    ) -> None:
        """Initialize and validate the embedding model.

        Args:
            model_name: HuggingFace model identifier (default: 'BAAI/bge-small-en-v1.5').
            device: Compute device ('cuda', 'cpu', 'mps', or None for auto-detect).
            normalize_embeddings: Whether to normalize output vectors to unit L2 norm.
            max_seq_length: Maximum sequence length in tokens (default: 512).

        Raises:
            ValueError: If the loaded model's embedding dimension is not 384.
        """
        self._model_name = model_name
        self._device = resolve_device(device)
        self._normalize_embeddings = normalize_embeddings
        self._max_seq_length = max_seq_length

        logger.info(
            "Loading embedding model '%s' on device '%s' (max_seq_length=%d, normalize=%s)...",
            self._model_name,
            self._device,
            self._max_seq_length,
            self._normalize_embeddings,
        )

        self._model = SentenceTransformer(self._model_name, device=self._device)
        self._model.max_seq_length = self._max_seq_length

        # Native tokenizer for tokenization audits
        self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)

        # Validate embedding dimension
        if hasattr(self._model, "get_embedding_dimension"):
            dim = int(self._model.get_embedding_dimension())
        else:
            dim = int(self._model.get_sentence_embedding_dimension())
        if dim != DEFAULT_EMBEDDING_DIM:
            raise ValueError(
                f"Embedding dimension mismatch: expected {DEFAULT_EMBEDDING_DIM}, but model has {dim}."
            )
        self._dimension = dim
        logger.info(
            "Successfully loaded '%s': dimension=%d, max_seq_length=%d, device=%s",
            self._model_name,
            self._dimension,
            self._max_seq_length,
            self._device,
        )

    @property
    def model_name(self) -> str:
        """HuggingFace model identifier."""
        return self._model_name

    @property
    def device(self) -> str:
        """Resolved compute device string."""
        return self._device

    @property
    def embedding_dimension(self) -> int:
        """Embedding dimension (fixed at 384)."""
        return self._dimension

    @property
    def max_seq_length(self) -> int:
        """Maximum tokenizer context length (tokens)."""
        return self._max_seq_length

    @property
    def normalize_embeddings(self) -> bool:
        """Default normalization flag."""
        return self._normalize_embeddings

    @property
    def model(self) -> SentenceTransformer:
        """Underlying SentenceTransformer instance."""
        return self._model

    @property
    def tokenizer(self) -> AutoTokenizer:
        """Underlying HuggingFace AutoTokenizer instance."""
        return self._tokenizer

    def count_tokens(self, text: str) -> int:
        """Count tokens in a text using the model's native tokenizer.

        Args:
            text: Input string.

        Returns:
            Number of tokens (including special tokens [CLS] and [SEP]).
        """
        encoded = self._tokenizer(text, add_special_tokens=True, truncation=False)
        return len(encoded["input_ids"])

    def batch_count_tokens(self, texts: Sequence[str]) -> list[int]:
        """Count tokens for a batch of texts using the native tokenizer.

        Args:
            texts: Sequence of input strings.

        Returns:
            List of integer token counts.
        """
        if not texts:
            return []
        encoded = self._tokenizer(list(texts), add_special_tokens=True, truncation=False)
        return [len(ids) for ids in encoded["input_ids"]]

    def encode(
        self,
        texts: str | Sequence[str],
        batch_size: int = 32,
        normalize_embeddings: bool | None = None,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        """Encode text or a sequence of texts into dense embedding vectors.

        Args:
            texts: Single string or sequence of strings.
            batch_size: Mini-batch size for inference (default: 32).
            normalize_embeddings: Whether to normalize embeddings to unit norm (defaults to instance setting).
            show_progress_bar: Whether to display a tqdm progress bar.

        Returns:
            2D numpy array of shape (N, 384) with dtype float32 if input was sequence.
            1D numpy array of shape (384,) with dtype float32 if input was a single string.
        """
        is_single = isinstance(texts, str)
        input_list: list[str] = [texts] if is_single else list(texts)

        if len(input_list) == 0:
            return np.empty((0, self._dimension), dtype=np.float32)

        norm = self._normalize_embeddings if normalize_embeddings is None else normalize_embeddings

        raw_embeddings = self._model.encode(
            input_list,
            batch_size=batch_size,
            show_progress_bar=show_progress_bar,
            normalize_embeddings=norm,
            convert_to_numpy=True,
        )

        embeddings = np.asarray(raw_embeddings, dtype=np.float32)

        # Validate numerical integrity
        validate_embeddings(
            embeddings,
            expected_dim=self._dimension,
            expected_count=len(input_list),
            check_normalized=norm,
        )

        if is_single:
            return embeddings[0]
        return embeddings

    def encode_documents(
        self,
        documents: str | Sequence[str],
        batch_size: int = 32,
        normalize_embeddings: bool | None = None,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        """Encode product retrieval_text documents without any query instruction.

        In BAAI BGE v1.5, documents (catalog passages) are encoded as raw text.

        Args:
            documents: Single product retrieval text or sequence of texts.
            batch_size: Batch size for inference.
            normalize_embeddings: Optional override for L2 normalization.
            show_progress_bar: Whether to display progress bar.

        Returns:
            Dense embedding array of shape (N, 384) or (384,).
        """
        return self.encode(
            texts=documents,
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
            show_progress_bar=show_progress_bar,
        )

    def encode_queries(
        self,
        queries: str | Sequence[str],
        instruction: str | None = DEFAULT_QUERY_INSTRUCTION,
        batch_size: int = 32,
        normalize_embeddings: bool | None = None,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        """Encode user search queries with the recommended BGE retrieval instruction.

        For asymmetric retrieval, BGE v1.5 recommends prepending:
        ``"Represent this sentence for searching relevant passages: "``

        Args:
            queries: Single query string or sequence of query strings.
            instruction: Prefix instruction to prepend. Pass None or "" to omit.
            batch_size: Batch size for inference.
            normalize_embeddings: Optional override for L2 normalization.
            show_progress_bar: Whether to display progress bar.

        Returns:
            Dense embedding array of shape (N, 384) or (384,).
        """
        is_single = isinstance(queries, str)
        query_list = [queries] if is_single else list(queries)

        prefix = instruction if instruction else ""
        formatted_queries = [f"{prefix}{q}" for q in query_list]

        embs = self.encode(
            texts=formatted_queries,
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
            show_progress_bar=show_progress_bar,
        )

        if is_single:
            return embs[0]
        return embs

    def compute_similarity(
        self,
        embeddings_a: np.ndarray,
        embeddings_b: np.ndarray,
    ) -> np.ndarray:
        """Compute cosine similarity between two embedding sets.

        For normalized vectors, cosine similarity equals the dot product.

        Args:
            embeddings_a: Array of shape (384,) or (N, 384).
            embeddings_b: Array of shape (384,) or (M, 384).

        Returns:
            Similarity array of shape (N, M), or float scalar / 1D array.
        """
        a = np.asarray(embeddings_a, dtype=np.float32)
        b = np.asarray(embeddings_b, dtype=np.float32)

        if a.ndim == 1:
            a = a[np.newaxis, :]
        if b.ndim == 1:
            b = b[np.newaxis, :]

        # Normalize if not already unit norm
        norm_a = np.linalg.norm(a, axis=1, keepdims=True)
        norm_b = np.linalg.norm(b, axis=1, keepdims=True)
        a_normed = a / np.maximum(norm_a, 1e-12)
        b_normed = b / np.maximum(norm_b, 1e-12)

        sims = np.dot(a_normed, b_normed.T)

        if embeddings_a.ndim == 1 and embeddings_b.ndim == 1:
            return float(sims[0, 0])
        if embeddings_a.ndim == 1:
            return sims[0]
        if embeddings_b.ndim == 1:
            return sims[:, 0]
        return sims
