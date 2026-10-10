# Phase 8.2 final engineering decision

Date: 2026-10-09. **Decision: PARTIAL. Offline deliverables completed; larger live comparisons were explicitly deferred by the user.** Keep refining Phase8 before accepting broad Phase9 readiness. No new extraction prompt, temperature, rule set or schema was promoted to production.

## Findings and methods

Twelve investigations cover soft extraction, exact-match quality, provider failures, temperature, scoring, rules, entity/filter semantics, dataset integrity, measurement, adapters, documentation and operational safety. Official Google structured-output/SDK/prompting/temperature/rate/pricing guidance and primary negation/paired-evaluation/self-consistency literature informed isolated candidates. Source titles, dates and URLs are in research_review.md. No research source proves a task-specific winner.

Offline work independently audited original50/dev15/oldheld20, replayed each rule group on identical raw responses, verified oracle invariance, authored80 new labels, built content-hashed registry and persistent budget runner, and executed mocked reliability and repository regression. Four bounded production generation calls tested connectivity/foreign currency and lifecycle; there was no large live run.

## Implemented changes and reasons

- config.py hides API key in repr/model serialization; security.py redacts configured/patterned credentials; engine and client errors expose safe types/status instead of raw provider text or user-query logs.
- gemini_client.py disables hidden SDK retries, uses exact model identifiers, extracts usage before validation, separates JSON/Pydantic stages and attempt/retry timings, accepts instrumentation hooks, and closes clients on their owning loop. Synchronous wrappers close in finally; Windows SSL transport drain is included.
- query_understanding.py keeps original prompt/schema/normalization and returns safe generic failure reasons.
- experiments/phase82 implements independent failure-aware metrics, uncertainty, consistency, isolated prompts/schema/rules, actual-content cache hashes, successful-response-only cache, persistent attempts/token reservations and resumable records.
- scripts audit frozen historical scorers, build authored fixtures, run opt-in experiments with dry-run default, and reproduce reports. New tests cover metrics, linguistic rules, reliability, cache/provenance and budgets. Gemini test lifecycle closes sessions before its loop shuts down.

These address reproducible accounting/lifecycle/security defects without claiming new semantic accuracy. Research caches and fixtures contain synthetic shopping text; customer-data retention/access policies remain to be designed.

## Final architecture and configuration

Production: bounded single-turn input → original v1 prompt → configured Gemini → JSON/Pydantic validation → existing category/brand/currency normalization → v1 result/clarification. Model remains gemini-3.1-flash-lite, temperature0, output cap2048, timeout30s, application max_retries3. SDK automatic attempts1 makes the application the only retry owner. Safe diagnostics/resource cleanup are implemented; production extraction semantics unchanged. Experimental v2 is isolated and has no consumer switch.

Original raw artifacts, fixtures and production prompt/schema remain preserved. Initial working-tree changes were not reverted. Database, product data, indexes and embeddings were not modified or regenerated. v2→v1 is structurally valid but semantically lossy; migration approval is still required before consumer changes.

## Quality and performance evidence

| Stored output reanalysis | Valid | HC micro F1 | Soft macro F1 | Soft micro F1 | Common EM | Full v2 slot EM |
| --- | --- | --- | --- | --- | --- | --- |
| Original50 (different dataset) | 100.00% | 99.70% | 66.41% | 76.32% | 54.00% | N/A |
| Old heldout20 E1-A/v1 | 100.00% | 99.22% | 65.00% | 72.34% | 40.00% | N/A for fair comparison |
| Old heldout20 E5-B/v2 | 100.00% | 99.22% | 78.33% | 75.00% | 60.00% | 50.00% |

The oldheld20 shared-field improvement of20 points has bootstrap95 interval−5 to+45 points. E5-B fullv2 EM=50%, soft macro78.33%, product/exclusion exact90%, brand95%; exclusion micro28.57% exposes sparse-negative failures. Offline conservative replay reaches full60%/soft80% on that already inspected sample while preserving literal manufacturer entities; it is not a new heldout model result. New comparative inference latency/tokens and repeated-run accuracy are unavailable. Historical timing/token medians are descriptive with incomplete provenance.

## Verification

| Executed check | Passed | Failed/errors | Scope |
| --- | --- | --- | --- |
| baseline_tests | 296 | 0 | Offline |
| focused_tests | 101 | 0 | Offline |
| regression_tests | 376 | 0 | All tests except Gemini integration module |
| smoke_tests | 2 | 0 | Bounded live subset; 2 distinct tests |
| smoke_retest | 2 | 0 | Bounded live subset; 2 distinct tests |

Final repository run passed376 tests, excluding the Gemini integration module. Targeted run passed101 overlapping tests; do not sum overlapping totals as distinct coverage. Original baseline offline run passed296 with12 integration-marked tests deselected. Production smoke passed2 tests twice (four calls, two unique tests), with initial SSL warnings and clean SSL retest after lifecycle fix. Remaining SDK deprecation warnings are upstream technical debt. Other four Gemini tests were not rerun; full live suite acceptance remains pending.

## Adoption, rejected approaches and next gates

Reject immediate candidate adoption, universal temperature optimum, guaranteed cloud determinism/schema success, broad regex semantic edits, treating unsupported manufacturers as NER errors, and old cache latency as fresh speed evidence. No provider/model change, typed-preference expansion or phase9/10 implementation occurred.

Open gates: independent annotation/adjudication; approved same-E5-B temperature/prompt/schema comparisons; locked validation/freshheldout evaluation; category-level error analysis; repeat sampling; finite numeric/strict coercion policy; negatives/boundary consumer migration; customer-text retention; and measured injection robustness. Multi-turn and currency conversion remain deferred scope limitations. Phase9 interface prototyping can proceed with documented gating and limitations, but quality readiness is not PASS.

## Acceptance ledger

Completed: repository/source/artifact review; independent historical audit; twelve evidence classifications; external research; controlled design; isolated infrastructure and budget tests; standardized metrics; product/exclusion analysis; rule audit;80-case partition preparation; safe reliability changes; offline regression; bounded live subset; seven reports; machine artifacts; historical documentation synchronization.

Pending by user decision: E5-B repeated temperature execution; live prompt/schema comparisons; independent expanded evaluation; newly selected semantic candidate; full live suite and production semantic adoption. Pending quality review: independently adjudicated annotations. These pending items are not marked passed. The authorized offline scope is complete; the comprehensive live optimization objective remains PARTIAL.
