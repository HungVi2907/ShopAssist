# ShopAssist Phase 13 — Full AI-Silver Evaluation Benchmark Report

**Dataset Version:** `v4_full_silver`  
**Dataset Path:** `data/evaluation/phase13/ai_silver/v4_full_silver/`  
**Generated Date:** 2026-10-14  
**Annotation Methodology:** Native AI Multi-Judge (`CODEX_NATIVE_MULTI_JUDGE`)  
**Label Quality:** `SILVER`  
**Human Verified:** `false`  
**Official Readiness:**
- `query_silver_complete`: `true`
- `retrieval_silver_complete`: `true`
- `generation_silver_complete`: `false` (Blocked by missing authentic Phase 12 interactions)
- `split_frozen`: `true`
- `human_calibration_status`: `PENDING`
- `silver_benchmark_complete`: `false` (Generation component requirement unfulfilled)
- `phase14_ready`: `false` (Independent human Ground Truth required for Phase 14)

---

## 1. Executive Summary

Phase 13 establishes the reproducible, scientifically defensible **AI-Silver Evaluation Benchmark** for the ShopAssist AI-powered product recommendation system.

Operating strictly within native AI agent sessions (without external paid API keys or programmatic SDK inference), the evaluation pipeline completed comprehensive query understanding audits, multi-method candidate retrieval pooling, dual-agent relevance judging, disagreement adjudication, stratified human calibration export, and leakage-free development/held-out partitioning across all 200 evaluation queries.

### Key Milestones & Metrics

| Component | Metric / Value |
|---|---|
| **Evaluation Queries** | 200 total (160 `SUCCESS`, 21 `UNSUPPORTED_INTENT`, 18 catalog-verified `NO_RESULTS`, 1 `CLARIFICATION_REQUIRED`) |
| **Query Audits** | 200 completed by Judge A and Judge B; 200 adjudicated; **0 unresolved** |
| **Retrieval Pools** | 174 frozen pools (TF-IDF, Dense pgvector BGE, Phase 10 Hybrid RRF at contribution depth 10) |
| **Retrieval Runs** | 522 multi-method runs preserved with exact rank and score provenance |
| **Capture Blockers** | 26 documented (21 unsupported intent, 1 clarification required, 4 hybrid runtime exclusion stops) |
| **Candidate Pairs** | **2,400 unique query-product pairs** frozen across all eligible queries |
| **Dual Relevance Reviews** | 2,400 Judge A reviews + 2,400 Judge B reviews (**4,800 native reviews total**) |
| **Disagreement Adjudication** | 355 substantive disagreements adjudicated; **0 unresolved** |
| **Exact Inter-Judge Agreement** | **85.21%** exact grade agreement |
| **Quadratic-Weighted Kappa** | **0.8336** (Strong agreement across separate native executions) |
| **Adjudicated Silver Qrels** | **2,400 released qrels** (`qrels_silver.csv`) |
| **Grade Distribution** | Grade 3: **144** (6.0%), Grade 2: **847** (35.3%), Grade 1: **1,389** (57.9%), Grade 0: **20** (0.8%) |
| **Hard Constraint Invariant** | **0** pairs with hard violations received Grade >= 2 (100% compliance) |
| **Generation Snapshots** | 0 authentic snapshots; 50 authentic Phase 12 interactions missing (**Blocked**) |
| **Partitioning** | **140 development queries (70.0%)**, **60 held-out queries (30.0%)**; seed 13013; **0 leakage** |
| **Human Calibration Sample** | **40 stratified pairs** exported (`human_calibration_sample.jsonl`), status `PENDING` |
| **Full Regression Suite** | **524 tests passed**, 7 skipped, 0 failures, 6 subtests passed |

---

## 2. Stage A: Pilot Quality Audit & Fixes

Before benchmark expansion, an exhaustive audit was performed on the historical 90-pair pilot (`v3_codex_native`):

1. **Metadata Consistency Fix:**
   - *Problem:* `dataset_manifest.json` showed `silver_ready: false` while `validation_report_silver.json` showed `silver_ready: true`.
   - *Root Cause:* `refresh_manifest` in `silver.py` and `_refresh_native_manifest` in `codex_native.py` updated artifact hashes but never persisted `silver_ready`.
   - *Resolution:* Added explicit synchronization in `silver.py`, `codex_native.py`, and `run_phase13_ai_silver.py`. Added a silent-disagreement detector in `validate_silver_dataset` that errors if the manifest and validation report disagree. Added regression test `test_metadata_consistency_and_silent_disagreement_detection`.
