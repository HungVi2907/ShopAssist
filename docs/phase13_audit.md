# Phase 13 implementation audit

The proposal targets 200–500 queries and a complete pipeline benchmark. `docs/development_status.md` records Phases 8–12 as component/prototype validated. The v1 Phase 13 pilot has 40 drafts; v2 expands this to 200 unreviewed drafts. These are dataset coverage, not ground truth.

| Existing asset | Reuse / limitation |
| --- | --- |
| Phase 8 v1 schema and contract; 50 query-understanding fixtures and Phase 8.2 dev/held-out fixtures | Category, brand, price, rating, currency, preferences and clarification fields are reusable. Existing fixtures have single-author and overlapping experimental history; they are not Phase 13 independent ground truth. v1 has no strict-price operator or typed exclusion. |
| Phase 9 contract and nine component preference cases | NFC/case-fold normalization and conservative negative/currency stop behavior guide annotation. Component checks are not relevance labels. |
| Phase 10 hybrid retrieval | Real typed result provides Top-20 candidates, branch ranks/scores, RRF, filters and status. Live database plus local BGE/TF-IDF runtime is required for capture. |
| Phase 11 `phase11_annotation_plan.md`, blank template, four frozen cases | Adopt the 40-query strata and 0–3 rubric. Four cases are local exact-cosine/TF-IDF pools with single-engineer labels; no double annotations or valid Phase 13 qrels. |
| Phase 12 seven scenario report and scripts | Provides bilingual and missing-attribute scenarios. Stored report has aggregate citation counts, not per-claim text/evidence judgments. Claim capture/review is required. |
| `products.parquet`, Phase 11 catalog manifest, Phase 6 TF-IDF assets | 8,405-row canonical snapshot with pinned SHA-256 `bd9bac023368289629c903ad04fc98bae85c347777f646dca63ad4bdfb029cdc`; 16 approved categories. Phase 10 runtime does not carry an in-band catalog hash, so capture must check IDs/text against this artifact. |

Missing before Phase 14: adjudicated query interpretations; live Phase 10 frozen pools; independent relevance and constraint judgments; actual generated claims with evidence and independent support labels; frozen dev/test split; held-out access discipline. The 200-query draft breadth is present and catalog-audited, with zero human-reviewed entries. The [dataset report](phase13_dataset_report.md) records the current evidence and blockers.
