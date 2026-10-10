# Phase 8.2 research review and experiment proposal

Date: 2026-10-09 (Asia/Saigon). Status: offline investigation complete; user explicitly deferred comparative live experiments. This report distinguishes historical reanalysis, implemented infrastructure, isolated candidates, and untested hypotheses.

## Context and verified architecture

ShopAssist's proposal defines single-turn shopping extraction before preference representation and filtered retrieval. Existing artifacts describe 8,405 products, 16 categories, INR prices and 384-dimensional BGE vectors. No database, index or embedding changes are part of Phase 8.2.

`QueryUnderstandingEngine` currently sends the original `SYSTEM_INSTRUCTION` with `QueryUnderstandingOutput` (v1), then runs category/brand/currency normalization. E5-B uses a different prompt, `RefinedQueryUnderstandingOutput` (v2), and experimental rules through `ExperimentRunner`. E5-B was recommended in documentation but never installed in the production parser. The initial working tree was dirty; `baseline_manifest.json` records revision, configuration and 76 file hashes. Original LLM sources are preserved in `baseline_sources/`.

Verified limitations: historical common-field exact match is 27/50; E5-B gets 10/20 full v2 matches, 7 soft-preference mismatches, 2 product-type mismatches, 2 exclusion mismatches, 1 clarification error and 1 brand error. Errors overlap. The development split shares 13 exact queries with the historical benchmark. Historical requests do not record reliable retry/cache provenance.

## Research method

Read the project proposal, README, Phase 8 and 8.1 reports, original issue registry, both conceptual guides, all LLM modules, fixtures, tests, cache and per-case artifacts. Recompute scores from stored outputs without modifying ground truth. Inspect provider documentation and original research papers; separate general findings from ShopAssist hypotheses. All sources below were accessed 2026-10-09. Living documentation can change; source statements do not retroactively describe the SDK version used in an old run.

## Source review and candidate mechanisms

| Method | Mechanism and issue addressed | Benefit and limitation | Complexity / incremental API cost | ShopAssist hypothesis |
|---|---|---|---|---|
| Schema-constrained extraction [R1,R2] | Supply explicit field types/descriptions and validate JSON locally | Reduces format ambiguity; does not establish semantic truth or successful transport | Low; one existing call, larger schemas may add tokens | Required slots D1 expose omissions more clearly than defaults |
| Compact definitions [R3] | Define item class, attributes, compatibility, alternatives and negation scope | Shorter instructions can reduce ambiguity; omitted examples may hurt edge cases | Low; one call/query | C2 improves shared fields without a hard-constraint regression |
| Contrastive examples [R3] | Show nearby utterances with different meanings | Clarifies class versus use, and rejection versus qualification; selected examples can bias labels | Low; one call, extra input tokens | C3 improves pseudo-negation and type boundaries on unseen cases |
| Few-shot demonstrations [R3] | Condition extraction on varied examples with consistent annotation | Useful scoping guidance; costs tokens and risks leakage | Low; one call, extra input tokens | C4 improves validation accuracy enough to justify token cost |
| Error-driven instructions [R3] | Add focused checks for development failure categories | Targets compatibility/currency failures; can overfit old examples | Low; one call | C5 improves fields without expanding the schema |
| Temperature ablation [R4] | Change decoding distribution while holding E5-B fixed | Current Google guidance favors default 1.0 for Gemini 3; this is not proof of the best temperature for this task | Low; 81 calls for 9 queries x 3 temperatures x 3 runs | B0/T05/T10 differ in extraction correctness and consistency |
| Scope-aware rules [R5] | Treat negation cue, subject and scope separately; restrict corrections to clear evidence | Regex can help narrow patterns but cannot solve all language or multiple scopes | Medium; zero new calls using identical raw outputs | E6 avoids intent deletion and pseudo-negation errors |
| Paired evaluation [R6,R7] | Compare the same queries and quantify uncertainty | More informative than unrelated mean scores; small hand-authored samples still limit external validity | Low; offline | Apparent improvements may remain inconclusive |
| Conservative equivalences [R1,R7] | Predeclare a few reviewed phrase classes, alongside strict metrics | Avoids lexical false negatives; broad embedding thresholds can accept opposite meanings | Low; offline | Report semantic soft F1 separately without weakening exact match |
| Repeated sampling / self-consistency [R8] | Generate independent samples and assess agreement | Original work addresses reasoning tasks, not shopping slot extraction; majority can repeat a shared error | Medium; roughly K times requests/tokens | First measure consistency; do not deploy voting without evidence |
| Retry/caching discipline [R2,R9,R10] | Count attempts before submission, respect delays, hash actual prompt/schema/settings, close sessions in their loop | Improves auditability and recovery; budgets do not remove provider outages | Medium; retries cost attempts, cache replays cost zero inference calls | Infrastructure can distinguish transport failures from invalid schema output |

These are experimental hypotheses. No new prompt, sampling temperature or schema has been declared a better production configuration.

## Proposal and budget

Prepare 80 authored cases: development 20, validation 20, fresh heldout 40. Labels precede live predictions, but only one annotator has reviewed them; independent annotation remains pending. Freeze prompt/schema/rule versions and selection criteria before final evaluation.

