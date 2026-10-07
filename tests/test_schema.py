"""Unit tests for Phase 5.1 Product Knowledge Base schema, contract definitions, and SQL migration."""

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from shopassist.data.schema import (
    CleanedCandidateRecord,
    ProductKnowledgeBaseRecord,
    SpecificationItem,
    validate_cleaned_dataset_readiness,
)

MIGRATION_PATH = Path("database/migrations/001_create_product_knowledge_base.sql")
READINESS_REPORT_PATH = Path("data/interim/phase5_schema_readiness.json")


class TestPydanticSchemaContracts:
    """Test suite for Pydantic schema validation."""

    def test_valid_cleaned_candidate_record(self):
        record_data = {
            "product_id": "test_uid_001",
            "product_name": "Logitech MX Master 3S Mouse",
            "category": "Computers",
            "brand": "Logitech",
            "retail_price": 9999.0,
            "discounted_price": 7999.0,
            "rating": 4.8,
            "description": "Ergonomic wireless performance mouse.",
            "product_specifications": json.dumps([{"key": "Color", "value": "Graphite"}]),
            "product_url": "http://www.flipkart.com/mouse",
            "uniq_id": "test_uid_001",
            "pid": "MOU123",
            "image": "http://img.com/mouse.jpg",
            "crawl_timestamp": "2016-01-01",
            "is_FK_Advantage_product": True,
        }
        record = CleanedCandidateRecord(**record_data)
        assert record.product_id == "test_uid_001"
        assert record.discounted_price == Decimal("7999.0")
        assert record.rating == 4.8

    def test_cleaned_candidate_rejects_non_positive_price(self):
        record_data = {
            "product_id": "test_uid_002",
            "product_name": "Defective Product",
            "category": "Computers",
            "discounted_price": 0.0,
            "uniq_id": "test_uid_002",
        }
        with pytest.raises(ValidationError):
            CleanedCandidateRecord(**record_data)

    def test_cleaned_candidate_rejects_invalid_rating(self):
        record_data = {
            "product_id": "test_uid_003",
            "product_name": "Defective Product",
            "category": "Computers",
            "discounted_price": 500.0,
            "rating": 6.5,  # Out of range 1.0 - 5.0
            "uniq_id": "test_uid_003",
        }
        with pytest.raises(ValidationError):
            CleanedCandidateRecord(**record_data)

    def test_cleaned_candidate_rejects_malformed_specs_json(self):
        record_data = {
            "product_id": "test_uid_004",
            "product_name": "Defective Product",
            "category": "Computers",
            "discounted_price": 500.0,
            "product_specifications": "not a json string",
            "uniq_id": "test_uid_004",
        }
        with pytest.raises(ValidationError):
            CleanedCandidateRecord(**record_data)

    def test_valid_product_knowledge_base_record(self):
        vector_384 = [0.1] * 384
        record_data = {
            "product_id": "prod_001",
            "product_name": "Puma Smash V2 Shoes",
            "category": "Footwear",
            "brand": "Puma",
            "retail_price": 3499.0,
            "discounted_price": 1999.0,
            "rating": 4.2,
            "description": "Classic leather sneakers for everyday comfort.",
            "product_specifications": [{"key": "Color", "value": "White"}, {"key": "Size", "value": "9"}],
            "product_url": "http://flipkart.com/puma",
            "image": "http://img.com/puma.jpg",
            "pid": "SHOE001",
            "retrieval_text": "Product: Puma Smash V2 Shoes | Category: Footwear | Brand: Puma | Specifications: Color: White; Size: 9 | Description: Classic leather sneakers",
            "embedding": vector_384,
            "embedding_model": "BAAI/bge-small-en-v1.5",
        }
        record = ProductKnowledgeBaseRecord(**record_data)
        assert record.product_id == "prod_001"
        assert len(record.embedding) == 384
        assert len(record.product_specifications) == 2

    def test_product_knowledge_base_record_rejects_wrong_vector_dim(self):
        vector_wrong = [0.1] * 768  # 768-d instead of 384-d
        record_data = {
            "product_id": "prod_002",
            "product_name": "Puma Shoes",
            "category": "Footwear",
            "discounted_price": 1999.0,
            "retrieval_text": "Product: Puma Shoes",
            "embedding": vector_wrong,
        }
        with pytest.raises(ValidationError):
            ProductKnowledgeBaseRecord(**record_data)


