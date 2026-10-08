"""Centralized project path, dataset, and database configuration."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values, load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve PROJECT_ROOT dynamically based on file location
# src/shopassist/core/config.py -> parents[3] is repository root
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
INTERIM_DATA_DIR = DATA_DIR / "interim"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
ENV_FILE_PATH = PROJECT_ROOT / ".env"
MIGRATIONS_DIR = PROJECT_ROOT / "database" / "migrations"
BASE_MIGRATION_PATH = MIGRATIONS_DIR / "001_create_product_knowledge_base.sql"
INDEX_MIGRATION_PATH = MIGRATIONS_DIR / "002_create_product_indexes.sql"

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


def mask_database_url(url: str | None) -> str:
    """Mask credentials and host in a database connection URL for secure logging and reporting.

    Never logs the plain password, project ref, or plain credentials.
    Example output:
        postgresql://postgres.***:***@***.pooler.supabase.com:5432/postgres

    Args:
        url: Raw database URL or None.

    Returns:
        Masked database URL string.
    """
    if not url or not str(url).strip():
        return "[NOT CONFIGURED]"

    clean_url = str(url).strip()
    try:
        from sqlalchemy.engine import make_url

        u = make_url(clean_url)
        driver = u.drivername or "postgresql"
        port = f":{u.port}" if u.port else ":5432"
        db = f"/{u.database}" if u.database else "/postgres"

        host_str = (u.host or "").lower()
        if "pooler.supabase.com" in host_str:
            masked_host = "***.pooler.supabase.com"
        elif "supabase.co" in host_str:
            masked_host = "***.supabase.co"
        else:
            masked_host = "***"

        return f"{driver}://postgres.***:***@{masked_host}{port}{db}"
    except Exception:
        return "postgresql://postgres.***:***@***.pooler.supabase.com:5432/postgres"


class Settings(BaseSettings):
    """Application and database configuration loaded from environment or .env."""

    supabase_db_url: str | None = Field(default=None, alias="SUPABASE_DB_URL")

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH) if ENV_FILE_PATH.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def get_raw_supabase_db_url(self) -> str:
        """Retrieve and validate the raw Supabase database URL.

        Raises:
            ValueError: If SUPABASE_DB_URL is missing, empty, or unconfigured.
        """
        if self.supabase_db_url and self.supabase_db_url.strip():
            return self.supabase_db_url.strip()

        # Fallback check direct os.environ and dotenv_values
        env_val = os.getenv("SUPABASE_DB_URL")
        if env_val and env_val.strip():
            return env_val.strip()

        if ENV_FILE_PATH.exists():
            file_vals = dotenv_values(str(ENV_FILE_PATH))
            file_val = file_vals.get("SUPABASE_DB_URL")
            if file_val and file_val.strip():
                return file_val.strip()

        raise ValueError(
            "SUPABASE_DB_URL is missing or empty. Please configure it in .env or environment variables."
        )

    def get_masked_supabase_db_url(self) -> str:
        """Retrieve masked version of the Supabase database URL."""
        try:
            raw = self.get_raw_supabase_db_url()
            return mask_database_url(raw)
        except ValueError:
            return "[NOT CONFIGURED]"


# Singleton instance
settings = Settings()