| Stage | Controlled comparison | Planned new generation calls |
|---|---|---:|
| A | Historical metric audit and rule-only replay | 0, executed |
| B | E5-B at 0.0/0.5/1.0, 9 development queries, 3 repetitions | 81 |
| Matching control | B0 on the other11 development queries, once | 11 |
| C | C2/C3/C4/C5 on 20 development queries | 80 |
| D | Required v2 slots D1 on 20 development queries | 20 |
| E | All rule groups on shared raw responses | 0 |
| Validation | Provisional winner and B0 control on20 validation queries | 40 |
| Final | Selected candidate and control on 40 fresh heldout queries | 80 |
| **Total** | Every prompt/schema comparison has same-query B0 control | **312** |

Proposed ceiling: 360 generation attempts, 500,000 charged/reserved tokens, zero automatic retries during screening, at least 4 seconds between attempt starts. Expected measured consumption is roughly 280,800 tokens at 900 tokens/call, with large uncertainty; byte-based reservations are higher than typical token counts. Unreturned usage retains its reservation. The token ceiling is enforced on reservations and observed usage; hidden/provider accounting can exceed an estimate, so it is not a mathematical billing guarantee. Stop after an unexpected overrun.

At the current standard text rates ($0.25/M input, $1.50/M output), 312 calls averaging 650 input and 250 output tokens would cost about $0.168. Treat $0.75 for 500,000 tokens entirely priced as output as a conservative planning amount, not a guaranteed invoice ceiling. Free-tier eligibility and actual project quotas are unknown. Allow about 25–45 minutes plus any provider delays. Four seconds is provisional pacing, not proof of a universal quota. Rates and tier limits come from the provider [R9,R11].

Your task §20 explicitly requires approval beyond small bounded smoke checks. Until that approval, the registry reports these comparisons as NOT_RUN/BLOCKED_APPROVAL. The two-request initial production smoke check is a connectivity/contract check, not comparative E5-B evidence. Any lifecycle retest is reported separately. No silently changed model/provider or production consumer is authorized by this proposal.

## Selection rule

Use development data to freeze one provisional candidate plus the B0 control. Reject candidates with schema validity below 99%, hard-constraint micro-F1 below 98%, or a material hard-constraint/clarification regression versus the same-query control. Rank eligible candidates by full v2 slot EM, then strict soft macro-F1, then token cost. Seek soft F1 >=85%, full v2 EM >=75%, brand >=98%, product type >=95%, exclusion micro-F1 >=90% and boundary accuracy >=98%; small datasets cannot validate these population targets precisely. Examine paired per-query effects and intervals. Require validation confirmation, then run the locked heldout once. If evidence is weak, retain the current production configuration and report uncertainty.

## References

- **R1** Google, [Structured outputs](https://ai.google.dev/gemini-api/docs/generate-content/structured-output). Living documentation; publication date not established. Schema subset and semantic validation limits.
- **R2** Google, [Gen AI Python SDK](https://googleapis.github.io/python-genai/) and [official implementation](https://github.com/googleapis/python-genai/blob/main/google/genai/_api_client.py). Living documentation/source; installed version 2.29.0 checked locally. Retry policy and session lifecycle.
- **R3** Google, [Prompt design strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies). Living documentation; publication date not established. Explicit instructions and consistent varied demonstrations.
- **R4** Google, [Gemini 3 developer guide, temperature](https://ai.google.dev/gemini-api/docs/gemini-3). Living/deprecated guide accessed on the stated date; recommends default 1.0 for Gemini 3. No model migration is implied.
- **R5** Wu and Sun, [Negation Scope Refinement via Boundary Shift Loss](https://aclanthology.org/2023.findings-acl.379/), Findings ACL, July 2023. Negation scope boundaries matter; its trained model was not implemented here.
- **R6** Dror et al., [The Hitchhiker's Guide to Testing Statistical Significance in NLP](https://aclanthology.org/P18-1128/), ACL, July 2018. Match tests to metrics and experimental units.
- **R7** Peyrard et al., [Better than Average: Paired Evaluation of NLP systems](https://aclanthology.org/2021.acl-long.179/), ACL, August 2021. Instance pairing informs comparison.
- **R8** Wang et al., [Self-Consistency Improves Chain of Thought Reasoning in Language Models](https://arxiv.org/abs/2203.11171), submitted March 21, 2022; ICLR 2023. Multi-sample reasoning evidence, not a shopping extraction guarantee.
- **R9** Google, [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits). Living documentation; limits depend on project/tier/model.
- **R10** aiohttp, [Advanced client usage: graceful shutdown](https://docs.aiohttp.org/en/stable/client_advanced.html#graceful-shutdown). Living documentation; SSL transport cleanup can require a brief delay.
- **R11** Google, [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing). Living documentation; rates checked for configured Gemini 3.1 Flash-Lite on the access date.
- **R12** Pydantic, [Strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/). Living documentation; normal validation may coerce types. Validation and semantic truth are different claims.


## Execution decision update

The user selected: finish offline work; leave live comparisons pending. No large-run approval exists. Corrected future plan312 calls includes11 additional same-query controls within the proposed360-attempt ceiling. Four bounded production generation calls were completed (two smoke tests, then the same two after lifecycle repair). Final regression passed376 tests excluding Gemini module; semantic candidates remain unadopted.
