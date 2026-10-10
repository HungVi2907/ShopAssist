"""Build traceable Phase 8.2 offline reports without making provider calls."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from shopassist.llm.experiments.phase82.candidates import CANDIDATES
from shopassist.llm.experiments.phase82.runner import atomic_write, digest

OUT = ROOT / "data/interim/phase8_2"
DOC = ROOT / "docs/phase8_2"
NOW = datetime.now(timezone.utc).isoformat()
STATUS = "NOT_RUN_USER_DEFERRED"


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf8"))


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf8")


def pct(value):
    return "N/A" if value is None else f"{100*value:.2f}%"


def table(headers, rows):
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "\n".join(
        "| " + " | ".join(str(v).replace("|", "/").replace("\n", " ") for v in row) + " |" for row in rows)


ISSUES = [
    ("ISSUE-01", "High", "UNRESOLVED", "Soft preferences below target",
     "Old heldout E5-B has 7/20 soft mismatches; TP=18, FP=9, FN=3; strict macro F1=78.33%, micro F1=75%.",
     "Product-class duplication, omitted attributes, compatibility confusion, literal synonyms and disputed unsupported-domain labels.",
     "Audit HELD001/002/005/007/013/019/020; run audit_phase8_2.py.",
     "prompts.py, prompt_variants.py, refinement_rules.py, scoring.py", "C2-C5 prompts; contextual cleanup; independent label review. Product cleanup fixes HELD005 on replay only."),
    ("ISSUE-02", "High", "UNRESOLVED", "Low complete slot accuracy",
     "E5-B full v2 slot EM=10/20; shared-field EM=12/20. Error counts overlap: soft 7, product type 2, exclusions 2, brand 1, clarification 1, active boundaries 0.",
     "Several independently imperfect slots compound into a failed query; exact wording is a separate metric.",
     "Inspect failure_analysis.json per-case records; compare field mismatches.",
     "schema_variants.py, scoring.py, failure_analysis.json", "Improve individual slots; keep strict metric. No semantic extraction winner adopted."),
    ("ISSUE-03", "Medium", "RESOLVED", "Development failure classification",
     "QU033 and QU036 both exhausted 429 retries. No successful provider JSON exists for these failures.",
     "Legacy validity combined transport and schema failures; fallback rules overwrote QU033's provider reason.",
     "Compare dev E5-B records with preserved raw cache; invalid_cases identifies API_429_RETRY_EXHAUSTED.",
     "gemini_client.py, runner.py, audit_phase8_2.py", "Stage diagnostics and failure-aware scoring implemented. JSON/schema defect allegation NOT REPRODUCED for these two cases; provider quota remains an operational risk."),
    ("ISSUE-04", "Medium", "DEFERRED", "Temperature conclusion unsupported",
     "E2 used E1-B/v1, not E5-B/v2. T1 quality is higher in those stored runs; T0/T0.5 also have API failures. No independent repeated-run evidence.",
     "Architecture transfer and quota confounding; no theorem makes T0 best for extraction.",
     "Inspect E2 configurations and raw cache; dry-run B0,T05,T10 with repetitions=3.",
     "prompt_variants.py, candidates.py, research_review.md", "Same-E5-B 0/0.5/1 experiment prepared; user explicitly deferred larger live work."),
    ("ISSUE-05", "High", "RESOLVED", "Unfair exact-match comparisons",
     "Original 98% excludes preferences. Historical 54% is common-field EM. The old v1 5% vs v2 50% mixed field capabilities; missing null product_type and active boundary flags received credit.",
     "Scoring defaults masked missing fields and failures; schema capability was confused with shared extraction quality.",
     "Run independent scoring tests and audit; same-query shared EM is 40% vs 60%.",
     "evaluation.py, experiments/metrics.py, phase82/scoring.py", "Independent versioned common/full-v2 metrics with explicit missing-field and failure policy. Old scorer retained solely for historical reproduction."),
    ("ISSUE-06", "High", "IMPROVED", "Rules can alter intent",
     "Historical rules damage 9/18 authored oracle outputs. Conservative rules preserve all 18. This is a rule-invariance test, not LLM quality evidence.",
     "Naive negation cues, unbound price operators, substring domain detection and global class-word blacklists.",
     "Test not only/not necessarily/not too expensive/except Nike/no less than/not under/double negation; run rule tests and offline ablations.",
     "refinement_rules.py, phase82/rules.py", "Isolated narrow evidence rules implemented. Ambiguous and multilingual scope is still not solved; production rules not switched."),
    ("ISSUE-07", "High", "UNRESOLVED", "Entity extraction versus filter activation",
     "Boeing is a named manufacturer in QU033. HELD020 treats Honda compatibility as accessory brand and omits for Honda City.",
     "Business support policy conflates named entities with active catalog filters; a single brand slot cannot encode both.",
     "Inspect QU033 raw output and HELD020; compare brand-preserving rule replay.",
     "normalization.py, refinement_rules.py, query_contract_review.md", "Preserve named manufacturers in experimental extraction; gate unsupported queries before filtering. Old labels unchanged; policy adjudication pending."),
    ("ISSUE-08", "High", "IMPROVED", "Coverage and annotation limitations",
     "13/15 development queries overlap original50. New 20/20/40 fixtures have 80 unique exact queries and no overlap with old fixtures.",
     "Small handcrafted data and single-annotator policy choices; exact disjointness does not establish semantic independence.",
     "Run fixture builder and dataset_integrity.json audit.",
     "tests/fixtures/phase8_2, build_phase8_2_fixtures.py", "Labels authored before predictions; independent annotation and ambiguous-case adjudication still pending."),
    ("ISSUE-09", "Medium", "IMPROVED", "Latency, tokens and cache provenance",
     "Old cache keys omit prompt/schema content and settings, cache errors, round temperature and reuse stored latency. Retry counts and cache flags are incomplete.",
     "Logical cases were counted instead of actual attempts; stored metrics cannot isolate provider speed.",
     "Run runner tests for fingerprint changes, failure caching, resume and budget exhaustion.",
     "experiments/runner.py, phase82/runner.py, gemini_client.py", "New content hashes, success-only opt-in cache, persistent attempt/token reservations and stage timings. Fresh comparative performance remains unmeasured."),
    ("ISSUE-10", "High", "UNRESOLVED", "v2 to v1 semantic loss",
     "Adapter drops product_type, strict/inclusive flags and typed exclusions; negatives become soft strings and may be truncated at ten preferences.",
     "Structural compatibility cannot preserve meanings absent in the target schema.",
     "Read both to_v1 methods and run existing schema adapter tests; see contract review example.",
     "schemas.py, schema_variants.py", "Versioned consumer migration proposed; no breaking production schema switch made."),
    ("ISSUE-11", "Medium", "RESOLVED", "Documentation contradictions",
     "Old report says seven resolved issues but enumerates eight; unsupported determinism, validity, latency and readiness guarantees remain in historical prose.",
     "Narrative claims exceeded per-case evidence and blurred experimental versus adopted behavior.",
     "Read synchronization addenda and compare generated figures with audit JSON.",
     "README.md, Phase8/8.1 reports, conceptual guides", "Explicit superseding corrections preserve historical measurements and provide current status counts."),
    ("ISSUE-12", "High", "IMPROVED", "Operational safety and lifecycle",
     "Settings representation/serialization and provider errors exposed sensitive values; Windows smoke teardown reproduced SSL transport warnings. Two-test retest passed after lifecycle fix.",
     "Unrestricted exception text, double retry layers, lazy SDK sessions closed after their owning event loop.",
     "Run reliability tests for 401/403/429/503/timeout/invalid JSON/key redaction/input bounds; inspect smoke_retest.xml.",
     "config.py, security.py, gemini_client.py, query_understanding.py, test_gemini_integration.py", "Redacted settings/errors, one retry owner, exact model identity, usage-before-validation, same-loop cleanup. Injection immunity, retention policy, strict coercion and finite numeric validation remain open."),
]


def test_evidence():
    results = {}
    for name in ("baseline_tests", "focused_tests", "regression_tests", "smoke_tests", "smoke_retest"):
        path = OUT / (name + ".xml")
        if not path.exists():
            continue
        root = ET.parse(path).getroot()
        suites = list(root.iter("testsuite"))
        counts = {k: sum(int(s.attrib.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
        counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
        counts["seconds"] = sum(float(s.attrib.get("time", 0)) for s in suites)
        counts["artifact"] = str(path.relative_to(ROOT)).replace("\\", "/")
        results[name] = counts
    return results


def main():
    audit = load("baseline_audit.json")["audits"]
    ablations = load("rule_ablation_results.json")["results"]
    failures = load("failure_analysis.json")
    integrity = load("dataset_integrity.json")
    baseline = audit["baseline_50"]["E0"]["standardized"]
    held = audit["legacy_heldout_20"]
    hm = {k: v["standardized"] for k, v in held.items()}
    tests = test_evidence()
    inventory = [dict(zip(("id", "severity", "status", "title", "evidence", "root_cause", "reproduction", "affected", "solution"), row)) for row in ISSUES]
    for item in inventory:
        item["tests"] = "Offline audit, targeted Phase8.2 tests and repository regression; see verification_report.json. Live evidence only the bounded production smoke subset."
    atomic_write(OUT / "issue_inventory.json", {"timestamp_utc": NOW, "issues": inventory,
        "status_counts": dict(Counter(x["status"] for x in inventory)), "scope": "12 requested investigations; original14 mapped in Markdown"})
    manifest = load("baseline_manifest.json")
    registry = []
    for key, candidate in CANDIDATES.items():
        registry.append({**candidate.metadata(), "model": manifest["configuration"]["model"] if "configuration" in manifest else "gemini-3.1-flash-lite",
            "prompt_sha256": digest(candidate.prompt), "schema_sha256": digest(candidate.schema.model_json_schema()),
            "prompt_characters": len(candidate.prompt), "dataset_version": "1.0.0", "status": STATUS,
            "new_api_requests": 0, "timestamp_utc": NOW, "metrics": None, "token_usage": None,
            "latency": None, "cache_status": "NOT_RUN", "retry_status": "NOT_RUN"})
    atomic_write(OUT / "experiment_registry.json", {"status": STATUS, "candidates": registry,
        "offline_groups": ["A historical audit", "D schema static review", "E shared-response rule ablation", "F oracle invariance", "G mocked reliability"],
        "future_plan": {"planned_calls": 312, "attempt_ceiling": 360, "token_ceiling": 500000, "approval": "User chose offline completion; no permission for larger live runs"}})
    for name, ids in (("prompt", ["B0", "C2", "C3", "C4", "C5"]), ("temperature", ["B0", "T05", "T10"]), ("schema", ["B0", "D1"])):
        atomic_write(OUT / (name + "_experiment_results.json"), {"status": STATUS, "new_api_requests": 0,
            "timestamp_utc": NOW, "results": [x for x in registry if x["id"] in ids],
            "historical_reference": "baseline_audit.json; E2 temperature runs used a different v1 architecture"})
    atomic_write(OUT / "heldout_evaluation_results.json", {"status": STATUS, "fresh_dataset": integrity["sets"]["phase82_heldout"],
        "fresh_metrics": None, "new_api_requests": 0, "timestamp_utc": NOW,
        "historical_reanalysis_only": held, "independent_annotation": "PENDING"})

    metric_rows = []
    for label, value in (("Original50 (different dataset)", baseline), ("Old heldout20 E1-A/v1", hm["E1-A"]), ("Old heldout20 E5-B/v2", hm["E5-B"])):
        metric_rows.append([label, pct(value["schema_validity"]["rate"]), pct(value["hard_micro"]["f1"]),
            pct(value["soft_macro_f1"]), pct(value["soft_micro"]["f1"]), pct(value["common_exact"]["rate"]),
            "N/A for fair comparison" if "v1" in label else pct(value["full_v2_exact"]["rate"])])
    metric_table = table(["Stored output reanalysis", "Valid", "HC micro F1", "Soft macro F1", "Soft micro F1", "Common EM", "Full v2 slot EM"], metric_rows)
    abl_table = table(["Rule variant / identical E5-B raw20", "HC F1", "Soft macro F1", "Common EM", "Full v2 EM", "Fixed full queries", "New full failures"],
        [[r["variant"], pct(r["metrics"]["hard_micro"]["f1"]), pct(r["metrics"]["soft_macro_f1"]), pct(r["metrics"]["common_exact"]["rate"]),
          pct(r["metrics"]["full_v2_exact"]["rate"]), ", ".join(r["corrected_full_em"]) or "0", ", ".join(r["introduced_full_em"]) or "0"]
         for r in ablations if r["dataset"] == "legacy_heldout_20"])
    err_table = table(["Case", "Soft false positives", "Soft false negatives", "Other failed fields"],
        [[r["test_id"], ", ".join(r["score"]["soft_fp"]) or "none", ", ".join(r["score"]["soft_fn"]) or "none",
          ", ".join(r["mismatch_fields"] + (["product_type"] if r["product_type_failure"] else []) + (["exclusions"] if r["exclusion_failure"] else [])) or "none"]
         for r in failures["failures"] if r["split"] == "legacy_heldout_20" and r["experiment"] == "E5-B"])
    test_table = table(["Executed check", "Passed", "Failed/errors", "Scope"],
        [[name, value["passed"], value["failures"] + value["errors"],
          "All tests except Gemini integration module" if name == "regression_tests" else "Bounded live subset; 2 distinct tests" if "smoke" in name else "Offline"] for name, value in tests.items()])

    write(DOC / "issue_investigation.md", """# Phase 8.2 issue investigation and root causes

