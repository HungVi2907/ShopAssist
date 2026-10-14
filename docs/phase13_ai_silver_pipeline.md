# Phase 13 AI-Silver Evaluation Pipeline

## Scope and scientific boundary

This is an evaluation-only pipeline for `data/evaluation/phase13/ai_silver/`.
It preserves `v1`, `v2`, `v3`, their review trails, and the existing human
ground-truth readiness rules. It is not a mechanism for promoting an
AI-generated label to a human annotation.

Every released artifact has `label_quality: "SILVER"`, `human_verified: false`,
and `phase14_ready: false`. Provider-backed namespaces use
`annotation_method: "AI_MULTI_JUDGE"`; Codex-native namespaces use
`annotation_method: "CODEX_NATIVE_MULTI_JUDGE"`. `silver_ready` means only
that the configured machine-label structural gates completed; it never means
Phase 14 is ready.

## Pipeline

```text
v3 source snapshot
  -> independent query audit A/B + deterministic checks
  -> audited oracle intent
  -> TF-IDF + dense + hybrid candidate-run capture
  -> frozen union/deduplicated pool with per-method provenance
  -> blinded relevance judge A/B
  -> agreement analysis + AI adjudication / explicit unresolved state
  -> Silver qrels and validator
  -> provisional, pool-conditional evaluation
```

The implementation is in [silver.py](../src/shopassist/evaluation/silver.py)
and the operational command is
[run_phase13_ai_silver.py](../scripts/run_phase13_ai_silver.py).

## CODEX_NATIVE multi-agent workflow (no external API)

`CODEX_NATIVE` is a file-mediated workflow for the isolated
`data/evaluation/phase13/ai_silver/v3_codex_native/` namespace. Python only
prepares blinded evidence packets, validates submitted JSONL, freezes retrieval
pools, and performs deterministic checks. It is not an inference client.
Actual judgment must be performed by two separately spawned, interactive Codex
subagent threads and collected by the parent Codex agent.

The native commands do not instantiate a provider, inspect
`SHOPASSIST_SILVER_*` environment variables, make HTTP requests, use an API
key, call an OpenAI Platform API, invoke the Codex CLI/SDK from a subprocess,
or invoke any other programmatic model client. Do not use the legacy `audit`,
`judge`, `adjudicate`, or `run-full` commands for this workflow. If native
subagents cannot be spawned, record `NATIVE_SUBAGENTS_UNAVAILABLE`, preserve
the checkpoint, and stop before creating a judgment; never substitute
Python-generated or provider-generated labels.

Blindness is procedural and must be maintained by the parent agent. Give Judge
A only its A packet and Judge B only its B packet. Neither judge may inspect
the other judge's output, historical provider output, v3 expected labels,
retrieval ranks/scores, or unrelated repository artifacts. The parent may
provide both completed reviews to the adjudicator only after the two imports
succeed. Separate native executions do not establish independent model families
or human review; use `UNKNOWN` for model metadata unless the current session
actually exposes it.

### Native lifecycle

1. Initialize a new namespace and prepare the four blinded query tasks. The
   preparation stage writes
   `codex_native_inputs/judge_a_query_tasks.jsonl` and
   `codex_native_inputs/judge_b_query_tasks.jsonl`.
2. Spawn Judge A and Judge B in distinct native subagent slots, never as
   successive turns in one shared judge thread. Each returns one JSONL record
   for every assigned task, following that packet's output schema and
   preserving its task fingerprint. The parent agent writes the returned JSONL
   to a submission file and imports it; judges do not write dataset artifacts
   themselves.
3. Only after both imports, prepare the query-adjudication packet, adjudicate
   differences against its canonical evidence, and finalize `query_audit.jsonl`.
   Unresolved ambiguity remains unresolved.
4. Capture eligible TF-IDF, dense, and hybrid pools. A safe-stop query (such as
   Q0008 when its exclusion is unsupported) is not forced into retrieval. The
   native smoke test is capped at 90 distinct query--product pairs.
5. Prepare 5--10-pair blinded relevance batches for each separate judge; import
   both review sets; then prepare and finalize only genuine disagreements.
   Finalization writes adjudications, Silver qrels, and the agreement report.
