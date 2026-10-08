-- =============================================================================
-- Migration: 002_create_product_indexes.sql
-- Description: Create relational B-Tree and HNSW vector indexes for products table.
-- Phase: Deferred to Phase 5.7 (Index Construction) per ShopAssist Development Plan.
-- Target Database: Supabase Cloud PostgreSQL + pgvector (Production)
-- Project: ShopAssist V1
-- =============================================================================

-- Step 1: Hard-constraint relational indexes (B-Tree)
CREATE INDEX IF NOT EXISTS idx_products_category
ON products (category);

CREATE INDEX IF NOT EXISTS idx_products_price
ON products (discounted_price);

CREATE INDEX IF NOT EXISTS idx_products_brand
ON products (brand);

-- Step 2: Composite index for primary hybrid query pattern (category + budget filtering)
CREATE INDEX IF NOT EXISTS idx_products_category_price
ON products (category, discounted_price);

-- Step 3: HNSW vector index for high-recall cosine similarity search
CREATE INDEX IF NOT EXISTS idx_products_embedding
ON products
USING hnsw (embedding vector_cosine_ops)
WITH (
    m = 16,
    ef_construction = 64
);
