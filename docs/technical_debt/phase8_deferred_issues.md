# Phase 8 Deferred Issues and Technical Debt

**Freeze snapshot:** 2026-10-10, commit `4ba3bfeb38decdf2512a346ba9efaf50bd7f9918` (clean before this handover). Evidence is reconciled from `docs/phase8_2/issue_investigation.md`, `docs/phase8_2/final_engineering_report.md`, `data/interim/phase8_2/issue_inventory.json`, historical Phase 8/8.1 reports, fixtures, and source code. Phase 8.2's status counts are **3 RESOLVED, 4 IMPROVED, 4 UNRESOLVED, 1 DEFERRED**.

Remediation is postponed for the frozen extraction system. A `RESOLVED` investigation remains resolved; an `UNRESOLVED` defect remains unresolved even though its next experiment is deferred. Severe safety, security, or integration defects can be fixed earlier.

## Original issue reconciliation

| Original issue | Current meaning | Consolidated investigation |
| --- | --- | --- |
| P8-01 | Soft preference extraction quality | ISSUE-01 |
| P8-02 | Product type versus preference confusion | ISSUE-01, ISSUE-02, ISSUE-06 |
| P8-03 | Negative/exclusion representation and extraction | ISSUE-02, ISSUE-06, ISSUE-10 |
| P8-04 | Strict versus inclusive price boundary loss | ISSUE-06, ISSUE-10 |
| P8-05 | SQL example column-name defect | ISSUE-11 (resolved documentation correction) |
| P8-06 | Evaluation metric integrity | ISSUE-05 (resolved scoring correction) |
| P8-07 | Brand, manufacturer, compatibility semantics | ISSUE-07 |
| P8-08 | Latency/token evidence | ISSUE-09 |
| P8-09 | Error contract and provider failures | ISSUE-03, ISSUE-12 |
| P8-10 | Multi-turn references | ISSUE-10 (deferred feature) |
| P8-11 | Foreign-currency conversion | ISSUE-06, ISSUE-10 (unsupported; clarify) |
| P8-12 | Category alternatives and unsupported categories | ISSUE-07, ISSUE-08 |
| P8-13 | Prompt injection | ISSUE-12 |
| P8-14 | Diagnostic/raw-text retention | ISSUE-12 |

The Phase 8.1 original register contains 14 items. Phase 8.2 consolidated them into 12 investigations; the mappings above preserve the original IDs rather than implying a one-to-one issue count.

## Consolidated backlog

### ISSUE-01 — Soft preference extraction quality

- **Original mapping / status / severity:** P8-01, P8-02; **UNRESOLVED**, High.
- **Description and evidence:** Experimental E5-B old held-out-20 soft macro F1 is 78.33% (18 TP, 9 FP, 3 FN; micro F1 75%). This is stored-output reanalysis, not a production result or broad population estimate. Product-class duplication, omitted attributes, compatibility confusion and disputed labels appear in inspected errors.
- **Root cause / implementation:** Production v1 still has a single string-list `soft_preferences` field. Prompt, extraction, label-policy and product-type errors can all affect its contents. Relevant code: `src/shopassist/llm/{prompts.py,schemas.py,normalization.py}`; experimental code remains isolated under `src/shopassist/llm/experiments/`.
- **Downstream impact:** Phase 9 can faithfully represent an incorrect upstream phrase. Phase 10: **QUALITY RISK**; Phase 11/12: ranking and explanations inherit candidate mismatch; Phase 13/14: **NON-BLOCKING WITH SAFEGUARDS**, stratify and annotate extraction errors; Phase 15–17: monitor and provide clarification paths. Not a blocker to an independently tested Phase 9 component.
- **Severity / workaround:** High; preserve v1 output, do not claim semantics are correct, and stop on unsupported polarity.
- **Permanent candidates / deferred work:** Prompt refinement, same-architecture temperature ablation, annotation adjudication, product-type separation, false-positive/negative review, repeated runs, and new held-out evaluation. Large live experiments remain deferred.
- **Prerequisites / revisit:** Phase 13 annotation review and Phase 14 evidence, or earlier material constraint failures. **Acceptance:** locked independent set meets a predeclared soft F1 target and no unsafe constraint failures; report macro/micro metrics and uncertainty.
- **Reproduction / source evidence:** `python scripts/audit_phase8_2.py`; inspect `data/interim/phase8_2/failure_analysis.json`, `heldout_evaluation_results.json`, `issue_inventory.json`, and the source docs above.

### ISSUE-02 — Complete structured-intent accuracy

