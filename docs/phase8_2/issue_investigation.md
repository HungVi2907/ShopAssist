# Phase 8.2 issue investigation and root causes

Date: 2026-10-09. Source-of-truth evidence: preserved source snapshots, original raw cache, independent audit JSON and executed tests. Larger live comparisons were explicitly deferred by the user. Confirmed means supported by source inspection or execution; suspected means further evidence is necessary.

## Original issues and Phase 8.1 changes

The original registry has fourteen P8 issues. Phase8.1 added experimental product type, typed exclusions and boundary flags, prompts and deterministic refinements. These never replaced the production v1 parser. Existing unit tests established particular examples, not broad semantic resolution.

| Original ID | Current assessment | Phase8.2 investigation |
| --- | --- | --- |
| P8-01 preference quality | Unresolved | ISSUE-01 |
| P8-02 product type | Improved experimentally; not production-resolved | ISSUE-01/02/06 |
| P8-03 negation schema | Representation added; extraction still imperfect | ISSUE-02/06/10 |
| P8-04 strict prices | v2 representation exists; v1 cannot carry flags | ISSUE-06/10 |
| P8-05 SQL column | Documentation uses product_name; resolved documentation defect | ISSUE-11 |
| P8-06 metrics | Independent policy implemented; old metric retained as historical | ISSUE-05 |
| P8-07 Boeing | Entity/filter policy disagreement remains | ISSUE-07 |
| P8-08 performance | Better instrumentation; speed improvement unproven | ISSUE-09 |
| P8-09 failure contract | Safe public failures implemented; operational failures remain | ISSUE-03/12 |
| P8-10 multi-turn | Deferred; single-turn scope remains | ISSUE-10 |
| P8-11 currency conversion | Deferred; foreign currency must clarify | ISSUE-06/10 |
| P8-12 category ambiguity | Unresolved for alternatives and unsupported domains | ISSUE-07/08 |
| P8-13 injection | Limited mocked checks; absolute immunity unproven | ISSUE-12 |
| P8-14 diagnostics | Error leakage improved; raw result envelope still private data | ISSUE-12 |

## Current evidence inventory
### ISSUE-01 — Soft preferences below target

Severity: High. Status: **UNRESOLVED**.

Evidence: Old heldout E5-B has 7/20 soft mismatches; TP=18, FP=9, FN=3; strict macro F1=78.33%, micro F1=75%.

Root cause: Product-class duplication, omitted attributes, compatibility confusion, literal synonyms and disputed unsupported-domain labels.

Reproduce: Audit HELD001/002/005/007/013/019/020; run audit_phase8_2.py.

Affected: `prompts.py, prompt_variants.py, refinement_rules.py, scoring.py`.

Candidate/fix: C2-C5 prompts; contextual cleanup; independent label review. Product cleanup fixes HELD005 on replay only.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-02 — Low complete slot accuracy

Severity: High. Status: **UNRESOLVED**.

Evidence: E5-B full v2 slot EM=10/20; shared-field EM=12/20. Error counts overlap: soft 7, product type 2, exclusions 2, brand 1, clarification 1, active boundaries 0.

Root cause: Several independently imperfect slots compound into a failed query; exact wording is a separate metric.

Reproduce: Inspect failure_analysis.json per-case records; compare field mismatches.

Affected: `schema_variants.py, scoring.py, failure_analysis.json`.

Candidate/fix: Improve individual slots; keep strict metric. No semantic extraction winner adopted.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-03 — Development failure classification

Severity: Medium. Status: **RESOLVED**.

Evidence: QU033 and QU036 both exhausted 429 retries. No successful provider JSON exists for these failures.

Root cause: Legacy validity combined transport and schema failures; fallback rules overwrote QU033's provider reason.

Reproduce: Compare dev E5-B records with preserved raw cache; invalid_cases identifies API_429_RETRY_EXHAUSTED.

