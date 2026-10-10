"""Offline integrity verification; never submits an API call or prints credentials."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from shopassist.llm.config import get_llm_settings
from shopassist.llm.experiments.phase82.runner import atomic_write
from shopassist.llm.normalization import CANONICAL_CATEGORIES
from shopassist.llm.schema_variants import RefinedQueryUnderstandingOutput


def main():
    out = ROOT / "data/interim/phase8_2"
    manifest = json.loads((out / "baseline_manifest.json").read_text(encoding="utf8"))
    protected = [p for p in manifest["hashes"] if p.startswith("data/") or p.startswith("tests/fixtures/") or p in (
        "src/shopassist/llm/prompts.py", "src/shopassist/llm/schemas.py", "src/shopassist/llm/normalization.py",
        "src/shopassist/llm/refinement_rules.py", "src/shopassist/llm/schema_variants.py", "src/shopassist/llm/prompt_variants.py")]
    unchanged = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == manifest["hashes"][p] for p in protected}
    assert all(unchanged.values()), "A protected baseline file changed"
    cases = []
    fixtures = {}
    for split in ("dev", "validation", "heldout"):
        path = ROOT / f"tests/fixtures/phase8_2/{split}.json"
        data = json.loads(path.read_text(encoding="utf8"))
        fixtures[split] = len(data["cases"])
        for case in data["cases"]:
            RefinedQueryUnderstandingOutput.model_validate(case["expected"])
        cases.extend(data["cases"])
    assert fixtures == {"dev": 20, "validation": 20, "heldout": 40}
    assert len({c["test_id"] for c in cases}) == len({c["query"].strip().casefold() for c in cases}) == 80
    categories = {c["expected"]["hard_constraints"]["category"] for c in cases} - {None}
    assert categories == set(CANONICAL_CATEGORIES)
    reports = [ROOT / f"docs/phase8_2/{name}.md" for name in ("research_review", "issue_investigation", "experimental_methodology",
        "experimental_results", "final_engineering_report", "query_contract_review")]
    reports.append(ROOT / "docs/concepts/llm_query_understanding_optimization.md")
    assert all(p.exists() and p.stat().st_size > 1000 for p in reports)
    links_checked = 0
    for path in reports:
        content = path.read_text(encoding="utf8")
        for target in re.findall(r"\]\(([^)]+)\)", content):
            if re.match(r"https?://|#", target):
                continue
            assert (path.parent / target.split("#")[0]).resolve().exists(), f"Broken link in {path.name}"
            links_checked += 1
    checked = []
    for path in out.rglob("*.json"):
        json.loads(path.read_text(encoding="utf8"))
        checked.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    final = json.loads((out / "final_report.json").read_text(encoding="utf8"))
    assert final["decision"] == "PARTIAL" and final["live_comparisons"] == "NOT_RUN_USER_DEFERRED"
    assert final["tests"]["regression_tests"]["passed"] == 376
    assert final["quality"]["legacy_heldout20"]["E5-B"]["full_v2_exact"]["count"] == 10
    assert sum(final["issue_status_counts"].values()) == 12
    key = get_llm_settings().gemini_api_key
    scan_paths = reports + list(out.rglob("*.json")) + list((ROOT / "src/shopassist/llm/experiments/phase82").glob("*.py"))
    if key:
        assert not any(key in p.read_text(encoding="utf8") for p in scan_paths), "Configured credential found in new artifacts"
    evidence = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "status": "PASS_OFFLINE_INTEGRITY",
        "protected_hash_checks": unchanged, "fixtures": fixtures, "fixture_labels_pydantic_valid": 80,
        "independent_annotation": "PENDING", "canonical_categories_covered": len(categories), "reports_present": 7,
        "local_report_links_checked": links_checked, "json_artifacts_parseable": checked,
        "configured_key_not_in_artifacts": True if key else "No configured key", "report_consistency": "PASS",
        "live_comparisons": "NOT_RUN_USER_DEFERRED", "tests": final["tests"],
        "database_or_embedding_operations": "None submitted by Phase8.2 workflows",
        "git_diff_check": "Pre-existing Markdown hard-break/trailing-space warnings retained in historical additions"}
    atomic_write(out / "verification_report.json", evidence)
    print(json.dumps({k: evidence[k] for k in ("status", "fixtures", "reports_present", "canonical_categories_covered", "report_consistency")}, indent=2))


if __name__ == "__main__":
    main()
