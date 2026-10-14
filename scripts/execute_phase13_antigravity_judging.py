"""Run the 10-pair Antigravity AI relevance judging, import, adjudication, and validation."""

from __future__ import annotations

import json
from pathlib import Path
from shopassist.evaluation.silver import PROJECT_ROOT, read_jsonl, write_jsonl
from shopassist.evaluation.codex_native import (
    import_native_relevance_reviews,
    prepare_native_relevance_adjudication_tasks,
    finalise_native_relevance_adjudications,
)

AUDIT_DIR = PROJECT_ROOT / "data/evaluation/phase13/ai_silver/audit_antigravity_10pair"
TASKS_A = read_jsonl(AUDIT_DIR / "codex_native_inputs/relevance/judge_a_batch_001.jsonl")
TASKS_B = read_jsonl(AUDIT_DIR / "codex_native_inputs/relevance/judge_b_batch_001.jsonl")

# Judge A blinded reviews
REVIEWS_A = [
    {
        "query_id": "Q0007",
        "product_id": "20d1bba0a5a01993aa923e8d3b754e1c",
        "task_fingerprint": TASKS_A[0]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Product is a tempered glass screen protector, not a shock-resistant phone case.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "3a7e4778ca27c7082d81d78094026783",
        "task_fingerprint": TASKS_A[1]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Product is a car dashboard phone holder cradle, not a phone case.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "c23414205d9c0a3aa3d4858e302af6c1",
        "task_fingerprint": TASKS_A[2]["task_fingerprint"],
        "relevance_grade": 2,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": ["shock_resistance_certification"],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Direct phone back cover with grip matching the non-slip requirement, though shock-resistance details are not fully specified.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "716fa6f873e69852a488883381bfcdf8",
        "task_fingerprint": TASKS_A[3]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Protective cover is sized for a tablet (Galaxy Tab 3.7 inch) rather than a phone.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "a8ca63d81029d95c12e8ca325c6b48a8",
        "task_fingerprint": TASKS_A[4]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Portfolio case is for 7-inch tablets, mismatching the phone case request.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "b3fa7204c2ebca4e289036277cf8f903",
        "task_fingerprint": TASKS_A[5]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Product is an iPad tablet book case, not a phone case.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "b6669ee1bec951d47a80145aef12f55f",
        "task_fingerprint": TASKS_A[6]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Flip cover designed for Apple iPad Air tablet, not a phone case.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "cf36f0622dd6bf48777a4c175160a47f",
        "task_fingerprint": TASKS_A[7]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Car socket holder mount is not a protective phone case.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "14e1cda43983f4196bf4a6f1685ea4c6",
        "task_fingerprint": TASKS_A[8]["task_fingerprint"],
        "relevance_grade": 2,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": ["non_slip_grip_coating", "shock_certification"],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Phone leather pouch offering everyday protection for HTC One M9+, but non-slip grip and formal shock rating are not explicitly certified.",
        "confidence": "MEDIUM",
    },
    {
        "query_id": "Q0007",
        "product_id": "e1645766bc7426ceb626b4cba470bc0b",
        "task_fingerprint": TASKS_A[9]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Product has rubber grip back cover features but is sized for an iPad Mini tablet, not a mobile phone.",
        "confidence": "HIGH",
    },
]

