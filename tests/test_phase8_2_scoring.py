"""Independent metric oracles and regressions for the historical evaluator defects."""
import pytest
from shopassist.llm.experiments.phase82.scoring import aggregate, paired_bootstrap, prf, score, wilson


@pytest.mark.parametrize("predicted,expected,counts,f1", [
    (set(), set(), (0,0,0),1), ({"a"},set(),(0,1,0),0), (set(),{"a"},(0,0,1),0),
    ({"a","b"},{"a","c"},(1,1,1),.5), ({"a","b"},{"a"},(1,1,0),2/3),
])
def test_precision_recall_f1_oracles(predicted,expected,counts,f1):
    s=prf(predicted,expected)
    assert tuple(s[k] for k in ("tp","fp","fn")) == counts
    assert s["f1"] == pytest.approx(f1)


def test_failed_empty_output_never_earns_exact_or_macro_credit():
    s=score(None, {"soft_preferences": [], "hard_constraints": {}},False)
    assert not s["common_exact"] and not s["soft_exact"]
    assert s["soft"]["f1"] == 0 and s["hard"]["fn"] == 1
    assert s["field_matches"]["category"] is False


def test_numeric_equality_null_and_case_handling():
    s=score({"hard_constraints":{"brand":" nIkE ","max_price":2000.0}},
            {"hard_constraints":{"brand":"Nike","max_price":2000}})
    assert s["hard_exact"] and s["hard"]["fp"] == 0


def test_wrong_constraint_counts_both_fp_and_fn():
    s=score({"hard_constraints":{"category":"Computers"}}, {"hard_constraints":{"category":"Footwear"}})
    assert (s["hard"]["tp"],s["hard"]["fp"],s["hard"]["fn"]) == (1,1,1)


def test_missing_v2_bound_and_explicit_null_product_type_fail():
    e={"product_type":None,"exclusions":[],"hard_constraints":{"max_price":80,"min_inclusive":True,"max_inclusive":False}}
    a={"product_type":"phone","exclusions":[],"hard_constraints":{"max_price":80}}
    s=score(a,e)
    assert s["common_exact"] and not s["full_v2_exact"]
    assert not s["product_type_match"] and not s["boundary_matches"]["max_inclusive"]


def test_absent_bound_flags_are_inapplicable():
    e={"product_type":"pen","exclusions":[],"hard_constraints":{"min_inclusive":True,"max_inclusive":True}}
    a={**e,"hard_constraints":{"min_inclusive":False,"max_inclusive":False}}
    assert score(a,e)["full_v2_exact"]


def test_cross_schema_common_fields_are_fair():
    e={"product_type":"pen","exclusions":[],"hard_constraints":{"min_inclusive":True,"max_inclusive":True}}
    v1={"hard_constraints":{},"soft_preferences":[]}
    s=score(v1,e)
    assert s["common_exact"] and s["full_v2_exact"] is False
    assert score(v1,{"hard_constraints":{}})["full_v2_exact"] is None


def test_semantic_equivalence_is_supplementary_and_conservative():
    s=score({"soft_preferences":["lumbar support","lumbar support"]},{"soft_preferences":["with lumbar support"]})
    assert s["soft"]["f1"] == 0 and s["semantic_soft"]["f1"] == 1
    assert score({"soft_preferences":["short battery life"]},{"soft_preferences":["long battery life"]})["semantic_soft"]["f1"] == 0


def test_semantic_query_wording_is_separate():
    s=score({"semantic_query":"pen for school"},{"semantic_query":"school pen"})
    assert s["common_exact"] and s["semantic_query_lexical_match"] is False


def test_denominators_include_service_failure_and_ignore_unannotated_fields():
    rows=[{"score":score({},{}),"cache_status":"historical_unknown"}, {"score":score(None,{},False),"cache_status":"historical_unknown"}]
    a=aggregate(rows)
    assert a["common_exact"]["rate"] == .5 and a["soft_macro_f1"] == .5
    assert a["product_type_accuracy"]["denominator"] == 0
    assert a["performance"]["live_end_to_end"]["n"] == 0


def test_macro_and_micro_are_distinct():
    rows=[{"score":score({"soft_preferences":["a"]},{"soft_preferences":["a"]})},
          {"score":score({"soft_preferences":[]},{"soft_preferences":["b","c","d"]})}]
    a=aggregate(rows)
    assert a["soft_macro_f1"] == .5 and a["soft_micro"]["f1"] == .4


def test_wilson_interval_small_sample():
    assert wilson(10,20) == pytest.approx([.2992980082,.7007019918])
    assert wilson(0,0) is None


def test_bootstrap_pairs_case_ids_and_preserves_reproducibility():
    left=[{"test_id":str(i),"score":{"common_exact":False}} for i in range(4)]
    right=[{"test_id":str(i),"score":{"common_exact":True}} for i in range(4)]
    result=paired_bootstrap(left,list(reversed(right)))
    assert result["effect"] == 1 and result["percentile95"] == [1,1]
    assert result == paired_bootstrap(left,right)
    with pytest.raises(ValueError): paired_bootstrap(left,right[:2])


def test_failed_empty_exclusions_receive_no_success_credit():
    s=score(None,{"exclusions":[]},False)
    assert s["exclusions"]["f1"] == 0 and s["exclusion_exact"] is False


def test_repeated_sampling_agreement_is_not_independent_evidence():
    from shopassist.llm.experiments.phase82.scoring import consistency
    rows=[{"test_id":"q","is_valid":True,"actual":{"a":1},"score":score({},{} )},
          {"test_id":"q","is_valid":True,"actual":{"a":1},"score":score({},{} )},
          {"test_id":"q","is_valid":False,"actual":None,"score":score(None,{},False)}]
    assert consistency(rows)["rate"] == pytest.approx(1/3)
    assert aggregate(rows)["common_exact"]["wilson95"] is None
