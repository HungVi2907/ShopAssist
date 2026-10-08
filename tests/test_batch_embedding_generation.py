"""Automated unit and integration tests for Phase 5.5 Batch Embedding Generation & Parquet Export."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

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
    DEFAULT_MODEL_NAME,
    EmbeddingModel,
    validate_embeddings,
)


@pytest.fixture
def sample_valid_input_df() -> pd.DataFrame:
    """Fixture providing a minimal valid candidate DataFrame with 3 products."""
    data = [
        {
            "product_id": "prod_001",
            "product_name": "Logitech K380 Wireless Multi-Device Bluetooth Keyboard",
            "category": "Computers",
            "brand": "Logitech",
            "retail_price": 45.0,
            "discounted_price": 35.0,
            "rating": 4.5,
            "description": "Compact bluetooth keyboard for Windows, Mac, and Chrome OS.",
            "product_specifications": json.dumps([{"key": "Connectivity", "value": "Bluetooth"}]),
            "product_url": "https://example.com/p1",
            "image": "https://example.com/img1.jpg",
            "pid": "SKU_001",
            "uniq_id": "prod_001",
            "crawl_timestamp": "2024-01-01",
            "is_FK_Advantage_product": True,
            "retrieval_text": "Product: Logitech K380 Wireless Multi-Device Bluetooth Keyboard | Category: Computers | Brand: Logitech | Specifications: Connectivity: Bluetooth | Description: Compact bluetooth keyboard",
        },
        {
            "product_id": "prod_002",
            "product_name": "Durian Modern Leather Two Seater Sofa",
            "category": "Furniture",
            "brand": "Durian",
            "retail_price": 800.0,
            "discounted_price": 650.0,
            "rating": 4.2,
            "description": "Premium leather 2-seater couch for living room.",
            "product_specifications": json.dumps([{"key": "Material", "value": "Leather"}]),
            "product_url": "https://example.com/p2",
            "image": "https://example.com/img2.jpg",
            "pid": "SKU_002",
            "uniq_id": "prod_002",
            "crawl_timestamp": "2024-01-01",
            "is_FK_Advantage_product": False,
            "retrieval_text": "Product: Durian Modern Leather Two Seater Sofa | Category: Furniture | Brand: Durian | Specifications: Material: Leather | Description: Premium leather 2-seater couch",
        },
        {
            "product_id": "prod_003",
            "product_name": "11e Women Casual Flat Strap Sandals",
            "category": "Footwear",
            "brand": None,
            "retail_price": None,
            "discounted_price": 18.0,
            "rating": None,
            "description": "Comfortable daily flat sandals for women.",
            "product_specifications": json.dumps([]),
            "product_url": "https://example.com/p3",
            "image": None,
            "pid": "SKU_003",
            "uniq_id": "prod_003",
            "crawl_timestamp": "2024-01-01",
            "is_FK_Advantage_product": False,
            "retrieval_text": "Product: 11e Women Casual Flat Strap Sandals | Category: Footwear | Description: Comfortable daily flat sandals",
        },
    ]
    return pd.DataFrame(data)


@pytest.fixture
def mock_normalized_embeddings() -> np.ndarray:
    """Fixture providing 3 valid 384-dimensional unit-normalized embeddings."""
    rng = np.random.default_rng(42)
    raw = rng.standard_normal((3, 384)).astype(np.float32)
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    return (raw / norms).astype(np.float32)


# ==============================================================================
# 1. Input Dataset Validation Tests
# ==============================================================================

def test_validate_input_dataset_success(sample_valid_input_df: pd.DataFrame) -> None:
    """Verify input validation succeeds on properly formatted candidate records."""
    prepared_df, metrics = validate_input_dataset(sample_valid_input_df, expected_count=3)
    assert metrics["status"] == "PASS"
    assert metrics["input_rows"] == 3
    assert metrics["product_id_unique"] is True
    assert metrics["retrieval_text_generated"] is False
    assert len(prepared_df) == 3


def test_validate_input_dataset_count_mismatch(sample_valid_input_df: pd.DataFrame) -> None:
    """Verify ValueError is raised when expected product count does not match."""
    with pytest.raises(ValueError, match="Input dataset row count mismatch"):
        validate_input_dataset(sample_valid_input_df, expected_count=8405)


def test_validate_input_dataset_missing_mandatory_columns() -> None:
    """Verify ValueError is raised when essential schema columns are absent."""
    incomplete_df = pd.DataFrame([{"product_id": "p1", "category": "Computers"}])
    with pytest.raises(ValueError, match="Missing mandatory column 'product_name'"):
        validate_input_dataset(incomplete_df, expected_count=1)


def test_validate_input_dataset_duplicate_product_ids(sample_valid_input_df: pd.DataFrame) -> None:
    """Verify ValueError is raised when product_id contains duplicates."""
    df_dup = sample_valid_input_df.copy()
    df_dup.loc[1, "product_id"] = "prod_001"
    with pytest.raises(ValueError, match="Found duplicate product_id"):
        validate_input_dataset(df_dup, expected_count=3)


def test_validate_input_dataset_null_or_empty_product_id(sample_valid_input_df: pd.DataFrame) -> None:
    """Verify ValueError is raised when product_id is null or empty."""
    df_null = sample_valid_input_df.copy()
    df_null.loc[0, "product_id"] = ""
    with pytest.raises(ValueError, match="null or empty product_id"):
        validate_input_dataset(df_null, expected_count=3)


def test_validate_input_dataset_invalid_price_and_rating(sample_valid_input_df: pd.DataFrame) -> None:
    """Verify invalid numeric values (negative price, out-of-range rating) are rejected."""
    df_price = sample_valid_input_df.copy()
    df_price.loc[0, "discounted_price"] = -5.0
    with pytest.raises(ValueError, match="invalid discounted_price"):
        validate_input_dataset(df_price, expected_count=3)

    df_rating = sample_valid_input_df.copy()
    df_rating.loc[0, "rating"] = 5.5
    with pytest.raises(ValueError, match="invalid rating"):
        validate_input_dataset(df_rating, expected_count=3)


def test_validate_input_dataset_invalid_specifications(sample_valid_input_df: pd.DataFrame) -> None:
    """Verify malformed JSON specifications are rejected."""
    df_spec = sample_valid_input_df.copy()
    df_spec.loc[0, "product_specifications"] = "{not valid json}"
    with pytest.raises(ValueError, match="Invalid product_specifications"):
        validate_input_dataset(df_spec, expected_count=3)


# ==============================================================================
# 2. Retrieval Text Resolution Tests
# ==============================================================================

def test_retrieval_text_auto_generation_when_missing(sample_valid_input_df: pd.DataFrame) -> None:
    """Verify retrieval_text is automatically generated if omitted from input."""
    df_no_text = sample_valid_input_df.drop(columns=["retrieval_text"])
    prepared_df, metrics = validate_input_dataset(
        df_no_text, expected_count=3, allow_missing_retrieval_text=True
    )
    assert metrics["retrieval_text_generated"] is True
    assert "retrieval_text" in prepared_df.columns
    assert prepared_df["retrieval_text"].iloc[0].startswith("Product: Logitech K380")


def test_retrieval_text_disallowed_generation_raises(sample_valid_input_df: pd.DataFrame) -> None:
    """Verify ValueError is raised if retrieval_text is absent and auto-generation is disabled."""
    df_no_text = sample_valid_input_df.drop(columns=["retrieval_text"])
    with pytest.raises(ValueError, match="missing and automatic generation is disabled"):
        validate_input_dataset(df_no_text, expected_count=3, allow_missing_retrieval_text=False)


def test_retrieval_text_rejection_of_corrupt_entry(sample_valid_input_df: pd.DataFrame) -> None:
    """Verify invalid retrieval_text (e.g. placeholder, empty) is caught and rejected."""
    df_corrupt = sample_valid_input_df.copy()
    df_corrupt.loc[1, "retrieval_text"] = "Brand: None | Category: None"
    with pytest.raises(ValueError, match="invalid retrieval_text records"):
        validate_input_dataset(df_corrupt, expected_count=3)


# ==============================================================================
# 3. Embedding Generation & Numerical Validation Tests
# ==============================================================================

def test_generate_catalog_embeddings_with_mock_model(
    sample_valid_input_df: pd.DataFrame,
    mock_normalized_embeddings: np.ndarray,
) -> None:
    """Verify batch inference execution and performance metrics with a mock model."""
    mock_model = MagicMock()
    mock_model.model_name = DEFAULT_MODEL_NAME
    mock_model.device = "cpu"
    mock_model.embedding_dimension = DEFAULT_EMBEDDING_DIM
    mock_model.encode_documents.return_value = mock_normalized_embeddings

    embs, perf = generate_catalog_embeddings(
        df=sample_valid_input_df,
        model=mock_model,
        batch_size=2,
        show_progress=False,
    )

    assert embs.shape == (3, 384)
    assert embs.dtype == np.float32
    assert perf["status"] == "PASS"
    assert perf["total_items"] == 3
    assert perf["total_batches"] == 2
    assert perf["validation"]["status"] == "PASS"
    mock_model.encode_documents.assert_called_once()


def test_embedding_numerical_validation_detects_nan(mock_normalized_embeddings: np.ndarray) -> None:
    """Verify NaN vectors in embeddings are detected and raise ValueError."""
    corrupted = mock_normalized_embeddings.copy()
    corrupted[0, 10] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        validate_embeddings(corrupted, expected_dim=384, check_normalized=False)


def test_embedding_numerical_validation_detects_inf(mock_normalized_embeddings: np.ndarray) -> None:
    """Verify Inf vectors in embeddings are detected and raise ValueError."""
    corrupted = mock_normalized_embeddings.copy()
    corrupted[1, 5] = np.inf
    with pytest.raises(ValueError, match="Inf"):
        validate_embeddings(corrupted, expected_dim=384, check_normalized=False)


def test_embedding_numerical_validation_detects_zero_vector(mock_normalized_embeddings: np.ndarray) -> None:
    """Verify all-zero vectors in embeddings are detected and raise ValueError."""
    corrupted = mock_normalized_embeddings.copy()
    corrupted[2, :] = 0.0
    with pytest.raises(ValueError, match="all-zero"):
        validate_embeddings(corrupted, expected_dim=384, check_normalized=False)


def test_embedding_numerical_validation_detects_dimension_mismatch(mock_normalized_embeddings: np.ndarray) -> None:
    """Verify vectors with incorrect dimension (e.g. 512 instead of 384) are rejected."""
    wrong_dim = np.ones((3, 512), dtype=np.float32)
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        validate_embeddings(wrong_dim, expected_dim=384, check_normalized=False)


def test_embedding_numerical_validation_detects_unnormalized_vectors() -> None:
    """Verify unnormalized vectors exceeding tolerance are rejected."""
    unnorm = np.full((3, 384), 2.0, dtype=np.float32)
    with pytest.raises(ValueError, match="L2 normalization"):
        validate_embeddings(unnorm, expected_dim=384, check_normalized=True)


# ==============================================================================
# 4. Final Dataset Assembly & Schema Compatibility Tests
# ==============================================================================

def test_assemble_knowledge_base_dataframe_canonical_schema(
    sample_valid_input_df: pd.DataFrame,
    mock_normalized_embeddings: np.ndarray,
) -> None:
    """Verify assembled DataFrame has exact canonical columns in correct order."""
    final_df = assemble_knowledge_base_dataframe(
        sample_valid_input_df,
        embeddings=mock_normalized_embeddings,
        model_name="BAAI/bge-small-en-v1.5",
        include_timestamps=False,
    )

    assert list(final_df.columns) == CANONICAL_COLUMNS
    assert len(final_df) == 3
    assert final_df["embedding_model"].iloc[0] == "BAAI/bge-small-en-v1.5"

    # Excluded interim columns
    assert "uniq_id" not in final_df.columns
    assert "crawl_timestamp" not in final_df.columns
    assert "is_FK_Advantage_product" not in final_df.columns

    # Verify 1st embedding
    emb0 = final_df["embedding"].iloc[0]
    assert isinstance(emb0, np.ndarray)
    assert emb0.shape == (384,)
    assert emb0.dtype == np.float32


def test_assemble_knowledge_base_dataframe_with_timestamps(
    sample_valid_input_df: pd.DataFrame,
    mock_normalized_embeddings: np.ndarray,
) -> None:
    """Verify optional inclusion of created_at and updated_at timestamps."""
    final_df = assemble_knowledge_base_dataframe(
        sample_valid_input_df,
        embeddings=mock_normalized_embeddings,
        include_timestamps=True,
    )
    assert list(final_df.columns) == CANONICAL_COLUMNS_WITH_TIMESTAMPS
    assert "created_at" in final_df.columns
    assert "updated_at" in final_df.columns


def test_assemble_knowledge_base_dataframe_length_mismatch_raises(
    sample_valid_input_df: pd.DataFrame,
    mock_normalized_embeddings: np.ndarray,
) -> None:
    """Verify ValueError is raised if embedding count differs from DataFrame rows."""
    wrong_embs = mock_normalized_embeddings[:2]
    with pytest.raises(ValueError, match="Row count mismatch"):
        assemble_knowledge_base_dataframe(sample_valid_input_df, embeddings=wrong_embs)


# ==============================================================================
# 5. Processed Dataset Validation Tests
# ==============================================================================

def test_validate_processed_dataset_success(
    sample_valid_input_df: pd.DataFrame,
    mock_normalized_embeddings: np.ndarray,
) -> None:
    """Verify validation passes on canonical processed DataFrame."""
    final_df = assemble_knowledge_base_dataframe(
        sample_valid_input_df,
        embeddings=mock_normalized_embeddings,
    )
    metrics = validate_processed_dataset(final_df, expected_count=3)
    assert metrics["status"] == "PASS"
    assert metrics["total_products"] == 3
    assert metrics["embedding_dimension"] == 384
    assert metrics["nan_count"] == 0
    assert metrics["inf_count"] == 0
    assert metrics["zero_vector_count"] == 0


def test_validate_processed_dataset_schema_mismatch(
    sample_valid_input_df: pd.DataFrame,
    mock_normalized_embeddings: np.ndarray,
) -> None:
    """Verify ValueError is raised if column list or ordering does not match schema."""
    final_df = assemble_knowledge_base_dataframe(
        sample_valid_input_df,
        embeddings=mock_normalized_embeddings,
    )
    reordered_df = final_df[["category", "product_id"] + [c for c in final_df.columns if c not in ("category", "product_id")]]
    with pytest.raises(ValueError, match="Column schema mismatch"):
        validate_processed_dataset(reordered_df, expected_count=3)


# ==============================================================================
# 6. Parquet Export & Roundtrip Verification Tests
# ==============================================================================

def test_export_products_parquet_atomic_and_roundtrip(
    sample_valid_input_df: pd.DataFrame,
    mock_normalized_embeddings: np.ndarray,
    tmp_path: Path,
) -> None:
    """Verify atomic Parquet export, serialization, and roundtrip deserialization."""
    final_df = assemble_knowledge_base_dataframe(
        sample_valid_input_df,
        embeddings=mock_normalized_embeddings,
    )

    out_file = tmp_path / "products.parquet"
    res = export_products_parquet(
        final_df,
        output_path=out_file,
        validate_roundtrip=True,
        expected_count=3,
    )

    assert out_file.exists()
    assert res["status"] == "PASS"
    assert res["roundtrip_validation"] == "PASS"
    assert res["file_size_bytes"] > 0

    # Ensure no leftover temporary files
    temp_files = list(tmp_path.glob(".tmp_*"))
    assert len(temp_files) == 0

    # Read back independently and verify integrity
    loaded_df = pd.read_parquet(out_file)
    assert len(loaded_df) == 3
    assert list(loaded_df.columns) == CANONICAL_COLUMNS
    assert loaded_df["product_id"].equals(sample_valid_input_df["product_id"])

    # Verify vector dimension and float32 preservation
    emb_loaded = loaded_df["embedding"].iloc[0]
    assert len(emb_loaded) == 384
    assert np.allclose(emb_loaded, mock_normalized_embeddings[0], atol=1e-6)


def test_export_products_parquet_cleans_up_on_failure(
    sample_valid_input_df: pd.DataFrame,
    mock_normalized_embeddings: np.ndarray,
    tmp_path: Path,
) -> None:
    """Verify temporary files are cleaned up if validation fails during export."""
    final_df = assemble_knowledge_base_dataframe(
        sample_valid_input_df,
        embeddings=mock_normalized_embeddings,
    )

    out_file = tmp_path / "products.parquet"
    with patch("shopassist.embeddings.batch.validate_processed_dataset", side_effect=ValueError("Simulated validation error")):
        with pytest.raises(RuntimeError, match="Parquet export failed"):
            export_products_parquet(
                final_df,
                output_path=out_file,
                validate_roundtrip=True,
                expected_count=3,
            )

    # Output file must NOT have been created
    assert not out_file.exists()
    # Temporary files must have been cleaned up
    temp_files = list(tmp_path.glob(".tmp_*"))
    assert len(temp_files) == 0


# ==============================================================================
# 7. Semantic Sanity Checks on Assembled Embeddings
# ==============================================================================

def test_verify_semantic_retrieval_sanity(
    sample_valid_input_df: pd.DataFrame,
) -> None:
    """Verify semantic retrieval sanity checker correctly ranks relevant documents."""
    mock_model = MagicMock()
    # Provide synthetic embeddings where row 0 matches query 0, row 1 matches query 1, row 2 matches query 2
    mock_vecs = np.zeros((3, 384), dtype=np.float32)
    mock_vecs[0, 0] = 1.0  # keyboard
    mock_vecs[1, 1] = 1.0  # sofa
    mock_vecs[2, 2] = 1.0  # sandal

    def mock_encode_query(q, show_progress_bar=False):
        v = np.zeros(384, dtype=np.float32)
        if "keyboard" in q:
            v[0] = 1.0
        elif "sofa" in q:
            v[1] = 1.0
        elif "sandals" in q:
            v[2] = 1.0
        return v

    def _mock_doc(t: str, **kwargs) -> np.ndarray:
        if "Logitech" in str(t):
            return mock_vecs[0]
        if "Durian" in str(t):
            return mock_vecs[1]
        return mock_vecs[2]

    mock_model.encode_documents.side_effect = _mock_doc
    mock_model.encode_queries.side_effect = mock_encode_query

    df = sample_valid_input_df.copy()
    df["embedding"] = list(mock_vecs)

    sanity_res = verify_semantic_retrieval_sanity(df, mock_model)
    assert sanity_res["status"] == "PASS"
    assert sanity_res["passed"] == 3


# ==============================================================================
# 8. Complete Pipeline Execution Test (with Mocks)
# ==============================================================================

def test_run_phase5_5_pipeline_mocked(
    sample_valid_input_df: pd.DataFrame,
    mock_normalized_embeddings: np.ndarray,
    tmp_path: Path,
) -> None:
    """Verify end-to-end pipeline execution and JSON report generation."""
    input_file = tmp_path / "cleaned_candidates.parquet"
    output_file = tmp_path / "processed" / "products.parquet"
    report_file = tmp_path / "interim" / "report.json"

    sample_valid_input_df.to_parquet(input_file, index=False)

    with patch("shopassist.embeddings.batch.EmbeddingModel") as MockModelClass:
        mock_instance = MagicMock()
        mock_instance.model_name = "BAAI/bge-small-en-v1.5"
        mock_instance.device = "cpu"
        mock_instance.embedding_dimension = 384

        def _mock_doc_batch(*args, **kwargs):
            docs = kwargs.get("documents", args[0] if args else None)
            if isinstance(docs, list):
                return mock_normalized_embeddings
            if "Logitech" in str(docs):
                return mock_normalized_embeddings[0]
            if "Durian" in str(docs):
                return mock_normalized_embeddings[1]
            return mock_normalized_embeddings[2]

        mock_instance.encode_documents.side_effect = _mock_doc_batch

        def _mock_query(q: str, show_progress_bar: bool = False) -> np.ndarray:
            if "keyboard" in q:
                return mock_normalized_embeddings[0]
            if "sofa" in q:
                return mock_normalized_embeddings[1]
            return mock_normalized_embeddings[2]

        mock_instance.encode_queries.side_effect = _mock_query
        MockModelClass.return_value = mock_instance

        exit_code, report = run_phase5_5_pipeline(
            input_path=input_file,
            output_path=output_file,
            report_path=report_file,
            batch_size=2,
            expected_count=3,
        )

        assert exit_code == 0
        assert report["overall_status"] == "PASS"
        assert output_file.exists()
        assert report_file.exists()

        # Check JSON report content
        with open(report_file, "r", encoding="utf-8") as f:
            saved_report = json.load(f)

        assert saved_report["phase"] == "5.5"
        assert saved_report["input_dataset"]["rows"] == 3
        assert saved_report["output_dataset"]["rows"] == 3
        assert saved_report["embedding_validation"]["status"] == "PASS"
        assert saved_report["timestamps_policy"]["omitted_columns"] == ["created_at", "updated_at"]
