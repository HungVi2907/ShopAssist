"""Semantic edge-case oracles; no model inference is claimed by these tests."""
import pytest
from shopassist.llm.experiments.phase82.rules import apply, boundary_evidence, direct_exclusions
from shopassist.llm.schema_variants import RefinedQueryUnderstandingOutput


@pytest.mark.parametrize("query,expected", [
    ("Nike shoes, not only running shoes",[]), ("Shoes not necessarily running shoes",[]),
    ("Shoes not running shoes",[("product_type","running shoes")]),
    ("Wallet without leather",[("attribute","leather")]), ("Shoes not too expensive",[]),
    ("Anything except Nike",[("brand","nike")]), ("Nike or Adidas shoes",[]),
    ("Watch no less than 2000",[]), ("Watch not under 2000",[]),
    ("Watch not less than 2000",[]), ("Not without leather",[]), ("not not leather",[]),
])
def test_negation_scope(query,expected):
    assert [(e.target_type,e.value) for e in direct_exclusions(query)] == expected


@pytest.mark.parametrize("query,side,value,inclusive", [
    ("under 3000, actually up to 4200","max",4200,True),
    ("up to 3000, make it below 4100","max",4100,False),
    ("not under 2000","min",2000,True), ("no less than 2000","min",2000,True),
    ("not more than 2000","max",2000,True), ("above 1900","min",1900,False),
    ("under ₹2,400","max",2400,False),
])
def test_boundary_scope_and_corrections(query,side,value,inclusive):
    b=boundary_evidence(query)
    assert b[side]["value"] == value and b[side]["inclusive"] is inclusive


def test_measurements_are_not_prices_and_unmatched_model_bound_is_preserved():
    assert not boundary_evidence("at least 4 stars and at least 1200 watts")
    out=RefinedQueryUnderstandingOutput(semantic_query="watch",hard_constraints={"max_price":1500,"max_inclusive":True})
    final,_=apply(out,"Watch under 2000",("price",))
    assert final.hard_constraints.max_inclusive is True


def test_valid_preferences_and_explicit_manufacturer_survive():
    out=RefinedQueryUnderstandingOutput(product_type="aircraft",semantic_query="Boeing aircraft",hard_constraints={"brand":"Boeing"},needs_clarification=True)
    final,_=apply(out,"Boeing aircraft for sale")
    assert final.hard_constraints.brand == "Boeing"
    assert final.needs_clarification
    out=RefinedQueryUnderstandingOutput(product_type="shoes",semantic_query="shoes",soft_preferences=["running","faux leather"],exclusions=[{"value":"leather"}])
    final,_=apply(out,"Shoes suitable for running without leather")
    assert final.soft_preferences == ["running","faux leather"]


def test_currency_clarification_and_no_mutation_of_raw_response():
    out=RefinedQueryUnderstandingOutput(semantic_query="watch",hard_constraints={"currency":"USD","max_price":100})
    final,_=apply(out,"Watch under 100 dollars")
    assert final.needs_clarification and final.hard_constraints.currency == "USD"
    assert out.needs_clarification is False and out.hard_constraints.max_inclusive is True


def test_related_exclusion_does_not_duplicate_model_span():
    out=RefinedQueryUnderstandingOutput(semantic_query="lens",exclusions=[{"target_type":"attribute","value":"telephoto"}])
    final,_=apply(out,"Lens but no telephoto lenses")
    assert len(final.exclusions) == 1


def test_class_cleanup_is_contextual():
    out=RefinedQueryUnderstandingOutput(product_type="analog watch",semantic_query="watch",soft_preferences=["analog","comfortable"])
    assert apply(out,"comfortable analog watch")[0].soft_preferences == ["comfortable"]
    out.product_type="watch"
    assert apply(out,"watch with analog display")[0].soft_preferences == ["analog","comfortable"]
