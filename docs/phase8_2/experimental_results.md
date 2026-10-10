# Phase 8.2 experimental results

Date: 2026-10-09. Decision: PARTIAL. All tables below derive from stored output audit or explicitly identified offline execution. Larger live comparisons and fresh heldout inference are NOT_RUN_USER_DEFERRED; there are no invented candidate accuracy, timing or token figures.

## Verified historical baseline and fair comparison

| Stored output reanalysis | Valid | HC micro F1 | Soft macro F1 | Soft micro F1 | Common EM | Full v2 slot EM |
| --- | --- | --- | --- | --- | --- | --- |
| Original50 (different dataset) | 100.00% | 99.70% | 66.41% | 76.32% | 54.00% | N/A |
| Old heldout20 E1-A/v1 | 100.00% | 99.22% | 65.00% | 72.34% | 40.00% | N/A for fair comparison |
| Old heldout20 E5-B/v2 | 100.00% | 99.22% | 78.33% | 75.00% | 60.00% | 50.00% |

Original50 reproduces hard micro F1=99.696%, soft macro F1=66.4095% and common EM=27/50. The historical 98% exact match omitted preferences. Original50 and oldheld20 are different datasets, so their percentages are not a before/after treatment effect.

For oldheld20, E1-A/v1 versus E5-B/v2 shared-field EM is 8/20 versus12/20, not the old full-schema 1/20 versus10/20 claim. E5-B full v2 slot EM is10/20. A v1 output cannot faithfully represent v2 fields; full-v2 capability scoring is excluded from fair quality comparisons.

## Development audit and temperature contradiction

| Historical dev experiment | Valid | HC micro F1 | Soft macro F1 (failure-aware) | Common EM |
| --- | --- | --- | --- | --- |
| E1-A | 100.00% | 98.08% | 70.00% | 53.33% |
| E1-B | 86.67% | 87.23% | 77.78% | 60.00% |
| E1-C | 86.67% | 90.72% | 80.00% | 73.33% |
| E2-A | 86.67% | 87.23% | 77.78% | 60.00% |
| E2-B | 86.67% | 91.84% | 73.33% | 60.00% |
| E2-C | 100.00% | 98.08% | 86.67% | 73.33% |
| E3 | 80.00% | 88.42% | 66.67% | 53.33% |
| E4 | 80.00% | 89.36% | 66.67% | 60.00% |
| E5-B | 86.67% | 93.88% | 80.00% | 73.33% |

E5-B's old reported HC F1=96% and soft F1=86.67% reproduce with the frozen scorer; the independent failure-aware policy yields HC F1=93.88% and soft F1=80%. QU033/QU036 are429 exhaustion, not evidence of malformed generated JSON. E2-B soft F1 falls from historical80% to73.33% when failed empty predictions no longer receive success credit. E2-A and E1-B use identical cached raw responses; they are not independent repetitions.

E2's T1 result remains descriptively better on that one v1 run, but does not prove T1 best for E5-B. New T0/T0.5/T1 E5-B comparisons are prepared and deferred. Consistency, hallucination, latency and token effects of these temperatures are not measured.

## Dataset and registry

Original50, dev15, oldheld20 remain unchanged. Thirteen dev queries overlap original50. New v1.0.0 fixtures contain20 development,20 validation,40 fresh heldout queries, with zero exact duplicates/old overlap. Independent annotation review is pending. The registry records model, prompt/schema hashes, temperature, rules and status for B0/T05/T10/C2/C3/C4/C5/D1/E6. No fresh candidate provider requests have been submitted.

| Group | Hypothesis/configuration | Dataset | New requests | Results / conclusion |
| --- | --- | --- | --- | --- |
| A | Independent historical metrics | Original50, dev15, oldheld20 | 0 | Executed; shared EM and failure policy corrected |
| B | Same E5-B, temperatures0/.5/1, three repeats | New dev9 | 0 | NOT RUN; no optimal temperature claim |
| C | Compact, contrastive, few-shot, error-focused prompts | New dev20 | 0 | NOT RUN; prompt quality/tokens/latency unknown |
| D | Required output slots versus existingv2 | New dev20 | 0 | Static review executed; provider comparison NOT RUN |
| E | Each rule group and all rules on same raw outputs | Valid raw dev13 and oldheld20 | 0 | Executed offline; see table below |
| F | Preserve known-correct oracle outputs | Authored dev18 | 0 | Historical9/18 versus conservative18/18; not model accuracy |
| G | Fake SDK failures, cache, budgets, same-loop shutdown | Offline tests | 0 | Executed; bounded production smoke separately below |
| Final | Locked candidate versus control | New heldout40 | 0 | NOT RUN; no new selected candidate |

## Rule ablation

