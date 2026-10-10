# ShopAssist Query Understanding Data Contract (Phase 8)

<!-- phase82-correction-start -->
> **Phase8.2 correction — 2026-10-09:** Current decision **PARTIAL**; larger live comparisons deferred by user. Production remains original **v1**, not E5-B/v2. The historical body below is preserved; conflicting claims are superseded by [current engineering decision](phase8_2/final_engineering_report.md), [audited results](phase8_2/experimental_results.md) and [contract review](phase8_2/query_contract_review.md).
>
> Original50 98% EM omits preferences; shared-field EM is54%. Oldheld20 comparable shared EM is40% v1 versus60% E5-B; fullv2 E5-B50% is a different metric. Semantic-query/reason wording is not covered by slot EM. E5-B soft macro78.33%, product/exclusion exact90%, exclusion micro28.57%. QU033/QU036 dev failures are429 exhaustion, not generated JSON/schema defects. New failure-aware dev E5-B HC F1 is93.88%, soft F1 is80%; historical96%/86.67% use the frozen old policy.
>
> Development overlaps original50 in13/15 queries. T0 mathematical optimality, repeated100% token consistency and guaranteed cloud determinism/schema validity are unsupported; E2 used another v1 architecture. Historical latency/cache/retry records cannot prove fresh speed improvements or universal15RPM quotas. Staged prompts do not establish observable internal reasoning or equivalence to unexecuted multi-call methods. Boeing suppression is filter policy, not necessarily correct NER. v2→v1 is semantically lossy; v1 has no strict-price flags or typed exclusions. Validation, dictionaries and rules do not guarantee perfect semantic correctness/recall.
>
> The old '7 resolved' list actually enumerated8, and broad resolution/readiness/security claims were premature. Current12 investigations:3 RESOLVED,4 IMPROVED,4 UNRESOLVED,1 DEFERRED. Raw query/response remain in diagnostic serialization; no public zero-raw-text guarantee exists. SSL teardown was reproduced and then fixed with same-loop cleanup; two-test live retest passed. Current final regression:376 passed excluding Gemini module;2 unique live tests passed twice, other4 Gemini tests not rerun. No new live quality winner or production semantic change is claimed.
<!-- phase82-correction-end -->

> **Document Version:** 1.0.0  
> **Schema Stability:** Stable  
> **Target Audience:** Core AI Engineers, Backend Engineers, and Downstream Retrieval Pipeline Developers (Phases 9, 10, 11, 12).

---

## Table of Contents

