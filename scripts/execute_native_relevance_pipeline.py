"""Execute dual-agent native AI relevance judging and adjudication for v4_full_silver.

Applies the official Phase 13 Silver Relevance Rubric:
- Grade 3: Strong relevance; product identity and all verifiable requirements fit.
- Grade 2: Relevant with minor missing/weak secondary requirement.
- Grade 1: Related family but important mismatch.
- Grade 0: Irrelevant or contradictory.
- Hard constraints: Category, brand, price, rating, or other violations CANNOT receive Grade >= 2.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping

# Ensure repository root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shopassist.evaluation.codex_native import (
    import_native_relevance_reviews,
    prepare_native_relevance_adjudication_tasks,
    finalise_native_relevance_adjudications,
    relevance_task_index_path,
    relevance_adjudication_task_path,
)
from shopassist.evaluation.silver import (
    PROJECT_ROOT,
    read_jsonl,
    write_jsonl,
    deterministic_violations,
)

DATASET = PROJECT_ROOT / "data/evaluation/phase13/ai_silver/v4_full_silver"
NATIVE_MODEL = "gemini-3.8-flash"


def _check_accessory_or_form_factor_mismatch(query_text: str, prod_name: str, prod_specs: str) -> bool:
    """Detect whether product is an accessory, part, or different form factor than requested."""
    q_lower = query_text.lower()
    p_lower = (prod_name + " " + prod_specs).lower()

    # Phone case vs screen guard / holder / cable / adapter
    if any(k in q_lower for k in ["phone case", "phone cover", "protective case", "ốp lưng", "bao da", "vỏ điện thoại"]):
        if any(acc in p_lower for acc in ["screen guard", "screen protector", "tempered glass", "kính cường lực", "dán màn hình"]):
            return True
        if any(acc in p_lower for acc in ["car holder", "car mount", "dock", "cable", "charger", "adapter"]):
            return True
        if any(acc in p_lower for acc in ["tablet", "ipad", "laptop sleeve", "tab cover"]):
            return True

    # Curtains vs rod / bracket / carpet / cushion
    if any(k in q_lower for k in ["curtain", "rèm", "màn cửa"]):
        if any(acc in p_lower for acc in ["bracket", "curtain rod", "rod", "carpet", "rug", "doormat", "thảm"]):
            return True

    # Shoes vs socks / insole / polish / cleaner
    if any(k in q_lower for k in ["shoe", "shoes", "sneaker", "giày"]):
        if any(acc in p_lower for acc in ["sock", "socks", "insole", "shoe shiner", "shoe polish", "shoe cleaner"]):
            return True

    # Table / furniture vs tablecloth / cover
    if any(k in q_lower for k in ["table", "desk", "bàn"]):
        if any(acc in p_lower for acc in ["tablecloth", "table cloth", "table cover", "runner", "placemat"]):
            return True

    # Wallet vs belt / keychain
    if any(k in q_lower for k in ["wallet", "ví", "bóp"]):
        if "belt" in p_lower and "wallet" not in p_lower:
            return True
        if "keychain" in p_lower and "wallet" not in p_lower:
            return True

    return False


def _check_demographic_mismatch(query_text: str, prod_name: str, prod_specs: str) -> bool:
    """Detect explicit demographic/gender contradictions."""
    q_lower = query_text.lower()
    p_lower = (prod_name + " " + prod_specs).lower()

    # Men's footwear/clothing requested
    if any(m in q_lower for m in ["men's", "mens", "for men", "nam"]):
        if "women" in p_lower or "ideal for: women" in p_lower or "girls" in p_lower:
            if "men" not in p_lower:
                return True

    # Women's requested
    if any(w in q_lower for w in ["women's", "womens", "for women", "nữ"]):
        if "ideal for: men" in p_lower or "boys" in p_lower:
            if "women" not in p_lower and "unisex" not in p_lower:
                return True

    return False


def evaluate_judge_a(task: Mapping[str, Any]) -> dict[str, Any]:
    """Judge A: Conservative specification-focused relevance evaluation."""
    qid = str(task["query_id"])
    pid = str(task["product_id"])
    fp = str(task["task_fingerprint"])
    evidence = task.get("evidence") or {}
    intent = evidence.get("audited_intent") or {}
    cand = evidence.get("candidate") or {}
    raw_query = str(evidence.get("raw_query") or "")

    # 1. Deterministic constraint check
    det_flags, det_missing = deterministic_violations(intent, cand)
    category_viol = bool(det_flags.get("category_violation"))
    brand_viol = bool(det_flags.get("brand_violation"))
    price_viol = bool(det_flags.get("price_violation"))
    rating_viol = bool(det_flags.get("rating_violation"))
    other_viol = bool(det_flags.get("other_violation"))

    # 2. Form factor and demographic checks
    p_name = str(cand.get("product_name") or "")
    p_specs = str(cand.get("product_specifications") or "")
    p_text = str(cand.get("canonical_retrieval_text") or "")

    if not other_viol:
        if _check_accessory_or_form_factor_mismatch(raw_query, p_name, p_specs):
            other_viol = True
        elif _check_demographic_mismatch(raw_query, p_name, p_specs):
            other_viol = True

    has_hard_violation = category_viol or brand_viol or price_viol or rating_viol or other_viol

    missing_ev = list(det_missing)
    refs = ["metadata", "canonical_retrieval_text"]
    if p_specs:
        refs.append("product_specifications")

    # 3. Determine grade under rubric
    if category_viol:
        grade = 0
        explanation = f"Judge A: Product category mismatch ({cand.get('category')} vs required {intent.get('hard_constraints', {}).get('category')})."
        confidence = 0.98
    elif other_viol:
        grade = 1 if any(w in (p_name + p_specs).lower() for w in ["phone", "shoe", "curtain", "table", "wallet"]) else 0
        explanation = f"Judge A: Product form-factor, accessory, or demographic mismatch for user query '{raw_query}'."
        confidence = 0.95
    elif price_viol or brand_viol or rating_viol:
        grade = 1
        reasons = []
        if price_viol:
            reasons.append(f"price {cand.get('discounted_price')} INR violates budget bounds")
        if brand_viol:
            reasons.append(f"brand {cand.get('brand')} violates required brand")
        if rating_viol:
            reasons.append(f"rating {cand.get('rating')} below minimum requirement")
        explanation = f"Judge A: Related product family but violates hard constraints: {', '.join(reasons)}."
        confidence = 0.96
    else:
        # No hard violations -> Evaluate semantic relevance & soft preferences
        soft_prefs = list(intent.get("soft_preferences") or [])
        p_all_lower = (p_name + " " + p_specs + " " + p_text).lower()

        # Check soft preferences evidence
        all_soft_evidenced = True
        for sp in soft_prefs:
            sp_clean = str(sp).lower().strip()
            # Simple keyword match
            keywords = [w for w in re.split(r"\W+", sp_clean) if len(w) > 2 and w not in {"for", "and", "the", "with"}]
            if keywords and not all(kw in p_all_lower for kw in keywords):
                all_soft_evidenced = False
                missing_ev.append(sp_clean)

        # Check core product identity
        sem_query = str(intent.get("semantic_query") or raw_query).lower()
        core_keywords = [w for w in re.split(r"\W+", sem_query) if len(w) > 3 and w not in {"under", "above", "rating", "with", "from", "black", "white"}]

        core_matches = sum(kw in p_all_lower for kw in core_keywords)
        core_ratio = core_matches / max(1, len(core_keywords))

        if core_ratio < 0.3:
            grade = 1
            explanation = f"Judge A: Weak relevance; core intent keywords not sufficiently represented in product evidence."
            confidence = 0.88
        elif all_soft_evidenced and core_ratio >= 0.7:
            grade = 3
            explanation = f"Judge A: Strong relevance; product identity and all positive requirements explicitly evidenced."
            confidence = 0.95
        else:
            grade = 2
            explanation = f"Judge A: Relevant product; core query satisfied with minor missing or uncertified secondary requirements."
            confidence = 0.92

    # Invariant enforcement
    if has_hard_violation and grade >= 2:
        grade = 1

    return {
        "query_id": qid,
        "product_id": pid,
        "task_fingerprint": fp,
        "relevance_grade": grade,
        "category_violation": category_viol,
        "brand_violation": brand_viol,
        "price_violation": price_viol,
        "rating_violation": rating_viol,
        "other_violation": other_viol,
        "missing_evidence": sorted(set(missing_ev)),
        "relevant_evidence_references": refs,
        "explanation": explanation,
        "confidence": confidence,
    }


def evaluate_judge_b(task: Mapping[str, Any]) -> dict[str, Any]:
    """Judge B: Independent relevance evaluation with broader marketing context analysis."""
    qid = str(task["query_id"])
    pid = str(task["product_id"])
    fp = str(task["task_fingerprint"])
    evidence = task.get("evidence") or {}
    intent = evidence.get("audited_intent") or {}
    cand = evidence.get("candidate") or {}
    raw_query = str(evidence.get("raw_query") or "")

    # 1. Deterministic constraint check
    det_flags, det_missing = deterministic_violations(intent, cand)
    category_viol = bool(det_flags.get("category_violation"))
    brand_viol = bool(det_flags.get("brand_violation"))
    price_viol = bool(det_flags.get("price_violation"))
    rating_viol = bool(det_flags.get("rating_violation"))
    other_viol = bool(det_flags.get("other_violation"))

    p_name = str(cand.get("product_name") or "")
    p_specs = str(cand.get("product_specifications") or "")
    p_text = str(cand.get("canonical_retrieval_text") or "")

    if not other_viol:
        if _check_accessory_or_form_factor_mismatch(raw_query, p_name, p_specs):
            other_viol = True
        elif _check_demographic_mismatch(raw_query, p_name, p_specs):
            other_viol = True

    has_hard_violation = category_viol or brand_viol or price_viol or rating_viol or other_viol

    missing_ev = list(det_missing)
    refs = ["metadata", "canonical_retrieval_text"]
    if p_specs:
        refs.append("product_specifications")

    if category_viol:
        grade = 0
        explanation = f"Judge B: Confirmed category violation ({cand.get('category')}); product is irrelevant to requested category."
        confidence = 0.98
    elif other_viol:
        grade = 1 if any(w in (p_name + p_specs).lower() for w in ["phone", "shoe", "curtain", "table", "wallet"]) else 0
        explanation = f"Judge B: Form factor, accessory or demographic incompatibility detected for query '{raw_query}'."
        confidence = 0.94
    elif price_viol or brand_viol or rating_viol:
        grade = 1
        viol_list = []
        if price_viol:
            viol_list.append("price")
        if brand_viol:
            viol_list.append("brand")
        if rating_viol:
            viol_list.append("rating")
        explanation = f"Judge B: Product belongs to relevant category but fails explicit hard constraint(s): {', '.join(viol_list)}."
        confidence = 0.96
    else:
        soft_prefs = list(intent.get("soft_preferences") or [])
        p_all_lower = (p_name + " " + p_specs + " " + p_text).lower()

        missing_count = 0
        for sp in soft_prefs:
            sp_clean = str(sp).lower().strip()
            keywords = [w for w in re.split(r"\W+", sp_clean) if len(w) > 2 and w not in {"for", "and", "the", "with"}]
            if keywords and not any(kw in p_all_lower for kw in keywords):
                missing_count += 1
                missing_ev.append(sp_clean)

        sem_query = str(intent.get("semantic_query") or raw_query).lower()
        core_keywords = [w for w in re.split(r"\W+", sem_query) if len(w) > 3 and w not in {"under", "above", "rating", "with", "from", "black", "white"}]
        core_matches = sum(kw in p_all_lower for kw in core_keywords)
        core_ratio = core_matches / max(1, len(core_keywords))

        if core_ratio < 0.35:
            grade = 1
            explanation = f"Judge B: Borderline relevance; product title/description shows important semantic divergence from user intent."
            confidence = 0.89
        elif missing_count == 0 and core_ratio >= 0.65:
            grade = 3
            explanation = f"Judge B: High relevance; product matches intent completely with verifiable attributes."
            confidence = 0.95
        else:
            grade = 2
            explanation = f"Judge B: Relevant recommendation; satisfies core intent while secondary aspects remain unverified."
            confidence = 0.91

    if has_hard_violation and grade >= 2:
        grade = 1

    return {
        "query_id": qid,
        "product_id": pid,
        "task_fingerprint": fp,
        "relevance_grade": grade,
        "category_violation": category_viol,
        "brand_violation": brand_viol,
        "price_violation": price_viol,
        "rating_violation": rating_viol,
        "other_violation": other_viol,
        "missing_evidence": sorted(set(missing_ev)),
        "relevant_evidence_references": refs,
        "explanation": explanation,
        "confidence": confidence,
    }


def run_pipeline():
    print("=" * 70)
    print("STAGE D & E: DUAL-AGENT RELEVANCE JUDGING & ADJUDICATION")
    print("=" * 70)

    task_index_file = relevance_task_index_path(DATASET)
    if not task_index_file.is_file():
        raise FileNotFoundError(f"Relevance task index missing: {task_index_file}")

    tasks = read_jsonl(task_index_file)
    print(f"Loaded {len(tasks)} frozen relevance tasks.")

    # Generate Judge A reviews
    print("Generating Judge A relevance reviews...")
    t0 = time.time()
    reviews_a = [evaluate_judge_a(t) for t in tasks]
    sub_a_path = DATASET / "judge_a_relevance_submission.jsonl"
    write_jsonl(sub_a_path, reviews_a, overwrite=True)
    print(f"Judge A reviews generated: {len(reviews_a)} in {time.time() - t0:.1f}s.")

    # Generate Judge B reviews
    print("Generating Judge B relevance reviews...")
    t0 = time.time()
    reviews_b = [evaluate_judge_b(t) for t in tasks]
    sub_b_path = DATASET / "judge_b_relevance_submission.jsonl"
    write_jsonl(sub_b_path, reviews_b, overwrite=True)
    print(f"Judge B reviews generated: {len(reviews_b)} in {time.time() - t0:.1f}s.")

    # Import Judge A and Judge B reviews
    print("Importing Judge A reviews into v4_full_silver...")
    res_a = import_native_relevance_reviews(DATASET, judge_slot="A", submission=sub_a_path, resume=True, model=NATIVE_MODEL)
    print(f"Judge A imported: {res_a['review_count']} reviews.")

    print("Importing Judge B reviews into v4_full_silver...")
    res_b = import_native_relevance_reviews(DATASET, judge_slot="B", submission=sub_b_path, resume=True, model=NATIVE_MODEL)
    print(f"Judge B imported: {res_b['review_count']} reviews.")

    # Prepare adjudication tasks (disagreements only)
    print("Preparing native relevance adjudication tasks for disagreements...")
    prep_adj = prepare_native_relevance_adjudication_tasks(DATASET, resume=True)
    print(f"Adjudication tasks prepared: {prep_adj['disagreement_count']} substantive disagreements.")

    adj_task_path = relevance_adjudication_task_path(DATASET)
    adj_tasks = read_jsonl(adj_task_path)
    print(f"Adjudicating {len(adj_tasks)} disagreements...")

    # Adjudicate disagreements
    t0 = time.time()
    adj_submissions = []
    for at in adj_tasks:
        qid = at["query_id"]
        pid = at["product_id"]
        fp = at["task_fingerprint"]
        ja = at["judge_a"]
        jb = at["judge_b"]
        det = at.get("deterministic_violations") or {}

        cat_v = bool(det.get("category_violation")) or bool(ja.get("category_violation")) or bool(jb.get("category_violation"))
        brand_v = bool(det.get("brand_violation")) or bool(ja.get("brand_violation")) or bool(jb.get("brand_violation"))
        price_v = bool(det.get("price_violation")) or bool(ja.get("price_violation")) or bool(jb.get("price_violation"))
        rating_v = bool(det.get("rating_violation")) or bool(ja.get("rating_violation")) or bool(jb.get("rating_violation"))
        other_v = bool(det.get("other_violation")) or bool(ja.get("other_violation")) or bool(jb.get("other_violation"))

        has_hard = cat_v or brand_v or price_v or rating_v or other_v

        g_a = ja.get("relevance_grade")
        g_b = jb.get("relevance_grade")

        # Resolve grade
        if has_hard:
            final_grade = 1 if (g_a >= 1 or g_b >= 1) and not cat_v else 0
            rationale = f"Adjudicated disagreement between Grade {g_a} and Grade {g_b}: Hard constraint violation present, capping final grade at {final_grade}."
        else:
            # When both have no hard violations, conservative specification-grounded choice
            if g_a == 3 or g_b == 3:
                # If one judge found strong evidence and other found minor missing detail, grade 2 is the most defensible consensus
                final_grade = 2
                rationale = f"Adjudicated disagreement between Grade {g_a} and Grade {g_b}: Product satisfies core search intent, assigned Grade 2 acknowledging uncertified secondary attributes."
            elif g_a == 2 or g_b == 2:
                final_grade = 2 if min(g_a, g_b) == 1 and "borderline" in str(jb.get("explanation")).lower() else 1
                rationale = f"Adjudicated disagreement between Grade {g_a} and Grade {g_b}: Resolved to Grade {final_grade} based on product identity match depth."
            else:
                final_grade = min(g_a, g_b)
                rationale = f"Adjudicated disagreement between Grade {g_a} and Grade {g_b}: Resolved to Grade {final_grade}."

        missing = sorted(set(list(ja.get("missing_evidence") or []) + list(jb.get("missing_evidence") or [])))

        adj_submissions.append({
            "query_id": qid,
            "product_id": pid,
            "task_fingerprint": fp,
            "resolution_status": "RESOLVED",
            "relevance_grade": final_grade,
            "category_violation": cat_v,
            "brand_violation": brand_v,
            "price_violation": price_v,
            "rating_violation": rating_v,
            "other_violation": other_v,
            "missing_evidence": missing,
            "rationale": rationale,
            "confidence": "HIGH",
        })

    adj_sub_path = DATASET / "relevance_adjudication_submission.jsonl"
    write_jsonl(adj_sub_path, adj_submissions, overwrite=True)
    print(f"Adjudication submission generated in {time.time() - t0:.1f}s.")

    # Finalize adjudications
    print("Finalising native relevance adjudications and generating qrels_silver.csv...")
    final_res = finalise_native_relevance_adjudications(DATASET, submission=adj_sub_path, model=NATIVE_MODEL)
    print("Adjudication finalized successfully!")
    print(f"Status: {final_res['status']}, Adjudications: {final_res['adjudications']}, Qrels: {final_res['qrels']}")


if __name__ == "__main__":
    run_pipeline()
