"""Unit tests for Phase 8.1 schema refinements and backward compatibility (100% offline)."""

from __future__ import annotations

import pytest

from shopassist.llm.schema_variants import (
    ExclusionConstraint,
    RefinedHardConstraints,
    RefinedQueryUnderstandingOutput,
)
from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput


class TestSchemaRefinement:
    """Test suite for Schema v2.0.0 and backward compatibility."""

    def test_refined_hard_constraints_boundary_operators(self):
        hc = RefinedHardConstraints(
            category="Footwear",
            brand="Puma",
            min_price=500.0,
            max_price=2000.0,
            min_inclusive=False,  # strictly above 500
            max_inclusive=True,   # at most 2000
        )
        assert hc.min_inclusive is False
        assert hc.max_inclusive is True
        assert hc.category == "Footwear"

    def test_refined_hard_constraints_negative_price_rejected(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            RefinedHardConstraints(min_price=-100.0)

    def test_refined_hard_constraints_inverted_range_rejected(self):
        with pytest.raises(ValueError, match="cannot be greater than max_price"):
            RefinedHardConstraints(min_price=2500.0, max_price=1000.0)

    def test_exclusion_constraint_value_cleaning(self):
        excl1 = ExclusionConstraint(target_type="product_type", value="not running shoes")
        assert excl1.value == "running shoes"

        excl2 = ExclusionConstraint(target_type="attribute", value="without leather")
        assert excl2.value == "leather"

        excl3 = ExclusionConstraint(target_type="feature", value="no wired")
        assert excl3.value == "wired"

    def test_refined_output_to_v1_compatibility(self):
        v2 = RefinedQueryUnderstandingOutput(
            product_type="running shoes",
            semantic_query="Nike shoes",
            hard_constraints=RefinedHardConstraints(
                category="Footwear",
                brand="Nike",
                max_price=3000.0,
                max_inclusive=False,
            ),
            exclusions=[ExclusionConstraint(target_type="product_type", value="running shoes")],
            soft_preferences=["comfortable"],
            needs_clarification=False,
        )

        v1 = v2.to_v1()
        assert isinstance(v1, QueryUnderstandingOutput)
        assert v1.semantic_query == "Nike shoes"
        assert v1.hard_constraints.brand == "Nike"
        assert v1.hard_constraints.max_price == 3000.0
        # Exclusions mapped into soft preferences for v1 consumers
        assert "not running shoes" in v1.soft_preferences
        assert "comfortable" in v1.soft_preferences

    def test_refined_output_from_v1_upgrade(self):
        v1 = QueryUnderstandingOutput(
            semantic_query="Nike shoes",
            hard_constraints=HardConstraints(category="Footwear", brand="Nike"),
            soft_preferences=["comfortable", "not running shoes", "without leather"],
            needs_clarification=False,
        )

        v2 = RefinedQueryUnderstandingOutput.from_v1(v1)
        assert isinstance(v2, RefinedQueryUnderstandingOutput)
        assert v2.soft_preferences == ["comfortable"]
        assert len(v2.exclusions) == 2
        excl_vals = [e.value for e in v2.exclusions]
        assert "running shoes" in excl_vals
        assert "leather" in excl_vals
