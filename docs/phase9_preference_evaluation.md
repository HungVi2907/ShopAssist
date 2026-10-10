# Phase 9 Evaluation and Verification Report

**Evidence date:** 2026-10-10. This report separates implemented checks from executed checks.

## Objectives

Check deterministic preference normalization/composition and polarity safety independently of Gemini; check Phase 8 v1 integration with mocks; validate the shared BGE model/dimension/vector properties; compare preference-only, contextual keyword and contextual composition with identical descriptions; measure local normalization/composition, model initialization, single and batch encoding.

## Curated cases

Cases cover lightweight laptop/long battery life, comfortable running shoes/breathable/daily jogging, waterproof backpack, beginner-friendly camera, compact wireless keyboard, and durable office chair. Unit tests separately cover empty lists, duplicates, case/space, Unicode, malformed values, limits, invalid/clarification states, negative phrases, foreign currency, and serialization.

The curated descriptions and inputs are recorded in `data/interim/phase9/phase9_test_cases.json`. They are test material, not a large relevance dataset.

## Normalization and composition

Expected deterministic behavior is encoded in `tests/test_preferences.py`: case-fold and whitespace normalization, first-seen ordering, duplicate and blank removal, no translation/synonym creation, and all phrase/context preservation. A safe example composes as `comfortable; breathable; for daily jogging — running shoes`.

The selected composition is contextual and includes no generated attribute. The BGE run measured 12 paired comparisons (four cases × three composition strategies). The curated relevant description ranked above its paired irrelevant description in **12/12** comparisons. Contextual Phase 9 composition won all four of its checks. Direct contextual keyword order produced the largest margin in two cases, while the Phase 9 composition did so in two. These authored pairs validate a sanity property only; they do not establish a composition winner or catalog-wide retrieval quality.

| Strategy | Mean relevant cosine | Mean irrelevant cosine | Mean paired margin | Wins |
| --- | ---: | ---: | ---: | ---: |
| Preference only | 0.7746 | 0.4496 | 0.3251 | 4/4 |
| Context keywords | 0.8730 | 0.4726 | 0.4004 | 4/4 |
| Phase 9 contextual composition | 0.8613 | 0.4579 | 0.4034 | 4/4 |

The two contextual strategies are close on four examples. Keep contextual composition because it explicitly retains both input groups; do not interpret the 0.003 mean-margin difference as a reliable performance improvement.

## Embedding/model validation

The production adapter references Phase 7's existing model name, query instruction, cached encoder, dimension and normalization. Runtime generated 16 vectors and confirmed 384 dimensions, finite values, nonzero norms and unit normalization within `1e-4`. The evaluated runtime was Python 3.10.11, PyTorch 2.6.0+cu124, Sentence Transformers 6.0.1, CUDA, NVIDIA GeForce RTX 3050 Laptop GPU. The default shell Python lacks those dependencies; the model-enabled execution context completed the run. See `phase9_embedding_validation.json`.

## Semantic cases and interpretation

Paired comparisons used the same BGE query encoder and same relevant/irrelevant short product descriptions across strategies. No thresholds were used as proof of universal semantic correctness. The 12/12 result applies only to these four authored pairs; no recommendation-accuracy or Phase 10 benefit claim follows.

## Tests

`tests/test_preferences.py` passed **22/22** tests: 20 unit cases and 2 mocked integration checks (Phase 8 v1 service and Phase 7 encoder adapter). `python -m pytest --ignore=tests/test_gemini_integration.py -q` passed **398/398** repository tests with zero failures or skips. This excludes the live Gemini integration module; no Gemini API calls were made. The default shell's pytest attempt stopped before collection because that Python lacks pytest; the model-enabled project execution context completed both runs.

The last Phase 8.2 run recorded 376 passed, excluding the Gemini module. The present 398-test regression includes Phase 9 and the offline repository suite. The bounded two-test live Gemini subset is historical evidence from 2026-10-09 and was not rerun.

## Performance

On the model-enabled runtime: initialization **17,958.6 ms**; normalization median **0.030 ms** / p95 **0.056 ms**; composition median **0.015 ms** / p95 **0.025 ms**; single embedding median **22.70 ms** / p95 **24.07 ms**; one four-query batch **25.19 ms**; vector validation median **0.075 ms** / p95 **0.103 ms**; end-to-end representation **21.22 ms**. There were three timed repetitions per curated query after model initialization, with no separate inference warm-up. This small local timing is not an SLO. Full details are in `phase9_performance_report.json`.

## Error analysis, limitations and status

The code contains bounded text-pattern safety checks; tests are authored but not yet executed. The checks are not full negation-scope analysis. The Phase 8 extraction quality and label limitations remain upstream. `represent_batch()` is per-item and currently does not coalesce model calls, although the embedding adapter has a batch method.

**Evaluation status: PASS for Phase 9 component scope.** Automated tests, runtime vector checks, curated paired rankings and local performance all executed. Limits remain: small authored semantic pairs, no catalog-wide or end-to-end recommendation evaluation, and no live Gemini regression run. No result is presented as broader evidence than it supports.