- **Original mapping / status / severity:** P8-02, P8-03; **UNRESOLVED**, High.
- **Evidence:** Experimental E5-B full v2 slot exact match is 10/20 (50%); shared-field exact match is 12/20 (60%). Errors overlap: seven soft, two product-type, two exclusion, one brand and one clarification mismatch. Product type and typed exclusions are experimental schema-v2 fields, not production v1 fields.
- **Root cause / implementation:** Several imperfect fields compound under strict exact match, and v1 cannot express all v2 semantics. Code: `src/shopassist/llm/schema_variants.py`, `schemas.py`, `experiments/phase82/scoring.py`.
- **Downstream impact:** Phase 9 accepts v1 and refuses invalid/clarification outputs; it cannot reconstruct missing product type/exclusions. Phase 10–12: **QUALITY RISK**, enforce only explicitly supported constraints; Phase 13–14: measure per slot; Phase 15–17: expose clarification and unsupported states. No phase is blocked if it retains these safeguards.
- **Severity / workaround:** High; use versioned metrics, accepted v1 only, and no silent v2-to-v1 promotion.
- **Candidates / deferred work:** Per-field error analysis, product-type and exclusion evaluation, preference consistency, independent annotation and contract migration design.
- **Prerequisites / revisit:** Phase 13 labels, Phase 14 error attribution; revisit sooner on missed mandatory requirements. **Acceptance:** predeclared full-slot/shared-field metrics pass on independent evaluation and all required intent fields have an explicit consumer contract.
- **Reproduction / references:** `python scripts/audit_phase8_2.py`; Phase 8.2 failure analysis, scoring, contract review.

### ISSUE-03 — Gemini operational failures

- **Original mapping / status / severity:** P8-09; **RESOLVED** diagnostic classification; **UNRESOLVED OPERATIONAL RISK**, Medium.
- **Evidence:** QU033/QU036 development failures exhausted 429 retries; no valid provider response exists for those attempts. The defect that classified transport failure as malformed JSON was corrected. Quota/availability remains a provider risk.
- **Root cause / implementation:** Legacy accounting mixed transport and schema validity; current reliability code distinguishes stages. Code: `src/shopassist/llm/gemini_client.py`, `experiments/phase82/runner.py`.
- **Downstream impact:** Phase 9 receives `is_valid=False` and returns `INVALID_INPUT`; Phase 10–12 must not execute that request. Phase 13/14 record failures separately; Phase 15–17 need bounded retries and user-facing retry/clarify handling. **NON-BLOCKING WITH SAFEGUARDS**; provider outage can temporarily block an individual request.
- **Severity / workaround:** Medium; safe failure results, one retry owner, clear failure classification; never interpret fallback text as verified intent.
- **Candidates / postponed work:** Track provider availability and quota with production SLOs; no quota claim from historical retry tests.
- **Prerequisites / revisit:** Online deployment/observability; revisit after repeated severe availability failures. **Acceptance:** errors remain stage-classified, redacted, bounded and observable.
- **Reproduction / references:** `python -m pytest tests/test_phase8_2_reliability.py`; `data/interim/phase8_2/verification_report.json`.

### ISSUE-04 — Temperature selection

- **Original mapping / status / severity:** P8-09; **DEFERRED**, Medium.
- **Evidence:** Existing E2 used an E1-B/v1 architecture rather than E5-B/v2; temperature runs include API failures and lack independent repeated-run evidence. Production stays at 0.0.
- **Root cause / implementation:** Architecture transfer and quota confounding prevent a justified choice. Config: `src/shopassist/llm/config.py`.
- **Downstream impact:** Phase 9/10–17 see only the accepted production result; no downstream phase should tune or assume temperature effects. **NON-BLOCKING WITH SAFEGUARDS**.
- **Severity / workaround:** Medium; freeze model/settings/prompt and label existing results by actual candidate.
- **Candidates / postponed work:** Same E5-B architecture at 0/0.5/1.0, at least three runs each, controlled quotas, error/consistency analysis. Do not run the deferred 312-call suite.
- **Prerequisites / revisit:** Explicit future authorization and reserved quota, or Phase 14 evidence that upstream variance is material. **Acceptance:** comparable repeated runs with failure-aware scoring, latency/token provenance and a predeclared decision rule.
- **Reproduction / references:** `data/interim/phase8_2/temperature_experiment_results.json`, Phase 8.2 research and final report.

### ISSUE-05 — Evaluation metric integrity

