# Phase 13 dataset report

**Status: PARTIAL (11 October 2026).** The 40-query v1 pilot remains unchanged. A new v2 contains 200 distinct **draft** queries and a catalog audit. The review, capture, adjudication, and versioned freeze tools are implemented and tested. There are still zero real human judgments, qrels, generation claims, or frozen splits. The v2 validator reports structural `PASS` and `phase14_ready=false`; Phase 14 final comparison must wait.

## P13 issue status

| Issue | Engineering completed | Verification | Remaining prerequisite |
| --- | --- | --- | --- |
| P13-01 runtime/candidates | Restored a separate Windows Python 3.12 environment; capture checks live DB IDs, pinned catalog, Top-20 provenance, timestamp, price operators and literal eligibility. Added immutable capture promotion. | Read-only Phase 10→11 live integration passed (1 test). | Two real query reviews and adjudicated interpretations before benchmark capture. |
| P13-02 query truth | Separate blind reviewer tasks, adjudication templates, explicit decision assembler, price boundary validation. | Synthetic file round-trip and negative tests passed. | Two real reviewers and adjudicator for every benchmark query. |
| P13-03 relevance truth | Blind candidate tasks, 0–3 grades, five violation flags, pair completeness, named decisions, disagreement count and weighted kappa. | Invalid grades, reviewer identity, missing decisions and grade/violation conflicts rejected in tests. | Frozen real pools, two independent human relevance rows per pair, and adjudication. |
| P13-04 generation truth | Phase 12 snapshot capture with provider/model/prompt, result SHA-256, product metadata and evidence association; blind claim review and final-label validation. | Existing flattening test and workflow negative tests passed. | Real eligible Phase 12 outputs and two independent human claim judgments across 50+ interactions. OpenRouter live smoke returned a schema-invalid response; Groq key returned HTTP 401. |
| P13-05 expansion | 160 new domain-specific drafts in v2; original 40 IDs/text unchanged. Catalog audit and query task export complete. | 200 distinct texts, 16 categories, nine types, 42 Vietnamese, zero lexical near-duplicate pairs; 8,405 unique catalog IDs. | Human realism/taxonomy check and complete annotations. |
| P13-06 split | Seeded grouped planner, near-duplicate grouping, strata report, new-version freeze and file hashes. | Determinism/leakage and refusal-to-freeze tests passed. | Finished adjudication and captures; `splits.json` remains `NOT_FROZEN`. |
| P13-07 regression | Compatible dependency lock, project dependency fixes, expanded negative tests and readiness gates. | 482 offline pytest passes; 7 skips; 15 deselections. Phase 13 unittest: 22 passes. | Live provider failures above; full human benchmark still absent. |

## Dataset counts and provenance

| Measure | v1 pilot | v2 draft |
| --- | ---: | ---: |
| Queries | 40 | 200 |
| English / Vietnamese | 30 / 10 | 158 / 42 |
| Approved categories / query types represented | 16 / 9 | 16 / 9 |
| Human-adjudicated interpretations / independently reviewed query pairs | 0 / 0 | 0 / 0 |
| Frozen candidate pools / reviewed relevance pairs / adjudicated qrels | 0 / 0 / 0 | 0 / 0 / 0 |
| Frozen generation claims / adjudicated claim labels | 0 / 0 | 0 / 0 |
| Development / held-out queries | 0 / 0 | 0 / 0 |

The v2 query-type counts are: simple constraint 20, multiple constraints 34, soft preference 23, use case 27, mixed hard/soft 23, difficult semantic 19, missing attribute 18, no-result **candidates** 18, and clarification/unsupported 18. The v2 source field distinguishes the 160 authored drafts from the historical pilot. Query type and category are planning metadata, never verified interpretations.

The [catalog audit](../data/evaluation/phase13/v2/catalog_draft_audit.json) checks the pinned SHA-256 `bd9bac023368289629c903ad04fc98bae85c347777f646dca63ad4bdfb029cdc`. All 16 planned categories contain products. The 18 literal `< 1 INR` price hypotheses have zero catalog matches within their planned categories. They remain unlabeled: reviewers must verify the intended product category, price operator and stop behavior before assigning `NO_RESULTS`. No query was labeled from this audit alone. The complete v2 [validation report](../data/evaluation/phase13/v2/validation_report.json) shows structural PASS, no duplicate or lexical near-duplicate texts, and false readiness gates for human review, captures, qrels, claims and split freeze.

## Test record

Runtime: official Python 3.12.10 x64 in ignored `.deps/phase13-win-venv`; dependency versions are in [requirements-phase13-windows.txt](../requirements-phase13-windows.txt) and reproduction steps in [phase13_runtime.md](phase13_runtime.md). The original `.venv` still refers to a missing Python 3.10 executable. Project dependency declarations now include Parquet, process memory and psycopg support.

| Command | Actual result |
| --- | --- |
| `python -m unittest tests.test_phase13_dataset tests.test_phase13_workflow -v` | 22 passed (14 dataset tests, 8 workflow tests). |
| `python -m pytest -q -m 'not integration' --disable-warnings --tb=short` | 482 passed, 7 skipped, 15 deselected, 4 warnings. |
| `python scripts/validate_phase13_dataset.py --dataset data/evaluation/phase13/v2` | Structural PASS; `phase14_ready=false`. |
| `SHOPASSIST_PHASE11_LIVE_DB=1` read-only Phase 10→11 pytest | 1 passed in 19.71 s after a transient database retrieval failure on the preceding attempt. |
| Opt-in OpenRouter Phase 12 smoke pytest | Failed after rate-limit retries: provider response lacked required `overview` and `products`. No claim capture. |
| Opt-in Groq Phase 12 smoke pytest | Failed HTTP 401: configured key invalid. No claim capture. |

The initial broad pytest collection attempts also exposed missing `psutil`, `psycopg` and blocked compiled SQLAlchemy/scikit-learn wheel versions. Those runtime defects were resolved without weakening assertions. The final 482-pass run used scikit-learn 1.7.2, matching the saved TF-IDF artifact, and pure-Python SQLAlchemy 2.0.41. Live provider failures remain external/integration evidence, not offline regression passes. The Gemini and other model integration selections were not executed in this final run.

## Continuation and technical debt

The exact commands, file formats and version sequence are in [phase13_review_handoff.md](phase13_review_handoff.md). The next action is to assign two real reviewers to all 200 query tasks, collect independent submissions, and adjudicate the Phase 8 interpretations. Only then can the capture utility run the authentic Phase 10 Top-20 pools for this benchmark. Relevance and claim review follow; the split release command refuses incomplete ground truth. Held-out queries must be withheld from tuning after freeze.

P11-01 and P11-04 remain open because there are no independent qrels or frozen evaluation split. P12-04 remains open because there are no independently reviewed generation interactions. P12-01 remains open because the original offline NLI entailment evidence on 50+ recommendations is absent; a claim-review schema does not close that model investigation. See [Phase 13 deferred issues](technical_debt/phase13_deferred_issues.md).

**Readiness:** Structural validation PASS; ground-truth completeness 0; human review 0; split `NOT_FROZEN`; offline regression PASS with the stated exclusions and live provider failures; Phase 14 ready **false**. A technical readiness flag will still require a separate human quality audit before using the benchmark for final claims.
