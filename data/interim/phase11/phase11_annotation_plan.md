# Phase 11 ranking annotation plan

**Status:** PLANNED, not measured. No queries, candidates, or relevance grades are fabricated in the template.

## Target set

Prepare 40 representative natural-language queries using real catalog products and real typed Phase 10 output. Target strata:

| Stratum | Queries |
| --- | ---: |
| Simple product identity | 5 |
| Multiple hard constraints | 7 |
| Soft preferences | 6 |
| Product use cases | 5 |
| Mixed hard and soft requirements | 7 |
| Semantically similar but incorrect candidates | 5 |
| Category-specific attributes and difficult ranking | 5 |
| **Total** | **40** |

Freeze each query's Phase 10 candidate IDs, ranks, branch scores, constraints, and canonical catalog checksum before annotating. Target 20 candidates per query where Phase 10 returns them. Record query intent/category and candidate evidence text in `phase11_annotation_template.csv`.

## Judgment procedure

Two reviewers independently assign grades from 0 to 3 using the existing rubric, without seeing method names or scores. Grade each frozen candidate using only the query's visible positive requirements and canonical product evidence. Record a short rationale. Adjudicate disagreements and preserve both original labels plus the final label. Do not convert missing evidence into a positive claim.

Only after annotation, freeze development and held-out partitions by query. Compare RRF, Multi-Signal, Cross-Encoder, and only development-selected Combined weights on the same pool and judgments. Report nDCG@5, MRR with grade >=2, Precision@5, query-level ranks, hard-constraint violations, and separated warm latency. Do not tune using held-out labels.

The repository currently contains four single-engineer query judgments. They remain historical component evidence and do not fill this planned 40-query set.