| Rule variant / identical E5-B raw20 | HC F1 | Soft macro F1 | Common EM | Full v2 EM | Fixed full queries | New full failures |
| --- | --- | --- | --- | --- | --- | --- |
| none | 98.46% | 78.33% | 60.00% | 50.00% | 0 | 0 |
| historical | 99.22% | 78.33% | 60.00% | 50.00% | 0 | 0 |
| historical_price | 98.46% | 78.33% | 60.00% | 50.00% | 0 | 0 |
| historical_negation | 98.46% | 78.33% | 60.00% | 50.00% | 0 | 0 |
| historical_product_type | 98.46% | 78.33% | 60.00% | 50.00% | 0 | 0 |
| historical_brand | 99.22% | 78.33% | 60.00% | 50.00% | 0 | 0 |
| price | 98.46% | 78.33% | 60.00% | 50.00% | 0 | 0 |
| negation | 98.46% | 78.33% | 60.00% | 50.00% | 0 | 0 |
| product_type | 98.46% | 80.00% | 65.00% | 55.00% | HELD005 | 0 |
| brand | 98.46% | 78.33% | 60.00% | 50.00% | 0 | 0 |
| currency | 98.46% | 78.33% | 65.00% | 55.00% | HELD009 | 0 |
| conservative_all | 98.46% | 80.00% | 70.00% | 60.00% | HELD005, HELD009 | 0 |

Every row uses the same twenty valid raw E5-B responses. All twelve original/narrow ablations also run on the thirteen valid raw development responses; the two provider failures are excluded equally, not erased from end-to-end experiment metrics. Full per-case outputs and changed-case lists are in rule_ablation_results.json.

Contextual product cleanup fixes HELD005 and changes soft macro F1 from78.33% to80%; foreign-currency clarification fixes HELD009. Combined common/full-v2 EM becomes70%/60% on already inspected oldheld20. Hard F1 remains98.46% with literal manufacturer preservation, versus99.22% under historical brand suppression matching the old business-policy label. This apparent hard-score loss is an extraction/filter-policy disagreement; it still prevents claiming an unqualified improvement. No new full-match failures appear in this replay, but it is not independent adoption evidence.

Historical negation adds a duplicate telephoto exclusion in HELD015; because it was already wrong, full-match counts conceal the additional slot damage. Historical price changes flags on absent bounds (HELD008/009), which scoring correctly ignores. Report changed fields as well as whole-query gains/losses. Narrow price/brand/negation groups show no full-query gain on this sample; retain only as experimental hypotheses pending broader evaluation.

## Robustness and per-field heldout results

Oracle invariance feeds hand-authored expected structures through rules: historical9/18 remain correct, conservative18/18 remain correct. The second interval is roughly82.4–100%, and even that pertains to the authored rule sample. Neither is Gemini extraction accuracy. Multilingual, typo, long-input and adversarial live robustness are not measured.

E5-B oldheld20: category/min-price/max-price/rating/currency100%; brand95%; clarification95%; product type90%; exclusion exact90%. Exclusion micro F1 is28.57% (TP1, FP3, FN2), despite macro/exact90%, because most queries have no exclusions. Active lower flags2/2 and upper flags13/13 match; that is small conditional coverage, not broad boundary reliability. Semantic-query lexical accuracy is8/20 and is separate from full slot EM.

## Individual failures

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

There are ten full-v2 failed queries. Overlapping field failures are soft7, type2, exclusions2, brand1, clarification1, boundary0. Lumbar wording has a narrow supplementary equivalence; unsupported-domain preferences and feature typing need annotation adjudication. Honda City is a substantive compatibility error, not a synonym issue.

## Timing, tokens and uncertainty

Historical original50 stored median1580.5ms, average1206.2 tokens; oldheld20 baseline median1638.2ms/1208tokens, E5-B1480.8ms/659.65tokens. These are stored descriptive figures with incomplete origin/cache/retry provenance, not verified fresh inference speed or cost savings. New prompt/temperature/schema timing and consumption remain N/A. Rule-only replays make zero billed requests; no inference token savings should be inferred.

Common EM oldheld20: baseline40% Wilson95≈21.9–61.3%; E5-B60%≈38.7–78.1%; E5-B full50%≈29.9–70.1%. Paired common effect+20 percentage points, six wins/two losses/twelve ties; query bootstrap2000seed82 interval−5 to+45 points. This is inconclusive and does not prove equivalence. No independent repeated-run consistency evidence exists in old records.

## Tests, selection and reproduction

| Executed check | Passed | Failed/errors | Scope |
| --- | --- | --- | --- |
| baseline_tests | 296 | 0 | Offline |
| focused_tests | 101 | 0 | Offline |
| regression_tests | 376 | 0 | All tests except Gemini integration module |
| smoke_tests | 2 | 0 | Bounded live subset; 2 distinct tests |
| smoke_retest | 2 | 0 | Bounded live subset; 2 distinct tests |

The initial two-request production smoke passed but emitted SSL teardown/unraisable warnings. The same two tests retested successfully after cleanup: two remaining SDK aiohttp inheritance deprecation warnings, no SSL teardown recurrence. Total four bounded generation calls, two distinct Gemini test cases; the other four Gemini integration tests were not rerun. Full repository regression excludes that module, so no claim of a fully rerun live suite is made.

Best candidate: no new live winner. E5-B remains experimental control; E6 is promising only on offline diagnostics. Reject immediate adoption, universal T0/T1 optimality, score-driven label edits and speed claims from old cache. Future comparisons remain explicitly pending. Reproduce using the commands in experimental_methodology.md; audit and report builders are offline.
