# Phase 18.7 handover: supervised Telegram end-to-end testing

The actual local backend is validated for supervised Telegram testing. Seven of 22 preclassified API cases succeeded through real catalog-backed retrieval and local Q1S/R3; source/metadata checks passed. This does not approve production or guarantee broad relevance. Live Telegram user delivery was deliberately not tested in Phase 18.6.

## Prerequisites and test evidence

Use `D:\Project\ShopAssist`, the existing `.venv`, current local catalog/TF-IDF/BGE assets, reachable configured PostgreSQL/pgvector and existing Ollama model. Keep one FastAPI worker. Do not rebuild assets, change database state or download models to start a test. Confirm the [runtime audit](runtime_audit.md) and [API results](api_integration_report.md) before interpreting failures.

The current supervised config is `data/interim/phase18_6/route_validation/live_catalog_01/gateway.yaml`. It is isolated, contains only native routes and has 24-hour test evidence. Checked-in production and experimental-template routes remain disabled/pending. An expired approval must not be bypassed or silently renewed at request time.

When a new supervised test session is authorized, first rerun the guarded regression. With unchanged catalog, frozen prompts/model and validated source, create a **new** evidence directory using the explicit tool:

```powershell
Set-Location D:\Project\ShopAssist
.\.venv\Scripts\python.exe data/interim/phase18_6/run_offline_regression.py

# Save a passing report as UTF-8 or PowerShell UTF-16; use a new report filename.
# The verified Phase 18.6 report below is suitable only for its unchanged source.
.\.venv\Scripts\python.exe scripts/prepare_ollama_catalog_validation.py `
  --out data/interim/phase18_6/route_validation/telegram_session_new `
  --retrieval-evidence data/interim/phase18_6/retrieval_results/live_hybrid_preflight_01.json `
  --offline-report data/interim/phase18_6/offline_regression_05.txt
```

The command verifies fresh tags/digest, canonical shapes and the passing report; it writes artifact hashes, source hashes and exact fingerprints through the normal loader. It grants only supervised experimental test permission. If catalog, source, prompt, model or retrieval assumptions change, collect fresh preflight evidence instead of reusing old shapes:

```powershell
.\.venv\Scripts\python.exe scripts/preflight_phase18_6_retrieval.py `
  --observations data/interim/phase18_6/api_test_results/server_02/observations.jsonl `
  --out data/interim/phase18_6/retrieval_results/preflight_new.json
```

That command uses captured QU results and actual current retrieval; it makes no LLM calls and grants no approval. For changed semantics, capture fresh authorized QU/API observations first. Review current relevance and shapes, then point the explicit permission tool at the new artifact and current passing test report. Never use wildcard fingerprint approval, duplicate products or trim evidence to force eligibility.

## Windows startup

Terminal 1: verify the existing operator-managed Ollama server/model:

```powershell
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

The required tag is `qwen2.5:1.5b-instruct-local`, digest `d010eb818583111cfafeb3523cc17802f85dcb7f4fe5e8ecdd4927dca40e3174`. Do not pull or create a model. Startup and stale requests verify this identity using the same shared native client; successful tag text alone is insufficient.

Terminal 2: select the newly authorized config explicitly and start the verified application entry point:

```powershell
Set-Location D:\Project\ShopAssist
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:PGCONNECT_TIMEOUT='5'
$env:PGOPTIONS='-c default_transaction_read_only=on'
$env:LLM_GATEWAY_ENABLED='true'
$env:LLM_GATEWAY_RUNTIME='ollama_experimental'
$env:LLM_GATEWAY_CONFIG_PATH='data/interim/phase18_6/route_validation/telegram_session_new/gateway.yaml'
$env:LLM_GATEWAY_AUTO_FAILOVER='false'
$env:LLM_GATEWAY_MAX_ATTEMPTS_PER_TASK='1'
$env:LLM_GATEWAY_ATTEMPT_TIMEOUT_SECONDS='30'
$env:LLM_GATEWAY_OLLAMA_IDENTITY_TTL_SECONDS='300'
$env:LLM_GATEWAY_OLLAMA_APPROVED_ENDPOINTS='[]'
$env:API_HOST='127.0.0.1'
$env:API_PORT='8000'
$env:API_REQUEST_TIMEOUT_SECONDS='90'
$env:API_DEFAULT_TOP_K='3'
$env:API_RETRIEVAL_TOP_N='20'
$env:API_RERANKING_METHOD='RRF'
.\.venv\Scripts\python.exe -m shopassist.api.main
```

