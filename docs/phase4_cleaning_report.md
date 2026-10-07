# Phase 4 — Dataset Cleaning Report

## Executive Summary

- **Input Dataset:** `data/interim/selected_category_candidates.parquet` (8,683 rows, 16 columns).
- **Output Cleaned Dataset:** `data/interim/cleaned_candidates.parquet` (8,405 rows, 15 columns).
- **Total Removed Records:** 278 (3.2%), consisting of 36 missing/unusable price records and 242 redundant duplicates.
- **Data Retention:** 8,405 / 8,683 (96.80% retained, well above the 85% minimum threshold).
- **Lineage & Primary Key:** 100% unique `product_id` mapped directly from `uniq_id` without synthetic regeneration.

---

## 1. Input Dataset

The candidate dataset produced at the end of Phase 3 contained **8,683** product records spanning the 16 selected product categories.
All original 15 raw columns plus `_level1_category` were preserved with raw integrity until Phase 4 cleaning.

| Metric | Input Candidate Dataset |
| :--- | :--- |
| Total Records | 8,683 |
| Total Columns | 16 |
| Unique `uniq_id` | 8,683 (100.0%) |
| Unique `pid` | 8,682 |
| Missing Prices (`retail_price` & `discounted_price`) | 36 (0.41%) |
| Missing Descriptions | 1 (0.01%) |
| Missing Brands | 2,018 (23.2%) |
| 'No rating available' Ratings | 7,782 (89.6%) |

---

## 2. Cleaning Rules & Principles

1. **Lineage Preservation:** Technical keys (`uniq_id`, `pid`, `product_url`, `image`, `crawl_timestamp`, `is_FK_Advantage_product`) are retained. Logical identifier is defined as `product_id = uniq_id`.
2. **Operational Budget Constraint:** Because conversational product recommendation requires strict budget filtering, records without usable `discounted_price` (`price > 0`) are excluded.
3. **Safe Specification Parsing:** Ruby hash specifications are parsed deterministically via regular expression tokenization without `eval()`, preventing code execution vulnerabilities and serializing cleanly to JSON.
4. **Brand Canonicalization:** Brands are whitespace-collapsed and casing inconsistencies are mapped to canonical forms derived from dataset frequency, while missing brands remain `null` without dropping rows.
5. **Rating Normalization:** Numeric ratings are converted to float within `[1.0, 5.0]`, while `'No rating available'` is normalized to `null`.
6. **Conservative Deduplication:** Redundant duplicates within identical `(name, brand, category, discounted_price)` clusters are merged **only** when specifications do not conflict, strictly preserving valid product variants (different colors, sizes, models, compatibility).
7. **No Over-Cleaning:** No stemming, lemmatization, stopword removal, or lowercasing of product descriptions or names. Crucial technical parameters (screen sizes, RAM, dimensions, materials) are preserved intact.

---

## 3. Invalid Record Removal

- **Missing Primary Key (`uniq_id`):** 0 records.
- **Missing / Blank Product Name:** 0 records.
- **Missing / Invalid Category:** 0 records.
- **Missing / Non-positive Price:** 36 records.
  - All 36 dropped price records were missing both `retail_price` and `discounted_price` (NaN).
  - There were zero records with `discounted_price <= 0` or negative values.
- **Unexpected Category Filtering:** 0 records.

---

## 4. Deduplication & Variant Preservation

A multi-layered conservative deduplication was applied to prevent duplicate listings without destroying valid product variants:

- **Total Clusters Inspected:** 6,947
- **Multi-item Duplicate Clusters:** 503
- **Redundant Duplicates Dropped:** 242 (2.8%)
- **Product Variants Preserved:** 1,913

### Variant Preservation Evidence

Products sharing identical title, brand, category, and price were analyzed for specification conflicts:
- **Color Variants:** e.g., `3A Autocare Car Mat Hyundai Grand i10` (Beige vs Black) and `A Click Away Women Heels` (Beige vs Gold vs Silver) were recognized as distinct variants and preserved.
- **Size / Compatibility Variants:** e.g., Footwear shoe sizes and Mobile phone cases compatible with distinct phone models were preserved.
- **True Duplicates Removed:** Exactly identical wall sticker listings (e.g., 21 redundant entries of `999store Medium Paper Sticker` sharing the identical price of Rs. 599 and identical dimensions/specs) were deduplicated, retaining the single most complete listing.

