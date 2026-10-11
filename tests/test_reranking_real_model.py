"""Opt-in local-checkpoint integration tests; never download weights in tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shopassist.reranking import load_local_cross_encoder


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = Path(os.getenv("SHOPASSIST_PHASE11_MODEL_DIR", ROOT / ".models/phase11/ms-marco-MiniLM-L2-v2"))
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not MODEL_DIR.joinpath("model.safetensors").exists(), reason="pinned Phase 11 model checkpoint is not installed locally")]


def test_real_cpu_model_loads_and_scores_canonical_product_pairs():
    scorer = load_local_cross_encoder(model_path=str(MODEL_DIR), device="cpu", max_length=512)
    pairs = [
        ("women red party wedges heel", "Product: red wedge heels for women"),
        ("women red party wedges heel", "Product: black leather walking boots for men"),
    ]
    scores = scorer.predict(pairs, batch_size=1)
    assert len(scores) == 2
    assert all(float(value) == float(value) for value in scores)
    assert scorer.token_length(*pairs[0]) <= 512


def test_real_cpu_model_batches_and_supports_empty_pair_input():
    scorer = load_local_cross_encoder(model_path=str(MODEL_DIR), device="cpu", max_length=512)
    assert scorer.predict([], batch_size=4) == []
    pairs = [("running shoes", f"Product: running shoes model {index}") for index in range(5)]
    assert len(scorer.predict(pairs, batch_size=2)) == len(pairs)


def test_real_tokenizer_truncates_long_product_text_at_model_limit():
    scorer = load_local_cross_encoder(model_path=str(MODEL_DIR), device="cpu", max_length=512)
    long_text = "Product specification detail " * 800
    assert scorer.token_length("running shoes", long_text) > 512
    assert scorer.token_length("running shoes", long_text, truncation=True) == 512
