"""Unit tests for Phase 8.1 deterministic business rules and validation (100% offline)."""

from __future__ import annotations

import pytest

from shopassist.llm.refinement_rules import (
    apply_rule_based_refinement_v1,
    apply_rule_based_refinement_v2,
    clean_product_type_from_preferences,
    detect_price_boundary_semantics,
    extract_exclusions_from_text,
    is_out_of_domain_query,
    refine_hard_constraints_rules,
    resolve_negation_conflicts,
)
from shopassist.llm.schema_variants import (
    ExclusionConstraint,
    RefinedHardConstraints,
    RefinedQueryUnderstandingOutput,
)
from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput


class TestRefinementRules:
    """Test suite for deterministic refinement rules."""

    def test_detect_strict_upper_price_boundary(self):
        b1 = detect_price_boundary_semantics("Puma running shoes under 2000 rupees")
        assert b1["max_inclusive"] is False

        b2 = detect_price_boundary_semantics("laptop below 50000")
        assert b2["max_inclusive"] is False

        b3 = detect_price_boundary_semantics("watch less than 1500")
        assert b3["max_inclusive"] is False

    def test_detect_inclusive_upper_price_boundary(self):
        b1 = detect_price_boundary_semantics("shoes at most 3000 rs")
        assert b1["max_inclusive"] is True

        b2 = detect_price_boundary_semantics("phone up to 20000")
        assert b2["max_inclusive"] is True

        b3 = detect_price_boundary_semantics("headphones maximum 4000")
        assert b3["max_inclusive"] is True

    def test_detect_strict_lower_price_boundary(self):
        b1 = detect_price_boundary_semantics("watch above 1000 rupees")
        assert b1["min_inclusive"] is False

        b2 = detect_price_boundary_semantics("shoes more than 2500")
        assert b2["min_inclusive"] is False

    def test_detect_inclusive_lower_price_boundary(self):
        b1 = detect_price_boundary_semantics("watch at least 1000 rupees")
        assert b1["min_inclusive"] is True

        b2 = detect_price_boundary_semantics("shoes minimum 2500")
        assert b2["min_inclusive"] is True

    def test_detect_in_query_correction(self):
        b = detect_price_boundary_semantics("shoes under 1000, actually make it under 1500")
        assert b["detected_corrections"] is True

    def test_extract_exclusions_from_text(self):
        q = "Nike shoes, but not running shoes and without leather"
        excls = extract_exclusions_from_text(q)
        assert len(excls) == 2
        vals = [e.value for e in excls]
        assert "running shoes" in vals
        assert "leather" in vals

    def test_resolve_negation_conflicts(self):
        soft_prefs = ["comfortable", "not running", "running shoes"]
        excls = [ExclusionConstraint(target_type="product_type", value="running shoes")]

        clean_prefs, final_excls, warns = resolve_negation_conflicts(soft_prefs, excls)
        # 'not running' moved to exclusions
        # 'running shoes' removed because it contradicts exclusion 'running shoes'
        assert "running shoes" not in clean_prefs
        assert "not running" not in clean_prefs
        assert clean_prefs == ["comfortable"]

    def test_clean_product_type_from_preferences(self):
        soft_prefs = ["comfortable", "running", "running shoes"]
        clean_prefs, warns = clean_product_type_from_preferences(
            soft_preferences=soft_prefs,
            product_type="running shoes",
            semantic_query="Puma running shoes",
        )
        assert clean_prefs == ["comfortable"]
        assert len(warns) == 2

    def test_p8_07_brand_suppression_on_unsupported_airplane(self):
        """Verify that P8-07 is resolved: 'Boeing' is suppressed on out-of-domain query."""
        raw_query = "commercial Boeing 747 airplane for sale"
        hc = RefinedHardConstraints(category=None, brand="Boeing")
        refined_hc, warns = refine_hard_constraints_rules(
            hc=hc,
            raw_query=raw_query,
            is_clarification=True,
        )
        assert refined_hc.brand is None
        assert any("Suppressed brand" in w for w in warns)

    def test_full_refinement_v2_end_to_end(self):
        out = RefinedQueryUnderstandingOutput(
            product_type="running shoes",
            semantic_query="Puma running shoes",
            hard_constraints=RefinedHardConstraints(
                category="Footwear",
                brand="Puma",
                max_price=2000.0,
            ),
            soft_preferences=["running", "comfortable"],
        )
        raw_q = "Puma running shoes under 2000 rupees"
        refined_out, warns = apply_rule_based_refinement_v2(out, raw_q)

        # max_inclusive should be False for 'under 2000'
        assert refined_out.hard_constraints.max_inclusive is False
        # 'running' should be stripped from soft_preferences
        assert refined_out.soft_preferences == ["comfortable"]
