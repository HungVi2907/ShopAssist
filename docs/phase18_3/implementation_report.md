# Phase 18.3 implementation report

2026-11-26, Asia/Saigon. Starting source: clean `main` at `4319fd5`, equal to `origin/main` after fetch. The Phase 18.1 audit, both Phase 18.2 reports, Phase 18 handover and actual E2 JSONL artifacts were inspected before editing. Phase 18 remains `IMPLEMENTED_PENDING_BACKUP_VALIDATION`; T17 and production routes are unchanged.

## Implemented changes

The architecture remains one native Ollama extraction → flat internal schema → Python transformation → semantic validation → unchanged public query contract. The model/tag, decoding configuration, schema, taxonomy and default application composition remain unchanged. `OllamaIntentExtractor` is still explicitly injected for experiments; no Telegram, API or Gateway production route was activated.

| Source | Change and justification |
|---|---|
| `src/shopassist/llm/transformation.py` | Bounded phrase normalization for singular/plural forms and three explicit product equivalents; copy supported preference wording; contextual Bluetooth speaker mapping; missing-brand sentinels; compatibility target handling; narrow explicit catalog-maker recovery; exclusion checks outside successfully parsed numeric spans. Final safety correction removes attribute-derived unverified manufacturer filters and clears a scalar brand under competing-maker ambiguity. |
| `src/shopassist/llm/constraints.py` | Only numeric change: recognize `not exceeding` as an upper bound. Frozen-parser comparisons and focused tests show the previous silent omission. Existing inclusive values, conflicting-bound refusal, correction semantics, currency/rating/spec guards and no-swap rule remain. |
| `src/shopassist/llm/extraction.py` | Preserves P0 and adds two bounded development prompts. P1 expands only preference definitions; P2 uses two complete development examples. Final research selection retains original P0 because the preference changes did not generalize. |
| `scripts/evaluate_phase18_3.py` | Live native comparisons and optional stored E2 replay. Q0 loads the Phase 18.2 transformation **and parser** from frozen source; Q1 shares its exact raw extraction. Stores source/model/prompt/schema/catalog/dataset hashes and all intermediate stages. |
| `scripts/revalidate_phase18_3.py` | Reapplies safety corrections to identical stored outputs without new inference, preserving initial failed evaluations. Explicitly marks post-provisional revision and inherited timing. |
| `scripts/inspect_phase18_3_downstream.py` | Scoped local 8,405-product catalog, TF-IDF and existing CPU CrossEncoder inspection. No retrieval/reranking algorithm changes. |
| `tests/test_phase18_3.py` | Grounding positives and negatives, price-negation protection, genuine exclusion gates, maker recovery, compatibility, numeric specs, multilingual guards and reproduced brand safety failures. |

No new dependency, agent framework, classification model, generalized rule engine or extra LLM pass was introduced. Historical source snapshots, prompts, schemas, results and ledgers were preserved.

## Grounding and clarification

Phrase matching is bounded: hyphen/space normalization, plural inflection and explicit `wireless charging pad`/`wireless charger`, `running footwear`/`running shoes`, `gaming notebook`/`gaming laptop` equivalents. A paper notebook is not automatically a laptop, a camera lens is not a camera bag, and sharing a category does not imply product equivalence. Compounds still use longest mapped phrase. `CATEGORY_SYNONYM_MAP` is reused; Bluetooth speaker adds a product mapping to an existing category only when its context is explicit. Vietnamese aliases remain limited and experimental.

Preferences are grounded against source wording. Small plural and material/style suffix variants may copy literal source phrases instead of being discarded. Optional preference absence never by itself requests clarification. The layer does not infer arbitrary missing preferences or rewrite numeric specifications to fit labels. Exact-match scores and meaningful paraphrases are reported separately; labels are never silently edited.

`unknown`, `not specified` and `not provided` are missing-brand sentinels in addition to existing normalization. Compatibility text after `for` or `compatible with` cannot supply the accessory manufacturer; that requirement remains in `semantic_query`. A single catalog maker is recovered only from explicit initial-name or `brand`/`by`/`from` syntax. A dictionary hit alone is insufficient. An unlisted leading maker can remain ambiguous and gated, as with missing Cello extraction. This is conservative grounding, not a complete entity recognizer.