Date: 2026-10-09. Source-of-truth evidence: preserved source snapshots, original raw cache, independent audit JSON and executed tests. Larger live comparisons were explicitly deferred by the user. Confirmed means supported by source inspection or execution; suspected means further evidence is necessary.

## Original issues and Phase 8.1 changes

The original registry has fourteen P8 issues. Phase8.1 added experimental product type, typed exclusions and boundary flags, prompts and deterministic refinements. These never replaced the production v1 parser. Existing unit tests established particular examples, not broad semantic resolution.

| Original ID | Current assessment | Phase8.2 investigation |
| --- | --- | --- |
| P8-01 preference quality | Unresolved | ISSUE-01 |
| P8-02 product type | Improved experimentally; not production-resolved | ISSUE-01/02/06 |
| P8-03 negation schema | Representation added; extraction still imperfect | ISSUE-02/06/10 |
| P8-04 strict prices | v2 representation exists; v1 cannot carry flags | ISSUE-06/10 |
| P8-05 SQL column | Documentation uses product_name; resolved documentation defect | ISSUE-11 |
| P8-06 metrics | Independent policy implemented; old metric retained as historical | ISSUE-05 |
| P8-07 Boeing | Entity/filter policy disagreement remains | ISSUE-07 |
| P8-08 performance | Better instrumentation; speed improvement unproven | ISSUE-09 |
| P8-09 failure contract | Safe public failures implemented; operational failures remain | ISSUE-03/12 |
| P8-10 multi-turn | Deferred; single-turn scope remains | ISSUE-10 |
| P8-11 currency conversion | Deferred; foreign currency must clarify | ISSUE-06/10 |
| P8-12 category ambiguity | Unresolved for alternatives and unsupported domains | ISSUE-07/08 |
| P8-13 injection | Limited mocked checks; absolute immunity unproven | ISSUE-12 |
| P8-14 diagnostics | Error leakage improved; raw result envelope still private data | ISSUE-12 |

