"""Failure analysis and error taxonomy classifier for Phase 8.1.

Classifies soft preference and extraction discrepancies into the 7 required categories:
1. Missing preference
2. Extra preference
3. Product-type confusion
4. Incorrect paraphrase
5. Incorrect negation
6. Inconsistent ground truth
7. Other
"""

from __future__ import annotations

from typing import Any, Sequence

# Known product nouns frequently misclassified as soft preferences
PRODUCT_NOUNS: set[str] = {
    "running", "running shoes", "shoes", "sneakers", "boots", "sandals",
    "dslr lens", "lens", "camera", "tablet", "induction cooktop",
    "shower head", "water softener filter", "fountain pen", "dashboard mount",
    "football studs", "smartwatch", "20kg", "platinum", "pack of 50",
    "cordless drill", "hanging lights",
}

# Known ground-truth inconsistencies identified during baseline audit
KNOWN_GROUND_TRUTH_INCONSISTENCIES: dict[str, str] = {
    "QU029": "Annotator replaced literal user adjective 'cheap' with synonym 'affordable' in ground truth, penalizing exact extraction.",
    "QU030": "Annotator invented unstated preference 'casual' for 'Nike shoes, but not running shoes'.",
    "QU005": "Preposition variance: Ground truth required 'for men' but model extracted 'men'.",
    "QU008": "Preposition variance: Ground truth required 'with safety harness' but model extracted 'safety harness'.",
    "QU031": "Ambiguous non-shopping query: Ground truth expected 'interesting' despite query lacking product intent.",
    "QU033": "Out-of-catalog Boeing 747: Ground truth expected brand=null due to unserviceable query, but model extracted manufacturer 'Boeing'.",
}


def classify_soft_preference_error(
    test_id: str,
    query: str,
    expected_prefs: list[str],
    actual_prefs: list[str],
    f1: float,
) -> list[dict[str, Any]]:
    """Classify the root causes of soft preference extraction errors for a single case."""
    if f1 == 1.0:
        return []

    exp_set = set(p.lower().strip() for p in expected_prefs)
    act_set = set(p.lower().strip() for p in actual_prefs)
    fps = act_set - exp_set
    fns = exp_set - act_set

    classifications: list[dict[str, Any]] = []

    # 1. Check for known ground-truth inconsistency
    if test_id in KNOWN_GROUND_TRUTH_INCONSISTENCIES:
        classifications.append({
            "category": "Inconsistent ground truth",
            "test_id": test_id,
            "query": query,
            "detail": KNOWN_GROUND_TRUTH_INCONSISTENCIES[test_id],
            "severity": "HIGH",
        })

    # 2. Check for product-type confusion
    for item in fns:
        if item in PRODUCT_NOUNS or any(pn in item for pn in ("lens", "tablet", "cooktop", "filter", "mount", "pen", "shoes")):
            classifications.append({
                "category": "Product-type confusion",
                "test_id": test_id,
                "term": item,
                "detail": f"Expected soft preference '{item}' is actually the core product type noun phrase, preserved in semantic query.",
                "severity": "HIGH",
            })

    # 3. Check for negation errors
    for item in fps.union(fns):
        if any(neg in item for neg in ("not ", "no ", "without ", "except ")):
            classifications.append({
                "category": "Incorrect negation",
                "test_id": test_id,
                "term": item,
                "detail": f"Negative constraint '{item}' was incorrectly handled in soft preferences rather than explicit exclusions.",
                "severity": "HIGH",
            })

    # 4. Check for paraphrase / lexical mismatch
    for exp_item in fns:
        matched_paraphrase = False
        for act_item in fps:
            if exp_item.replace("with ", "").replace("for ", "") == act_item.replace("with ", "").replace("for ", ""):
                classifications.append({
                    "category": "Incorrect paraphrase",
                    "test_id": test_id,
                    "expected": exp_item,
                    "actual": act_item,
                    "detail": f"Syntactic variation: '{exp_item}' vs '{act_item}'.",
                    "severity": "LOW",
                })
                matched_paraphrase = True
                break

    # 5. Remaining false negatives -> Missing preference
    already_attributed_fns = {c.get("term") for c in classifications if "term" in c}
    for item in fns:
        if item not in already_attributed_fns and not any(c.get("expected") == item for c in classifications):
            classifications.append({
                "category": "Missing preference",
                "test_id": test_id,
                "term": item,
                "detail": f"Model failed to extract expected soft preference '{item}'.",
                "severity": "MEDIUM",
            })

    # 6. Remaining false positives -> Extra preference
    already_attributed_fps = {c.get("actual") for c in classifications if "actual" in c}
    for item in fps:
        if item not in already_attributed_fps:
            classifications.append({
                "category": "Extra preference",
                "test_id": test_id,
                "term": item,
                "detail": f"Model extracted unrequested or extraneous preference '{item}'.",
                "severity": "MEDIUM",
            })

    return classifications


def run_failure_analysis_on_benchmark(cases_data: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Execute complete error analysis across benchmark cases."""
    all_classifications: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {
        "Missing preference": 0,
        "Extra preference": 0,
        "Product-type confusion": 0,
        "Incorrect paraphrase": 0,
        "Incorrect negation": 0,
        "Inconsistent ground truth": 0,
        "Other": 0,
    }

    per_case_report: list[dict[str, Any]] = []

    for c in cases_data:
        tid = c["test_id"]
        q = c["query"]
        exp_soft = c["expected"].get("soft_preferences", [])
        act_soft = c["actual"].get("soft_preferences", [])
        f1 = c["metrics"].get("soft_preferences_f1", 1.0)

        errs = classify_soft_preference_error(tid, q, exp_soft, act_soft, f1)
        for e in errs:
            cat = e["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1
            all_classifications.append(e)

        if errs:
            per_case_report.append({
                "test_id": tid,
                "query": q,
                "expected_soft": exp_soft,
                "actual_soft": act_soft,
                "soft_f1": f1,
                "errors": errs,
            })

    return {
        "total_failures_analyzed": len(per_case_report),
        "total_error_instances": len(all_classifications),
        "error_distribution": category_counts,
        "per_case_failures": per_case_report,
    }