Affected: `gemini_client.py, runner.py, audit_phase8_2.py`.

Candidate/fix: Stage diagnostics and failure-aware scoring implemented. JSON/schema defect allegation NOT REPRODUCED for these two cases; provider quota remains an operational risk.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-04 — Temperature conclusion unsupported

Severity: Medium. Status: **DEFERRED**.

Evidence: E2 used E1-B/v1, not E5-B/v2. T1 quality is higher in those stored runs; T0/T0.5 also have API failures. No independent repeated-run evidence.

Root cause: Architecture transfer and quota confounding; no theorem makes T0 best for extraction.

Reproduce: Inspect E2 configurations and raw cache; dry-run B0,T05,T10 with repetitions=3.

Affected: `prompt_variants.py, candidates.py, research_review.md`.

Candidate/fix: Same-E5-B 0/0.5/1 experiment prepared; user explicitly deferred larger live work.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-05 — Unfair exact-match comparisons

Severity: High. Status: **RESOLVED**.

Evidence: Original 98% excludes preferences. Historical 54% is common-field EM. The old v1 5% vs v2 50% mixed field capabilities; missing null product_type and active boundary flags received credit.

Root cause: Scoring defaults masked missing fields and failures; schema capability was confused with shared extraction quality.

Reproduce: Run independent scoring tests and audit; same-query shared EM is 40% vs 60%.

Affected: `evaluation.py, experiments/metrics.py, phase82/scoring.py`.

Candidate/fix: Independent versioned common/full-v2 metrics with explicit missing-field and failure policy. Old scorer retained solely for historical reproduction.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-06 — Rules can alter intent

Severity: High. Status: **IMPROVED**.

Evidence: Historical rules damage 9/18 authored oracle outputs. Conservative rules preserve all 18. This is a rule-invariance test, not LLM quality evidence.

Root cause: Naive negation cues, unbound price operators, substring domain detection and global class-word blacklists.

Reproduce: Test not only/not necessarily/not too expensive/except Nike/no less than/not under/double negation; run rule tests and offline ablations.

Affected: `refinement_rules.py, phase82/rules.py`.

Candidate/fix: Isolated narrow evidence rules implemented. Ambiguous and multilingual scope is still not solved; production rules not switched.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-07 — Entity extraction versus filter activation

Severity: High. Status: **UNRESOLVED**.

Evidence: Boeing is a named manufacturer in QU033. HELD020 treats Honda compatibility as accessory brand and omits for Honda City.

Root cause: Business support policy conflates named entities with active catalog filters; a single brand slot cannot encode both.

Reproduce: Inspect QU033 raw output and HELD020; compare brand-preserving rule replay.

Affected: `normalization.py, refinement_rules.py, query_contract_review.md`.

Candidate/fix: Preserve named manufacturers in experimental extraction; gate unsupported queries before filtering. Old labels unchanged; policy adjudication pending.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-08 — Coverage and annotation limitations

Severity: High. Status: **IMPROVED**.

Evidence: 13/15 development queries overlap original50. New 20/20/40 fixtures have 80 unique exact queries and no overlap with old fixtures.

Root cause: Small handcrafted data and single-annotator policy choices; exact disjointness does not establish semantic independence.

Reproduce: Run fixture builder and dataset_integrity.json audit.

Affected: `tests/fixtures/phase8_2, build_phase8_2_fixtures.py`.

Candidate/fix: Labels authored before predictions; independent annotation and ambiguous-case adjudication still pending.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-09 — Latency, tokens and cache provenance

Severity: Medium. Status: **IMPROVED**.

Evidence: Old cache keys omit prompt/schema content and settings, cache errors, round temperature and reuse stored latency. Retry counts and cache flags are incomplete.

Root cause: Logical cases were counted instead of actual attempts; stored metrics cannot isolate provider speed.

Reproduce: Run runner tests for fingerprint changes, failure caching, resume and budget exhaustion.