6. Run native validation. Fingerprints, schemas, duplicate detection, catalog
   membership, blind provenance, unresolved cases, and the 90-pair cap are
   checked before `silver_ready` can become true. `human_verified` and
   `phase14_ready` remain false.

The remaining native packet paths are
`codex_native_inputs/relevance_task_index.jsonl`,
`codex_native_inputs/relevance/judge_{a,b}_batch_*.jsonl`, and
`codex_native_inputs/relevance_adjudication_tasks.jsonl`. Packets and imports
are resumable only when their fingerprints are identical; add `--resume` only
after inspecting the existing checkpoint.

### Native operational commands

Run these from the repository root with the supported Windows runtime. The
submission paths below are parent-agent-owned files containing real native
subagent output, not files generated by a model client.

```powershell
$NativePython = ".\.deps\phase13-win-venv\Scripts\python.exe"
$NativeDataset = "data/evaluation/phase13/ai_silver/v3_codex_native"
$SourceSnapshot = "data/evaluation/phase13/v3"

# Stage A: create blinded query packets for the exact smoke-test queries.
& $NativePython scripts\run_phase13_ai_silver.py native-init --dataset $NativeDataset --source $SourceSnapshot
& $NativePython scripts\run_phase13_ai_silver.py native-prepare-query --dataset $NativeDataset --query-id Q0007 --query-id Q0008 --query-id Q0013 --query-id Q0045

# After separate native Judge A/B threads return their JSONL submissions.
& $NativePython scripts\run_phase13_ai_silver.py native-import-query --dataset $NativeDataset --judge A --submission path\to\judge_a_query_submission.jsonl --native-model UNKNOWN
& $NativePython scripts\run_phase13_ai_silver.py native-import-query --dataset $NativeDataset --judge B --submission path\to\judge_b_query_submission.jsonl --native-model UNKNOWN
& $NativePython scripts\run_phase13_ai_silver.py native-prepare-query-adjudication --dataset $NativeDataset
& $NativePython scripts\run_phase13_ai_silver.py native-finalize-query --dataset $NativeDataset --submission path\to\query_adjudication_submission.jsonl --native-model UNKNOWN

# Stage B starts only after the query audit is complete and eligible.
& $NativePython scripts\run_phase13_ai_silver.py native-capture --dataset $NativeDataset --methods tfidf,dense,hybrid --depth 20 --max-pairs 90
& $NativePython scripts\run_phase13_ai_silver.py native-prepare-relevance --dataset $NativeDataset --batch-size 10 --max-pairs 90
& $NativePython scripts\run_phase13_ai_silver.py native-import-relevance --dataset $NativeDataset --judge A --submission path\to\judge_a_relevance_submission.jsonl --native-model UNKNOWN
& $NativePython scripts\run_phase13_ai_silver.py native-import-relevance --dataset $NativeDataset --judge B --submission path\to\judge_b_relevance_submission.jsonl --native-model UNKNOWN
& $NativePython scripts\run_phase13_ai_silver.py native-prepare-relevance-adjudication --dataset $NativeDataset

# Omit --submission only when there are no relevance disagreements.
& $NativePython scripts\run_phase13_ai_silver.py native-finalize-relevance --dataset $NativeDataset --submission path\to\relevance_adjudication_submission.jsonl --native-model UNKNOWN
& $NativePython scripts\run_phase13_ai_silver.py native-validate --dataset $NativeDataset
```

`--native-model` accepts only model information observable in the current
interactive session. Leave it as `UNKNOWN` when unavailable; do not guess or
hardcode a model name. Native manifests record
`CODEX_NATIVE_MULTI_JUDGE`, `CODEX_NATIVE`, separate-subagent provenance, the
same-model correlation risk, machine adjudication, and the no-external-provider
boundary.

## Query audit methodology

The audit judges see the raw query, language, supported Phase 8 fields,
allowed categories, and known Phase 8--10 limitations. They do not receive
the historical v3 interpretation until after independently proposing one.
Deterministic checks separately detect explicit price bounds and their exact
operators:

- `under`/`below` -> `<`
- `up to`/`at most` -> `<=`
- `above`/`over` -> `>`
- `at least` -> `>=`