## Current evidence inventory
""" + "\n\n".join(f"### {i['id']} — {i['title']}\n\nSeverity: {i['severity']}. Status: **{i['status']}**.\n\nEvidence: {i['evidence']}\n\nRoot cause: {i['root_cause']}\n\nReproduce: {i['reproduction']}\n\nAffected: `{i['affected']}`.\n\nCandidate/fix: {i['solution']}\n\nValidation: {i['tests']}" for i in inventory) + """

## Per-case diagnosis and rejected fixes

""" + err_table + """

HELD007 is a reviewed lexical mismatch (lumbar support versus with lumbar support); supplementary equivalence handles it without changing strict labels. HELD013 and HELD019 expose an annotation policy question: useful attributes in unsupported domains were labeled empty. Do not erase original predictions or amend historical labels to improve scores. HELD004 has attribute-versus-feature exclusion typing; HELD015 has a wrong telephoto target and duplicate phrase introduced by rules. HELD020 is a real compatibility/brand confusion.

Rejected: universal deletion of product modifiers, substring rejection of any query mentioning milk/airplanes, suppressing all unsupported-domain manufacturer names, broad synonym/embedding acceptance, treating quota fallback as valid extraction, and production adoption based on already inspected heldout examples. Narrow rules improve isolated cases but cannot repair all semantic scopes.

