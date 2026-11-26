"""Offline checks for evaluation accounting and immutable prompt separation."""
from scripts.evaluate_ollama_query_understanding import PROMPTS, SCHEMA
from scripts.summarize_ollama_query_understanding import summarize
from shopassist.llm.prompts import SYSTEM_INSTRUCTION


def test_baseline_is_production_prompt_and_required_probe_is_not_production():
    assert PROMPTS['P0'] == SYSTEM_INSTRUCTION
    assert set(SCHEMA['required']) == {'semantic_query'}
    assert PROMPTS['P4'] != PROMPTS['P0']


def test_missing_output_cannot_be_scored_as_a_success():
    case = {'expected': {'hard_constraints': {'category': 'Footwear', 'brand': None,
             'min_price': None, 'max_price': 2000, 'min_rating': None, 'currency': 'INR'},
             'soft_preferences': ['lightweight'], 'needs_clarification': False}}
    result = summarize([case], 'normalized')
    assert result['counts']['exact'] == 0
    assert result['counts']['max_price'] == 0
    assert result['preference']['fn'] == 1


def test_price_inversion_is_counted_even_with_valid_json():
    hc = {'category': 'Footwear', 'brand': None, 'min_price': None,
          'max_price': 2000, 'min_rating': None, 'currency': 'INR'}
    row = {'expected': {'hard_constraints': hc, 'soft_preferences': [], 'needs_clarification': False},
           'normalized': {'hard_constraints': {**hc, 'min_price': 2000, 'max_price': None},
                          'soft_preferences': [], 'needs_clarification': False}}
    counts = summarize([row], 'normalized')['counts']
    assert counts['inversion'] == counts['hallucination'] == counts['missing'] == 1
