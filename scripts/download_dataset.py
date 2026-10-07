"""Script to download the canonical Flipkart Products 20K dataset.

Source: PromptCloud Flipkart Products sample dataset
Target: data/raw/flipkart_products.csv
"""

import sys
import time
from pathlib import Path
import urllib.request

DATASET_URL = (
    "https://huggingface.co/datasets/jason1966/PromptCloudHQ_flipkart-products/resolve/main/flipkart_com-ecommerce_sample.csv"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "raw" / "flipkart_products.csv"


def download_flipkart_dataset(output_path: Path = OUTPUT_PATH, force: bool = False) -> Path:
    if output_path.exists() and not force:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"Dataset already exists at: {output_path} ({size_mb:.2f} MB)")
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp")

    print(f"Downloading Flipkart Products 20K dataset from:\n  {DATASET_URL}")
    print(f"Saving to:\n  {output_path}")

    start_time = time.time()

    def report_progress(block_num: int, block_size: int, total_size: int) -> None:
        downloaded = block_num * block_size
        if total_size > 0:
            percent = min(100.0, downloaded * 100.0 / total_size)
            mb = downloaded / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            sys.stdout.write(f"\rProgress: {percent:6.2f}% ({mb:6.2f} MB / {total_mb:6.2f} MB)")
        else:
            mb = downloaded / (1024 * 1024)
            sys.stdout.write(f"\rDownloaded: {mb:6.2f} MB")
        sys.stdout.flush()

    try:
        urllib.request.urlretrieve(DATASET_URL, temp_path, reporthook=report_progress)
        print()
        temp_path.replace(output_path)
        elapsed = time.time() - start_time
        final_size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"Successfully downloaded {final_size_mb:.2f} MB in {elapsed:.1f}s.")
        return output_path
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"Failed to download dataset: {e}") from e


if __name__ == "__main__":
    force_download = "--force" in sys.argv
    download_flipkart_dataset(force=force_download)
