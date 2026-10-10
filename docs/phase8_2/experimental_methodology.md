# Phase 8.2 experimental methodology

Date: 2026-10-09. Scoring policy: `phase82-1.0`. Execution boundary: offline audit, mock reliability and small production smoke completed; large live experiments deferred by the user.

## Objectives, hypotheses and controls

RQ1-3 investigate defects and field failures; RQ4 temperature; RQ5 prompts; RQ6 schema; RQ7 deterministic rules; RQ8 evaluation; RQ9 efficiency; RQ10 downstream readiness. Candidate hypotheses and source references are in [research review](research_review.md). B0 preserves E5-B, T05/T10 change only temperature, C2-C5 change only prompt, D1 only required schema slots, E6 only rules. All other variables retain configured Gemini model, output cap, input wrapper, timeout, single-call extraction, dataset, scoring, SDK retry owner and seed. Randomize request order with seed82 to reduce time/quota confounding.

Freeze development candidates before validation, and freeze the selected candidate before fresh heldout. Choose at most two candidates, apply quality guardrails, rank full-v2 EM then strict soft macro F1 then cost. No winning configuration has been selected without live evidence.

## Baseline and data protocol

`baseline_manifest.json` records original hashes and dirty working tree; original LLM code is copied under baseline_sources. Production prompt/schema/semantic normalization remain unchanged. Historical fixtures and raw output artifacts remain unchanged.

New dataset v1.0.0: development20, validation20, heldout40. Eighty explicitly authored labels precede live predictions; one annotator only, independent review PENDING. All sixteen categories appear across the dataset. Coverage includes synonyms, misspellings, short/long inputs, intended use, class nouns, multiple brands/products, compatibility, price correction, units, ratings, qualifiers/double negation, unsupported domains, foreign currency, Vietnamese/mixed language, conversational references and injection strings. Exact duplicate and cross-split overlap checks pass. The old development fixture overlaps original50 in 13 queries; it cannot support a claim of fully independent development data.

Annotation rubric: identify the requested item class, canonical English category/product type, explicit requested manufacturer, literal numeric constraints with final corrections, active boundary operators, positive attributes/intended-use phrases, and scoped typed rejections. Preferences retain source language and prepositions; case/whitespace normalization is scoring-only. Compatibility target is not requested accessory brand. Multiple unresolved alternatives require clarification rather than arbitrary scalar selection. INR is default; unsupported currency/domain requires clarification while preserving explicit intent. Double negatives must be interpreted by scope, not cue count. Product-class adjectives belong to product_type only when class-defining in context.

Adjudication procedure before model runs: second annotator reviews without seeing predictions, flags disagreements, records a rationale and final policy, then versions changed labels and reruns controls. Examples needing review include feature-versus-attribute typing, articles in negative phrases, analog/gaming class specificity, and unsupported-domain attributes. Do not silently edit old benchmark labels. Fresh heldout is an authored test partition, not yet an independently validated population sample. Its text was inspected for integrity and design, never used to tune candidate predictions.

## Metrics and applicability

For typed/value atom sets A (actual) and E (expected): TP=|A∩E|, FP=|A−E|, FN=|E−A|.

\[P=TP/(TP+FP),\quad R=TP/(TP+FN),\quad F_1=2TP/(2TP+FP+FN).\]

Valid both-empty preference sets score1. Empty prediction with nonempty truth has recall/F1=0; undefined precision is represented as1 by the explicit empty-prediction convention, so macro precision must not be mistaken for accuracy. Any failed service/validation row scores0 for preference/exclusion macro metrics and exact matches, even if the truth is empty. Wrong hard values count both FP and FN. Hard atoms contain category, brand, min_price, max_price, min_rating and default INR currency. Null slots are compared for field accuracy but contribute no hard atoms. Integers and equivalent floats compare numerically; text is trimmed/casefolded/whitespace-collapsed; list order and duplicates are ignored.

\[EM=N^{-1}\sum_{i=1}^N \mathbf{1}[\text{all applicable fields equal and result valid}].\]

Common EM covers six hard slots, soft preference set and clarification flag. It is the fair v1/v2 comparison. Full v2 slot EM additionally covers explicitly annotated product_type, typed exclusions, and flags only for present numeric bounds. Missing actual fields fail even if expected product_type is null. Full-v2 on v1 outputs is a capability diagnostic, not a fair quality uplift; publish N/A in fair comparison tables. Unannotated fields have denominator0 and N/A, not invented accuracy. Hard EM and soft EM are separate. Semantic-query exact wording and clarification-reason wording are excluded from slot EM, with semantic-query lexical match supplementary; no claim of literal complete-output equality is made.

