"""Centralized project path and dataset configuration."""

from pathlib import Path

# Resolve PROJECT_ROOT dynamically based on file location
# src/shopassist/core/config.py -> parents[3] is repository root
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# Canonical raw dataset path
FLIPKART_RAW_DATASET_PATH = RAW_DATA_DIR / "flipkart_products.csv"

# Candidate fields defined in proposal.md
PROPOSAL_CANDIDATE_FIELDS = [
    "uniq_id",
    "pid",
    "product_name",
    "product_category_tree",
    "retail_price",
    "discounted_price",
    "description",
    "product_rating",
    "overall_rating",
    "brand",
    "product_specifications",
    "product_url",
]
