# Phase 13 evaluation dataset contract

**Version:** `phase13-pilot-v1`  
**State:** draft pilot; no human ground truth  
**Catalog:** `data/processed/products.parquet`, SHA-256 pinned in `dataset_manifest.json`

## Boundary and lineage

Phase 13 records evaluation data; Phase 14 measures systems. The query text, typed human interpretation, product judgments, and claim support decisions have different origins. A Phase 10 result can supply candidate IDs and provenance, but no ranking score or Phase 12 output can supply a relevance or correctness label. The four historical Phase 11 single-engineer judgments remain in `data/interim/phase11/phase11_reranking_cases.json`; they are not imported as independently reviewed qrels. The Phase 12 seven-scenario summary stores aggregate citation checks, not the per-claim evidence required here.

The `v1` directory is a versioned scaffold. `build_phase13_dataset.py` refuses to overwrite it. `v2` preserves all 40 pilot rows and adds 160 category-specific, unreviewed draft queries. Material changes to query definitions or reviewed labels require a new dataset version with a new manifest. Candidate pools must be captured once, checked, and frozen before relevance annotation. The v2 manifest hashes all six core data files and its catalog audit; later versions hash reviewer/adjudicator submissions too. A frozen release additionally hashes its final split inputs.

## Files and schemas

| File | Key fields | Meaning |
| --- | --- | --- |
| `queries.jsonl` | `query_id`, `raw_query`, `language`, `query_type`, `planning_category`, `intent_group`, `difficulty`, `source`, `expected_query_understanding`, `price_boundary_semantics`, `expected_status`, `annotation_status` | One query per line. Planning fields are draft metadata, not labels. `expected_query_understanding` is `null` until reviewed. |
| `candidate_pools.jsonl` | `query_id`, `phase10_status`, `catalog_sha256`, `candidate_count`, `provenance`, `candidates` | One frozen Phase 10 result per eligible query. Each candidate has Phase 10 `rank`, ID, name, category, brand, discounted price, rating, `rrf_score`, branch `sources`, metadata, and canonical `retrieval_text`. |
| `query_annotations.csv` | `query_id`, `annotator_id`, v1 extraction fields, operators, preferences JSON, stop status, comment | Independent reviewer working rows. |
| `relevance_annotations.csv` | `query_id`, `product_id`, `annotator_id`, grade, violation flags, comment | Independent blind product judgments. |
| `qrels.csv` | `query_id`, `product_id`, reviewer A/B grades, adjudicated grade, violation flags, reason | Final query-product judgments after adjudication. Grade is 0–3. A final grade requires both original grades. |
| `generation_claims.csv` | claim ID, query/product IDs, text, evidence IDs/text JSON, generation snapshot, reviewer A/B and final claim support, factual correctness, relevance, missing-information handling | Phase 12 claim review. The generation output and exact evidence must be frozen first. |
| `splits.json` | `status`, `development`, `held_out` | `NOT_FROZEN` until adjudication. A frozen partition covers every query, with no shared `intent_group` or near-duplicate crossing. |
| `dataset_manifest.json` | version, date, catalog hash/count, distributions, annotation status, reviewers, source artifacts | Snapshot and status summary. |
| `validation_report.json` | structural status, readiness, errors, warnings, statistics | Machine-readable validation result. |

`expected_query_understanding` follows the production Phase 8 v1 shape: `semantic_query`, `hard_constraints` (`category`, `brand`, `min_price`, `max_price`, `min_rating`, `currency`), `soft_preferences`, `needs_clarification`, and `clarification_reason`. Price operators are evaluation metadata in `price_boundary_semantics` (`min_operator`: `>` or `>=`; `max_operator`: `<` or `<=`). Phase 8 v1 has no operator fields. Phase 10 requires separately verified inclusivity flags; never infer them from its numeric bounds.

`expected_status` describes the correct retrieval/stop behavior: `SUCCESS`, `NO_RESULTS`, `CLARIFICATION_REQUIRED`, or `UNSUPPORTED_INTENT`. A no-result label needs a catalog eligibility check under the exact query constraints. A vague query or foreign currency is a stop case under current contracts; unsupported exclusion patterns must not become positive preferences.

Claim support, factual correctness, relevance, and missing-information labels use the enumerations in the [annotation guidelines](phase13_annotation_guidelines.md). Final qrels carry distinct real reviewer IDs, both grades, all five Boolean constraint flags, and the adjudicated grade. A frozen split cannot contain missing final claim or qrel fields.

## Candidate capture and evaluation scope

`capture_phase13_candidates.py` accepts only adjudicated query interpretations. It constructs typed Phase 8 inputs, runs Phase 9, calls the real Phase 10 service with Top-20 and explicit price boundary flags, and copies canonical retrieval text by exact catalog ID. It writes to a new staging path and refuses overwrite. The live database is read only. Its `query_input` provenance says `human_adjudicated_phase8_oracle`: this pool assesses retrieval/reranking conditional on correct query understanding. A separate Phase 14 end-to-end run must feed actual Phase 8 outputs and report stop/error propagation. A Top-20 pool alone cannot establish catalog-wide Recall@K; supplementary judged pools or exhaustive eligibility review may be needed.

No-results and stopped queries may have zero candidates. Preserve that fact. Do not pad short pools. Candidate ranks and scores are visible in the machine file for reproducibility but must be hidden in reviewer exports. `query_annotations.csv`, `relevance_annotations.csv`, and `generation_claims.csv` are reviewer work templates; export a blinded task view without score, method, and other-reviewer columns before assignment.

`prepare_phase13_annotation_tasks.py --out <new directory>` exports query, relevance, and claim tasks plus blank adjudication templates. Optional `--reviewer-a-id` and `--reviewer-b-id` create separate copies for real, distinct reviewers. It orders relevance rows by a stable hash and excludes ranks/scores. `assemble_phase13_ground_truth.py` accepts independent submissions and explicit adjudication decisions, rejects incomplete pairs, and writes a new version. `capture_phase13_generation.py --source <saved-results.jsonl> --out <new CSV>` flattens real serialized Phase 12 `RecommendationResult` records with `{query_id, generation_snapshot, provider, model_version, prompt_configuration, result}` wrappers. It includes strength, limitation, summary, and comparison claims with the product's evidence text and source-result hash; it never labels them. `promote_phase13_capture.py` versions a staged Phase 10 or Phase 12 capture after validating references and hashes. These tools refuse to overwrite an existing output. The complete handoff is in [phase13_review_handoff.md](phase13_review_handoff.md).

## Validation and readiness

Run `python scripts/validate_phase13_dataset.py --dataset data/evaluation/phase13/v2`. Structural PASS means file shape, references, boundaries, lineage hashes, and split rules are consistent. `phase14_ready=true` additionally requires at least 200 adjudicated queries, all 16 categories and nine query types, frozen pools for eligible queries, verified no-result cases, independently reviewed and adjudicated qrels for every candidate, independently reviewed claims from at least 50 generation interactions including unsupported and unknown/missing-information cases, named adjudication trails, a frozen grouped split with matching hashes, regression evidence, and resolved critical blockers. This is a necessary technical gate, not a substitute for auditing annotation quality and held-out access controls.

The pilot has 40 drafts and v2 has 200 drafts, with no final labels, pools, claim cases, or split. Phase 14 final comparison is therefore blocked. The v2 catalog audit confirms all 16 categories have products and 18 literal below-1-INR hypotheses have zero matches under the stated category and price boundary; these remain draft no-result candidates until adjudicated. Optional expansion beyond 200 is conditional on coverage and statistical need.