Vietnamese budget forms such as `dưới 2 triệu` are also checked. Historical
mojibake is repaired only for deterministic matching; the original raw query
is retained unchanged. Exclusions are recorded as typed limitations rather
than inserted into positive soft preferences. Phrases such as Vietnamese
`không bị trơn` are recognized as the positive property `non-slip`, not as an
exclusion.

The deterministic layer flags issues but does not claim semantic correctness.
Without two completed independent judge reviews, the audit has status `BLOCKED`
rather than being passed off as an AI or human adjudication.

## Retrieval pooling and frozen evidence

`capture` invokes existing `TFIDFIndex`, `SemanticSearchEngine`, and
`HybridRetrievalService` independently with the audited oracle intent. Each
method's own ranked list is stored in `retrieval_runs.jsonl`. The candidate
pool is the union keyed by `product_id`, carries exact canonical catalog text
and metadata, and retains every contributing method/rank/score. It is never
truncated using a score from a different method.

The default capture requests `tfidf,dense,hybrid`. If a database, model, or
credential is unavailable, the method is recorded in `capture_blockers.jsonl`.
No pool is frozen unless every requested method completed, unless the operator
explicitly supplies `--allow-partial-methods`; such a capture is marked
`PARTIAL_METHODS` and is not a fair multi-method comparison.

Candidate capture evaluates **oracle query understanding** only. An
end-to-end score needs separately captured actual Phase 8 outputs and remains
blocked until that evidence exists. `NO_RESULTS` records catalog constraint
matches, retrieved results, and semantic relevance as distinct facts.

## Relevance judging and adjudication

`judge` sends only a blinded product packet: raw query, audited intent,
product identity/metadata, canonical retrieval text, specifications, and
available evidence-reference names. It deliberately excludes ranks, lexical
and dense scores, RRF score, pool position, retriever identity, and Phase 12
text.

The relevance rubric is grade 3 (strong), 2 (relevant with minor
weakness/missing evidence), 1 (related but important mismatch), or 0
(irrelevant/contradictory). Missing metadata is recorded as missing evidence,
not a violation. Deterministic authoritative metadata checks category, brand,
price/rating bounds, and currency. A final grade of 2 or 3 cannot coexist with
a confirmed hard-constraint violation.

Judge A and B use separate configured slots. If they use the same model, the
manifest explicitly records `REDUCED_SHARED_MODEL`; this is two separate calls
with separate cached fingerprints, not a claim of independent human review.
Malformed/retry-exhausted responses are recorded as failed, never converted to
grade 0. Disagreements are passed to the adjudicator when configured; otherwise
they become `UNRESOLVED` rather than forced consensus.

`judge_agreement.json` calculates actual exact agreement, disagreement rate,
quadratic-weighted Cohen's kappa, grade distributions, and breakdowns by
language, query type, and product category. Agreement is a consistency signal,
not evidence that labels are correct.

## Artifact contract and validation

A completed namespace may contain:

```text
ai_silver/v1/
  queries.jsonl                 # immutable source snapshot
  query_audit.jsonl             # audit evidence/statuses
  query_audit_report.json       # actual finding counts by language/type
  candidate_pools.jsonl         # frozen union and canonical evidence
  retrieval_runs.jsonl          # pre-union method rankings
  judge_a_reviews.jsonl
  judge_b_reviews.jsonl
  adjudications.jsonl
  qrels_silver.csv
  judge_agreement.json
  generation_snapshots.jsonl    # only real Phase 12 snapshots
  generation_claims_silver.csv  # only claims flattened from those snapshots
  validation_report_silver.json
  dataset_manifest.json
```

Files are written only when their stage has real evidence; an unavailable stage
is represented by a blocker report, not invented empty labels. The manifest
records source/canonical catalog hashes, each artifact hash, provider/model and
prompt configuration, unresolved cases, and known limitations. Released
namespaces are immutable; create `v2` rather than overwrite one.

`validate` distinguishes structural validity, semantic quality, and research
readiness. It verifies IDs, catalog hashes, pair coverage, duplicate records,
hard constraints, blind-review provenance, qrel/adjudication consistency,
artifact hashes, and the prohibition on `human_verified=true` or
`phase14_ready=true`. It explicitly fails missing adjudication records and
does not make absent candidates grade 0.

