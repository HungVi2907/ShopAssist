# Phase 8 Freeze and Technical Handover

**Freeze date:** 2026-10-10 (Asia/Saigon). **Accepted production state:** Phase 8 implemented on Schema v1 with known limitations. **Phase 8.2:** partial; offline research and validation completed, larger live optimization deferred. This is a continuation decision, not a claim of production-grade semantic accuracy.

## Executive summary and reason for freezing

Phase 8 production behavior is preserved so ShopAssist can implement and evaluate the downstream pipeline before spending more time optimizing extraction. Its open issues remain in the [technical debt register](technical_debt/phase8_deferred_issues.md). The four planned Phase 8.2 live comparisons and the 312-call Gemini suite were not run as part of this work.

## Current production architecture and configuration

Verified from `src/shopassist/llm/query_understanding.py`, `prompts.py`, `schemas.py`, `normalization.py`, `config.py`, `gemini_client.py`, `.env` model settings and Phase 8.2 source audit:

| Item | Frozen value |
| --- | --- |
| Provider/model | Google Gemini, `gemini-3.1-flash-lite` |
| Temperature | `0.0` |
| Output cap / timeout / application retry maximum | 2048 tokens / 30 seconds / 3 |
| Production schema | `QueryUnderstandingOutput`, v1 fields |
| Prompt | Original `SYSTEM_INSTRUCTION` from `src/shopassist/llm/prompts.py`; query text is added by `build_user_prompt()` |
| Entry points | `QueryUnderstandingEngine.parse_query_async()` and synchronous `parse_query()` |
| Pipeline | input validation → Gemini structured response → Pydantic v1 validation → existing category/brand/currency normalization and business rules → `QueryUnderstandingResult` |
| Experimental code | Schema v2/E5-B, candidate prompts and Phase 8.2 rules are not production-selected |

`data/interim/phase8_freeze_manifest.json` records the initial commit, clean pre-freeze worktree, configuration, active prompt hash, source hashes, preserved test evidence and deferred work. The `.env` API key is never included. Historical data files remain intact.

## Current query contract

The production result is `QueryUnderstandingResult(query, output, ..., is_valid, validation_errors)`. The v1 `output` has `semantic_query`, `hard_constraints`, `soft_preferences`, `needs_clarification` and `clarification_reason`. Hard constraints include category, brand, min/max price, min rating and currency. Soft preferences are normalized to lowercase, de-duplicated, and truncated to ten by the current schema. A valid Pydantic object is not proof that extracted meaning is correct.

Phase 9 consumes this v1 object without changing it. It stops on `is_valid=False`, clarification, unsupported non-INR currency, or a detected negative/exclusion phrase. It never reinterprets numeric/brand hard constraints.

## Verified quality baseline and experiment history

Original Phase 8, audited stored-output results: hard-constraint micro F1 **99.70%**, soft-preference macro F1 **66.41%**, common-field exact match **54.00%** on 50 queries. The historical 98% exact match excludes preferences and is not full intent accuracy.

On a separate historical held-out set of 20, production-style v1 versus experimental E5-B/v2 had hard micro F1 99.22% vs 99.22%; soft macro F1 65.00% vs 78.33%; shared-field exact match 40% vs 60%; experimental full-v2 slot exact match 50%. This is stored-output reanalysis with broad uncertainty and no production promotion. Experimental E5-B exclusion micro F1 is 28.57% on a small sparse sample.

Phase 8.2 reconciles 12 investigations as 3 RESOLVED, 4 IMPROVED, 4 UNRESOLVED and 1 DEFERRED. The issue-level original-ID map and evidence are in the debt register. The prepared 80-case split does not have independent annotation approval. Historical latency/token reports do not prove a fresh comparative speed or cost improvement.

## Outstanding issues and downstream risks

High priority: soft extraction quality, complete intent accuracy, rule/negation safety, entity versus filter semantics, small/unreviewed labels, v1/v2 semantic loss, and security/robustness. Provider quota remains an operational risk despite correction of diagnostic classification. Temperature selection remains deferred. Metric integrity and documentation correction are resolved but remain under regression control.

For Phases 9–17, a limitation is generally non-blocking when the affected request returns explicit unsupported/clarification status. Phase 10 must not treat negative preferences as positive evidence, silently ignore exclusions, apply foreign currency amounts to INR prices, execute clarification-required requests, or claim v1 preserves strict inequalities. Phase 17 must satisfy the remaining security and lifecycle gates.

## Phase 9 integration contract

Input is the validated Phase 8 v1 `QueryUnderstandingResult`. The component uses only `semantic_query`, `soft_preferences`, `is_valid`, `needs_clarification`, `clarification_reason`, and currency as a safety gate. Positive preferences are normalized deterministically and composed with the semantic context; the shared Phase 7 query encoder supplies an optional 384D unit vector. No-preference results have no preference vector; Phase 7 remains the base query encoder.

## Phase 10 integration risks

The representation is a preference signal, never a hard-constraint filter. Phase 10 must independently validate vector model, dimension, finite values and normalization; enforce only supported hard constraints; preserve preference and constraint provenance; and stop rather than silently dropping unsupported exclusions, foreign currency, ambiguity or lost schema-v2 fields. Similarity does not guarantee that every preference is satisfied.

## Technical-debt policy and deferred optimization

Preserve each current issue state; postponed work does not convert an unresolved issue to resolved. Return to broad prompt/schema/temperature optimization after Phase 14 attributes errors to query understanding, or earlier if mandatory constraints fail, exclusion/product-type errors are severe, the public contract changes, or a security/reliability incident occurs. The live temperature/prompt/schema comparison, independent annotation, fresh held-out runs, and full live test suite remain future work.

## Regression and frozen artifacts

The latest Phase 8.2 repository evidence is 376 passed / 0 failed, excluding the Gemini integration module. A two-test bounded live subset passed twice; four other Gemini tests were not rerun. Those are preserved historical verification results, not tests rerun for this freeze. Current environment limitations and Phase 9 verification are recorded separately in the Phase 9 evaluation report.

Frozen source and raw experiment artifacts are identified by hash in the manifest. No Phase 8 prompt/model/temperature/schema/extraction change, Gemini optimization call, product database update, or product embedding regeneration is part of this handover.

## Revisit triggers and acceptance decision

Revisit Phase 8 after Phase 14 end-to-end evaluation; evidence that extraction is a primary recommendation error source; any failure of a mandatory user constraint; significant realistic exclusion/product-type failures; a public-contract change; or a severe security/reliability event. Fix severe integration/security defects earlier.

**PHASE 8 — IMPLEMENTED / ACCEPTED WITH KNOWN LIMITATIONS**  
**PHASE 8.1 — EXPERIMENTAL REFINEMENT COMPLETE / NOT FULLY ADOPTED IN PRODUCTION**  
**PHASE 8.2 — PARTIAL / RESEARCH AND OFFLINE VALIDATION COMPLETE / LIVE OPTIMIZATION DEFERRED**