The inventory contains 12 investigations: 3 RESOLVED, 4 IMPROVED, 4 UNRESOLVED, 1 DEFERRED. RESOLVED applies to the stated diagnostic/scoring/documentation issue, not to all upstream semantics. Independent annotation, finite numeric validation, sensitive-data retention, multilingual extraction and repeated live sampling remain open.
""")

    write(DOC / "experimental_methodology.md", r"""# Phase 8.2 experimental methodology

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
""")

    dev_rows = [[key, pct(v["standardized"]["schema_validity"]["rate"]), pct(v["standardized"]["hard_micro"]["f1"]),
                 pct(v["standardized"]["soft_macro_f1"]), pct(v["standardized"]["common_exact"]["rate"])] for key, v in audit["dev_15"].items()]
    fields = hm["E5-B"]["field_accuracy"]
    write(DOC / "experimental_results.md", """# Phase 8.2 experimental results

Date: 2026-10-09. Decision: PARTIAL. All tables below derive from stored output audit or explicitly identified offline execution. Larger live comparisons and fresh heldout inference are NOT_RUN_USER_DEFERRED; there are no invented candidate accuracy, timing or token figures.

## Verified historical baseline and fair comparison

""" + metric_table + """

Original50 reproduces hard micro F1=99.696%, soft macro F1=66.4095% and common EM=27/50. The historical 98% exact match omitted preferences. Original50 and oldheld20 are different datasets, so their percentages are not a before/after treatment effect.

For oldheld20, E1-A/v1 versus E5-B/v2 shared-field EM is 8/20 versus12/20, not the old full-schema 1/20 versus10/20 claim. E5-B full v2 slot EM is10/20. A v1 output cannot faithfully represent v2 fields; full-v2 capability scoring is excluded from fair quality comparisons.

## Development audit and temperature contradiction

""" + table(["Historical dev experiment", "Valid", "HC micro F1", "Soft macro F1 (failure-aware)", "Common EM"], dev_rows) + """

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

""" + abl_table + """

Every row uses the same twenty valid raw E5-B responses. All twelve original/narrow ablations also run on the thirteen valid raw development responses; the two provider failures are excluded equally, not erased from end-to-end experiment metrics. Full per-case outputs and changed-case lists are in rule_ablation_results.json.

Contextual product cleanup fixes HELD005 and changes soft macro F1 from78.33% to80%; foreign-currency clarification fixes HELD009. Combined common/full-v2 EM becomes70%/60% on already inspected oldheld20. Hard F1 remains98.46% with literal manufacturer preservation, versus99.22% under historical brand suppression matching the old business-policy label. This apparent hard-score loss is an extraction/filter-policy disagreement; it still prevents claiming an unqualified improvement. No new full-match failures appear in this replay, but it is not independent adoption evidence.