Strict soft macro F1 is the historical headline; micro F1 pools atoms and exposes prevalence. Exclusion target type is part of each atom. Publish micro exclusions alongside macro/exact scores because many empty exclusions inflate macro. A small fixed equivalence map is supplementary only (e.g. lumbar support/with lumbar support); it does not accept opposite meaning or replace the strict benchmark. Schema validity is end-to-end validated extraction rate; record API response, JSON syntax and Pydantic stage separately. Hallucination proxy is reference-relative false-positive hard atoms/query rate, not an exhaustive hallucination detector.

## Groups and request accounting

A independently recomputes original50/dev15/oldheld20 stored outputs using frozen historical and new scorers. B compares same E5-B at0/.5/1 on nine development queries, three independent repetitions. Add11 B0 control calls for full development coverage. C compares four prompts on20; D required-slot schema on20. E applies each original/narrow rule group and all groups to identical valid raw outputs, excludes provider failures equally and reports corrected/introduced full-match cases. F tests eighteen oracle inputs for rule invariance and prepares the remaining multilingual/adversarial cases for future live extraction. G uses fake SDK responses for bounded retry, cache and lifecycle tests.

Future plan:312 planned calls, ceiling360 attempts/500k charged-reserved tokens; zero retries in screening, pacing≥4s. The user selected offline completion, so this is a proposal rather than authorization. Production smoke used four generation calls total: two tests once, then the same two tests after cleanup correction. No comparative candidate requests were submitted.

Budget reserves visible prompt/user/schema UTF8 byte estimate + output cap + overhead before each submission and persists to a ledger. Settle observed usage before JSON/Pydantic validation. Unknown usage retains reservation; crashes cannot silently reset counters. A budget rejection produces no fake completed query row. This is an estimated accounting guard, not a guarantee against hidden/billable token overruns. If returned usage exceeds reservation, record the actual overrun and stop before another call. Ledger is single-process; do not run concurrent writers sharing an output directory.

## Latency, token economics and caching

Record each attempt's client-measured API round-trip, retry wait, pacing, local JSON/Pydantic and normalization time, total extraction wall time, provider model version, input/output/total usage, and unknown attempts. API round-trip includes transport/provider execution; true provider generation-only time is unavailable unless the provider reports it. Cache hits have their own lookup latency, zero generation attempts and no billed usage claim. Historical saved response times have unknown cache/retry provenance and are descriptive only.

Successful raw responses can be cached only on explicit replay paths. Fingerprint model, exact prompt/user wrapper/schema content hashes, temperature without rounding, output cap, timeout, retry settings, SDK version and query hash. Failures are never cached. Repetitions and temperature experiments prohibit cache so agreement cannot be fabricated. Resume skips only exact task/dataset/annotation/rule/scoring fingerprints. Synthetic fixtures/raw records are local research data; establish consent, retention, permissions and redaction before applying persistent caching to real customer text.

Costs: sum observed input/output/total tokens across returned responses; provider total may include additional components. Report unknown-usage attempts and reserved amounts separately. Tokens per valid and per correct extraction divide total observed cost by successful counts, including failed billed requests in the numerator. Report current provider rates as estimates, not retrospective measured bills.

## Statistics and validity threats

Wilson95 intervals accompany query proportions; paired bootstrap uses2000 query resamples, seed82 and identical IDs. On repeated sampling, whole queries are clusters; record-level confidence intervals are suppressed. Pairwise response agreement is descriptive and does not establish correctness. The current helper compares full normalized dictionaries, including wording; slot-specific variability can be assessed separately. No significance claim follows merely from overlap of intervals. Paired bootstrap here estimates effect uncertainty, not a formal universal p-value.

Threats: small handcrafted sets, single annotation author, unresolved policy ambiguities, historical development overlap, tuning on already inspected oldheld20, incomplete original cache/time provenance, mutable cloud models, quota selection bias, multiple comparisons, and unmeasured repeated runs. Offline rule oracle accuracy must not be presented as LLM accuracy. Prompts and schemas without live results remain hypotheses.

## Reproduction

```powershell
python scripts/build_phase8_2_fixtures.py
python scripts/audit_phase8_2.py
python -m pytest --ignore=tests/test_gemini_integration.py -q --junitxml=data/interim/phase8_2/regression_tests.xml
python scripts/run_phase8_2_experiments.py --dry-run --experiments B0,T05,T10 --split dev --limit 9 --repetitions 3 --max-requests 360 --max-tokens 500000 --max-retries 0 --pacing 4
python scripts/build_phase8_2_reports.py
```

Dry-run is the default, makes no provider call or report mutation, and does not create a Gemini client. A future operator must obtain a new explicit large-run approval before adding --live. Use a shared persistent ledger for cumulative budget across stages; resume exact B0 records instead of repeating controls. Current runner loads fixtures and records file/case hashes, config, repetition, timestamp, success/error stage, cache status and attempts. Plans and completed results are distinct artifacts.
