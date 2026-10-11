# Phase 13 annotation guidelines

The concrete task files, version sequence, and commands are in [phase13_review_handoff.md](phase13_review_handoff.md). The `v2` expansion is draft material; its catalog audit supplies planning evidence only and contains no human labels.

## Review order

1. Review the query itself. Two annotators independently fill the Phase 8 v1 fields and stop behavior from user meaning. Do not view model outputs.
2. Reconcile interpretations and explicit price operators. Record disagreements and a reason; preserve the two original rows.
3. Capture and freeze Phase 10 pools from the reconciled interpretation. Give product reviewers query text, verified structured catalog fields, and canonical `retrieval_text`. Hide rank, RRF, dense/lexical score, model names, and other labels.
4. Two annotators independently grade each query-product pair and flag constraint violations. An adjudicator records a final grade with a reason where reviewers differ. Never average grades silently.
5. Freeze selected Phase 12 outputs and evidence. Review individual claims and the overall explanation independently, then adjudicate. Citation validity alone does not prove semantic support.
6. After annotation is complete, inspect near-duplicate flags, assign groups to development or held-out, freeze the version, and restrict held-out access to final evaluation.

## Query interpretation

Use exactly one of the nine taxonomy values in the contract. `planning_category` and `query_type` in the seed are suggestions; reviewers can correct them. Set a canonical category only when the request indicates a supported product domain. Extract a brand only if explicit. An unmatched requested brand stays as spoken and may produce zero results. `currency` defaults to INR; explicit foreign currency requires clarification/unsupported downstream handling. Never convert money silently. Record numeric rating only when explicit; absent catalog ratings do not satisfy a minimum rating.

Record `under 2000` as `max_price=2000`, `max_operator=<`; `up to 2000` as `<=`; `above 500` as `min_operator=>`; `at least 500` as `>=`. Price applies to discounted price. `max 3000` is inclusive unless context says otherwise. If wording is genuinely ambiguous, flag it for adjudication. Do not project the Phase 8 v1 inclusive-only default onto the user's intended strict bound.

For preferences, use short positive phrases at a useful semantic granularity: `easy to carry` and `portable` may match for scoring; `comfortable` and `breathable` remain distinct. Split a compound phrase when both parts are independently testable. Preserve use-case meaning such as `for daily jogging`; do not invent features such as waterproofing merely because the activity is outdoors. A category/product identity is not automatically a soft preference. Keep negations and exclusions out of the positive list; current Phase 9 can stop on recognized exclusion intent. Vietnamese text remains in natural Vietnamese; normalizers can use NFC and case folding without pretending that translation is exact.

`NO_RESULTS` requires verified catalog evidence under the exact constraints. Treat the two very-low-price pilot queries as *candidates* for this stratum until checked. `CLARIFICATION_REQUIRED` covers ambiguity and out-of-domain requests supported by Phase 8. Foreign currency and explicit exclusions may produce `UNSUPPORTED_INTENT` downstream; annotate the expected stage and reason. Do not manufacture a product response for stopped cases.

## Relevance and constraints

Reuse Phase 11's 0–3 scale. **3:** product identity and all visible positive requirements fit. **2:** relevant product with one missing or weak secondary detail. **1:** related family with an important mismatch. **0:** unrelated or contradictory, including a clear hard-constraint violation. Grade >=2 is relevant for binary metrics. A true category, brand, price, rating, or other explicit hard violation cannot coexist with grade >=2. Record each flag separately. A missing attribute is unknown, not a negative claim; if it prevents confirming an explicit hard requirement, explain the uncertainty and adjudicate conservatively. Wrong vehicle fitment, wrong explicit gender, and artificial leather when genuine leather is required are important mismatches.

For each candidate, base judgments on product title, canonical evidence, and verified metadata. Do not use retrieval score, generation explanation, or model ranking as authority. Additional candidates beyond the Phase 10 pool need their own source and freeze record, especially for Recall@K denominators.

## Generation review

Freeze provider, model version, prompt/context configuration, returned recommendation, candidate IDs, claim text, evidence IDs, and evidence text. Label support as `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, or `NOT_ENOUGH_INFORMATION`. Also record factual correctness, whether the explanation addresses the shopping request, and whether missing information is represented as *not specified* rather than *does not have*. An evidence ID belonging to the right product is a structural check only. A claim can still exaggerate, contradict, or overgeneralize its cited evidence. Review summary reasons and comparison notes as claims where they assert facts.

Factual correctness uses `CORRECT`, `PARTIALLY_CORRECT`, `INCORRECT`, or `NOT_ENOUGH_INFORMATION`. Recommendation relevance uses `RELEVANT`, `PARTIALLY_RELEVANT`, or `IRRELEVANT`. Missing-information handling uses `CORRECTLY_DISTINGUISHED` when the wording properly identifies absent evidence, `MISSTATED_ABSENCE` when it claims the product lacks a feature that is merely unspecified, and `NOT_APPLICABLE` when no missing-attribute assertion occurs. Record each reviewer's label before the adjudicated value.

## Adjudication and agreement

Assign stable real reviewer IDs; never invent them. Keep independent rows private until both are submitted. Preserve both values and the adjudicated result with a short reason. Report exact agreement and weighted Cohen's kappa on the actually double-reviewed pairs; state sample size and null if too small or undefined. Do not merge unresolved rows into frozen qrels. The manifest reviewer count must reflect actual humans. Machine suggestions, if used, must be marked as draft assistance and are never a reviewer.
