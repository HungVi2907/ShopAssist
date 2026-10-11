# AI-assisted Phase 13 query drafts

`ai_assisted_query_annotations.csv` contains 200 preliminary, machine-assisted
interpretations generated from `../queries.jsonl`.  Each row is explicitly
marked `AI_ASSISTED_DRAFT_NOT_A_REVIEWER`.

These are review aids only.  They must not be copied into
`../query_annotations.csv`, supplied to `assemble_phase13_ground_truth.py`, or
counted as an independent reviewer, qrel, adjudication, or ground truth.

A human reviewer must accept, amend, or reject every field in a private review
submission.  In particular, review all rows marked `HIGH`, all price operators,
foreign-currency and unsupported cases, missing-attribute cases, and proposed
`NO_RESULTS` labels.  The latter require a frozen Phase 10 pool and catalog
eligibility evidence; this draft does not provide that evidence.