## Generation evaluation

`capture_real_generation_claims` accepts actual saved Phase 12 result JSONL
only. It refuses absent provider/model/prompt provenance, products outside the
frozen pool, missing product-bound evidence, or invalid citations. It records
the exact generation snapshot/result hashes and does not synthesize a
recommendation interaction to meet the 50-interaction research target.

The same provider abstraction and independent-review principle are intended
for claim support, factual correctness, recommendation relevance, missing
information handling, and hallucination review. A valid evidence ID is not by
itself support for the claim.

## Commands and isolated provider configuration

Use the supported Windows runtime, not the MSYS2 `python` on `PATH`. The
repository contains a locked Python 3.12 environment at
`.deps/phase13-win-venv`. Run the read-only preflight first:

```powershell
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\check_phase13_runtime.py
```

It must report PyArrow/Pandas versions, 8,405 unique catalog IDs, required
fields, and the catalog SHA-256 before a live capture. The old project-root
`.venv` refers to a removed Python 3.10 interpreter and is not a supported
runtime. Do not regenerate the canonical Parquet file to work around this.

### Verified local runtime state (2026-10-13)

The supported runtime completed the Phase 13 dataset, workflow, and AI-Silver
test suites: **33 passed**. Its catalogue preflight found 8,405 rows and 8,405
unique IDs, with catalog SHA-256
`bd9bac023368289629c903ad04fc98bae85c347777f646dca63ad4bdfb029cdc`.

A read-only retrieval smoke capture also ran against the existing v3 snapshot:

| Query | Methods actually invoked | Result |
| --- | --- | --- |
| Q0007 | TF-IDF; dense and hybrid | All three completed in provisional captures; the dense/hybrid union contains 10 candidates. |
| Q0013 | TF-IDF, dense, hybrid | All completed; frozen provisional union contains 15 candidates. |
| Q0045 | TF-IDF, dense, hybrid | All completed; frozen provisional union contains 10 candidates. |
| Q0008 | None completed | Correctly stopped before retrieval: Phase 8 v1 cannot safely represent the negative/exclusion intent. |

These files remain under `data/interim/phase13_v3_*` with
`UNVERIFIED_V3_REFERENCE`. They are diagnostic evidence only, are not Silver
labels, and cannot be promoted to Phase 14.

### Limited live AI-Silver smoke checkpoint (2026-10-14)

The isolated `ai_silver/v2` namespace contains the authorised four-query
live audit (`Q0007`, `Q0008`, `Q0013`, `Q0045`). It made eight persisted audit
calls with no provider retry: Judge A (OpenRouter Gemma) failed all four with
HTTP errors; Judge B (Groq GPT-OSS) completed only Q0013. Consequently there
are **0 completed audits, 0 frozen candidate pools, 0 relevance reviews, 0
qrels, and `silver_ready: false`**. Retrieval and product-evidence transfer
were correctly not started; Q0008 therefore also never reached retrieval.

The successful Groq call reported 425 prompt tokens and 600 completion tokens
(1,025 total). Failed calls did not return usage. The OpenRouter key preflight
reported free-tier access; the Groq model inventory confirmed the requested
model. The exact account-level privacy controls cannot be read using these API
keys. Endpoint preflight found no ZDR or `data_collection: deny`-eligible
endpoint for the specified OpenRouter free model, so the run used only
`allow_fallbacks: false`, recorded that provenance, and did not claim ZDR.

The structural validator passes this incomplete namespace with a readiness
warning; it does not convert the provider failures into labels. Resume only
after inspecting and resolving the provider errors, and never switch the model
or provider implicitly.