Historical negation adds a duplicate telephoto exclusion in HELD015; because it was already wrong, full-match counts conceal the additional slot damage. Historical price changes flags on absent bounds (HELD008/009), which scoring correctly ignores. Report changed fields as well as whole-query gains/losses. Narrow price/brand/negation groups show no full-query gain on this sample; retain only as experimental hypotheses pending broader evaluation.

## Robustness and per-field heldout results

Oracle invariance feeds hand-authored expected structures through rules: historical9/18 remain correct, conservative18/18 remain correct. The second interval is roughly82.4–100%, and even that pertains to the authored rule sample. Neither is Gemini extraction accuracy. Multilingual, typo, long-input and adversarial live robustness are not measured.

E5-B oldheld20: category/min-price/max-price/rating/currency100%; brand95%; clarification95%; product type90%; exclusion exact90%. Exclusion micro F1 is28.57% (TP1, FP3, FN2), despite macro/exact90%, because most queries have no exclusions. Active lower flags2/2 and upper flags13/13 match; that is small conditional coverage, not broad boundary reliability. Semantic-query lexical accuracy is8/20 and is separate from full slot EM.

## Individual failures

""" + err_table + """

There are ten full-v2 failed queries. Overlapping field failures are soft7, type2, exclusions2, brand1, clarification1, boundary0. Lumbar wording has a narrow supplementary equivalence; unsupported-domain preferences and feature typing need annotation adjudication. Honda City is a substantive compatibility error, not a synonym issue.

## Timing, tokens and uncertainty

Historical original50 stored median1580.5ms, average1206.2 tokens; oldheld20 baseline median1638.2ms/1208tokens, E5-B1480.8ms/659.65tokens. These are stored descriptive figures with incomplete origin/cache/retry provenance, not verified fresh inference speed or cost savings. New prompt/temperature/schema timing and consumption remain N/A. Rule-only replays make zero billed requests; no inference token savings should be inferred.

Common EM oldheld20: baseline40% Wilson95≈21.9–61.3%; E5-B60%≈38.7–78.1%; E5-B full50%≈29.9–70.1%. Paired common effect+20 percentage points, six wins/two losses/twelve ties; query bootstrap2000seed82 interval−5 to+45 points. This is inconclusive and does not prove equivalence. No independent repeated-run consistency evidence exists in old records.

## Tests, selection and reproduction

""" + test_table + """

The initial two-request production smoke passed but emitted SSL teardown/unraisable warnings. The same two tests retested successfully after cleanup: two remaining SDK aiohttp inheritance deprecation warnings, no SSL teardown recurrence. Total four bounded generation calls, two distinct Gemini test cases; the other four Gemini integration tests were not rerun. Full repository regression excludes that module, so no claim of a fully rerun live suite is made.

Best candidate: no new live winner. E5-B remains experimental control; E6 is promising only on offline diagnostics. Reject immediate adoption, universal T0/T1 optimality, score-driven label edits and speed claims from old cache. Future comparisons remain explicitly pending. Reproduce using the commands in experimental_methodology.md; audit and report builders are offline.
""")

    write(DOC / "query_contract_review.md", """# Phase 8.2 query contract review

Date: 2026-10-09. **Accepted production contract: existing v1.0.0**, `QueryUnderstandingOutput` inside `QueryUnderstandingResult`. Existing v2.0.0 remains experimental. D1 RequiredV2 is an isolated required-slot research model, not a public contract version or production migration.

## Current fields and implemented behavior

| Meaning | Productionv1 | Experimentalv2 | Limitation |
| --- | --- | --- | --- |
| Requested item | semantic_query text | product_type plus semantic_query | Item class and useful descriptors need clear annotation |
| Positive hard slots | category,brand,min/max_price,min_rating,currency | Same slots | Single brand/category cannot encode alternatives |
| Price operators | No flags | min_inclusive/max_inclusive, defaulttrue | v1 loses strict under/above intent |
| Positive attributes/use | soft_preferences string list | Same list | Validators deduplicate/lowercase and truncate at10 |
| Rejections | Embedded text only | exclusions[target_type,value] | Scope and target typing can still be wrong |
| Clarification | needs_clarification/reason | Same | No invariant currently requires a nonempty reason |
| Diagnostics | query,raw_response_text,model,latency,tokens,is_valid,errors | Research records separately | Result serialization still includes raw query/response |

Public schemas ignore extra fields; Pydantic validation normally permits coercion. Category/brand strings are not schema enums. Negative prices, reversed ranges and ratings outside1–5 fail, but finite NaN/infinity enforcement is not explicit. Empty semantic text can become an unspecified fallback; schema-valid is not semantically trustworthy. Omitted optional fields take defaults. RequiredV2 addresses a few omissions only; typed preferences or scope/source spans are deferred until measured benefit supports their complexity.

## Semantic conventions under review

