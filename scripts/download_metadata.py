"""Download and validate Amazon Reviews 2023 Appliances product metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


SOURCE_URL = (
    "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/"
    "resolve/main/raw/meta_categories/meta_Appliances.jsonl"
)
EXPECTED_SHA256 = "b25ae892af7bc452c4a54b7e4fee52f4c3e9adf058768ca3cb07ecb8d328b41e"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
FILENAME = "meta_Appliances.jsonl"


def validate(path: Path) -> int:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as source:
        for count, line in enumerate(source, start=1):
            digest.update(line)
            record = json.loads(line)
            if not isinstance(record, dict) or not record.get("parent_asin"):
                raise ValueError(f"Invalid product record on line {count}")
    if count == 0:
        raise ValueError("Metadata file is empty")
    if digest.hexdigest() != EXPECTED_SHA256:
        raise ValueError(f"SHA-256 mismatch for {path}")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir", type=Path, default=RAW_DIR, help="Destination directory"
    )
    args = parser.parse_args()
    raw_dir = args.raw_dir.resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)
    output = raw_dir / FILENAME

    if output.exists():
        print(f"Validating existing metadata: {output}", flush=True)
        count = validate(output)
    else:
        curl = shutil.which("curl.exe" if os.name == "nt" else "curl")
        if curl is None:
            raise RuntimeError("curl is required to download metadata")
        with tempfile.NamedTemporaryFile(dir=raw_dir, suffix=".part", delete=False) as temp:
            temporary_path = Path(temp.name)
        try:
            print(f"Downloading: {SOURCE_URL}", flush=True)
            subprocess.run(
                [curl, "--fail", "--location", "--retry", "3", "--silent", "--show-error", "--output", str(temporary_path), SOURCE_URL],
                check=True,
            )
            print("Validating SHA-256 and JSONL records...", flush=True)
            count = validate(temporary_path)
            os.replace(temporary_path, output)
        finally:
            temporary_path.unlink(missing_ok=True)

    print(f"Products: {count:,}")
    print(f"SHA-256: {EXPECTED_SHA256}")
    print(f"Metadata: {output}")


if __name__ == "__main__":
    main()