```powershell
# Initialise an entirely new version; never point this at v1/v2/v3.
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py init --dataset data/evaluation/phase13/ai_silver/v1

# Safe local-only preflight: audit a representative 40-query selection without reading provider credentials.
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py run-pilot --dataset data/evaluation/phase13/ai_silver/v1 --offline-only --max-requests 100

# Resume a stage only after inspecting its evidence; checkpoint fingerprints are reused.
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py audit --dataset data/evaluation/phase13/ai_silver/v1 --resume --max-requests 600
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py capture --dataset data/evaluation/phase13/ai_silver/v1 --resume --depth 20
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py judge --dataset data/evaluation/phase13/ai_silver/v1 --resume --max-requests 1000 --concurrency 2
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py adjudicate --dataset data/evaluation/phase13/ai_silver/v1 --resume
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py validate --dataset data/evaluation/phase13/ai_silver/v1 --resume
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py freeze-split --dataset data/evaluation/phase13/ai_silver/v1 --held-out-fraction 0.2 --seed 13013
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py evaluate --dataset data/evaluation/phase13/ai_silver/v1 --resume

# Optional: capture and judge only actual, saved Phase 12 interactions.
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py capture-generation --dataset data/evaluation/phase13/ai_silver/v1 --source-results path/to/real_phase12_results.jsonl
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py judge-generation --dataset data/evaluation/phase13/ai_silver/v1 --max-requests 1000

# Full execution (stops truthfully at unavailable dependencies).
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_ai_silver.py run-full --dataset data/evaluation/phase13/ai_silver/v1 --max-requests 2000 --concurrency 2
```

If independent LLM audit is unavailable, a retrieval-only diagnostic can use
the historical v3 interpretation for Q0007/Q0008/Q0013/Q0045. It writes under
`data/interim`, has `UNVERIFIED_V3_REFERENCE` provenance, and is mechanically
rejected by the Silver validator:

```powershell
& .\.deps\phase13-win-venv\Scripts\python.exe scripts\run_phase13_v3_retrieval_smoke.py --out data/interim/phase13_v3_retrieval_smoke
```

Configure judges separately from Phase 8/12, for example:

```text
SHOPASSIST_SILVER_A_BASE_URL=https://provider.example/v1
SHOPASSIST_SILVER_A_API_KEY=...
SHOPASSIST_SILVER_A_MODEL=...
SHOPASSIST_SILVER_A_INPUT_COST_PER_MILLION=...
SHOPASSIST_SILVER_A_OUTPUT_COST_PER_MILLION=...
SHOPASSIST_SILVER_B_BASE_URL=https://provider.example/v1
SHOPASSIST_SILVER_B_API_KEY=...
SHOPASSIST_SILVER_B_MODEL=...
SHOPASSIST_SILVER_ADJUDICATOR_BASE_URL=https://provider.example/v1
SHOPASSIST_SILVER_ADJUDICATOR_API_KEY=...
SHOPASSIST_SILVER_ADJUDICATOR_MODEL=...
```

For a provider that supports request-level privacy/routing controls, the
optional `SHOPASSIST_SILVER_<SLOT>_REQUEST_OPTIONS_JSON` accepts only a
`provider` object. For example, OpenRouter can be restricted without changing
the configured model:

```text
SHOPASSIST_SILVER_A_REQUEST_OPTIONS_JSON={"provider":{"allow_fallbacks":false,"data_collection":"deny","zdr":true}}
```

The object is recorded as request provenance but credentials never are. It
cannot override the configured model, prompts, temperature, response format,
or request budget.

Never commit these values. The driver caps requests, uses bounded concurrency,
records individual failures, and only reuses a review whose blinded-input,
model, and prompt fingerprints are unchanged. `judge --max-cost-usd ...`
preflights the conservative maximum request cost only when the provider's input
and output prices are explicitly configured; it refuses to pretend an unknown
price is within budget.

## Provisional Phase 14 use and limits

`evaluate` reports Precision@K, MRR, nDCG@K, judged constraint-violation
rate, judgment coverage, and unjudged returned-result counts by retriever. It
never calls pool-conditional recall a catalog-wide recall measure and never
assigns an unjudged result grade 0. Reranking, actual end-to-end Phase 8,
latency, bootstrap uncertainty, split/tuning, and generation-quality results
remain blocked until their real captures exist.

`freeze-split` is intentionally refused until every frozen candidate pair has
a resolved Silver qrel and validation passes. It partitions by `intent_group`
using a recorded seed and checks that neither intent groups nor exact duplicate
raw queries cross development/held-out boundaries. Tuning must use only the
development partition.

The benchmark may guide research hypotheses. It must not on its own tune or
promote Cross-Encoder/combined reranking to production, establish user-facing
quality, or replace independently reviewed Gold evaluation data.
