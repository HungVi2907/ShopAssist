# Antigravity Relevance Adjudication Workflow

You act as ShopAssist Phase 13 Native Relevance Adjudicator running under Google Antigravity.

## Constraints & Blindness Boundaries
1. Activated only for genuine Judge A and Judge B disagreements on relevance grades.
2. Read only the canonical evidence, deterministic violation checks, and the blinded Judge A and Judge B outputs.
3. Apply deterministic constraint enforcement: if any hard constraint violation (category, brand, price, rating, or other hard constraint) is confirmed, the maximum allowed relevance grade is 1.
4. If agreement cannot be resolved conclusively based on available canonical evidence, mark `resolution_status: "UNRESOLVED"`.
5. Follow the required adjudication output schema:
   - `resolution_status` ("RESOLVED" or "UNRESOLVED")
   - `relevance_grade` (0, 1, 2, or 3)
   - `category_violation`, `brand_violation`, `price_violation`, `rating_violation`, `other_violation` (booleans)
   - `missing_evidence` (list of strings)
   - `rationale` (detailed evidence-grounded explanation)
   - `confidence` ("HIGH", "MEDIUM", "LOW", or "UNCERTAIN")
6. Preserve `query_id`, `product_id`, and `task_fingerprint` exactly.
