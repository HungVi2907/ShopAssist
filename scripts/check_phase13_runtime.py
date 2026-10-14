"""Read-only Phase 13 runtime and pinned-catalog preflight.

Run this with the supported Windows environment:

``& .\\.deps\\phase13-win-venv\\Scripts\\python.exe scripts\\check_phase13_runtime.py``

It neither sends data over the network nor changes the catalog.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data/processed/products.parquet"
REQUIRED = ["product_id", "product_name", "category", "brand", "discounted_price", "rating", "retrieval_text"]


def main() -> None:
    import numpy as np
    import pandas as pd
    import pyarrow as pa

    frame = pd.read_parquet(CATALOG)
    missing = [column for column in REQUIRED if column not in frame.columns]
    result = {
        "status": "PASS" if not missing and len(frame) == frame["product_id"].astype(str).nunique() else "FAIL",
        "python": {"executable": sys.executable, "version": sys.version, "prefix": sys.prefix, "platform": platform.platform()},
        "packages": {"numpy": np.__version__, "pandas": pd.__version__, "pyarrow": pa.__version__},
        "catalog": {"path": str(CATALOG.relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
                    "product_count": len(frame), "unique_product_ids": frame["product_id"].astype(str).nunique(),
                    "required_missing": missing, "category_count": int(frame["category"].nunique()), "embedding_present": "embedding" in frame.columns},
    }
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