Product type names the requested item class. Running shoes is a class; shoes suitable for running is shoes plus intended-use preference. Wireless/noise cancelling can be separate attributes; class specificity requires a reviewed rubric. Canonical English category/product type and literal source-language preference policy are used in the new fixtures, not a new production multilingual guarantee.

Exclusions preserve typed rejected values separately from positive preferences. Attribute and feature overlap is an annotation risk. Not only/not necessarily is not rejection; not too expensive is qualitative; double negatives require scope. No substring rule can safely replace scope interpretation. A literal manufacturer outside the catalog remains useful extracted intent; unsupported requests must be gated before filter activation. Compatibility targets such as Honda City or iPhone must not become the accessory's requested brand. Multi-brand/product alternatives require clarification with current scalar representation.

For v2: under/below imply max_price with max_inclusive=false; up to/at most implytrue. Above implies min_inclusive=false; at least/no less than/not under implytrue. Last explicit correction takes precedence. Flags are inapplicable when the numeric bound is null. Watts, years and stars are not prices. Currency conversion is absent; do not apply foreign numeric prices to an INR catalog without clarification.

## Structural versus semantic adaptation

`to_v1()` creates an object accepted by v1, but discards product_type and both boundary flags. It appends exclusion words as soft strings; target type, enforcement and polarity structure disappear, and ten-item truncation can drop negatives. For a v2 request under2000 excludingrunning shoes, the v1 object carries only max_price2000 and a negative string: an inclusive SQL consumer may accept exactly2000, and a preference embedder may accidentally rank running shoes positively. Do not claim full backward semantic compatibility.

## Phase9 and Phase10 interfaces

Phase9 may prototype against documented v1 positive preference strings with explicit gating for is_valid=false or needs_clarification=true. Preserve query semantics and avoid embedding exclusion strings as positive evidence. Semantic query needs a separate retention and retrieval-content policy. Full quality acceptance is not established by the current samples.

Phase10 must construct parameterized filters against actual `product_name`, `category`, `brand`, `discounted_price` and `rating` columns. Do not treat LLM-generated SQL as executable. For an eventually accepted v2 contract choose > versus≥, < versus≤ according to active flags; preserve rejection intent using reviewed product metadata/evidence. Simple title substring exclusion may overexclude or miss synonyms. INR-only filters must gate foreign currency. Product rating null handling and strict user rating intent must be defined even though the proposal describes rating mainly as a ranking signal. This is interface guidance; no Phase9 embeddings, Phase10 retrieval or database mutation was implemented.

## Migration requirements

Before adoption: independently validate v2 semantics, choose canonical class/exclusion policy, verify all consumers, version any breaking schema change, provide dual-read adapters with explicit loss warnings, add consumer tests for boundaries/negation/clarification, and obtain approval before switching production consumers. Consider a minimal future amendment requiring finite numbers, explicit required slots and clarification consistency; measure provider schema compatibility and token cost first. Retain v1 as production until these gates pass. No consumer may infer quality, security or catalog support solely from Pydantic success.
""")

    write(DOC / "final_engineering_report.md", """# Phase 8.2 final engineering decision

Date: 2026-10-09. **Decision: PARTIAL. Offline deliverables completed; larger live comparisons were explicitly deferred by the user.** Keep refining Phase8 before accepting broad Phase9 readiness. No new extraction prompt, temperature, rule set or schema was promoted to production.

## Findings and methods

Twelve investigations cover soft extraction, exact-match quality, provider failures, temperature, scoring, rules, entity/filter semantics, dataset integrity, measurement, adapters, documentation and operational safety. Official Google structured-output/SDK/prompting/temperature/rate/pricing guidance and primary negation/paired-evaluation/self-consistency literature informed isolated candidates. Source titles, dates and URLs are in research_review.md. No research source proves a task-specific winner.

Offline work independently audited original50/dev15/oldheld20, replayed each rule group on identical raw responses, verified oracle invariance, authored80 new labels, built content-hashed registry and persistent budget runner, and executed mocked reliability and repository regression. Four bounded production generation calls tested connectivity/foreign currency and lifecycle; there was no large live run.

## Implemented changes and reasons

- config.py hides API key in repr/model serialization; security.py redacts configured/patterned credentials; engine and client errors expose safe types/status instead of raw provider text or user-query logs.
- gemini_client.py disables hidden SDK retries, uses exact model identifiers, extracts usage before validation, separates JSON/Pydantic stages and attempt/retry timings, accepts instrumentation hooks, and closes clients on their owning loop. Synchronous wrappers close in finally; Windows SSL transport drain is included.
- query_understanding.py keeps original prompt/schema/normalization and returns safe generic failure reasons.
- experiments/phase82 implements independent failure-aware metrics, uncertainty, consistency, isolated prompts/schema/rules, actual-content cache hashes, successful-response-only cache, persistent attempts/token reservations and resumable records.
- scripts audit frozen historical scorers, build authored fixtures, run opt-in experiments with dry-run default, and reproduce reports. New tests cover metrics, linguistic rules, reliability, cache/provenance and budgets. Gemini test lifecycle closes sessions before its loop shuts down.