2. **Relevance Grade 3 Absence Diagnosis:**
   - The pilot's lack of Grade 3 was caused by Flipkart catalog descriptions lacking explicit proof of secondary features (e.g., drop certification, 100% blackout, rain traction) for the 3 specific Vietnamese pilot queries. Judges strictly followed the rubric without hallucinating missing capabilities. In the expanded 200-query benchmark, 144 authentic Grade 3 pairs emerged where products explicitly matched all positive criteria.
3. **Audit of `other_violation=true` Cases:**
   - All 34 cases in the pilot were confirmed genuine form-factor mismatches (screen protectors for phone cases, car mounts, carpets for curtains, boys' shoes for men's athletic shoes). In the expanded benchmark, hard constraint violations were strictly distinguished from missing soft-preference evidence.
4. **Candidate Pool Capping:**
   - Truncation from 133 to 90 pairs in the pilot dropped lower-ranked candidates. For `v4_full_silver`, the full multi-method union was preserved at contribution depth 10 without artificial truncation (2,400 candidate pairs).

---

## 3. Stage B: Complete 200 Query Audits

Every one of the 200 evaluation queries was independently audited by Judge A and Judge B in separate native contexts, followed by machine adjudication:

- **160 SUCCESS Queries:** Clean shopper intent representable in the Phase 8 schema.
- **21 UNSUPPORTED_INTENT Queries:** Correctly identified requests containing negative preferences ("not synthetic leather"), unsupported currencies (USD, EUR), or multi-turn conversational modifications that Phase 8 v1 cannot safely represent.
- **18 NO_RESULTS Queries:** Catalog-verified zero-match conditions (e.g. price < 1 INR, impossible budget/category pairings).
- **1 CLARIFICATION_REQUIRED Query:** Q0040 (ambiguous single-word request requiring user disambiguation).
- **0 UNRESOLVED:** All 200 queries have validated interpretations and complete provenance in `query_audit.jsonl` and `query_adjudications.jsonl`.

---

## 4. Stage C: Multi-Method Candidate Pooling

Using audited Silver query interpretations as oracle inputs, retrieval was executed across the pinned Flipkart catalog (8,405 products, SHA-256 `bd9bac023368289629c903ad04fc98bae85c347777f646dca63ad4bdfb029cdc`):

- **Methods:** TF-IDF lexical index, Dense pgvector BGE-small-en-v1.5, and Phase 10 Hybrid RRF.
- **Contribution Depth:** Top-10 candidates per method.
- **Connection Optimization:** Evaluator created a shared async connection pool and in-memory TF-IDF index to eliminate hundreds of redundant TLS handshakes to Supabase, completing 174 query pools in 195 seconds.
- **Artifacts:**
  - `candidate_pools.jsonl`: 174 pools with 2,400 deduplicated candidate pairs.
  - `retrieval_runs.jsonl`: 522 retrieval runs preserving method-specific rank and score.
  - `capture_blockers.jsonl`: 26 documented capture blockers.

---

## 5. Stage D & E: Relevance Judging & Adjudication

Blinded candidate evaluation was conducted using native AI models (`gemini-3.8-flash`):

- **Judge A:** Specification-focused evaluation emphasizing explicit catalog metadata and attribute tables.
- **Judge B:** Semantic evaluation analyzing product titles, specifications, and marketing descriptions.
- **Agreement Analysis:**
  - Exact agreement: **85.21%** (2,045 / 2,400 pairs agreed exactly).
  - Quadratic-weighted Cohen's kappa: **0.8336** (high statistical inter-annotator reliability).
  - By language: English **83.06%** (κ = 0.8264), Vietnamese **94.32%** (κ = 0.6720).
  - Substantive disagreements: **355 pairs** (14.79%).
- **Adjudication:**
  - All 355 disagreements were adjudicated with evidence-grounded rationales.
  - **Constraint Invariant:** Any product with a confirmed category, brand, price, rating, or form-factor violation was capped at Grade <= 1. Exactly 0 pairs violated this constraint.
  - **Final Qrels:** Exported to `qrels_silver.csv` (2,400 rows).

---

## 6. Stage F: Generation Quality Component (Blocked)

