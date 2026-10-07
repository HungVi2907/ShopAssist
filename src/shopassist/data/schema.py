"""Pydantic schema definitions and dataset readiness validation for Product Knowledge Base (Phase 5)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class SpecificationItem(BaseModel):
    """Structured key-value specification item."""

    key: str = Field(..., min_length=1, description="Specification attribute name")
    value: str | None = Field(default=None, description="Specification attribute value")

    model_config = ConfigDict(extra="ignore")


class CleanedCandidateRecord(BaseModel):
    """Schema contract for candidate records generated at the end of Phase 4."""

    product_id: str = Field(..., min_length=1, description="Primary technical identifier")
    product_name: str = Field(..., min_length=1, description="Cleaned product title")
    category: str = Field(..., min_length=1, description="Official Level-1 category")
    brand: str | None = Field(default=None, description="Canonical brand name or None")
    retail_price: Decimal | None = Field(default=None, description="Original MSRP retail price")
    discounted_price: Decimal = Field(..., gt=0, description="Cleaned operational price")
    rating: float | None = Field(default=None, ge=1.0, le=5.0, description="Product rating")
    description: str | None = Field(default=None, description="Cleaned product description")
    product_specifications: str = Field(default="[]", description="JSON string of specification items")
    product_url: str | None = Field(default=None, description="Product URL")
    uniq_id: str = Field(..., min_length=1, description="Raw technical ID")
    pid: str | None = Field(default=None, description="Flipkart catalog SKU")
    image: str | None = Field(default=None, description="Raw image URL representation")
    crawl_timestamp: str | None = Field(default=None, description="Raw scraping timestamp")
    is_FK_Advantage_product: bool | None = Field(default=None, description="Raw Flipkart advantage flag")

    @field_validator("product_specifications")
    @classmethod
    def validate_specs_json(cls, v: str) -> str:
        """Ensure specifications can be parsed as a list of dicts."""
        try:
            parsed = json.loads(v)
            if not isinstance(parsed, list):
                raise ValueError("product_specifications must be a JSON array")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON string in product_specifications: {exc}") from exc
        return v

    model_config = ConfigDict(extra="ignore")


class ProductKnowledgeBaseRecord(BaseModel):
    """Full production schema contract for Supabase Cloud PostgreSQL products table."""

    product_id: str = Field(..., min_length=1, max_length=64, description="Primary key")
    product_name: str = Field(..., min_length=1, description="Product name")
    category: str = Field(..., min_length=1, max_length=128, description="Product category")
    brand: str | None = Field(default=None, max_length=128, description="Brand name")
    retail_price: Decimal | None = Field(default=None, gt=0, description="Retail price")
    discounted_price: Decimal = Field(..., gt=0, description="Discounted price")
    rating: float | None = Field(default=None, ge=1.0, le=5.0, description="Product rating")
    description: str | None = Field(default=None, description="Product description")
    product_specifications: list[SpecificationItem] = Field(
        default_factory=list, description="Structured specifications array"
    )
    product_url: str | None = Field(default=None, description="Product link")
    image: str | None = Field(default=None, description="Primary product image URL")
    pid: str | None = Field(default=None, max_length=64, description="Flipkart SKU identifier")
    retrieval_text: str = Field(..., min_length=1, description="Composite semantic retrieval text")
    embedding: list[float] = Field(..., min_length=384, max_length=384, description="384-d dense embedding vector")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", description="Embedding model ID")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Record creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Record update timestamp")

    model_config = ConfigDict(extra="ignore")


def validate_cleaned_dataset_readiness(
    df: pd.DataFrame,
    selected_categories: list[str] | None = None,
) -> dict[str, Any]:
    """Validate cleaned candidates DataFrame against planned Phase 5 schema requirements."""
    total_rows = len(df)

    # 1. Product ID and Lineage verification
    id_present = int(df["product_id"].notna().sum())
    uniq_id_present = int(df["uniq_id"].notna().sum()) if "uniq_id" in df.columns else 0
    id_unique = bool(df["product_id"].is_unique)
    id_mismatches = int((df["product_id"] != df["uniq_id"]).sum()) if "uniq_id" in df.columns else 0

    # 2. Required core fields
    name_valid = int(((df["product_name"].notna()) & (df["product_name"].astype(str).str.strip() != "")).sum())
    cat_valid = int(((df["category"].notna()) & (df["category"].astype(str).str.strip() != "")).sum())

    category_violations = 0
    if selected_categories:
        category_violations = int((~df["category"].isin(selected_categories)).sum())

    # 3. Numeric constraints
    price_positive = int(((df["discounted_price"].notna()) & (df["discounted_price"] > 0)).sum())
    price_violations = total_rows - price_positive

    rating_violations = int(
        (
            df["rating"].notna()
            & ((df["rating"] < 1.0) | (df["rating"] > 5.0))
        ).sum()
    )

    # 4. Specifications structure
    valid_specs_count = 0
    empty_specs_count = 0
    invalid_specs_count = 0

    for s in df["product_specifications"]:
        try:
            if s is None or pd.isna(s):
                invalid_specs_count += 1
                continue
            parsed = json.loads(str(s))
            if isinstance(parsed, list):
                if len(parsed) == 0:
                    empty_specs_count += 1
                else:
                    valid_specs_count += 1
            else:
                invalid_specs_count += 1
        except Exception:
            invalid_specs_count += 1

    # 5. Field availability counts
    field_counts = {
        col: int(df[col].notna().sum()) if col in df.columns else 0
        for col in [
            "product_id",
            "product_name",
            "category",
            "brand",
            "retail_price",
            "discounted_price",
            "rating",
            "description",
            "product_specifications",
            "product_url",
            "image",
            "pid",
        ]
    }

    report = {
        "rows_checked": total_rows,
        "product_id_validation": {
            "total_ids": id_present,
            "is_unique": id_unique,
            "id_equals_uniq_id_matches": total_rows - id_mismatches,
            "id_mismatches": id_mismatches,
            "status": "PASS" if id_unique and id_mismatches == 0 else "FAIL",
        },
        "source_fields": {
            "product_id": "ready",
            "product_name": "ready",
            "category": "ready",
            "brand": "ready",
            "retail_price": "ready",
            "discounted_price": "ready",
            "rating": "ready",
            "description": "ready",
            "product_specifications": "ready",
            "product_url": "ready",
            "image": "ready",
            "pid": "ready",
        },
        "field_coverage_counts": field_counts,
        "future_generated_fields": {
            "retrieval_text": "phase_5_2",
            "embedding": "phase_5_5",
            "embedding_model": "phase_5_5",
            "created_at": "database_default",
            "updated_at": "database_default",
        },
        "specification_validation": {
            "valid_specs_arrays": valid_specs_count,
            "empty_specs_arrays": empty_specs_count,
            "invalid_specs": invalid_specs_count,
            "status": "PASS" if invalid_specs_count == 0 else "FAIL",
        },
        "numeric_validation": {
            "valid_discounted_price": price_positive,
            "price_violations": price_violations,
            "rating_violations": rating_violations,
            "status": "PASS" if price_violations == 0 and rating_violations == 0 else "FAIL",
        },
        "taxonomy_validation": {
            "valid_categories": cat_valid,
            "category_violations": category_violations,
            "status": "PASS" if category_violations == 0 else "FAIL",
        },
        "overall_status": (
            "READY_FOR_PHASE_5_2"
            if (
                id_unique
                and id_mismatches == 0
                and price_violations == 0
                and rating_violations == 0
                and invalid_specs_count == 0
                and category_violations == 0
            )
            else "VALIDATION_FAILED"
        ),
    }

    return report


def save_schema_readiness_report(report: dict[str, Any], output_path: Path) -> None:
    """Save schema readiness audit report to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("Saved schema readiness report to %s", output_path)
