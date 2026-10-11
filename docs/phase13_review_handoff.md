# Phase 13 review and release handoff

The main draft is `data/evaluation/phase13/v2/`. It contains 200 **unreviewed** queries. The 40-query `v1` pilot is unchanged. Blank reviewer and adjudicator templates are in `v2/annotation_tasks/`; their empty rows are tasks, not labels. All commands below use the runtime described in [phase13_runtime.md](phase13_runtime.md). Substitute real reviewer IDs and new version names. Never overwrite an existing version or task directory.

## 1. Independent query review

Assign two real people distinct IDs. Generate separate blind copies in a **new** directory:

```powershell
$py='.\.deps\phase13-win-venv\Scripts\python.exe'
& $py scripts/prepare_phase13_annotation_tasks.py --dataset data/evaluation/phase13/v2 --out data/evaluation/phase13/query_review_round1 --reviewer-a-id <real_id_a> --reviewer-b-id <real_id_b>
```

Give each person only their own `query_tasks_<id>.csv`. Keep submissions private until both are complete. Fill the Phase 8 interpretation, currency, exact price operators, preferences JSON, stop status, and comments. The adjudicator fills `query_adjudications_template.jsonl` with one explicit decision per query, a real `adjudicator_id`, and a reason wherever reviewers disagree. The existing draft `query_type` and `planning_category` are planning cues; reviewers should flag taxonomy mistakes for a later version. Verify every `NO_RESULTS` judgment against the pinned catalog and exact constraints before finalizing it.

Assemble a new version. For the first round, the relevance and claim task/decision files remain header-only:

```powershell
& $py scripts/assemble_phase13_ground_truth.py --dataset data/evaluation/phase13/v2 --out data/evaluation/phase13/v3 --query-reviews <completed_query_a.csv> <completed_query_b.csv> --query-decisions <completed_query_adjudications.jsonl> --relevance-reviews data/evaluation/phase13/v2/annotation_tasks/relevance_tasks.csv --relevance-decisions data/evaluation/phase13/v2/annotation_tasks/relevance_adjudications_template.csv --claim-reviews data/evaluation/phase13/v2/annotation_tasks/claim_tasks.csv --claim-decisions data/evaluation/phase13/v2/annotation_tasks/claim_adjudications_template.csv
```

The assembler requires exactly two distinct reviewer rows and one named adjudication per query. It rejects missing decisions and disagreements without reasons. It preserves submitted rows and final decisions in separate files. `v3` is still unfrozen and not Phase 14 ready.

## 2. Freeze real Phase 10 candidates and judge relevance

Only after query adjudication, run read-only Phase 10 capture. The database ID inventory must match the pinned catalog. Capture records the Top-20 retrieval configuration, exact boundary operators, catalog hash, timestamp, rank/branch provenance, canonical text, and literal catalog eligibility count. A `NO_RESULTS` pool is only marked verified when exact catalog constraints have zero eligible rows.

```powershell
& $py scripts/capture_phase13_candidates.py --dataset data/evaluation/phase13/v3 --out data/evaluation/phase13/staging/v3_candidates.jsonl
& $py scripts/promote_phase13_capture.py --source data/evaluation/phase13/v3 --capture data/evaluation/phase13/staging/v3_candidates.jsonl --kind candidates --out data/evaluation/phase13/v4
& $py scripts/prepare_phase13_annotation_tasks.py --dataset data/evaluation/phase13/v4 --out data/evaluation/phase13/relevance_review_round1 --reviewer-a-id <real_id_a> --reviewer-b-id <real_id_b>
```

Use only the blinded `relevance_tasks_<id>.csv` for reviewers. It excludes rank, score, branch and competing labels. Supply all five constraint flags plus a 0–3 grade for **every** frozen query-product pair. The adjudicator fills `relevance_adjudications_template.csv`. A final grade >=2 cannot have a hard-constraint violation. For pool-conditional Recall@K, use the frozen pool as denominator and state the limitation; catalog-wide Recall@K needs an independently judged supplemental candidate source.

Re-run `assemble_phase13_ground_truth.py` with source `v4`, the same query submissions/decisions, both completed relevance submissions/decisions, and header-only claim files, writing `v5`. Reviewer agreement reports the actual pair count, exact grade agreement, disagreement count, and quadratic-weighted kappa; kappa is null for fewer than two pairs or an undefined expected denominator.

## 3. Freeze Phase 12 outputs and review claims

The saved real Phase 12 input is JSONL, one object per generation interaction:

```json
{"query_id":"Q0001","generation_snapshot":"<real_snapshot_id>","provider":"<real_provider>","model_version":"<actual_model>","prompt_configuration":"<actual_prompt_or_hash>","result":{}}
```

`result` must be an actual serialized `RecommendationResult` with product IDs and `available_evidence`. Save the exact result outside a dataset version. The capture utility validates product/evidence association with frozen pools and stores a SHA-256 of the result; no output is fabricated. Capture at least 50 distinct query/snapshot interactions for the full generation-quality gate, including real unsupported and missing-information cases.

```powershell
& $py scripts/capture_phase13_generation.py --source <saved_real_phase12_results.jsonl> --dataset data/evaluation/phase13/v5 --out data/evaluation/phase13/staging/v5_claims.csv
& $py scripts/promote_phase13_capture.py --source data/evaluation/phase13/v5 --capture data/evaluation/phase13/staging/v5_claims.csv --kind generation --out data/evaluation/phase13/v6
& $py scripts/prepare_phase13_annotation_tasks.py --dataset data/evaluation/phase13/v6 --out data/evaluation/phase13/claim_review_round1 --reviewer-a-id <real_id_a> --reviewer-b-id <real_id_b>
```

Two reviewers independently label support, factual correctness, recommendation relevance, and missing-information handling for each claim. A valid evidence ID alone does not make a claim supported. The adjudicator fills `claim_adjudications_template.csv`; reconcile disagreements with reasons. Re-run the assembler with all completed query, relevance and claim submissions, writing `v7`.

## 4. Freeze a release only after review

The split planner groups declared intent families and detected lexical near duplicates, then balances category, type, language and difficulty. It uses a fixed seed. Test the planner on synthetic fixtures while labels are pending. Do not inspect a held-out partition during tuning.

```powershell
& $py scripts/plan_phase13_splits.py --dataset data/evaluation/phase13/v7 --out data/evaluation/phase13/staging/proposed_split.json --seed 13 --held-out-fraction 0.3
& $py scripts/plan_phase13_splits.py --dataset data/evaluation/phase13/v7 --release-out data/evaluation/phase13/v8 --freeze --seed 13 --held-out-fraction 0.3
& $py scripts/validate_phase13_dataset.py --dataset data/evaluation/phase13/v8
```

The release command refuses to freeze if any query interpretation, candidate pair, claim review, 50-generation-case coverage, catalog no-result verification, or artifact hash is incomplete. The new version records final split IDs, seed, timestamp, group mapping and per-file hashes. Phase 14 additionally requires regression evidence and critical blockers resolved in the manifest. The validator's technical `phase14_ready` flag is a necessary gate; a human audit must still confirm review quality and held-out access control.
