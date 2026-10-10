"""Unit tests for Phase 8.1 evaluation metrics and error audit (100% offline)."""

from __future__ import annotations

import pytest

from shopassist.llm.experiments.failure_analysis import (
    classify_soft_preference_error,
    run_failure_analysis_on_benchmark,
)
from shopassist.llm.experiments.metrics import (
    compute_experiment_metrics,
    evaluate_refined_case,
)


class TestEvaluationAuditMetrics:
    """Test suite for rigorous metric calculation."""

    def test_perfect_match_case(self):
        actual = {
            "semantic_query": "Puma running shoes",
            "product_type": "running shoes",
            "hard_constraints": {
                "category": "Footwear",
                "brand": "Puma",
                "min_price": None,
                "max_price": 2000.0,
                "min_inclusive": True,
                "max_inclusive": False,
                "min_rating": None,
                "currency": "INR",
            },
            "exclusions": [],
            "soft_preferences": ["comfortable"],
            "needs_clarification": False,
        }
        expected = {
            "product_type": "running shoes",
            "hard_constraints": {
                "category": "Footwear",
                "brand": "Puma",
                "min_price": None,
                "max_price": 2000.0,
                "min_inclusive": True,
                "max_inclusive": False,
                "min_rating": None,
                "currency": "INR",
            },
            "exclusions": [],
            "soft_preferences": ["comfortable"],
            "needs_clarification": False,
        }

        res = evaluate_refined_case(actual, expected)
        assert res["category_match"] is True
        assert res["brand_match"] is True
        assert res["price_match"] is True
        assert res["boundary_operator_match"] is True
        assert res["soft_preferences_f1"] == 1.0
        assert res["is_legacy_exact_match"] is True
        assert res["is_strict_complete_exact_match"] is True

    def test_legacy_vs_strict_exact_match_discrepancy(self):
        """Verify that when soft_preferences differ, legacy exact match is True but strict complete exact match is False."""
        actual = {
            "semantic_query": "Puma running shoes",
            "product_type": "running shoes",
            "hard_constraints": {
                "category": "Footwear",
                "brand": "Puma",
                "min_price": None,
                "max_price": 2000.0,
                "currency": "INR",
            },
            "exclusions": [],
            "soft_preferences": ["running"],  # Extracted extra product noun
            "needs_clarification": False,
        }
        expected = {
            "product_type": "running shoes",
            "hard_constraints": {
                "category": "Footwear",
                "brand": "Puma",
                "min_price": None,
                "max_price": 2000.0,
                "currency": "INR",
            },
            "exclusions": [],
            "soft_preferences": [],  # Expected empty
            "needs_clarification": False,
        }

        res = evaluate_refined_case(actual, expected)
        assert res["is_legacy_exact_match"] is True
        assert res["is_strict_complete_exact_match"] is False
        assert res["soft_preferences_f1"] == 0.0
        assert res["soft_false_positives"] == ["running"]

    def test_soft_preferences_f1_calculation(self):
        actual = {"soft_preferences": ["lightweight", "comfortable", "red"]}
        expected = {"soft_preferences": ["lightweight", "comfortable", "breathable"]}

        res = evaluate_refined_case(actual, expected)
        # 2 overlapping out of 3 actual (prec=2/3), 2 out of 3 expected (rec=2/3) -> F1 = 2/3 = 0.6667
        assert round(res["soft_preferences_f1"], 2) == 0.67
        assert res["soft_false_positives"] == ["red"]
        assert res["soft_false_negatives"] == ["breathable"]

    def test_aggregate_metrics_computation(self):
        case_results = [
            {
                "is_valid": True,
                "latency_ms": 1200.0,
                "token_usage": {"prompt_tokens": 1000, "candidates_tokens": 100, "total_tokens": 1100},
                "metrics": {
                    "category_match": True,
                    "brand_match": True,
                    "price_match": True,
                    "boundary_operator_match": True,
                    "rating_match": True,
                    "currency_match": True,
                    "clarification_match": True,
                    "product_type_match": True,
                    "is_legacy_exact_match": True,
                    "is_strict_complete_exact_match": True,
                    "soft_exact_match": True,
                    "soft_preferences_f1": 1.0,
                    "soft_preferences_precision": 1.0,
                    "soft_preferences_recall": 1.0,
                    "exclusions_f1": 1.0,
                    "true_positives": 5,
                    "false_positives": 0,
                    "false_negatives": 0,
                },
            },
            {
                "is_valid": True,
                "latency_ms": 1800.0,
                "token_usage": {"prompt_tokens": 1000, "candidates_tokens": 100, "total_tokens": 1100},
                "metrics": {
                    "category_match": True,
                    "brand_match": True,
                    "price_match": True,
                    "boundary_operator_match": True,
                    "rating_match": True,
                    "currency_match": True,
                    "clarification_match": True,
                    "product_type_match": True,
                    "is_legacy_exact_match": True,
                    "is_strict_complete_exact_match": False,
                    "soft_exact_match": False,
                    "soft_preferences_f1": 0.5,
                    "soft_preferences_precision": 0.5,
                    "soft_preferences_recall": 0.5,
                    "exclusions_f1": 1.0,
                    "true_positives": 5,
                    "false_positives": 0,
                    "false_negatives": 0,
                },
            },
        ]

        agg = compute_experiment_metrics(case_results)
        assert agg["total_cases_evaluated"] == 2
        assert agg["legacy_exact_match_rate"] == 1.0
        assert agg["strict_complete_exact_match_rate"] == 0.5
        assert agg["soft_preferences_metrics"]["mean_f1"] == 0.75
        assert agg["latency_stats_ms"]["p50"] == 1500.0


class TestFailureClassification:
    """Test suite for error taxonomy classification."""

    def test_classify_product_type_confusion(self):
        errs = classify_soft_preference_error(
            test_id="QU010",
            query="Canon DSLR camera lens above 25000",
            expected_prefs=["dslr lens"],
            actual_prefs=[],
            f1=0.0,
        )
        assert any(e["category"] == "Product-type confusion" for e in errs)

    def test_classify_inconsistent_ground_truth(self):
        errs = classify_soft_preference_error(
            test_id="QU029",
            query="cheap laptop",
            expected_prefs=["affordable"],
            actual_prefs=["cheap"],
            f1=0.0,
        )
        assert any(e["category"] == "Inconsistent ground truth" for e in errs)

    def test_classify_incorrect_negation(self):
        errs = classify_soft_preference_error(
            test_id="QU030",
            query="Nike shoes, but not running shoes",
            expected_prefs=["casual", "not running"],
            actual_prefs=["not running shoes"],
            f1=0.0,
        )
        assert any(e["category"] == "Incorrect negation" for e in errs)