- **Original mapping / status / severity:** P8-06; **RESOLVED**, Medium.
- **Evidence:** Audit corrected historical 98% exact match: it omitted soft preferences. Original-50 common-field exact match is 54%; old held-out-20 v1/v2 comparison is 40%/60% common fields. Full-v2 E5-B exact match is 50%. Independent, versioned scorers now report capabilities explicitly.
- **Root cause / implementation:** Old scoring masked missing fields and failure cases. Code: `src/shopassist/llm/evaluation.py`, `experiments/metrics.py`, `experiments/phase82/scoring.py`.
- **Downstream impact:** Phase 9 component checks remain independent; Phase 10–17 must use metric names/scope correctly. **NON-BLOCKING WITH SAFEGUARDS**.
- **Severity / workaround:** Medium; retain old scorer only for historical reproduction; use versioned metrics and denominators.
- **Candidates / postponed work:** Regression tests on new schema versions; do not reopen without new scoring evidence.
- **Prerequisites / revisit:** Any schema or evaluator change. **Acceptance:** tests make missing-field and transport-failure policies explicit.
- **Reproduction / references:** `python scripts/audit_phase8_evaluation.py`, `python scripts/audit_phase8_2.py`, scoring tests and JSON audits.

### ISSUE-06 — Rule-based overcorrection and boundary semantics

- **Original mapping / status / severity:** P8-03, P8-04, P8-11; **IMPROVED**, High.
- **Evidence:** Historical rules damaged 9/18 authored oracle cases; narrow conservative rules preserved all 18. This proves invariance on those authored cases, not general accuracy. Production rules were not switched. v1 also cannot express strict/inclusive boundaries; foreign currencies require clarification and are not converted.
- **Root cause / implementation:** Broad negation, operator, domain and substring rules can alter intent. Experimental isolated rules: `src/shopassist/llm/experiments/phase82/rules.py`; production normalization remains in `src/shopassist/llm/normalization.py`.
- **Downstream impact:** Phase 9 catches common negative strings and non-INR currency, but is not a full parser. Phase 10 filters must preserve strict/inclusive gaps and never treat negatives as positives; Phase 11/12 cannot hide these gaps. Phase 13/14 must include negation/boundary cases; Phase 15–17 must request clarification when unsupported. **NON-BLOCKING WITH SAFEGUARDS**, with a per-query stop when unresolved.
- **Severity / workaround:** High; only apply explicit supported constraints, no currency conversion, no silent exclusion drops.
- **Candidates / postponed work:** Negation scope, context-aware product types, numeric-operator binding, rule ablation and conservative correction.
- **Prerequisites / revisit:** Versioned consumer contract and adversarial/annotated cases. **Acceptance:** no mandatory exclusion/boundary is silently accepted when unsupported; independent tests cover ambiguous scopes.
- **Reproduction / references:** `python -m pytest tests/test_phase8_2_rules.py`; `rule_ablation_results.json`, Phase 8.2 issue investigation and query contract review.

### ISSUE-07 — Brand, compatibility target and entity/filter semantics

- **Original mapping / status / severity:** P8-07, P8-12; **UNRESOLVED**, High.
- **Evidence:** Boeing is a named manufacturer in QU033; HELD020's “seat cover for Honda City” illustrates vehicle compatibility being confused with accessory brand. Entity recognition and supported SQL filter activation are different decisions.
- **Root cause / implementation:** Production schema has one brand slot and no typed compatibility target. Code: `src/shopassist/llm/schemas.py`, `normalization.py`, `refinement_rules.py`.
- **Downstream impact:** Phase 9 preserves only the provided semantic query/preferences and must not invent a brand. Phase 10 must not filter on a compatibility entity as accessory brand; Phase 11/12 need provenance; Phase 13/14 need entity-policy annotations; Phase 15–17 must surface unsupported entities. **QUALITY RISK / NON-BLOCKING WITH SAFEGUARDS**.
- **Severity / workaround:** High; do not activate a brand filter unless the contract clearly identifies requested product brand; ask when target is unclear.
- **Candidates / postponed work:** Separate requested brand, manufacturer mention, compatibility target, unsupported entity and active-filter fields; adjudicate Boeing/Honda policy.
- **Prerequisites / revisit:** Catalog policy and versioned schema migration. **Acceptance:** reviewed cases distinguish entity from SQL filter activation with no silent filter corruption.
- **Reproduction / references:** `data/interim/phase8_2/failure_analysis.json`; issue investigation ISSUE-07 and query contract review.

### ISSUE-08 — Ground truth, sample coverage and annotation quality