The final safety correction addresses two reproduced failures. Multiple maker alternatives cannot leave an arbitrary scalar brand filter even when retrieval is gated. Unrecognized brand output that overlaps a qualitative attribute, or comes only from lowercase text without explicit maker syntax, lacks enough maker evidence: clear the filter and request clarification. This costs coverage for some legitimate unfamiliar/lowercase brands; no claim of perfect brand recognition follows. Raw input and correction diagnostics preserve what was refused.

Only successfully parsed numeric spans are removed before negation checks. `not exceeding 2000` is therefore valid, while `not under 2000`, `without leather`, `no telephoto` and other unrepresentable exclusions still gate. Parser ambiguity issues remain authoritative. The broader downstream exclusion guard still treats some numeric negations as unsafe; it was not relaxed in this phase and is an experimental integration blocker.

## Prompt experiment and stop decision

P0 is the frozen Phase 18.2 extraction prompt. P1 changes only its preference definition to request all explicit features, materials, comfort, portability, intended uses and contexts, including source `for ...` phrases. P2 uses that definition with two complete constructed examples: a portable Acer laptop for coding, and a soft leather wallet for women. No categories, price interpretation, SQL or database policy was added. All three retain untrusted-input rules, null/empty behavior and one-call extraction.

P1 won development preference F1 (78.3%), but failed to generalize on provisional labels (37.4% versus Q1/P0 46.7%). P2 was worse than P1 on development and was not evaluated on new cases. No further prompt optimization was pursued. The original P1 freeze and failed provisional results remain immutable. After the limited safety correction, **Q1S = P0 + grounding + brand safety** is the final frozen research candidate. This is a practical simplicity decision, not a declaration that acceptance gates passed.

## Fresh dataset and annotation policy

`data/interim/phase18_3/provisional_cases.json` contains 50 varied requests written after the initial candidate freeze, with all 16 existing category domains, numeric specifications, corrections, foreign currencies, unsupported products, exclusions, ambiguity, competing makers, multiple products, adversarial instructions and limited Unicode Vietnamese. The builder is preserved. `review_status` explicitly says agent labels, `reviewer` is null, and results are provisional. The dataset is now seen and cannot become an independent holdout by renaming it.

Review rules: product is the requested item class; category must be one supported canonical class or null; manufacturer is separate from device compatibility; absent prices/ratings are null; clear relational budgets use the existing inclusive value convention without currency conversion; preferences retain explicit source attributes and use phrases; foreign currency, unresolved competing prices/makers, unsupported domains, missing intent and unrepresentable exclusions require clarification. Numeric product specs remain semantic/preference text, not price. Multi-product requests require review where v1 cannot express the conjunction. `no budget limit` is provisionally answerable even though current broad negation gates it—labels were not shaped to make the implementation pass. Before acceptance a human must adjudicate the labels, correction decisions and intended scope of mandatory specifications.

The legacy development/regression labels retain their old v2-oriented exclusion answerability. They intentionally differ from the fresh provisional v1-safe policy. Both disagreements and consequent coverage penalties remain visible.

## Freeze, testing and readiness

The authoritative source and prompt freeze is `data/interim/phase18_3/frozen_candidate/final/manifest.json`. It follows a disclosed post-provisional safety repair; no independent-evaluation claim applies. It records source, model digest, prompt, schema, options and selection evidence. The adjacent earlier freezes preserve the initial decision and intermediate safety revision. Result/dataset hashes are indexed separately in `experiment_manifests/index.json`.

Offline tests use the network-guarded runner under `data/interim/phase18_3`; external DNS/sockets are denied and model download modes are disabled. Windows loopback remains allowed for asyncio. All tests use mocks or local deterministic resources. Full selected-test results, safety tests that failed before correction, final revalidation and local downstream artifacts are reported in the evaluation report.

The candidate can support controlled, opt-in experimental Phase 18.4 compatibility testing. Production readiness is blocked by preference recall, coverage, provisional category performance, unresolved named entities, unreviewed correction policy, imperfect injection detection and missing independent human validation. Real catalog inspection found product-type relevance problems despite satisfied broad hard filters. No production-quality retrieval guarantee or approval to deploy is implied. Parent-deadline handling in the experimental native branch also remains a Phase 18.2 integration limitation. The scope stops here rather than adding a large language rule engine.