These address reproducible accounting/lifecycle/security defects without claiming new semantic accuracy. Research caches and fixtures contain synthetic shopping text; customer-data retention/access policies remain to be designed.

## Final architecture and configuration

Production: bounded single-turn input → original v1 prompt → configured Gemini → JSON/Pydantic validation → existing category/brand/currency normalization → v1 result/clarification. Model remains gemini-3.1-flash-lite, temperature0, output cap2048, timeout30s, application max_retries3. SDK automatic attempts1 makes the application the only retry owner. Safe diagnostics/resource cleanup are implemented; production extraction semantics unchanged. Experimental v2 is isolated and has no consumer switch.

Original raw artifacts, fixtures and production prompt/schema remain preserved. Initial working-tree changes were not reverted. Database, product data, indexes and embeddings were not modified or regenerated. v2→v1 is structurally valid but semantically lossy; migration approval is still required before consumer changes.

## Quality and performance evidence

""" + metric_table + """

The oldheld20 shared-field improvement of20 points has bootstrap95 interval−5 to+45 points. E5-B fullv2 EM=50%, soft macro78.33%, product/exclusion exact90%, brand95%; exclusion micro28.57% exposes sparse-negative failures. Offline conservative replay reaches full60%/soft80% on that already inspected sample while preserving literal manufacturer entities; it is not a new heldout model result. New comparative inference latency/tokens and repeated-run accuracy are unavailable. Historical timing/token medians are descriptive with incomplete provenance.

## Verification

""" + test_table + """

Final repository run passed376 tests, excluding the Gemini integration module. Targeted run passed101 overlapping tests; do not sum overlapping totals as distinct coverage. Original baseline offline run passed296 with12 integration-marked tests deselected. Production smoke passed2 tests twice (four calls, two unique tests), with initial SSL warnings and clean SSL retest after lifecycle fix. Remaining SDK deprecation warnings are upstream technical debt. Other four Gemini tests were not rerun; full live suite acceptance remains pending.

## Adoption, rejected approaches and next gates

Reject immediate candidate adoption, universal temperature optimum, guaranteed cloud determinism/schema success, broad regex semantic edits, treating unsupported manufacturers as NER errors, and old cache latency as fresh speed evidence. No provider/model change, typed-preference expansion or phase9/10 implementation occurred.

Open gates: independent annotation/adjudication; approved same-E5-B temperature/prompt/schema comparisons; locked validation/freshheldout evaluation; category-level error analysis; repeat sampling; finite numeric/strict coercion policy; negatives/boundary consumer migration; customer-text retention; and measured injection robustness. Multi-turn and currency conversion remain deferred scope limitations. Phase9 interface prototyping can proceed with documented gating and limitations, but quality readiness is not PASS.

## Acceptance ledger

Completed: repository/source/artifact review; independent historical audit; twelve evidence classifications; external research; controlled design; isolated infrastructure and budget tests; standardized metrics; product/exclusion analysis; rule audit;80-case partition preparation; safe reliability changes; offline regression; bounded live subset; seven reports; machine artifacts; historical documentation synchronization.

Pending by user decision: E5-B repeated temperature execution; live prompt/schema comparisons; independent expanded evaluation; newly selected semantic candidate; full live suite and production semantic adoption. Pending quality review: independently adjudicated annotations. These pending items are not marked passed. The authorized offline scope is complete; the comprehensive live optimization objective remains PARTIAL.
""")

    final = {"timestamp_utc": NOW, "decision": "PARTIAL", "authorized_offline_scope": "COMPLETE",
        "live_comparisons": STATUS, "production_model": "gemini-3.1-flash-lite", "production_schema": "v1.0.0",
        "new_semantic_candidate_adopted": False, "tests": tests, "bounded_live_generation_calls": 4,
        "distinct_live_tests": 2, "remaining_gemini_tests_not_rerun": 4, "issue_status_counts": dict(Counter(i["status"] for i in inventory)),
        "quality": {"original50": baseline, "legacy_heldout20": hm}, "fresh_heldout_metrics": None,
        "recommendation": "Keep refining Phase8; allow interface prototypes only with documented limitations"}
    atomic_write(OUT / "final_report.json", final)

    # Keep historical bodies intact; explicitly supersede unsupported assertions.
    old_docs = ["README.md", "docs/phase8_llm_query_understanding.md", "docs/phase8_query_contract.md",
        "docs/phase8_1_refinement_experiments.md", "docs/phase8_1_issue_resolution.md", "docs/phase8_1_evaluation_methodology.md",
        "docs/concepts/llm_experimentation_and_extraction_refinement.md", "docs/concepts/llm_query_understanding_fundamentals.md",
        "docs/issues/shopassist_phase8_open_issues.md"]
    for relative in old_docs:
        path = ROOT / relative
        body = path.read_text(encoding="utf8")
        start, end = "<!-- phase82-correction-start -->", "<!-- phase82-correction-end -->"
        if start in body:
            a, b = body.index(start), body.index(end) + len(end)
            body = body[:a] + body[b:]
        target = "phase8_2" if path.parent == ROOT / "docs" else "../phase8_2" if path.parent in (ROOT / "docs/concepts", ROOT / "docs/issues") else "docs/phase8_2"
        notice = f"""{start}
