"""Dataset validation utilities for Phase 1 inspection."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd


def validate_raw_file(path: Path | str) -> Path:
    """Validate that the raw file exists, is readable, and is not empty.

    Args:
        path: Path to the raw dataset file.

    Returns:
        Resolved Path object.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is empty (0 bytes).
        PermissionError: If the file cannot be accessed.
    """
    resolved_path = Path(path).resolve()

    if not resolved_path.exists():
        raise FileNotFoundError(f"Raw dataset file not found at: {resolved_path}")

    if not resolved_path.is_file():
        raise ValueError(f"Path is not a regular file: {resolved_path}")

    file_size = resolved_path.stat().st_size
    if file_size == 0:
        raise ValueError(f"Raw dataset file is empty (0 bytes): {resolved_path}")

    return resolved_path


def check_duplicate_columns(df: pd.DataFrame) -> List[str]:
    """Check for duplicate column names in the DataFrame.

    Args:
        df: Pandas DataFrame to check.

    Returns:
        List of duplicate column names (empty if none).
    """
    columns = list(df.columns)
    seen = set()
    duplicates = set()
    for col in columns:
        if col in seen:
            duplicates.add(col)
        seen.add(col)
    return sorted(list(duplicates))


def validate_dataframe(df: pd.DataFrame) -> None:
    """Validate that the loaded DataFrame is non-empty and has columns.

    Args:
        df: Loaded Pandas DataFrame.

    Raises:
        ValueError: If DataFrame is empty or has no columns.
    """
    if df is None:
        raise ValueError("DataFrame is None.")

    if len(df.columns) == 0:
        raise ValueError("DataFrame has no columns.")

    if len(df) == 0:
        raise ValueError("DataFrame has 0 rows.")


def check_candidate_fields(
    df: pd.DataFrame, candidate_fields: List[str]
) -> Dict[str, bool]:
    """Check availability of candidate fields in the DataFrame columns.

    Args:
        df: Pandas DataFrame.
        candidate_fields: List of expected field names.

    Returns:
        Dict mapping field name -> True (FOUND) or False (NOT FOUND).
    """
    actual_columns = set(df.columns)
    return {field: field in actual_columns for field in candidate_fields}


def inspect_raw_schema(
    df: pd.DataFrame, candidate_fields: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Inspect raw schema of the DataFrame without transforming any data.

    Args:
        df: Pandas DataFrame.
        candidate_fields: Optional list of candidate fields to check.

    Returns:
        Dictionary containing schema inspection details.
    """
    validate_dataframe(df)

    duplicate_cols = check_duplicate_columns(df)
    candidate_status = {}
    if candidate_fields:
        candidate_status = check_candidate_fields(df, candidate_fields)

    return {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "duplicate_columns": duplicate_cols,
        "candidate_status": candidate_status,
        "first_5_rows": df.head(5).to_dict(orient="records"),
    }
