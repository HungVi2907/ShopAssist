"""Data loading utilities for ShopAssist."""

from pathlib import Path
from typing import Optional
import pandas as pd

from shopassist.core.config import FLIPKART_RAW_DATASET_PATH
from shopassist.data.validation import validate_dataframe, validate_raw_file


def load_raw_dataset(
    path: Optional[Path | str] = None,
    **csv_kwargs,
) -> pd.DataFrame:
    """Load the raw Flipkart dataset as an immutable input DataFrame.

    Does not modify, clean, drop, or transform any data.

    Args:
        path: Optional path to the CSV file. Defaults to FLIPKART_RAW_DATASET_PATH.
        **csv_kwargs: Additional arguments forwarded to pd.read_csv.

    Returns:
        pd.DataFrame containing the raw dataset.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If file is empty or parsed dataframe has no rows/columns.
        pd.errors.ParserError: If CSV parsing encounters fatal errors.
    """
    target_path = Path(path) if path is not None else FLIPKART_RAW_DATASET_PATH
    validated_path = validate_raw_file(target_path)

    # Set default encoding parameters if not overridden
    if "encoding" not in csv_kwargs:
        csv_kwargs["encoding"] = "utf-8"

    try:
        df = pd.read_csv(validated_path, **csv_kwargs)
    except UnicodeDecodeError:
        # Fallback to utf-8-sig or latin1 if non-standard characters exist
        if "encoding" in csv_kwargs and csv_kwargs["encoding"] == "utf-8":
            csv_kwargs["encoding"] = "utf-8-sig"
            df = pd.read_csv(validated_path, **csv_kwargs)
        else:
            raise

    validate_dataframe(df)
    return df
