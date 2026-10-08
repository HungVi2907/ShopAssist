"""Unit and integration tests for Phase 5.3 Embedding Model Setup and Validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from shopassist.embeddings.model import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_MAX_SEQ_LENGTH,
    DEFAULT_MODEL_NAME,
    DEFAULT_QUERY_INSTRUCTION,
    EmbeddingModel,
    resolve_device,
    validate_embeddings,
)


# 1. Default model name & metadata constants
def test_default_metadata_constants() -> None:
    assert DEFAULT_MODEL_NAME == "BAAI/bge-small-en-v1.5"
    assert DEFAULT_EMBEDDING_DIM == 384
    assert DEFAULT_MAX_SEQ_LENGTH == 512
    assert "Represent this sentence" in DEFAULT_QUERY_INSTRUCTION


# 2. Device resolution logic
def test_device_resolution_explicit() -> None:
    assert resolve_device("cpu") == "cpu"
    assert resolve_device("CPU ") == "cpu"

    with patch("torch.cuda.is_available", return_value=False):
        assert resolve_device("cuda") == "cpu"


def test_device_resolution_auto() -> None:
    with patch("torch.cuda.is_available", return_value=True):
        assert resolve_device(None) == "cuda"

    with patch("torch.cuda.is_available", return_value=False):
        with patch("torch.backends.mps.is_available", return_value=True, create=True):
            assert resolve_device(None) == "mps"

    with patch("torch.cuda.is_available", return_value=False):
        with patch("torch.backends.mps.is_available", return_value=False, create=True):
            assert resolve_device(None) == "cpu"


# 3. Embedding dimension validation rejects non-384 vectors
def test_dimension_validation_rejects_non_384() -> None:
    wrong_dim = np.ones((5, 512), dtype=np.float32)
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        validate_embeddings(wrong_dim, expected_dim=384, check_normalized=False)

    correct_dim = np.ones((5, 384), dtype=np.float32)
    res = validate_embeddings(correct_dim, expected_dim=384, check_normalized=False)
    assert res["status"] == "PASS"
    assert res["dimension"] == 384


# 4. Finite-value validation detects NaN
def test_finite_validation_detects_nan() -> None:
    vecs = np.ones((4, 384), dtype=np.float32)
    vecs[2, 50] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        validate_embeddings(vecs, check_normalized=False)


# 5. Finite-value validation detects Inf
def test_finite_validation_detects_inf() -> None:
    vecs = np.ones((4, 384), dtype=np.float32)
    vecs[1, 10] = np.inf
    with pytest.raises(ValueError, match="Inf"):
        validate_embeddings(vecs, check_normalized=False)

    vecs_neg = np.ones((4, 384), dtype=np.float32)
    vecs_neg[3, 20] = -np.inf
    with pytest.raises(ValueError, match="Inf"):
        validate_embeddings(vecs_neg, check_normalized=False)


# 6. Zero-vector detection
def test_zero_vector_detection() -> None:
    vecs = np.ones((3, 384), dtype=np.float32)
    vecs[1, :] = 0.0
    with pytest.raises(ValueError, match="all-zero"):
        validate_embeddings(vecs, check_normalized=False)


# 7. L2 normalization validation
def test_l2_normalization_validation() -> None:
    # Unnormalized array
    unnorm = np.full((3, 384), 2.0, dtype=np.float32)
    with pytest.raises(ValueError, match="L2 normalization"):
        validate_embeddings(unnorm, check_normalized=True)

    # Unit normalized array
    norm = unnorm / np.linalg.norm(unnorm, axis=1, keepdims=True)
    res = validate_embeddings(norm, check_normalized=True)
    assert res["status"] == "PASS"
    assert abs(res["mean_l2_norm"] - 1.0) < 1e-4


# 8. Batch order preservation
def test_batch_order_preservation() -> None:
    mock_st = MagicMock()
    mock_st.get_sentence_embedding_dimension.return_value = 384
    mock_st.get_embedding_dimension.return_value = 384

    # Simulate encoding 3 distinct items
    mock_st.encode.return_value = np.array([
        [1.0] + [0.0] * 383,
        [0.0, 1.0] + [0.0] * 382,
        [0.0, 0.0, 1.0] + [0.0] * 381,
    ], dtype=np.float32)

    with patch("shopassist.embeddings.model.SentenceTransformer", return_value=mock_st):
        with patch("shopassist.embeddings.model.AutoTokenizer.from_pretrained", return_value=MagicMock()):
            model = EmbeddingModel(device="cpu")
            texts = ["item_A", "item_B", "item_C"]
            embs = model.encode(texts)
            assert embs[0, 0] == 1.0
            assert embs[1, 1] == 1.0
            assert embs[2, 2] == 1.0


# 9. Deterministic output
def test_deterministic_output() -> None:
    mock_st = MagicMock()
    mock_st.get_sentence_embedding_dimension.return_value = 384
    mock_st.get_embedding_dimension.return_value = 384
    fixed_vec = np.array([[1.0] + [0.0] * 383], dtype=np.float32)
    mock_st.encode.return_value = fixed_vec

    with patch("shopassist.embeddings.model.SentenceTransformer", return_value=mock_st):
        with patch("shopassist.embeddings.model.AutoTokenizer.from_pretrained", return_value=MagicMock()):
            model = EmbeddingModel(device="cpu")
            run1 = model.encode("keyboard")
            run2 = model.encode("keyboard")
            assert np.array_equal(run1, run2)


# 10. Input empty list handling
def test_empty_list_handling() -> None:
    mock_st = MagicMock()
    mock_st.get_sentence_embedding_dimension.return_value = 384
    mock_st.get_embedding_dimension.return_value = 384

    with patch("shopassist.embeddings.model.SentenceTransformer", return_value=mock_st):
        with patch("shopassist.embeddings.model.AutoTokenizer.from_pretrained", return_value=MagicMock()):
            model = EmbeddingModel(device="cpu")
            embs = model.encode([])
            assert isinstance(embs, np.ndarray)
            assert embs.shape == (0, 384)
            assert embs.dtype == np.float32


# 11. Invalid input validation
def test_invalid_input_validation() -> None:
    with pytest.raises(TypeError, match="must be np.ndarray"):
        validate_embeddings([1, 2, 3])  # type: ignore

    with pytest.raises(ValueError, match="must be 2D"):
        validate_embeddings(np.ones(384, dtype=np.float32))

    with pytest.raises(ValueError, match="must be 2D"):
        validate_embeddings(np.ones((2, 2, 384), dtype=np.float32))


# 12. Query and document encode APIs
def test_query_and_document_encode_apis() -> None:
    mock_st = MagicMock()
    mock_st.get_sentence_embedding_dimension.return_value = 384
    mock_st.get_embedding_dimension.return_value = 384
    mock_st.encode.side_effect = lambda texts, **kwargs: np.ones((len(texts), 384), dtype=np.float32) / np.sqrt(384)

    with patch("shopassist.embeddings.model.SentenceTransformer", return_value=mock_st):
        with patch("shopassist.embeddings.model.AutoTokenizer.from_pretrained", return_value=MagicMock()):
            model = EmbeddingModel(device="cpu")

            # Documents encoded directly
            model.encode_documents(["Doc 1", "Doc 2"])
            called_docs = mock_st.encode.call_args[0][0]
            assert called_docs == ["Doc 1", "Doc 2"]

            # Queries encoded with instruction prefix
            model.encode_queries(["Query 1"])
            called_queries = mock_st.encode.call_args[0][0]
            assert called_queries == [f"{DEFAULT_QUERY_INSTRUCTION}Query 1"]

            # Custom instruction override or omit
            model.encode_queries(["Query 2"], instruction=None)
            called_queries_raw = mock_st.encode.call_args[0][0]
            assert called_queries_raw == ["Query 2"]


# 13. Cosine similarity consistency
def test_cosine_similarity_consistency() -> None:
    mock_st = MagicMock()
    mock_st.get_sentence_embedding_dimension.return_value = 384
    mock_st.get_embedding_dimension.return_value = 384

    with patch("shopassist.embeddings.model.SentenceTransformer", return_value=mock_st):
        with patch("shopassist.embeddings.model.AutoTokenizer.from_pretrained", return_value=MagicMock()):
            model = EmbeddingModel(device="cpu")

            vec_a = np.zeros(384, dtype=np.float32)
            vec_a[0] = 1.0

            vec_b = np.zeros(384, dtype=np.float32)
            vec_b[0] = 1.0

            vec_c = np.zeros(384, dtype=np.float32)
            vec_c[1] = 1.0

            # Identical vectors: similarity = 1.0
            assert abs(model.compute_similarity(vec_a, vec_b) - 1.0) < 1e-6
            # Orthogonal vectors: similarity = 0.0
            assert abs(model.compute_similarity(vec_a, vec_c) - 0.0) < 1e-6

            # 2D batch similarity
            sims = model.compute_similarity(np.array([vec_a, vec_c]), np.array([vec_b]))
            assert sims.shape == (2, 1)
            assert abs(sims[0, 0] - 1.0) < 1e-6
            assert abs(sims[1, 0] - 0.0) < 1e-6


# 14. Report schema verification
def test_report_schema_contains_required_keys() -> None:
    report_path = Path("data/interim/phase5_3_embedding_model_report.json")
    if not report_path.exists():
        pytest.skip("Phase 5.3 report JSON not generated yet")

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    required_keys = [
        "phase",
        "model_name",
        "framework",
        "framework_version",
        "torch_version",
        "device",
        "dataset_rows",
        "embedding_dimension_expected",
        "embedding_dimension_actual",
        "max_sequence_length",
        "tokenization",
        "sample_validation",
        "normalization",
        "performance",
        "semantic_sanity_checks",
        "overall_status",
    ]

    for k in required_keys:
        assert k in report, f"Missing required report key: {k}"

    assert report["phase"] == "5.3"
    assert report["embedding_dimension_actual"] == 384
    assert report["dataset_rows"] == 8405
    assert report["overall_status"] == "PASS"


# 15. Real model integration smoke test
@pytest.mark.integration
def test_real_embedding_model_smoke() -> None:
    """Smoke test with the real loaded BGE model (cached locally)."""
    model = EmbeddingModel()
    assert model.embedding_dimension == 384
    assert model.max_seq_length == 512

    # Single string encode
    text = "Product: Logitech K380 Bluetooth Keyboard | Category: Computers"
    vec = model.encode(text)
    assert isinstance(vec, np.ndarray)
    assert vec.shape == (384,)
    assert vec.dtype == np.float32
    assert abs(np.linalg.norm(vec) - 1.0) < 1e-4

    # Batch encode
    docs = [
        "Product: Logitech Wireless Keyboard | Category: Computers",
        "Product: Puma Running Shoes | Category: Footwear",
    ]
    batch_vecs = model.encode_documents(docs)
    assert batch_vecs.shape == (2, 384)

    # Token counting
    tok_count = model.count_tokens(text)
    assert tok_count > 5
    assert tok_count < 100