---

## 5. Price Cleaning

| Attribute | Before Cleaning | After Cleaning |
| :--- | :--- | :--- |
| Records with Valid `discounted_price` | 8,647 (99.59%) | 8,405 (100.0%) |
| Records with Missing Price | 36 (0.41%) | 0 (0.0%) |
| Minimum `discounted_price` | 35.0 INR | 35.0 INR |
| Maximum `discounted_price` | 250,000.0 INR | 250,000.0 INR |
| Median `discounted_price` | 749.0 INR | 750.0 INR |

> [!NOTE]
> High-end luxury/electronics items (e.g. enterprise servers or premium luxury watches up to 250,000 INR) were verified as valid listings and retained without artificial percentile capping.

---

## 6. Rating Normalization

- Raw rating columns (`product_rating` and `overall_rating`) contained `'No rating available'` for **89.6%** of candidate products.
- Numeric ratings were parsed into float values bounded between 1.0 and 5.0.
- **Normalized Numeric Ratings:** 894 (10.64%).
- **Null Ratings:** 7,511 (89.36%).
- **Conclusion:** Rating is designated as an **optional ranking / filtering signal** and will not be used as a hard constraint.

---

## 7. Brand Normalization

- **Valid Normalized Brands:** 6,417 (76.35%).
- **Missing Brands:** 1,988 (23.65%) mapped safely to `null`.
- **Canonical Casing Inconsistencies Fixed:** 63 brand variants (e.g. `D-LINK` -> `D-Link`, `shopmania` -> `SHOPMANIA`, `asian` -> `Asian`).
- **Integrity:** Brand queries in downstream retrieval will use `brand IS NULL` safe handling.

---

## 8. Category Normalization

All candidate records were mapped from `_level1_category` to `category`. Every record strictly belongs to the 16 official Phase 3 selected categories.

### Category Retention Breakdown

| Category | Before Cleaning | After Cleaning | Removed Records | Loss % | Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Footwear | 1,227 | 1,179 | 48 | 3.91% | Normal |
| Mobiles & Accessories | 1,099 | 1,097 | 2 | 0.18% | Normal |
| Automotive | 1,012 | 1,010 | 2 | 0.2% | Normal |
| Home Decor & Festive Needs | 929 | 866 | 63 | 6.78% | Normal |
| Home Furnishing | 700 | 689 | 11 | 1.57% | Normal |
| Kitchen & Dining | 647 | 643 | 4 | 0.62% | Normal |
| Computers | 578 | 573 | 5 | 0.87% | Normal |
| Watches | 530 | 528 | 2 | 0.38% | Normal |
| Baby Care | 483 | 360 | 123 | 25.47% | **WARNING (>20%)** |
| Tools & Hardware | 391 | 387 | 4 | 1.02% | Normal |
| Pens & Stationery | 313 | 313 | 0 | 0.0% | Normal |
| Bags, Wallets & Belts | 265 | 263 | 2 | 0.75% | Normal |
| Furniture | 180 | 180 | 0 | 0.0% | Normal |
| Sports & Fitness | 166 | 166 | 0 | 0.0% | Normal |
| Cameras & Accessories | 82 | 72 | 10 | 12.2% | Normal |
| Home Improvement | 81 | 79 | 2 | 2.47% | Normal |

> [!WARNING]
> **Baby Care Category Loss Notice:**
> `Baby Care` experienced a 25.47% reduction (from 483 to 360 records). Investigation confirmed this was solely due to the removal of massive redundant duplicate wall sticker batches (e.g. 21 identical copies of `999store Medium Paper Sticker` and multiple redundant batches of `WallDesign` / `Wallmantra` stickers). No valid distinct products or variants were lost.

---

## 9. Description Cleaning

- Decoded HTML entities (`&amp;`, `&quot;`, `&#39;`).
- Stripped dangling HTML tags (`<br>`, `<p>`) and uncollapsed whitespaces.
- Removed invisible ASCII control characters.
- **Valid Description Coverage:** 99.99% (only 1 product lacked description, which had complete specifications).
- Crucial product details (dimensions, materials, warranty terms, model numbers) were preserved intact.