- **Original mapping / status / severity:** P8-12; **IMPROVED**, High.
- **Evidence:** Phase 8.2 prepared 80 unique cases (20 dev, 20 validation, 40 held-out), disjoint from old fixtures; development still overlaps original-50 on 13/15 queries. Independent annotation review is pending. Disjoint text does not prove semantic independence.
- **Root cause / implementation:** Hand-authored small datasets and unresolved policy judgments. Fixtures under `tests/fixtures/phase8_2/`.
- **Downstream impact:** Phase 9 curated component cases are useful correctness checks but not population-quality estimates. Phase 10–12 quality claims remain **QUALITY RISK**; Phase 13 is the intended owner; Phase 14 must keep a locked held-out set; Phase 15–17 should monitor live errors. No phase is code-blocked.
- **Severity / workaround:** High; label evidence type and test deterministic behavior independently of Gemini.
- **Candidates / postponed work:** Independent annotator review, disagreement adjudication, realistic coverage expansion and frozen held-out set.
- **Prerequisites / revisit:** Phase 13. **Acceptance:** annotation policy and adjudication documented; split integrity verified; evaluation size and uncertainty reported.
- **Reproduction / references:** `python scripts/build_phase8_2_fixtures.py`; `dataset_integrity.json`, `verification_report.json`.

### ISSUE-09 — Latency, token costs and provenance

- **Original mapping / status / severity:** P8-08; **IMPROVED**, Medium.
- **Evidence:** Instrumentation now records content fingerprints, stages, retry/time reservations and token usage. Fresh comparative inference timing is absent; old cache timings and historical timings cannot establish a speedup or current SLO.
- **Root cause / implementation:** Earlier cache identity and attempt accounting were incomplete. Code: `src/shopassist/llm/experiments/{runner.py,phase82/runner.py}` and `gemini_client.py`.
- **Downstream impact:** Phase 9 local encoder latency is measured separately; Phase 10–12 need stage-level timing; Phase 13/14 need comparable measurements; Phase 15–17 need production SLOs. **NON-BLOCKING WITH SAFEGUARDS**.
- **Severity / workaround:** Medium; label cached/live timing and avoid extrapolating historic numbers.
- **Candidates / postponed work:** Fresh uncached runs, retry and rate-limit time, token economics and production percentiles.
- **Prerequisites / revisit:** Controlled live budget and deployment telemetry. **Acceptance:** measured attempts, retries, cache source, tokens and latency have provenance and fixed protocol.
- **Reproduction / references:** Phase 8.2 runner tests, experiment registry and final report.

### ISSUE-10 — Schema v1/v2 semantic compatibility and deferred single-turn limitations

- **Original mapping / status / severity:** P8-03, P8-04, P8-10, P8-11; **UNRESOLVED** for semantic loss; multi-turn and currency conversion are **DEFERRED**; High for unsafe conversion.
- **Evidence:** v2→v1 adapter loses product type, typed exclusions, strict/inclusive boundary flags and may serialize negative concepts as ordinary preferences; v1 caps preferences at ten. Multi-turn references are not supported. INR-only catalog cannot safely apply USD/EUR amounts.
- **Root cause / implementation:** Target v1 has no corresponding typed fields; structural validity does not preserve meaning. Code: `src/shopassist/llm/schemas.py`, `schema_variants.py`, `docs/phase8_query_contract.md`.
- **Downstream impact:** Phase 9 uses v1 and refuses common negative/currency cases; Phase 10 must preserve typed contract and block lossy filters; Phase 11/12 must not imply lossless interpretation. Phase 13/14 test adapter behavior; Phase 15–17 request clarification for unsupported query. **NON-BLOCKING WITH SAFEGUARDS**; individual unsupported requests stop.
- **Severity / workaround:** High; keep v1 accepted in production, do not auto-adapt v2 as if lossless, clarify foreign currency/multi-turn references.
- **Candidates / postponed work:** Explicit schema version negotiation, migration with consumer support, separate currency conversion policy and conversation state owner.
- **Prerequisites / revisit:** Downstream Phase 10 contract and explicit product decision. **Acceptance:** lossless versioned representation or explicit unsupported status for every dropped field; no INR filtering of foreign values.
- **Reproduction / references:** Schema adapter tests; `phase8_2/query_contract_review.md`, ISSUE-10 and final report.

### ISSUE-11 — Documentation consistency

- **Original mapping / status / severity:** P8-05, P8-06; **RESOLVED**, Medium.
- **Evidence:** Phase 8.2 corrected old “seven resolved” count (list enumerated eight), exact-match scope, v1 production status and claims about latency, quotas, determinism and readiness. Historical documents retain superseding notices and original results.
- **Root cause / implementation:** Narrative statements outran the underlying evidence. Relevant source docs: README, Phase 8/8.1/8.2 reports, issue register.
- **Downstream impact:** Phase 9 docs preserve extraction-versus-representation responsibility; Phase 10–17 use current status and metrics. **NON-BLOCKING WITH SAFEGUARDS**.
- **Severity / workaround:** Medium; this freeze handover is canonical current status and old report corrections remain visible.
- **Candidates / postponed work:** Keep roadmap and machine reports synchronized as phases change.
- **Prerequisites / revisit:** Any change of production contract or accepted metrics. **Acceptance:** README, current status, code and artifacts agree; old results remain clearly historical.
- **Reproduction / references:** `data/interim/phase8_2/verification_report.json`, `final_engineering_report.md`.

