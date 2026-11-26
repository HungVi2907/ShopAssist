# Phase 18.5 handover — common Ollama Native Gateway adapter

Phase 18.4 selected **R3 fact selection plus Python source quotations** for guarded compatibility testing. Production activation is not approved. Q1S remains experimental; semantic usefulness/independent human review and complete relevance handling are unresolved. Phase 18 remains `IMPLEMENTED_PENDING_BACKUP_VALIDATION`; the historical T17 ledger is untouched and exhausted.

## Task bindings

| Task | Caller-owned schema and postprocessing | Proposed distinct binding |
|---|---|---|
| Query Understanding | Frozen `ExtractedShoppingIntent` from Phase 18.3; original-query transformation and semantic validation remain outside Gateway. Do not reopen prompt optimization. | New flat-intent schema ID, e.g. `phase8.intent.flat.v1`; never substitute it for `phase8.query.v1`. |
| Recommendation Generation | Required per-product selection keys and bounded fact-index arrays from `selection_schema(supplied)`; caller retains alias→product/evidence maps, source templates and relevance/fallback gates. | `phase12.catalog-selection.v2`, with per-request schema fingerprint; never substitute it for `phase12.recommendation.v1`. |

The selection schema is generated from candidate cardinality and supplied fact counts. The adapter should accept the caller's Pydantic response schema and send its exact JSON Schema through native `format`, rather than hardcoding one five-product shape. Validate route evidence across 1/3/5 candidates, sparse/rich evidence, malformed/unknown keys and context limits. Stable schema meaning/version plus actual fingerprint are both needed for reproducibility.

## Adapter capabilities

1. Use native `POST /api/chat`, `messages`, `format`, `stream=false` and task-specific `options`. Never translate to OpenAI-compatible endpoints. The measured model is `qwen2.5:1.5b-instruct-local`, digest `d010eb818583111cfafeb3523cc17802f85dcb7f4fe5e8ecdd4927dca40e3174`.
2. Configure base URL/model and bounded task options in an isolated pending profile. Existing Gateway provider/endpoint allowlists and provider enums currently lack native Ollama support; extend and test them deliberately. Local endpoint needs no authentication in this experiment; any remote/authenticated endpoint requires explicit endpoint/credential binding, not arbitrary forwarded headers. Do not log credentials or prompt/response content.
3. Use one startup-owned `httpx.AsyncClient`/connection pool for both tasks. Existing experimental clients must become injected task consumers or be retired from production composition; do not accumulate per-task permanent HTTP clients. Respect ownership on shutdown and use one async event loop.
4. Map `prompt_eval_count`, `eval_count`, native durations, completion status and `done_reason` to usage/attempt evidence. Total tokens are the reported counts' sum. Unknown usage remains unknown; a failed/truncated generation is not a successful recommendation. Estimated monetary cost must not be invented from absent provider cost data.
5. Validate reported model tag and startup/current `/api/tags` digest against route evidence. Do not silently accept another model. No pull/create/delete/download operation is part of adapter startup.
6. Enforce parent deadline before dispatch; request timeout is the smaller of configured attempt timeout and remaining parent time, leaving room for validation/assembly. HTTP timeout may yield caller-controlled deterministic fallback; parent expiry and cancellation must propagate through existing typed Gateway errors. Preserve the distinction between parent/attempt deadline and avoid swallowing task cancellation.
7. Preserve at most one inference attempt per task under the current requirement: a native profile must not inherit two-attempt failover to an external provider. Failure uses the caller's explicit invalid/clarification/catalog fallback path. No paid/external route may be introduced through an automatic backup.
8. Admit context conservatively and expose overflow instead of silently trimming requirements/evidence. Check completion status, lengths and schema; duplicate keys, unknown product keys, invalid fact indices or wrong model must fail validation. The Gateway performs transport/structural validation; product/evidence ownership, quote assembly and suitability gates remain in the caller.

## Measured configuration and composition work

Q1S keeps its frozen extraction settings. Recommendation selection was compared initially at 1536 output tokens, then measured at a 256-token final cap: maximum development completion 73, prompt maximum 712 tokens; provisional prompt maximum 769, completion maximum 47. Final development generation-stage P95 for actual R3 calls was about 946 ms. These are small local samples, not universal latency guarantees. The original nested payload still truncated at 1536, and a sparse case also truncated at 2048; do not bind that payload under the selection route's budget.

Current `RecommendationService(local_generator=...)` is explicit experimental injection only. Phase 18.5 should add caller schema/request binding and native adapter construction at the existing startup composition point, keep all routes disabled/pending during validation, and preserve request/task IDs, attribution, health/quotas, cancellation and one-attempt policy. Register schema decoders without treating selection indices as the public recommendation payload. Preserve `QueryUnderstandingResult` and `RecommendationResult` and explicit upstream terminal states.

Current API/bot timeouts are 90/95 seconds and recommendation HTTP timeout 30 seconds; do not consume the full parent budget in a child. Public recommendation items have no URL field: keep existing API/catalog URL assembly rather than changing schemas or asking the model to reproduce URLs.

## Evidence and open gates

Use `frozen_candidate/final/manifest.json`, exact request schemas, fixtures, raw outputs and `experiment_manifests/index.json`. The generation source/prompt/schema was frozen before new provisional cases; later composition-only guards and schema descriptor corrections are separately recorded. Semantic review is provisional: no independent human reviewer approved usefulness, claim interpretation, relevance or language quality. Selected strings are catalog quotations, not independently established truth or guarantees of fit.

Phase 18.6 should investigate the preserved pad→cable, speaker→headphones and body-cover→steering-cover relevance failures. R3 currently refuses them; it does not repair retrieval. The relevance guard also rejects some legitimate synonyms/unsupported mandatory features, so no broad coverage claim is justified. Vietnamese templates retain raw catalog facts, with potential English code-switching. The historical free-text validator still does not prove entailment and must not be treated as a semantic acceptance oracle.

Before route approval: guarded native transport/Gateway tests for both bindings; API composition tests; no-external-network/cost checks; route/model/schema-specific validation; supervised catalog-backed end-to-end testing; independent groundedness/usefulness/language review; and the existing approval gates. Adapter implementation or successful JSON alone must not mark Phase 18 complete or reset T17.