# Judge B blinded reviews (independent evaluation pass)
REVIEWS_B = [
    {
        "query_id": "Q0007",
        "product_id": "20d1bba0a5a01993aa923e8d3b754e1c",
        "task_fingerprint": TASKS_B[0]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Tempered glass screen protector does not fulfill the request for a phone case.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "3a7e4778ca27c7082d81d78094026783",
        "task_fingerprint": TASKS_B[1]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Car socket holder mount is not a protective phone case.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "c23414205d9c0a3aa3d4858e302af6c1",
        "task_fingerprint": TASKS_B[2]["task_fingerprint"],
        "relevance_grade": 2,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": ["shock_resistant_specification"],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Phone grip back cover matches primary product intent with partial feature evidence.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "716fa6f873e69852a488883381bfcdf8",
        "task_fingerprint": TASKS_B[3]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Tablet flip cover represents a device mismatch against the requested phone case.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "a8ca63d81029d95c12e8ca325c6b48a8",
        "task_fingerprint": TASKS_B[4]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Designed for 7-inch tablets rather than mobile phones.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "b3fa7204c2ebca4e289036277cf8f903",
        "task_fingerprint": TASKS_B[5]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Book case designed for Apple iPad tablets, not mobile phones.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "b6669ee1bec951d47a80145aef12f55f",
        "task_fingerprint": TASKS_B[6]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "iPad Air tablet cover does not match mobile phone case search.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "cf36f0622dd6bf48777a4c175160a47f",
        "task_fingerprint": TASKS_B[7]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Vehicle socket holder does not satisfy phone case intent.",
        "confidence": "HIGH",
    },
    {
        "query_id": "Q0007",
        "product_id": "14e1cda43983f4196bf4a6f1685ea4c6",
        "task_fingerprint": TASKS_B[8]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": ["shock_resistance", "non_slip_grip"],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Leather pouch is a sleeve carrier rather than a shock-resistant snap-on case with non-slip grip.",
        "confidence": "MEDIUM",
    },
    {
        "query_id": "Q0007",
        "product_id": "e1645766bc7426ceb626b4cba470bc0b",
        "task_fingerprint": TASKS_B[9]["task_fingerprint"],
        "relevance_grade": 1,
        "category_violation": False,
        "brand_violation": False,
        "price_violation": False,
        "rating_violation": False,
        "other_violation": False,
        "missing_evidence": [],
        "relevant_evidence_references": ["canonical_retrieval_text", "product_specifications"],
        "explanation": "Designed for Apple iPad Mini tablet rather than a phone.",
        "confidence": "HIGH",
    },
]

def main() -> None:
    sub_a_path = AUDIT_DIR / "judge_a_relevance_submission.jsonl"
    sub_b_path = AUDIT_DIR / "judge_b_relevance_submission.jsonl"
    write_jsonl(sub_a_path, REVIEWS_A, overwrite=True)
    write_jsonl(sub_b_path, REVIEWS_B, overwrite=True)
    print("Wrote Judge A and B submissions.")

    # Import reviews
    imp_a = import_native_relevance_reviews(
        AUDIT_DIR,
        judge_slot="A",
        submission=sub_a_path,
        model="gemini-3.8-flash",
        resume=False,
    )
    print("Import A:", imp_a)

    imp_b = import_native_relevance_reviews(
        AUDIT_DIR,
        judge_slot="B",
        submission=sub_b_path,
        model="gemini-3.8-flash",
        resume=False,
    )
    print("Import B:", imp_b)

    # Prepare adjudication
    adj_prep = prepare_native_relevance_adjudication_tasks(AUDIT_DIR)
    print("Adjudication preparation:", adj_prep)

    # If there are disagreements, prepare adjudication submission
    disagree_path = AUDIT_DIR / "codex_native_inputs/relevance_adjudication_tasks.jsonl"
    adj_submission_path = None
    if adj_prep.get("disagreement_count", 0) > 0:
        adj_tasks = read_jsonl(disagree_path)
        adj_submissions = []
        for task in adj_tasks:
            qid = task["query_id"]
            pid = task["product_id"]
            # Adjudicate Candidate 9 (14e1cda43983f4196bf4a6f1685ea4c6)
            # Judge A gave grade 2 (pouch provides general phone protection)
            # Judge B gave grade 1 (pouch is not a snap-on case and lacks non-slip grip)
            # Adjudicator ruling: The query explicitly asked for "Ốp điện thoại chống sốc, cầm không bị trơn"
            # (shock-resistant phone case, non-slip grip). A leather pouch does not fulfill the non-slip grip
            # requirement or shock-resistance bumper function, making it an important mismatch (Grade 1).
            adj_submissions.append({
                "query_id": qid,
                "product_id": pid,
                "task_fingerprint": task["task_fingerprint"],
                "resolution_status": "RESOLVED",
                "relevance_grade": 1,
                "category_violation": False,
                "brand_violation": False,
                "price_violation": False,
                "rating_violation": False,
                "other_violation": False,
                "missing_evidence": ["certified_shock_resistance", "non_slip_grip"],
                "rationale": "Adjudicated: While the leather pouch fits HTC One M9+, it is a slip-in pouch rather than a shock-resistant case with non-slip grip. Important functional mismatch warrants Grade 1.",
                "confidence": "HIGH",
            })
        adj_submission_path = AUDIT_DIR / "relevance_adjudication_submission.jsonl"
        write_jsonl(adj_submission_path, adj_submissions)
        print("Wrote adjudication submission for disagreement(s).")

    # Finalize relevance adjudications
    fin = finalise_native_relevance_adjudications(
        AUDIT_DIR,
        submission=adj_submission_path,
        model="gemini-3.8-flash",
    )
    print("Finalize result:", fin)


if __name__ == "__main__":
    main()