Retain the existing local database credentials; do not paste them into reports. These process-scoped settings do not modify `.env` or enable production YAML. The YAML remains the only endpoint/model/inference-options source. The native profile forbids cloud fallback and uses maximum one QU plus one R3 call.

In a separate shell, check liveness/readiness and run the verified public API smoke:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/live
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
$body=@{query='running shoes under 2000 INR';top_k=3;language='en'} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/recommend `
  -ContentType 'application/json; charset=utf-8' -Body $body
```

Expect `alive`, healthy readiness and `SUCCESS` for that verified fixture under unchanged resources. Inspect the business status, metadata/URLs, usage and telemetry, not HTTP 200 alone. Identity checks refresh on stale inference requests; they never renew route approval. An idle readiness probe can report stale identity before the next task rechecks it. Database failure, expired approval or changed model requires resolving the actual condition, not weakening guards.

Gateway JSONL defaults to `data/interim/llm_gateway/gateway.jsonl`, or the explicit `LLM_GATEWAY_TELEMETRY_DIR`. Inspect `attempt`/`task_summary`/`fallback`, provider/model/digest, schema fingerprint, request/task IDs, usage, error reasons and attempt counts. No prompts, raw responses, credentials or authorization headers belong in production telemetry. Phase 18.6 isolated observation files contain evaluation content and must remain separate.

Terminal 3, only during authorized Phase 18.7 user testing:

```powershell
Set-Location D:\Project\ShopAssist
$env:TELEGRAM_BOT_TOKEN='<operator-provided-token>'
$env:SHOPASSIST_API_URL='http://127.0.0.1:8000'
$env:BOT_REQUEST_TIMEOUT_SECONDS='95'
$env:BOT_DEFAULT_TOP_K='3'
.\.venv\Scripts\python.exe -m shopassist.bot.main
```

Both module entry points exist; the API command was actually run and checked. The bot command is verified against existing source and mocked tests, not by Telegram network execution in this phase. Use the operator's configured token; never place a real token in documentation/artifacts. Avoid starting a second polling instance for the same bot.

## Messages and acceptance

Begin with `/start`, then `running shoes under 2000 INR` and `AMCO running shoes under 2000 INR`. Verify actual card delivery, INR price, catalog link/image where present, source quotations and session IDs. Then try `Shoes not exceeding 2000 rupees`, an empty-result budget, genuine exclusions, foreign currency and missing intent. Expected clarification or safe terminal behavior is valid; it must not display unrelated candidates as successful recommendations.

Preserve wireless charging pad → Lightning cable, Bluetooth speaker → headphones and Honda City body cover → steering cover as negative cases. Do not relax R3. The Vietnamese case currently asks clarification, and catalog quotations can retain English wording. Record usefulness/language judgments separately from source fidelity.

After user-delivery checks, stop bot polling with Ctrl+C, then stop FastAPI with Ctrl+C so clients/database pools close. Leave the operator's Ollama service alone unless they choose otherwise. Keep backend/bot at 90/95 seconds, single worker, process-local quota and at most two inference calls. No public tunnel or direct LLM/DB access belongs in Telegram; the bot remains a presentation/API client.

Production remains unapproved: independent semantic/usefulness review, wider coverage/relevance, operational availability and historical backup/failover gates are open. Local-only operation does not satisfy the original cloud-backup acceptance requirement without a separate recorded scope decision. Overall Phase 18 is not complete.