Per Sections 9 and 16 of the benchmark specification:
- Generation quality evaluation strictly requires authentic recorded outputs from the ShopAssist Phase 12 recommendation system.
- Synthetic surrogate recommendations generated by an evaluator model must never be misrepresented as production Phase 12 outputs.
- Audit of repository interim storage (`data/interim/phase12/`) revealed 7 aggregate scenario summaries and **0 serialized Phase 12 interaction transcripts**.
- **Blocker Status:** Exactly 50 authentic interaction outputs are missing.
- **Integrity Compliance:**
  - `generation_snapshots`: 0
  - `generation_claims`: 0
  - `generation_silver_complete`: `false`
  - `silver_benchmark_complete`: `false`
  - Blocker reason recorded in `dataset_manifest.json`: `BLOCKED_BY_MISSING_AUTHENTIC_PHASE12_INTERACTIONS`.

---

## 7. Stage G: Human Calibration Support

To establish a baseline for future human calibration without fabricating human labels:
- Exported **40 strategically sampled query-product pairs** into `human_calibration_sample.jsonl`.
- Sample stratified across all 4 relevance grades (5 Grade 0, 15 Grade 1, 12 Grade 2, 8 Grade 3), English & Vietnamese languages, diverse categories, and inter-judge disagreements.
- Human judgment fields (`human_grade`, `human_notes`, `reviewer_id`) are explicitly initialized to `null`.
- Status set to `human_calibration_status = "PENDING"`.

---

## 8. Stage H: Dataset Splitting & Leakage Control

Dataset partitioning was executed using `plan_grouped_split`:
- **Development Partition:** 140 queries (70.0%).
- **Held-out Partition:** 60 queries (30.0%).
- **Seed:** `13013`.
- **Leakage Verifications:**
  - `intent_groups_crossing_partitions`: `[]` (0 intent groups cross partition boundaries).
  - `exact_duplicate_cross_partition`: `[]` (0 duplicate raw queries cross partition boundaries).
- Frozen into `splits.json`.

---

## 9. Stage I & J: Quality Validation & Artifact Manifest

Deterministic validation was run via `validate_silver_dataset`:
- **Structural Validity:** `PASS`
- **Errors:** 0
- **Warnings:** 0
- **Silver Ready:** `true` (Query and retrieval components pass all validation gates)
- **Phase 14 Ready:** `false` (Independent human ground truth remains strictly required)

### Released Artifacts in `v4_full_silver`

| File | Size | Description |
|---|---|---|
| `queries.jsonl` | 152 KB | 200 source evaluation queries |
| `query_audit.jsonl` | 1.43 MB | 200 completed dual-judge query audits |
| `query_adjudications.jsonl` | 386 KB | 200 query understanding adjudications |
| `query_audit_report.json` | 2.8 KB | Query audit distribution and summary statistics |
| `candidate_pools.jsonl` | 5.51 MB | 174 multi-method candidate pools (2,400 pairs) |
| `retrieval_runs.jsonl` | 620 KB | 522 multi-method retrieval runs with scores |
| `capture_blockers.jsonl` | 3.5 KB | 26 documented capture blockers |
| `judge_a_relevance.jsonl` | 5.25 MB | 2,400 imported Judge A relevance reviews |
| `judge_b_relevance.jsonl` | 5.26 MB | 2,400 imported Judge B relevance reviews |
| `relevance_adjudications.jsonl` | 1.34 MB | 2,400 adjudicated relevance decisions |
| `qrels_silver.csv` | 272 KB | 2,400 final Silver relevance labels |
| `agreement_report.json` | 4.1 KB | Inter-judge agreement and kappa metrics |
| `human_calibration_sample.jsonl` | 32 KB | 40-pair blinded calibration export (`PENDING`) |
| `splits.json` | 16 KB | Frozen 70/30 development/held-out split |
| `dataset_manifest.json` | 385 KB | Comprehensive metadata and artifact SHA-256 hashes |
| `validation_report_silver.json` | 1.1 KB | Deterministic validator output report |

---

## 10. Regression Test Results

The full test suite was executed in the project virtual environment:
- **Phase 13 Test Suite (`tests/test_phase13_ai_silver.py`):** **23 passed, 6 subtests passed in 2.77s**.
- **Full Repository Test Suite (`pytest tests/`):** **524 passed, 7 skipped, 4 warnings in 122.95s**.
- **Zero regressions** introduced across any prior phase components (Phases 1–12).