> **Phase8.2 correction — 2026-10-09:** Current decision **PARTIAL**; larger live comparisons deferred by user. Production remains original **v1**, not E5-B/v2. The historical body below is preserved; conflicting claims are superseded by [current engineering decision]({target}/final_engineering_report.md), [audited results]({target}/experimental_results.md) and [contract review]({target}/query_contract_review.md).
>
> Original50 98% EM omits preferences; shared-field EM is54%. Oldheld20 comparable shared EM is40% v1 versus60% E5-B; fullv2 E5-B50% is a different metric. Semantic-query/reason wording is not covered by slot EM. E5-B soft macro78.33%, product/exclusion exact90%, exclusion micro28.57%. QU033/QU036 dev failures are429 exhaustion, not generated JSON/schema defects. New failure-aware dev E5-B HC F1 is93.88%, soft F1 is80%; historical96%/86.67% use the frozen old policy.
>
> Development overlaps original50 in13/15 queries. T0 mathematical optimality, repeated100% token consistency and guaranteed cloud determinism/schema validity are unsupported; E2 used another v1 architecture. Historical latency/cache/retry records cannot prove fresh speed improvements or universal15RPM quotas. Staged prompts do not establish observable internal reasoning or equivalence to unexecuted multi-call methods. Boeing suppression is filter policy, not necessarily correct NER. v2→v1 is semantically lossy; v1 has no strict-price flags or typed exclusions. Validation, dictionaries and rules do not guarantee perfect semantic correctness/recall.
>
> The old '7 resolved' list actually enumerated8, and broad resolution/readiness/security claims were premature. Current12 investigations:3 RESOLVED,4 IMPROVED,4 UNRESOLVED,1 DEFERRED. Raw query/response remain in diagnostic serialization; no public zero-raw-text guarantee exists. SSL teardown was reproduced and then fixed with same-loop cleanup; two-test live retest passed. Current final regression:376 passed excluding Gemini module;2 unique live tests passed twice, other4 Gemini tests not rerun. No new live quality winner or production semantic change is claimed.
{end}"""
        first, sep, rest = body.partition("\n")
        write(path, first + "\n\n" + notice + "\n\n" + rest.lstrip())
    research = DOC / "research_review.md"
    text = research.read_text(encoding="utf8")
    text = text.replace("| C | C2/C3/C4/C5", "| Matching control | B0 on the other11 development queries, once | 11 |\n| C | C2/C3/C4/C5") if "Matching control" not in text else text
    text = text.replace("**301**", "**312**").replace("301 calls", "312 calls").replace("270,900", "280,800").replace("$0.162", "$0.168")
    text = text.replace("Baselines use matching raw responses where available", "Every prompt/schema comparison has same-query B0 control")
    text = text.replace("Two eligible configurations on 20 validation queries", "Provisional winner and B0 control on20 validation queries")
    text = text.replace("freeze at most two candidates", "freeze one provisional candidate plus the B0 control")
    text = text.replace("Status: offline investigation complete; comparative live experiments require budget approval.", "Status: offline investigation complete; user explicitly deferred comparative live experiments.")
    text += "\n\n## Execution decision update\n\nThe user selected: finish offline work; leave live comparisons pending. No large-run approval exists. Corrected future plan312 calls includes11 additional same-query controls within the proposed360-attempt ceiling. Four bounded production generation calls were completed (two smoke tests, then the same two after lifecycle repair). Final regression passed376 tests excluding Gemini module; semantic candidates remain unadopted.\n" if "Execution decision update" not in text else ""
    write(research, text)
    sources = [{"id": line.split("**")[1], "description": line.strip(), "access_date": "2026-10-09"}
               for line in text.splitlines() if line.startswith("- **R")]
    docs = list(DOC.glob("*.md")) + [ROOT / "docs/concepts/llm_query_understanding_optimization.md"]
    atomic_write(OUT / "research_manifest.json", {"timestamp_utc": NOW, "sources": sources,
        "baseline_revision": manifest["git_revision"], "baseline_manifest": "baseline_manifest.json",
        "model": "gemini-3.1-flash-lite", "sdk": "google-genai2.29.0", "source_policy": "Official docs and primary papers; living docs accessed2026-10-09",
        "reports": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in docs if p.exists()},
        "annotation_review": "PENDING", "live_execution": STATUS, "new_requests_comparative": 0})
    print(json.dumps({"reports": sum(p.exists() for p in docs), "decision": "PARTIAL", "tests": tests, "issues": final["issue_status_counts"]}, indent=2))


if __name__ == "__main__":
    main()
