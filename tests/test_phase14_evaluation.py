"""Unit tests for Phase 14 Evaluation Metrics & AI-Silver Validation.

Verifies:
1. Metric correctness with hand-calculated numerical examples.
2. Rank preservation in MRR and nDCG (unjudged items do not shift subsequent ranks).
3. Incomplete judgment handling (judged-only vs. conservative precision).
4. Ideal DCG calculation against candidate pool universe.
5. Constraint compliance evaluation with metadata.
6. Benchmark immutability and split isolation.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import pytest

from shopassist.evaluation.phase14_metrics import (
    RankingItem,
    aggregate_cutoff_metrics,
    bootstrap_ci,
    check_product_constraints,
    compute_dcg,
    compute_idcg,
    evaluate_query_cutoff,
)
from shopassist.evaluation.silver import file_sha256, load_manifest

ROOT = Path(__file__).resolve().parents[1]
V4_DIR = ROOT / "data/evaluation/phase13/ai_silver/v4_full_silver"


def test_dcg_preserves_original_ranks():
    """Verify that DCG respects original ranks and does not compact unjudged items."""
    # Case A: Grade 3 at rank 1, Grade 2 at rank 2
    # Gain(3) = 7, Discount = log2(2) = 1.0 -> 7.0
    # Gain(2) = 3, Discount = log2(3) = 1.5849625 -> 1.892789
    dcg_a = compute_dcg([(1, 3), (2, 2)])
    expected_a = (7.0 / 1.0) + (3.0 / math.log2(3))
    assert math.isclose(dcg_a, expected_a, rel_tol=1e-5)

    # Case B: Rank 1 is unjudged (absent), Grade 3 is at rank 2
    # In buggy implementations that compact, Grade 3 would be discounted at log2(2) = 1.0 -> 7.0.
    # In rank-preserving implementation, Grade 3 MUST be discounted at log2(3) -> 4.416726.
    dcg_b = compute_dcg([(2, 3)])
    expected_b = 7.0 / math.log2(3)
    assert math.isclose(dcg_b, expected_b, rel_tol=1e-5)
    assert dcg_b < 5.0  # Proves rank 2 discount was properly applied


def test_mrr_preserves_original_ranks():
    """Verify that Reciprocal Rank uses original product rank, not compacted index."""
    # Rank 1: unjudged, Rank 2: relevant (Grade 2), Rank 3: irrelevant (Grade 0)
    items = [
        RankingItem("P_UNJUDGED", original_rank=1, score=0.9, is_judged=False),
        RankingItem("P_REL", original_rank=2, score=0.8, is_judged=True, relevance_grade=2, is_relevant=True),
        RankingItem("P_IRREL", original_rank=3, score=0.7, is_judged=True, relevance_grade=0, is_relevant=False),
    ]
    universe = [2, 0]
    metrics = evaluate_query_cutoff(items, universe, k=3)

    # First relevant is at original rank 2 -> RR must be 1/2 = 0.5
    assert metrics.first_relevant_rank == 2
    assert math.isclose(metrics.reciprocal_rank, 0.5, rel_tol=1e-5)


def test_idcg_against_judgment_universe():
    """Verify IDCG@K is calculated against all available grades in the pool universe."""
    universe = [3, 2, 2, 1, 0]
    # For K=3, the top 3 best grades in universe are [3, 2, 2]
    # Ideal DCG@3 = (7/log2(2)) + (3/log2(3)) + (3/log2(4)) = 7.0 + 1.892789 + 1.5 = 10.392789
    idcg_3 = compute_idcg(universe, k=3)
    expected_idcg = 7.0 + (3.0 / math.log2(3)) + (3.0 / 2.0)
    assert math.isclose(idcg_3, expected_idcg, rel_tol=1e-5)

    # If system returns only poor products [1, 0, 1] at ranks 1, 2, 3:
    poor_items = [
        RankingItem("P1", original_rank=1, score=0.9, is_judged=True, relevance_grade=1, is_relevant=False),
        RankingItem("P2", original_rank=2, score=0.8, is_judged=True, relevance_grade=0, is_relevant=False),
        RankingItem("P3", original_rank=3, score=0.7, is_judged=True, relevance_grade=1, is_relevant=False),
    ]
    poor_metrics = evaluate_query_cutoff(poor_items, universe, k=3)

    # DCG is (1/log2(2)) + 0 + (1/log2(4)) = 1.0 + 0.5 = 1.5
    # nDCG = 1.5 / 10.392789 = 0.14433
    assert math.isclose(poor_metrics.dcg, 1.5, rel_tol=1e-5)
    assert math.isclose(poor_metrics.ndcg, 1.5 / expected_idcg, rel_tol=1e-5)
    assert poor_metrics.ndcg < 0.2


def test_precision_judged_vs_conservative():
    """Verify the transparent separation between judged-only and conservative precision."""
    # Top 3: 1 relevant, 1 irrelevant, 1 unjudged
    items = [
        RankingItem("P1", original_rank=1, score=0.9, is_judged=True, relevance_grade=3, is_relevant=True),
        RankingItem("P2", original_rank=2, score=0.8, is_judged=False),
        RankingItem("P3", original_rank=3, score=0.7, is_judged=True, relevance_grade=1, is_relevant=False),
    ]
    universe = [3, 1]
    metrics = evaluate_query_cutoff(items, universe, k=3)

    assert metrics.returned_count == 3
    assert metrics.judged_count == 2
    assert metrics.relevant_count == 1
    assert math.isclose(metrics.judgment_coverage, 2 / 3, rel_tol=1e-5)
    # Judged precision: 1 / 2 = 0.5
    assert math.isclose(metrics.precision_judged, 0.5, rel_tol=1e-5)
    # Conservative precision: 1 / 3 = 0.333333
    assert math.isclose(metrics.precision_conservative, 1 / 3, rel_tol=1e-5)


def test_pool_conditional_recall():
    """Verify pool-conditional recall calculation."""
    # Universe has 4 relevant items (grades >= 2): [3, 2, 2, 2, 1, 0]
    universe = [3, 2, 2, 2, 1, 0]
    # System retrieved 2 of them in top 5
    items = [
        RankingItem("P1", original_rank=1, score=0.9, is_judged=True, relevance_grade=3, is_relevant=True),
        RankingItem("P2", original_rank=2, score=0.8, is_judged=True, relevance_grade=2, is_relevant=True),
        RankingItem("P3", original_rank=3, score=0.7, is_judged=True, relevance_grade=1, is_relevant=False),
    ]
    metrics = evaluate_query_cutoff(items, universe, k=5)
    # Retrieved 2 out of 4 relevant in pool -> Recall = 2/4 = 0.5
    assert math.isclose(metrics.pool_conditional_recall, 0.5, rel_tol=1e-5)


def test_check_product_constraints():
    """Verify hard constraint compliance evaluation against product metadata."""
    product = {
        "product_id": "P001",
        "category": "Clothing and Accessories >> Footwear >> Men's Shoes",
        "brand": "Puma",
        "discounted_price": 1499.0,
        "rating": 4.2,
    }

    # Matches all constraints
    assert check_product_constraints(
        product,
        {"category": "Footwear", "brand": "Puma", "max_price": 2000.0, "min_rating": 4.0},
    )

    # Fails category
    assert not check_product_constraints(product, {"category": "Electronics"})

    # Fails brand
    assert not check_product_constraints(product, {"brand": "Nike"})

    # Fails price
    assert not check_product_constraints(product, {"max_price": 1000.0})

    # Fails rating
    assert not check_product_constraints(product, {"min_rating": 4.5})

    # Null rating fails rating threshold
    null_rating_product = dict(product)
    null_rating_product["rating"] = None
    assert not check_product_constraints(null_rating_product, {"min_rating": 3.0})


def test_bootstrap_ci():
    """Verify bootstrap confidence interval calculation."""
    values = [0.2, 0.4, 0.6, 0.8, 1.0]
    ci = bootstrap_ci(values, samples=500, seed=123)
    assert ci["mean"] == 0.6
    assert ci["ci_lower"] is not None
    assert ci["ci_upper"] is not None
    assert ci["ci_lower"] <= ci["mean"] <= ci["ci_upper"]

    # Single item
    single_ci = bootstrap_ci([0.75])
    assert single_ci["mean"] == 0.75
    assert single_ci["ci_lower"] == 0.75
    assert single_ci["ci_upper"] == 0.75

    # Empty list
    empty_ci = bootstrap_ci([])
    assert empty_ci["mean"] is None


def test_v4_benchmark_immutability_and_splits():
    """Verify frozen AI-Silver v4 files and zero partition leakage."""
    assert V4_DIR.is_dir()
    manifest = load_manifest(V4_DIR)

    # Check key files exist and match manifest hashes
    for filename, expected_hash in manifest.get("artifact_sha256", {}).items():
        file_path = V4_DIR / filename
        assert file_path.is_file(), f"Missing frozen file: {filename}"
        assert file_sha256(file_path) == expected_hash, f"Hash mismatch for {filename}"

    # Verify split partition isolation
    splits = json.loads((V4_DIR / "splits.json").read_text(encoding="utf-8"))
    dev_qids = set(splits["development"])
    held_out_qids = set(splits["held_out"])

    assert len(dev_qids) == 140
    assert len(held_out_qids) == 60
    assert len(dev_qids & held_out_qids) == 0, "Partition leakage detected between dev and held_out!"


def test_rag_educational_trace_generation():
    """Verify RAG educational trace contains all required pipeline stages."""
    from shopassist.evaluation.phase14_evaluator import Phase14Dataset, build_rag_educational_trace

    dataset = Phase14Dataset.load(V4_DIR)
    trace = build_rag_educational_trace(dataset, query_id="Q0001")

    assert trace["query_id"] == "Q0001"
    assert len(trace["pipeline_stages"]) == 5

    stage_names = [s["step"] for s in trace["pipeline_stages"]]
    assert any("Phase 8" in name for name in stage_names)
    assert any("Phase 9" in name for name in stage_names)
    assert any("Phase 10" in name for name in stage_names)
    assert any("Phase 11" in name for name in stage_names)
    assert any("Phase 12" in name for name in stage_names)


def test_deterministic_grounding_validator():
    """Verify programmatic verification of candidate IDs, citations, and constraints."""
    from shopassist.evaluation.phase14_evaluator import evaluate_deterministic_grounding

    catalog = {
        "P001": {"product_id": "P001", "category": "Footwear", "brand": "Puma", "discounted_price": 1500.0},
        "P002": {"product_id": "P002", "category": "Footwear", "brand": "Nike", "discounted_price": 2500.0},
    }

    # Valid payload
    valid_payload = {
        "products": [
            {
                "product_id": "P001",
                "strengths": [{"claim": "Great shoe", "evidence_ids": ["P001-E1"]}],
            }
        ]
    }
    valid_res = evaluate_deterministic_grounding(valid_payload, catalog)
    assert valid_res["is_deterministic_valid"] is True
    assert valid_res["valid_citations_count"] == 1

    # Invalid product ID payload
    invalid_pid_payload = {
        "products": [{"product_id": "P999_HALLUCINATED", "strengths": []}]
    }
    invalid_pid_res = evaluate_deterministic_grounding(invalid_pid_payload, catalog)
    assert invalid_pid_res["is_deterministic_valid"] is False
    assert any("does not exist in candidate pool" in err for err in invalid_pid_res["errors"])

    # Invalid citation tag payload
    invalid_cit_payload = {
        "products": [
            {
                "product_id": "P001",
                "strengths": [{"claim": "Great shoe", "evidence_ids": ["P002-E1"]}],  # Cites wrong product ID!
            }
        ]
    }
    invalid_cit_res = evaluate_deterministic_grounding(invalid_cit_payload, catalog)
    assert invalid_cit_res["is_deterministic_valid"] is False
    assert any("does not match product ID prefix" in err for err in invalid_cit_res["errors"])


def test_llm_judge_offline_workflow():
    """Verify structured LLM-as-a-Judge execution and rubric parsing."""
    from shopassist.evaluation.phase14_judge import run_llm_judge

    result = run_llm_judge(
        user_query="men running shoes",
        evidence_text="[P1-E1] Running shoe by Puma",
        recommendation_output="Puma running shoes [P1-E1]",
        mock_mode=True,
    )
    assert result.overall_decision == "PASS"
    assert result.groundedness_score == 5
    assert result.execution_mode == "OFFLINE_DEMONSTRATION"
    assert result.evidence_supported is True

