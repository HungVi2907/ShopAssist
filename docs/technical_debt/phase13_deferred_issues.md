# Phase 13 deferred issues

**Status:** PARTIAL. The 200-query v2 draft, runtime, capture/review/assembly tools, audit, tests and readiness validator are in place. No human evaluation label is represented as complete. Phase 14 final comparison remains blocked.

| ID | Completed engineering | Exact remaining prerequisite and exit evidence |
| --- | --- | --- |
| P13-01 | Windows runtime restored; read-only Phase 10→11 integration passed; catalog-pinned capture and immutable promotion implemented. | Two real reviews and adjudicated Phase 8 interpretation for each eligible query. Then capture real Top-20 pools with timestamps/configuration, verify DB/catalog IDs, and promote them to a new version. |
| P13-02 | Blind independent query tasks, strict/inclusive operator fields, named decision templates and assembler tested. | Two real reviewer submissions plus explicit adjudication for 200 queries, with documented disagreements and verified stop outcomes. |
| P13-03 | Blind relevance tasks, pair-completeness checks, qrel assembly, five violation flags and agreement metrics tested. | Frozen pools followed by two real grades for every candidate and final decisions. Supplemental independently judged candidates remain necessary for catalog-wide Recall@K. |
| P13-04 | Real-output claim capture schema and evidence checks, blind tasks, four quality-label dimensions and adjudication gates implemented. | At least 50 diverse real generated interactions and independent human claim reviews; configured Groq key currently returns HTTP 401, OpenRouter smoke returned schema-invalid content after rate limits. |
| P13-05 | v2 has 200 distinct drafts, all 16 categories and nine types, 42 Vietnamese queries, zero detected lexical near duplicates; 18 literal low-price hypotheses have no catalog matches. | Human realism/taxonomy review and all required ground-truth labels. Draft planning checks cannot close this issue. |
| P13-06 | Reproducible grouped/stratified planner, leakage checks, versioned freeze with hashes tested. | Complete adjudicated data and capture evidence; release then freeze the development/held-out split and enforce held-out access restrictions. |
| P13-07 | Final offline pytest selection: 482 passed, 7 skipped, 15 deselected; Phase 13 unittest: 22 passed. | Resolve or document live provider failures and execute any additional integration gates needed for the final benchmark. Preserve test evidence in the release manifest. |

P11-01 and P11-04 remain open until independent qrels and a frozen split exist. P12-04 remains open until 50+ diverse interactions have blinded, double-annotated quality labels. P12-01 additionally requires an offline NLI entailment scorer evaluated on 50+ generated recommendations; the current human review schema does not supply that model evidence. See the [dataset report](../phase13_dataset_report.md) and [review handoff](../phase13_review_handoff.md).
