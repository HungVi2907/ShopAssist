"""Unit tests for data loading and validation module."""

import pytest
import pandas as pd
from pathlib import Path

from shopassist.data.loader import load_raw_dataset
from shopassist.data.validation import (
    check_candidate_fields,
    check_duplicate_columns,
    inspect_raw_schema,
    validate_dataframe,
    validate_raw_file,
)


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create a temporary valid CSV file fixture."""
    file_path = tmp_path / "valid_sample.csv"
    df = pd.DataFrame(
        {
            "uniq_id": ["u1", "u2"],
            "pid": ["p1", "p2"],
            "product_name": ["Product 1", "Product 2"],
            "retail_price": [100.0, 200.0],
            "discounted_price": [80.0, 150.0],
            "brand": ["BrandA", "BrandB"],
        }
    )
    df.to_csv(file_path, index=False)
    return file_path


@pytest.fixture
def empty_csv(tmp_path: Path) -> Path:
    """Create a temporary empty (0 bytes) CSV file fixture."""
    file_path = tmp_path / "empty_sample.csv"
    file_path.touch()
    return file_path


def test_validate_raw_file_success(sample_csv: Path):
    resolved = validate_raw_file(sample_csv)
    assert resolved == sample_csv.resolve()
    assert resolved.exists()


def test_validate_raw_file_missing(tmp_path: Path):
    missing_path = tmp_path / "non_existent.csv"
    with pytest.raises(FileNotFoundError, match="Raw dataset file not found"):
        validate_raw_file(missing_path)


def test_validate_raw_file_empty(empty_csv: Path):
    with pytest.raises(ValueError, match="is empty"):
        validate_raw_file(empty_csv)


def test_load_raw_dataset_success(sample_csv: Path):
    df = load_raw_dataset(sample_csv)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == [
        "uniq_id",
        "pid",
        "product_name",
        "retail_price",
        "discounted_price",
        "brand",
    ]


def test_validate_dataframe_none():
    with pytest.raises(ValueError, match="DataFrame is None"):
        validate_dataframe(None)


def test_validate_dataframe_empty():
    with pytest.raises(ValueError, match="0 rows"):
        validate_dataframe(pd.DataFrame(columns=["a", "b"]))


def test_check_duplicate_columns():
    df_no_dup = pd.DataFrame([[1, 2]], columns=["a", "b"])
    assert check_duplicate_columns(df_no_dup) == []

    # Construct DataFrame with duplicate column names
    df_dup = pd.DataFrame([[1, 2, 3]])
    df_dup.columns = ["a", "b", "a"]
    assert check_duplicate_columns(df_dup) == ["a"]


def test_check_candidate_fields(sample_csv: Path):
    df = load_raw_dataset(sample_csv)
    candidates = ["uniq_id", "product_name", "not_a_field"]
    status = check_candidate_fields(df, candidates)
    assert status["uniq_id"] is True
    assert status["product_name"] is True
    assert status["not_a_field"] is False


def test_inspect_raw_schema(sample_csv: Path):
    df = load_raw_dataset(sample_csv)
    candidates = ["uniq_id", "brand", "product_rating"]
    schema = inspect_raw_schema(df, candidates)

    assert schema["row_count"] == 2
    assert schema["column_count"] == 6
    assert schema["duplicate_columns"] == []
    assert schema["candidate_status"]["uniq_id"] is True
    assert schema["candidate_status"]["brand"] is True
    assert schema["candidate_status"]["product_rating"] is False
    assert len(schema["first_5_rows"]) == 2