---

## 10. Specification Parsing

- **Parsing Method:** Safe deterministic regex tokenization (`_SPEC_KV_RE`), strictly avoiding `eval()`.
- **Parsed Successfully:** 8,628 records.
- **Empty / Nil Specifications:** 19 records (serialized as `[]`).
- **Output Representation:** Serialized JSON array of key-value pairs (`[{"key": "...", "value": "..."}]`) guaranteeing compatibility with PostgreSQL JSONB and Phase 5 retrieval builder.

---

## 11. Output Dataset Quality

The cleaned dataset in `data/interim/cleaned_candidates.parquet` contains **15 columns** structured into core product attributes and auxiliary lineage metadata:

### Core Product Schema
- `product_id` (str, primary key, unique)
- `product_name` (str, non-empty, cleaned)
- `category` (str, 16 official selected categories)
- `brand` (str | null, canonical casing)
- `retail_price` (float | null)
- `discounted_price` (float, strictly positive, operational price)
- `rating` (float | null, 1.0 to 5.0)
- `description` (str | null, cleaned freeform text)
- `product_specifications` (str, JSON-serialized list of key-value dicts)
- `product_url` (str, Flipkart product link)

### Auxiliary Lineage Metadata
- `uniq_id` (str, raw technical identifier)
- `pid` (str, Flipkart product ID)
- `image` (str, image URL array string)
- `crawl_timestamp` (str, raw crawl timestamp)
- `is_FK_Advantage_product` (bool, raw advantage flag)

### Quality Assertions Verification
- [x] `product_id` is 100% unique (0 duplicate IDs).
- [x] `product_name` is non-empty across all records.
- [x] `category` strictly matches the 16 official selected categories.
- [x] `discounted_price` is numeric and > 0 for 100% of records.
- [x] `rating` is either `null` or within [1.0, 5.0].
- [x] `brand` is normalized or `null`.
- [x] Exact duplicate rows = 0.
- [x] No `eval()` was used for parsing specifications.
- [x] Overall data loss is 3.20%, far below the 15% maximum threshold.

---

## 12. Before vs After Comparison

| Metric | Before Cleaning | After Cleaning | Change |
| :--- | :---: | :---: | :---: |
| Total Records | 8,683 | 8,405 | -278 (-3.2%) |
| Exact Duplicate Rows | 0 | 0 | 0 |
| Identical (Name, Brand, Cat, Price) Duplicates | 1,702 | 1,458 | -244 |
| Price Coverage | 99.59% | 100.0% | +0.41% |
| Brand Coverage | 76.76% | 76.35% | -0.41% |
| Numeric Rating Coverage | 10.38% | 10.64% | +0.26% |
| Description Coverage | 99.99% | 99.99% | 0.0% |
| Specification Coverage | 99.78% | 99.79% | +0.01% |

---

## 13. Risks / Remaining Issues

1. **Missing Brand Coverage (23.65%):** Nearly a quarter of products do not have an explicit brand. Retrieval pipelines must ensure hard brand filters gracefully handle `brand IS NULL` without accidentally excluding relevant generic items.
2. **Sparse Rating Signals (89.36% null):** Rating cannot be used as a hard filter constraint. It should only be incorporated as an optional lightweight score booster during hybrid reranking.
3. **Category Imbalance in Variants:** Categories like `Baby Care` and `Footwear` naturally carry more repetitive variant listings than `Furniture` or `Computers`. Downstream recommendation should diversify results to avoid showing multiple identical variants of the same product line in the top 5.

---

## 14. Input for Phase 5

The cleaned candidate dataset is fully prepared for **Phase 5 — Product Knowledge Base Construction**:
1. `product_specifications` can be unmarshaled with `json.loads` to extract structured technical attributes for text enrichment.
2. `discounted_price` and `brand` are ready for SQL schema typing (`NUMERIC(10,2)` and `VARCHAR(255)`).
3. Cleaned textual fields (`product_name`, `description`, `product_specifications`, `brand`, `category`) provide clean tokens for building composite `retrieval_text` and sparse TF-IDF indices in Phase 5.