Affected: `experiments/runner.py, phase82/runner.py, gemini_client.py`.

Candidate/fix: New content hashes, success-only opt-in cache, persistent attempt/token reservations and stage timings. Fresh comparative performance remains unmeasured.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-10 — v2 to v1 semantic loss

Severity: High. Status: **UNRESOLVED**.

Evidence: Adapter drops product_type, strict/inclusive flags and typed exclusions; negatives become soft strings and may be truncated at ten preferences.

Root cause: Structural compatibility cannot preserve meanings absent in the target schema.

Reproduce: Read both to_v1 methods and run existing schema adapter tests; see contract review example.

Affected: `schemas.py, schema_variants.py`.

Candidate/fix: Versioned consumer migration proposed; no breaking production schema switch made.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-11 — Documentation contradictions

Severity: Medium. Status: **RESOLVED**.

Evidence: Old report says seven resolved issues but enumerates eight; unsupported determinism, validity, latency and readiness guarantees remain in historical prose.

Root cause: Narrative claims exceeded per-case evidence and blurred experimental versus adopted behavior.

Reproduce: Read synchronization addenda and compare generated figures with audit JSON.

Affected: `README.md, Phase8/8.1 reports, conceptual guides`.

Candidate/fix: Explicit superseding corrections preserve historical measurements and provide current status counts.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

### ISSUE-12 — Operational safety and lifecycle

Severity: High. Status: **IMPROVED**.

Evidence: Settings representation/serialization and provider errors exposed sensitive values; Windows smoke teardown reproduced SSL transport warnings. Two-test retest passed after lifecycle fix.

Root cause: Unrestricted exception text, double retry layers, lazy SDK sessions closed after their owning event loop.

Reproduce: Run reliability tests for 401/403/429/503/timeout/invalid JSON/key redaction/input bounds; inspect smoke_retest.xml.

Affected: `config.py, security.py, gemini_client.py, query_understanding.py, test_gemini_integration.py`.

Candidate/fix: Redacted settings/errors, one retry owner, exact model identity, usage-before-validation, same-loop cleanup. Injection immunity, retention policy, strict coercion and finite numeric validation remain open.

Validation: Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset.

## Per-case diagnosis and rejected fixes

| Case | Soft false positives | Soft false negatives | Other failed fields |
| --- | --- | --- | --- |
| HELD001 | gaming | none | product_type |
| HELD002 | none | noise cancelling | product_type |
| HELD004 | none | none | exclusions |
| HELD005 | analog | none | none |
| HELD007 | lumbar support | with lumbar support | none |
| HELD009 | none | none | clarification |
| HELD013 | 1 litre, carton, farm, fresh, organic | none | none |
| HELD015 | none | none | exclusions |
| HELD019 | commercial | none | none |
| HELD020 | none | for honda city | brand |

HELD007 is a reviewed lexical mismatch (lumbar support versus with lumbar support); supplementary equivalence handles it without changing strict labels. HELD013 and HELD019 expose an annotation policy question: useful attributes in unsupported domains were labeled empty. Do not erase original predictions or amend historical labels to improve scores. HELD004 has attribute-versus-feature exclusion typing; HELD015 has a wrong telephoto target and duplicate phrase introduced by rules. HELD020 is a real compatibility/brand confusion.

Rejected: universal deletion of product modifiers, substring rejection of any query mentioning milk/airplanes, suppressing all unsupported-domain manufacturer names, broad synonym/embedding acceptance, treating quota fallback as valid extraction, and production adoption based on already inspected heldout examples. Narrow rules improve isolated cases but cannot repair all semantic scopes.

The inventory contains 12 investigations: 3 RESOLVED, 4 IMPROVED, 4 UNRESOLVED, 1 DEFERRED. RESOLVED applies to the stated diagnostic/scoring/documentation issue, not to all upstream semantics. Independent annotation, finite numeric validation, sensitive-data retention, multilingual extraction and repeated live sampling remain open.