class TestSQLMigrationArtifact:
    """Static validation tests for database/migrations/001_create_product_knowledge_base.sql."""

    def test_migration_file_exists(self):
        assert MIGRATION_PATH.exists(), f"Migration file missing at {MIGRATION_PATH}"

    def test_migration_contains_pgvector_and_table(self):
        sql = MIGRATION_PATH.read_text(encoding="utf-8")
        assert "CREATE EXTENSION IF NOT EXISTS vector;" in sql
        assert "CREATE TABLE IF NOT EXISTS products" in sql
        assert "embedding               vector(384) NOT NULL" in sql
        assert "product_specifications  JSONB NOT NULL DEFAULT '[]'::jsonb" in sql

    def test_migration_contains_constraints(self):
        sql = MIGRATION_PATH.read_text(encoding="utf-8")
        assert "product_id              VARCHAR(64) PRIMARY KEY" in sql
        assert "CHECK (discounted_price > 0)" in sql
        assert "CHECK (rating IS NULL OR (rating >= 1.0 AND rating <= 5.0))" in sql
        assert "CHECK (length(trim(product_name)) > 0)" in sql
        assert "CHECK (length(trim(category)) > 0)" in sql
        assert "CHECK (length(trim(retrieval_text)) > 0)" in sql

    def test_migration_contains_approved_indexes(self):
        sql = MIGRATION_PATH.read_text(encoding="utf-8")
        assert "idx_products_category" in sql
        assert "idx_products_price" in sql
        assert "idx_products_brand" in sql
        assert "idx_products_category_price" in sql
        assert "idx_products_embedding" in sql
        assert "USING hnsw (embedding vector_cosine_ops)" in sql
        assert "m = 16" in sql
        assert "ef_construction = 64" in sql

    def test_migration_contains_updated_at_trigger(self):
        sql = MIGRATION_PATH.read_text(encoding="utf-8")
        assert "CREATE OR REPLACE FUNCTION update_products_updated_at()" in sql
        assert "CREATE TRIGGER trg_products_updated_at" in sql
        assert "BEFORE UPDATE ON products" in sql

    def test_migration_does_not_contain_unapproved_indexes(self):
        sql = MIGRATION_PATH.read_text(encoding="utf-8")
        assert "ivfflat" not in sql.lower()
        assert "to_tsvector" not in sql.lower()


class TestDatasetSchemaReadiness:
    """Test suite verifying dataset readiness against planned schema."""

    def test_readiness_report_exists_and_passes(self):
        assert READINESS_REPORT_PATH.exists(), f"Readiness report missing at {READINESS_REPORT_PATH}"
        data = json.loads(READINESS_REPORT_PATH.read_text(encoding="utf-8"))
        assert data["rows_checked"] == 8405
        assert data["overall_status"] == "READY_FOR_PHASE_5_2"
        assert data["product_id_validation"]["status"] == "PASS"
        assert data["product_id_validation"]["id_mismatches"] == 0
        assert data["numeric_validation"]["price_violations"] == 0
        assert data["numeric_validation"]["rating_violations"] == 0
        assert data["specification_validation"]["invalid_specs"] == 0

    def test_readiness_validator_synthetic_fixture(self):
        df_fixture = pd.DataFrame(
            [
                {
                    "product_id": "id1",
                    "uniq_id": "id1",
                    "product_name": "Item 1",
                    "category": "Footwear",
                    "discounted_price": 500.0,
                    "rating": 4.5,
                    "product_specifications": json.dumps([{"key": "Color", "value": "Red"}]),
                },
                {
                    "product_id": "id2",
                    "uniq_id": "id2",
                    "product_name": "Item 2",
                    "category": "Footwear",
                    "discounted_price": 1000.0,
                    "rating": None,
                    "product_specifications": "[]",
                },
            ]
        )
        report = validate_cleaned_dataset_readiness(df_fixture, selected_categories=["Footwear"])
        assert report["rows_checked"] == 2
        assert report["overall_status"] == "READY_FOR_PHASE_5_2"
        assert report["specification_validation"]["valid_specs_arrays"] == 1
        assert report["specification_validation"]["empty_specs_arrays"] == 1
