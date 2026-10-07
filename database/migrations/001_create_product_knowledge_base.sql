-- =============================================================================
-- Migration: 001_create_product_knowledge_base.sql
-- Description: Create products table with pgvector support, constraints,
--              automatic updated_at trigger, and approved B-Tree / HNSW indexes.
-- Target Database: Supabase Cloud PostgreSQL + pgvector (Production)
--                  Local PostgreSQL + pgvector (Development / CI Testing)
-- Project: ShopAssist V1
-- =============================================================================

-- Step 1: Enable the pgvector extension if not already enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- Step 2: Create products table
CREATE TABLE IF NOT EXISTS products (
    -- Primary identifier (mapped 1:1 from Flipkart uniq_id)
    product_id              VARCHAR(64) PRIMARY KEY,

    -- Core descriptive and classification attributes
    product_name            TEXT NOT NULL CHECK (length(trim(product_name)) > 0),
    category                VARCHAR(128) NOT NULL CHECK (length(trim(category)) > 0),
    brand                   VARCHAR(128),

    -- Pricing and operational constraints
    retail_price            NUMERIC(10, 2) CHECK (retail_price IS NULL OR retail_price > 0),
    discounted_price        NUMERIC(10, 2) NOT NULL CHECK (discounted_price > 0),
    rating                  NUMERIC(3, 2) CHECK (rating IS NULL OR (rating >= 1.0 AND rating <= 5.0)),

    -- Rich textual content and structured specifications
    description             TEXT,
    product_specifications  JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Presentation and external reference attributes
    product_url             TEXT,
    image                   TEXT,
    pid                     VARCHAR(64),

    -- Retrieval representations and vector embeddings
    retrieval_text          TEXT NOT NULL CHECK (length(trim(retrieval_text)) > 0),
    embedding               vector(384) NOT NULL,
    embedding_model         VARCHAR(64) NOT NULL DEFAULT 'BAAI/bge-small-en-v1.5',

    -- Operational timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Step 3: Hard-constraint relational indexes (B-Tree)
CREATE INDEX IF NOT EXISTS idx_products_category
ON products (category);

CREATE INDEX IF NOT EXISTS idx_products_price
ON products (discounted_price);

CREATE INDEX IF NOT EXISTS idx_products_brand
ON products (brand);

-- Step 4: Composite index for primary hybrid query pattern (category + budget filtering)
CREATE INDEX IF NOT EXISTS idx_products_category_price
ON products (category, discounted_price);

-- Step 5: HNSW vector index for high-recall cosine similarity search
CREATE INDEX IF NOT EXISTS idx_products_embedding
ON products
USING hnsw (embedding vector_cosine_ops)
WITH (
    m = 16,
    ef_construction = 64
);

-- Step 6: Automatic updated_at trigger
CREATE OR REPLACE FUNCTION update_products_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_products_updated_at ON products;
CREATE TRIGGER trg_products_updated_at
BEFORE UPDATE ON products
FOR EACH ROW
EXECUTE FUNCTION update_products_updated_at();