### ISSUE-12 — Operational security, robustness and lifecycle

- **Original mapping / status / severity:** P8-13, P8-14, part of P8-09; **IMPROVED**, High.
- **Evidence:** API key representation and provider error redaction improved; retry ownership is singular; Windows SSL teardown was reproduced and same-loop cleanup added. Two unique live smoke tests passed twice. Injection immunity, raw diagnostic retention policy, strict coercion, finite numeric checks and full live coverage remain open.
- **Root cause / implementation:** Exception leakage, overlapping retry layers, event-loop-owned SDK resources, and unreviewed raw response retention. Code: `src/shopassist/llm/{security.py,gemini_client.py,query_understanding.py,schemas.py}`.
- **Downstream impact:** Phase 9 avoids echoing provider exceptions and halts invalid input; Phase 10–12 must validate finite values and avoid raw private diagnostics; Phase 13/14 use synthetic/offline fixtures carefully; Phase 15–17 require injection tests, retention/access policy, secret redaction and lifecycle checks. **QUALITY RISK**, individual security/lifecycle defects can block deployment.
- **Severity / workaround:** High; keep raw response private, never log credentials, apply finite numeric validation at consuming boundaries, and require clarification for untrusted/unsupported intents.
- **Candidates / postponed work:** Threat-model injection, retention/access controls, strict schema coercion, finite number validation, broader live lifecycle suite.
- **Prerequisites / revisit:** Before external deployment, earlier if an incident occurs. **Acceptance:** adversarial test coverage, redaction/retention policy, finite numeric and strict input validation, leak-free lifecycle run.
- **Reproduction / references:** `python -m pytest tests/test_phase8_2_reliability.py`; inspect `smoke_retest.xml`, `verification_report.json` and final report.

## Cross-phase dependency assessment

Legend: **B** = BLOCKING; **S** = NON-BLOCKING WITH SAFEGUARDS; **Q** = QUALITY RISK; **D** = DEFERRED FEATURE; **—** = no direct dependency. For each row, listed phase IDs cover Phases 9 through 17 in order.

| Issue | 9 Pref. | 10 Hybrid | 11 Rerank | 12 Generate | 13 Dataset | 14 Eval | 15 API | 16 Bot | 17 Deploy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ISSUE-01 extraction | Q | Q/S | Q | Q | S | S | S | S | Q |
| ISSUE-02 full intent | S | Q/S | Q | Q | S | S | S | S | Q |
| ISSUE-03 provider failure | S | S | S | S | S | S | S | S | Q/S |
| ISSUE-04 temperature | — | — | — | — | S | S | — | — | — |
| ISSUE-05 metrics | S | S | S | S | S | S | — | — | — |
| ISSUE-06 negation/boundary | S | S (stop unsupported) | S | S | S | S | S | S | S |
| ISSUE-07 entity semantics | S | S (no unsupported brand filter) | Q | Q | S | S | S | S | Q |
| ISSUE-08 dataset | S | Q | Q | Q | S | S | Q | Q | Q |
| ISSUE-09 measurements | — | S | S | S | S | S | Q | Q | S |
| ISSUE-10 schema loss/multi-turn/currency | S | S (clarify unsupported) | S | S | S | S | S | D/S | D/S |
| ISSUE-11 docs | S | S | S | S | S | S | S | S | S |
| ISSUE-12 security/lifecycle | S | S | S | S | S | S | S | S | Q/S |

No planned implementation phase is globally blocked by these issues when its boundary returns explicit failure/clarification results and preserves the v1 version. Unsupported exclusions, non-INR prices, ambiguous compatibility entities, invalid model output and clarification-required requests must stop the affected request. Phase 17 deployment is blocked until security, retention, finite-value and lifecycle gates in ISSUE-12 are met.

## Deferred work policy

Phase 8 extraction optimization remains frozen until Phase 14 identifies a material upstream cause, a mandatory user constraint fails, realistic exclusions/product types show severe errors, the public contract changes, or a security/reliability incident requires earlier action. Any live Gemini experiment requires a separately bounded design; the deferred 312-call suite is not run under this handover.