- [1. Contract Purpose](#1-contract-purpose)
- [2. Canonical Pydantic Schema](#2-canonical-pydantic-schema)
- [3. Field Definitions & Type Specifications](#3-field-definitions--type-specifications)
- [4. Null & Missing-Value Semantics](#4-null--missing-value-semantics)
- [5. Category Enumeration & Normalization](#5-category-enumeration--normalization)
- [6. Brand Extraction & Catalog Matching](#6-brand-extraction--catalog-matching)
- [7. Numeric Constraint & Boundary Semantics](#7-numeric-constraint--boundary-semantics)
- [8. Currency Conventions & Foreign Currency Handling](#8-currency-conventions--foreign-currency-handling)
- [9. Soft Preference Representation](#9-soft-preference-representation)
- [10. Cleaned Semantic Query Semantics](#10-cleaned-semantic-query-semantics)
- [11. Ambiguity & Clarification Protocols](#11-ambiguity--clarification-protocols)
- [12. Unsupported Domains & Out-of-Catalog Requests](#12-unsupported-domains--out-of-catalog-requests)
- [13. Error Response Contract](#13-error-response-contract)
- [14. Representative Valid Output Examples](#14-representative-valid-output-examples)
- [15. Representative Invalid Inputs & Rejection Modes](#15-representative-invalid-inputs--rejection-modes)
- [16. Phase 9 Integration Interface](#16-phase-9-integration-interface)
- [17. Phase 10 Hybrid Retrieval Interface](#17-phase-10-hybrid-retrieval-interface)
- [18. Schema Evolution & Versioning Policy](#18-schema-evolution--versioning-policy)

---

## 1. Contract Purpose

This data contract formally establishes the structured output format, typing, invariants, and validation semantics produced by the **Phase 8 Query Understanding Engine**.

Downstream consumer components (Phase 9 Soft Preference Representation, Phase 10 Hybrid Retrieval, Phase 11 Reranking, and Phase 12 Recommendation Generation) depend strictly on the guarantees set forth in this contract.

Phase 8 guarantees:
1. **Zero Raw Text Bleed:** Free-form user input is parsed into typed, validated, and normalized attributes.
2. **Schema Invariance:** Every query evaluated returns a valid, non-null `QueryUnderstandingResult` containing a `QueryUnderstandingOutput`.
3. **No Hallucinated Constraints:** Unstated criteria are returned strictly as `None`/`null`.
4. **Relational Compatibility:** Extracted hard constraints align directly with database column types and values in `public.products`.

---

## 2. Canonical Pydantic Schema

The core contract is implemented using Pydantic v2 in [`src/shopassist/llm/schemas.py`](file:///d:/Project/ShopAssist/src/shopassist/llm/schemas.py):

```python
class HardConstraints(BaseModel):
    """Hard constraints that candidate products must strictly satisfy."""
    category: str | None = Field(default=None, description="One of 16 approved canonical catalog categories, or null.")
    brand: str | None = Field(default=None, description="Explicit brand name extracted from query, or null.")
    min_price: float | None = Field(default=None, description="Minimum price bound (>= 0).")
    max_price: float | None = Field(default=None, description="Maximum price bound (>= min_price).")
    min_rating: float | None = Field(default=None, description="Minimum rating threshold (1.0 to 5.0).")
    currency: str | None = Field(default="INR", description="Standardized ISO currency code (default: 'INR').")


class QueryUnderstandingOutput(BaseModel):
    """Structured representation of user shopping intent extracted by LLM."""
    semantic_query: str = Field(description="Cleaned, noise-free product search query.")
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    soft_preferences: list[str] = Field(default_factory=list, description="Qualitative, lifestyle, or aesthetic desires.")
    needs_clarification: bool = Field(default=False, description="Flag indicating if query is ambiguous or incompatible.")
    clarification_reason: str | None = Field(default=None, description="Explanation when clarification is required.")


class QueryUnderstandingResult(BaseModel):
    """End-to-end execution container with diagnostic and telemetry metadata."""
    query: str
    output: QueryUnderstandingOutput
    raw_response_text: str = ""
    model: str = ""
    latency_ms: float = 0.0
    token_usage: TokenUsageMetadata | None = None
    is_valid: bool = True
    validation_errors: list[str] = Field(default_factory=list)
```

---

## 3. Field Definitions & Type Specifications

| Field Path | Type | Nullable | Default | Description & Bounds |
| :--- | :--- | :--- | :--- | :--- |
| `output.semantic_query` | `string` | No | Required | 1 to 500 chars. Preserves product noun & core descriptors. Filler words removed. |
| `output.hard_constraints.category` | `string` | Yes | `null` | Must exactly match one of the 16 canonical categories, or be `null`. |
| `output.hard_constraints.brand` | `string` | Yes | `null` | Brand name. If matched in catalog, normalized to catalog casing; otherwise preserved. |
| `output.hard_constraints.min_price` | `float` | Yes | `null` | Lower price limit in `currency`. Invariant: $\ge 0.0$. |
| `output.hard_constraints.max_price` | `float` | Yes | `null` | Upper price limit in `currency`. Invariant: $\ge \text{min\_price}$. |
| `output.hard_constraints.min_rating`| `float` | Yes | `null` | Minimum customer rating. Invariant: $1.0 \le \text{min\_rating} \le 5.0$. |
| `output.hard_constraints.currency` | `string` | Yes | `"INR"` | Standardized ISO-4217 code (`INR`, `USD`, `EUR`, `GBP`). |
| `output.soft_preferences` | `list[str]`| No | `[]` | List of lowercased, deduplicated strings (max 10 items). |
| `output.needs_clarification` | `bool` | No | `False` | True if request is ambiguous, out-of-domain, or specifies non-INR currency. |
| `output.clarification_reason` | `string` | Yes | `null` | Human-readable explanation when `needs_clarification=True`. |

---

## 4. Null & Missing-Value Semantics

A central tenet of the ShopAssist architecture is **Zero Hallucinated Restrictions**:
- If the user does not state a budget, `min_price` and `max_price` **MUST** be `null`.
- If the user does not state a brand, `brand` **MUST** be `null`.
- If the user does not request a minimum rating, `min_rating` **MUST** be `null`.
- If the user does not mention a product type or category, `category` **MUST** be `null`.

Downstream retrieval interprets `null` as **unconstrained**:
$$\text{Filter}(f, v) = \begin{cases} \text{ApplySQLFilter}(f, v) & \text{if } v \ne \text{null} \\ \text{NoOp} & \text{if } v = \text{null} \end{cases}$$

---

## 5. Category Enumeration & Normalization

ShopAssist operates over a closed catalog of **exactly 16 approved canonical categories**:

1. `Automotive`
2. `Baby Care`
3. `Bags, Wallets & Belts`
4. `Cameras & Accessories`
5. `Computers`
6. `Footwear`
7. `Furniture`
8. `Home Decor & Festive Needs`
9. `Home Furnishing`
10. `Home Improvement`
11. `Kitchen & Dining`
12. `Mobiles & Accessories`
13. `Pens & Stationery`
14. `Sports & Fitness`
15. `Tools & Hardware`
16. `Watches`

### Category Mapping Rules
- Direct matches and case-insensitive variations are normalized to the exact canonical string.
- Sub-categories and keyword synonyms are deterministically mapped:
  - `laptop`, `desktop`, `keyboard`, `monitor`, `printer` $\to$ `Computers`
  - `sneakers`, `running shoes`, `boots`, `sandals`, `loafers` $\to$ `Footwear`
  - `smartphone`, `cellphone`, `charger`, `power bank`, `earbuds`, `headphones` $\to$ `Mobiles & Accessories`
  - `smartwatch`, `wristwatch`, `analog watch`, `chronograph` $\to$ `Watches`
  - `stroller`, `diaper`, `baby blanket`, `crib`, `pacifier` $\to$ `Baby Care`
  - `sofa`, `office chair`, `dining table`, `wardrobe`, `bed` $\to$ `Furniture`
  - `drill`, `screwdriver`, `hammer`, `pliers`, `wrench` $\to$ `Tools & Hardware`
- Queries outside these 16 domains (e.g. `"fresh bananas"`, `"commercial airplane"`, `"real estate"`) produce `category = null` and set `needs_clarification = True`.

---

## 6. Brand Extraction & Catalog Matching

1. **Extraction:** Brands are extracted only when explicitly requested (e.g., `"Puma"`, `"Nike"`, `"Samsung"`, `"Dell"`, `"Casio"`).
2. **Catalog Validation:**
   - The engine checks extracted brand against the 8,405-product catalog brand dictionary.
   - If matched, the brand is normalized to canonical catalog casing (e.g. `"puma"` $\to$ `"Puma"`).
3. **Unmatched Brands:**
   - If the user explicitly asks for a brand not currently present in the catalog (e.g. `"Under Armour"`), the brand is **preserved** rather than replaced.
   - Downstream retrieval handles 0-result catalog matches gracefully rather than silently altering user intent.

---

## 7. Numeric Constraint & Boundary Semantics

### Price Boundaries
- **Upper Bound:** Phrases such as `"under 2000"`, `"below 1500"`, `"less than 1000"`, or `"max 3000"` set `max_price`.
- **Lower Bound:** Phrases such as `"above 500"`, `"at least 1000"`, or `"minimum 2500"` set `min_price`.
- **Range:** Phrases such as `"between 1000 and 3000"` or `"from 500 to 1500"` set both `min_price` and `max_price`.
- **Boundary Semantics:** All boundaries are evaluated as **inclusive** $(\le, \ge)$ in SQL execution:
  ```sql
  discounted_price >= min_price AND discounted_price <= max_price
  ```

### In-Query Corrections
When a user corrects themselves in a single sentence (e.g., `"shoes under 1000, actually make it under 1500"`), the engine extracts the final corrected value (`max_price = 1500.0`).

### Qualitative Budget Adjectives
Vague words like `"cheap"`, `"affordable"`, `"budget"`, or `"luxury"` **MUST NOT** generate numeric prices. They are placed in `soft_preferences: ["affordable"]`.

---

## 8. Currency Conventions & Foreign Currency Handling

- **Catalog Standard:** The ShopAssist catalog is exclusively priced in Indian Rupees (`INR`).
- **Default Behavior:** Unspecified currencies, `"rupees"`, `"rs"`, and `"₹"` are normalized to `"INR"`.
- **Foreign Currencies:**
  - If a user explicitly specifies a foreign currency (`"USD"`, `"$"`, `"EUR"`, `"GBP"`), the currency is accurately captured in `hard_constraints.currency`.
  - The engine sets `needs_clarification = True` with an explanatory reason:
    `"Query specifies currency 'USD'. Catalog prices are exclusively in INR. Currency conversion or clarification required."`
  - This prevents applying a 500 USD filter directly against INR database values (which would wrongly return products under 500 rupees!).

---

## 9. Soft Preference Representation

Soft preferences capture subjective, stylistic, or environmental desires:
- Format: Lowercased, stripped, deduplicated strings.
- Count: Maximum 10 items.
- Examples: `["comfortable", "lightweight", "good battery life", "for programming", "wooden finish"]`.
- Purpose: Forwarded to Phase 9 (Embedding generation) and Phase 11 (Cross-encoder reranking).

---

## 10. Cleaned Semantic Query Semantics

The `semantic_query` field provides the cleaned lexical/semantic search string:
- Removes conversational filler: `"I am looking for"`, `"Please show me"`, `"Do you have"`.
- Removes hard constraint tokens: Removes raw numbers and price strings (`"under 2000 rupees"`).
- Preserves the target product noun and essential descriptors: `"Puma running shoes"`.
- Forwarded to Phase 6 (TF-IDF) and Phase 7 (Dense Vector Search).

---

## 11. Ambiguity & Clarification Protocols

`needs_clarification` is set to `True` under three specific conditions:
1. **Severe Ambiguity:** Query lacks product intent (e.g. `"show me something interesting"`, `"help me buy stuff"`).
2. **Foreign Currency:** Query specifies non-INR currency (`USD`, `EUR`, etc.).
3. **Out-of-Domain Requests:** Query asks for items not sold in the 16 approved categories (e.g. `"commercial Boeing 747 airplane"`).

When `needs_clarification=True`, downstream components must present `clarification_reason` to the user instead of executing empty or misleading searches.

---

## 12. Unsupported Domains & Out-of-Catalog Requests

If a request is completely outside the e-commerce catalog:
- `hard_constraints.category` = `null`
- `hard_constraints.brand` = `null`
- `needs_clarification` = `True`
- `clarification_reason` = `"Out of domain request or unsupported product category."`

---

## 13. Error Response Contract

If an unrecoverable failure occurs (e.g. complete network outage or malformed input):
- `is_valid` = `False`
- `output.needs_clarification` = `True`
- `output.clarification_reason` = `"Processing failure: <Error details>"`
- `validation_errors` = `["<Detailed diagnostic message>"]`
- No unhandled exceptions are allowed to escape to web consumers.

---

## 14. Representative Valid Output Examples

### Example 1: Multi-Constraint Query
**Input:** `"Puma running shoes under 2000 rupees"`
```json
{
  "semantic_query": "Puma running shoes",
  "hard_constraints": {
    "category": "Footwear",
    "brand": "Puma",
    "min_price": null,
    "max_price": 2000.0,
    "min_rating": null,
    "currency": "INR"
  },
  "soft_preferences": [
    "running"
  ],
  "needs_clarification": false,
  "clarification_reason": null
}
```

### Example 2: Qualitative + Rating Query
**Input:** `"comfortable Nike sneakers under 3500 rs with at least 4 star rating"`
```json
{
  "semantic_query": "Nike sneakers",
  "hard_constraints": {
    "category": "Footwear",
    "brand": "Nike",
    "min_price": null,
    "max_price": 3500.0,
    "min_rating": 4.0,
    "currency": "INR"
  },
  "soft_preferences": [
    "comfortable"
  ],
  "needs_clarification": false,
  "clarification_reason": null
}
```

### Example 3: Foreign Currency Query
**Input:** `"laptop under 500 dollars"`
```json
{
  "semantic_query": "laptop",
  "hard_constraints": {
    "category": "Computers",
    "brand": null,
    "min_price": null,
    "max_price": 500.0,
    "min_rating": null,
    "currency": "USD"
  },
  "soft_preferences": [],
  "needs_clarification": true,
  "clarification_reason": "Query specifies currency 'USD'. Catalog prices are exclusively in INR. Currency conversion or clarification required."
}
```

---

## 15. Representative Invalid Inputs & Rejection Modes

1. **Non-String Input:** Passing `12345` or `None` $\to$ raises `TypeError: Query must be a string`.
2. **Empty Input:** Passing `""` or `"   "` $\to$ raises `ValueError: Query cannot be empty or whitespace-only`.
3. **Excessive Length:** Passing $> 500$ characters $\to$ raises `ValueError: Query length exceeds maximum allowed limit of 500 chars`.

---

## 16. Phase 9 Integration Interface

Phase 9 (Soft Preference Representation) consumes:
- `output.soft_preferences: list[str]`
- `output.semantic_query: str`

Contract: Phase 9 generates dense vector representations of `soft_preferences` to complement the catalog product vectors.

---

## 17. Phase 10 Hybrid Retrieval Interface

Phase 10 (Hybrid Retrieval) consumes:
- `output.hard_constraints: HardConstraints`
- `output.semantic_query: str`

Contract: Phase 10 constructs the SQL filter clause (with strict/inclusive boundary operator support):
```sql
SELECT product_id, product_name, discounted_price, rating,
       1 - (embedding <=> :query_vector) AS cosine_similarity
FROM public.products
WHERE (:category IS NULL OR category = :category)
  AND (:brand IS NULL OR brand = :brand)
  -- Boundary semantics: strict (<, >) vs inclusive (<=, >=)
  AND (:min_price IS NULL OR 
       (CASE WHEN :min_inclusive = TRUE THEN discounted_price >= :min_price 
             ELSE discounted_price > :min_price END))
  AND (:max_price IS NULL OR 
       (CASE WHEN :max_inclusive = TRUE THEN discounted_price <= :max_price 
             ELSE discounted_price < :max_price END))
  AND (:min_rating IS NULL OR rating >= :min_rating)
ORDER BY embedding <=> :query_vector ASC
LIMIT :top_k;
```

---

## 18. Schema Evolution & Versioning Policy

- **Historical Version:** `1.0.0` (Implemented in Phase 8)
- **Refined Version:** `2.0.0` (Evaluated and proven in Phase 8.1)
  - `product_type: str | None`: Explicit representation of the target product noun phrase, resolving confusion with soft preferences.
  - `exclusions: list[ExclusionConstraint]`: Explicit representation of negative constraints (`target_type`, `value`), preventing unintended promotion of excluded items.
  - `min_inclusive: bool`, `max_inclusive: bool`: Explicit boundary operators preserving strict inequalities (`<` vs `<=`).
- **Backward Compatibility:** Schema v2.0.0 models provide `to_v1()` converters ensuring existing Phase 8 consumers continue functioning without breaking changes.
- **Breaking Changes Policy:** Any removal of existing fields or changes to canonical category identifiers triggers a major version bump (`3.0.0`).
