"""Offline Phase 11 contract, scoring, and Phase 10 integration tests."""

from __future__ import annotations

import numpy as np
import pytest

from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput, QueryUnderstandingResult
from shopassist.preferences.schemas import PreferenceRepresentationResult, RepresentationStatus
from shopassist.retrieval.hybrid import (
    CandidateSource,
    HybridCandidate,
    HybridRetrievalResult,
    HybridRetrievalStatus,
)
from shopassist.reranking import (
    CrossEncoderScorer,
    MappingProductTextProvider,
    validate_catalog_manifest,
    RerankingConfig,
    RerankingMethod,
    RerankingService,
    RerankingStatus,
)


def q8(**constraints):
    return QueryUnderstandingResult(
        query="running shoes for jogging",
        output=QueryUnderstandingOutput(
            semantic_query="running shoes",
            hard_constraints=HardConstraints(**constraints),
            soft_preferences=["comfortable"] if not constraints.pop("no_prefs", False) else [],
        ),
    )


def q9(status=RepresentationStatus.SUCCESS):
    success = status == RepresentationStatus.SUCCESS
    return PreferenceRepresentationResult(
        semantic_query="running shoes",
        normalized_preferences=["comfortable"] if success else [],
        preference_query="comfortable — running shoes" if success else None,
        has_preferences=success,
        status=status,
    )


def cand(pid, rank, dense_rank=None, lexical_rank=None, *, category="Footwear", brand="Puma", price=1000, rating=4.0):
    sources = {}
    if dense_rank is not None:
        sources["dense"] = CandidateSource(dense_rank, 1.0 / dense_rank)
    if lexical_rank is not None:
        sources["lexical"] = CandidateSource(lexical_rank, 1.0 / lexical_rank)
    return HybridCandidate(
        rank=rank,
        product_id=pid,
        product_name=f"Running shoe {pid}",
        category=category,
        brand=brand,
        discounted_price=price,
        rating=rating,
        rrf_score=1.0 / (60 + rank),
        sources=sources,
        metadata={"product_specifications": {"Color": "black"}, "query_vector_source": "phase9_preference"},
    )


def result(*candidates, status=HybridRetrievalStatus.SUCCESS):
    return HybridRetrievalResult(status=status, candidates=list(candidates), applied_constraints={"category": "Footwear"})


def service(texts, *, method=RerankingMethod.RRF, scorer=None, config=None):
    return RerankingService(
        MappingProductTextProvider(texts),
        config=config or RerankingConfig(top_k=2, method=method),
        cross_encoder=scorer,
    )


def test_rrf_pass_through_is_subset_deterministic_and_preserves_provenance():
    candidates = [cand("p1", 1, 1, 3), cand("p2", 2, 2, 1), cand("p3", 3, 3, 2)]
    out = service({f"p{i}": f"Product: shoe {i}" for i in range(1, 4)}).rerank(q8(), q9(), result(*candidates))
    assert out.status == RerankingStatus.SUCCESS
    assert [p.product_id for p in out.products] == ["p1", "p2"]
    assert out.returned_count == 2 and out.total_candidates == 3
    assert out.products[0].original_rank == 1 and out.products[0].reranked_rank == 1
    assert out.products[0].metadata["product_specifications"] == {"Color": "black"}
    assert out.products[0].retrieval_text == "Product: shoe 1"
    assert out.products[0].sources["dense"]["rank"] == 1


def test_multi_signal_uses_verified_dense_and_lexical_ranks():
    candidates = [cand("p1", 1, 1, 5), cand("p2", 2, 2, 1), cand("p3", 3, 3, 2)]
    out = service({f"p{i}": f"canonical {i}" for i in range(1, 4)}, method=RerankingMethod.MULTI_SIGNAL).rerank(
        q8(), q9(), result(*candidates), top_k=3
    )
    assert [p.product_id for p in out.products] == ["p2", "p1", "p3"]
    assert "multi_signal_rank_utility" in out.products[0].score_components


class FakeCrossEncoder:
    def __init__(self, scores):
        self.scores = scores
        self.pairs = None
        self.batch_size = None

    def predict(self, pairs, *, batch_size):
        self.pairs = list(pairs)
        self.batch_size = batch_size
        return self.scores


def test_cross_encoder_pairs_by_product_id_batches_and_ranks():
    scorer = FakeCrossEncoder(np.array([0.2, 0.9, 0.4]))
    candidates = [cand("p1", 1), cand("p2", 2), cand("p3", 3)]
    texts = {"p1": "canonical product one", "p2": "canonical product two", "p3": "canonical product three"}
    out = service(texts, method=RerankingMethod.CROSS_ENCODER, scorer=scorer).rerank(q8(), q9(), result(*candidates), top_k=3)
    assert [p.product_id for p in out.products] == ["p2", "p3", "p1"]
    assert scorer.pairs == [("comfortable — running shoes", texts[f"p{i}"]) for i in (1, 2, 3)]
    assert scorer.batch_size == 16
    assert out.products[0].score_components["cross_encoder_raw"] == 0.9


def test_combined_weights_are_normalized_and_config_validated():
    with pytest.raises(ValueError):
        RerankingConfig(cross_encoder_weight=float("nan"))
    scorer = FakeCrossEncoder([0.2, 0.9])
    candidates = [cand("p1", 1, 1, 2), cand("p2", 2, 2, 1)]
    texts = {"p1": "one", "p2": "two"}
    config = RerankingConfig(top_k=2, method=RerankingMethod.COMBINED, cross_encoder_weight=2.0, multi_signal_weight=1.0)
    out = service(texts, method=RerankingMethod.COMBINED, scorer=scorer, config=config).rerank(q8(), q9(), result(*candidates), top_k=2)
    assert out.status == RerankingStatus.SUCCESS
    assert all(0 <= p.final_score <= 1 for p in out.products)


def test_equal_cross_encoder_scores_are_stable_and_use_original_rank():
    scorer = FakeCrossEncoder([4, 4])
    candidates = [cand("p2", 2), cand("p1", 1)]
    texts = {"p1": "one", "p2": "two"}
    out = service(texts, method=RerankingMethod.CROSS_ENCODER, scorer=scorer).rerank(q8(), q9(), result(*candidates), top_k=2)
    assert [p.product_id for p in out.products] == ["p1", "p2"]
    assert all(p.final_score == 0.5 for p in out.products)


@pytest.mark.parametrize("scores", [[1.0], [float("nan"), 0], [float("inf"), 0], [[1, 2], [3, 4]]])
def test_bad_cross_encoder_output_is_failure(scores):
    candidates = [cand("p1", 1), cand("p2", 2)]
    out = service({"p1": "one", "p2": "two"}, method=RerankingMethod.CROSS_ENCODER, scorer=FakeCrossEncoder(scores)).rerank(
        q8(), q9(), result(*candidates), top_k=2
    )
    assert out.status == RerankingStatus.MODEL_FAILURE
    assert out.products == []


def test_cross_encoder_exception_fails_without_fallback():
    class RaisingScorer:
        def predict(self, pairs, *, batch_size):
            raise RuntimeError("inference failed")

    out = service({"p1": "one"}, method=RerankingMethod.CROSS_ENCODER, scorer=RaisingScorer()).rerank(
        q8(), q9(), result(cand("p1", 1))
    )
    assert out.status == RerankingStatus.MODEL_FAILURE
    assert out.products == []


def test_phase10_failures_are_propagated_without_scoring():
    out = service({}).rerank(q8(), q9(), result(status=HybridRetrievalStatus.UNSUPPORTED_INTENT))
    assert out.status == RerankingStatus.UNSUPPORTED_INTENT
    assert out.products == []


def test_phase9_failure_and_exclusions_do_not_become_success():
    candidate = cand("p1", 1)
    texts = {"p1": "canonical shoe"}
    failed = service(texts).rerank(q8(), q9(RepresentationStatus.EMBEDDING_FAILURE), result(candidate))
    assert failed.status == RerankingStatus.EMBEDDING_FAILURE
    excluded_query = QueryUnderstandingResult(
        query="running shoes but no leather",
        output=QueryUnderstandingOutput(semantic_query="running shoes", hard_constraints=HardConstraints(), soft_preferences=[]),
    )
    stopped = service(texts).rerank(excluded_query, q9(RepresentationStatus.NO_PREFERENCES), result(candidate))
    assert stopped.status == RerankingStatus.UNSUPPORTED_INTENT


def test_phase8_phase9_preference_mismatch_stops():
    mismatch = q9().model_copy(update={"normalized_preferences": ["lightweight"]})
    out = service({"p1": "product"}).rerank(q8(), mismatch, result(cand("p1", 1)))
    assert out.status == RerankingStatus.INVALID_INPUT


@pytest.mark.parametrize(
    "constraints,candidate",
    [
        ({"category": "Footwear"}, cand("p1", 1, category="Computers")),
        ({"brand": "Puma"}, cand("p1", 1, brand="Adidas")),
        ({"min_rating": 4.5}, cand("p1", 1, rating=4.0)),
        ({"max_price": 900}, cand("p1", 1, price=1000)),
    ],
)
def test_visible_hard_constraint_violation_fails_closed(constraints, candidate):
    out = service({"p1": "product"}).rerank(q8(**constraints), q9(), result(candidate))
    assert out.status == RerankingStatus.CONSTRAINT_VIOLATION
    assert out.products == []


def test_null_rating_fails_minimum_constraint_but_is_allowed_without_one():
    no_rating = cand("p1", 1, rating=None)
    blocked = service({"p1": "product"}).rerank(q8(min_rating=4), q9(), result(no_rating))
    allowed = service({"p1": "product"}).rerank(q8(), q9(), result(no_rating))
    assert blocked.status == RerankingStatus.CONSTRAINT_VIOLATION
    assert allowed.status == RerankingStatus.SUCCESS
    assert allowed.products[0].rating is None


def test_equal_price_boundary_is_trusted_after_successful_phase10_verification():
    equal_price = cand("p1", 1, price=1000)
    out = service({"p1": "product"}).rerank(q8(max_price=1000), q9(), result(equal_price))
    assert out.status == RerankingStatus.SUCCESS
    assert out.products[0].discounted_price == 1000


def test_foreign_currency_duplicate_ids_and_missing_product_text_fail_safely():
    foreign = service({"p1": "product"}).rerank(q8(currency="USD"), q9(), result(cand("p1", 1)))
    duplicate = service({"p1": "product"}).rerank(q8(), q9(), result(cand("p1", 1), cand("p1", 2)))
    missing_text = service({}).rerank(q8(), q9(), result(cand("p1", 1)))
    assert foreign.status == RerankingStatus.UNSUPPORTED_INTENT
    assert duplicate.status == RerankingStatus.INVALID_INPUT
    assert missing_text.status == RerankingStatus.RETRIEVAL_FAILURE


def test_cross_encoder_missing_is_explicit_model_unavailable():
    out = service({"p1": "product"}, method=RerankingMethod.CROSS_ENCODER).rerank(q8(), q9(), result(cand("p1", 1)))
    assert out.status == RerankingStatus.MODEL_UNAVAILABLE


def test_cross_encoder_adapter_handles_empty_pairs_without_model_call():
    scorer = FakeCrossEncoder([])
    assert CrossEncoderScorer(scorer).predict([], batch_size=16) == []
    assert scorer.pairs is None


def test_pinned_model_loader_passes_revision_device_and_offline_settings(monkeypatch):
    import sentence_transformers
    from shopassist.reranking import load_local_cross_encoder

    observed = {}

    class StubModel:
        device = "cpu"

    def factory(source, **kwargs):
        observed["source"] = source
        observed.update(kwargs)
        return StubModel()

    monkeypatch.setattr(sentence_transformers, "CrossEncoder", factory)
    scorer = load_local_cross_encoder("cross-encoder/ms-marco-MiniLM-L2-v2", model_path="local-model")
    assert observed["source"] == "local-model"
    assert observed["max_length"] == 512
    assert observed["device"] == "cpu"
    assert observed["automodel_args"]["revision"] == "1b5cd67b15209f24824c50370e0397743aa9b787"
    assert observed["automodel_args"]["local_files_only"] is True
    assert observed["tokenizer_args"] == observed["automodel_args"]
    assert scorer.revision == observed["automodel_args"]["revision"]


def test_pinned_model_loader_supports_current_sentence_transformers_signature(monkeypatch):
    import sentence_transformers
    from shopassist.reranking import load_local_cross_encoder

    observed = {}

    class StubModel:
        device = "cpu"

    def factory(source, *, max_length, device, revision, local_files_only):
        observed.update({"source": source, "max_length": max_length, "device": device, "revision": revision, "local_files_only": local_files_only})
        return StubModel()

    monkeypatch.setattr(sentence_transformers, "CrossEncoder", factory)
    load_local_cross_encoder()
    assert observed["revision"] == "1b5cd67b15209f24824c50370e0397743aa9b787"
    assert observed["local_files_only"] is True
    assert observed["max_length"] == 512


def test_token_length_uses_actual_model_tokenizer():
    class Tokenizer:
        def __call__(self, query, text, **kwargs):
            assert (query, text) == ("q", "product")
            assert kwargs["truncation"] is True
            assert kwargs["max_length"] == 7
            return {"input_ids": [1, 2, 3]}

    class Model:
        tokenizer = Tokenizer()

    assert CrossEncoderScorer(Model(), max_length=7).token_length("q", "product", truncation=True) == 3


def test_catalog_manifest_is_preserved_in_phase12_product_metadata():
    from shopassist.reranking import MappingProductTextProvider

    manifest = {"artifact_name": "products.parquet", "sha256": "abc", "product_count": 1}
    reranker = RerankingService(MappingProductTextProvider({"p1": "canonical"}, manifest=manifest))
    out = reranker.rerank(q8(), q9(), result(cand("p1", 1)))
    assert out.status == RerankingStatus.SUCCESS
    assert out.products[0].metadata["phase11_canonical_text_snapshot"] == manifest


def test_catalog_manifest_rejects_changed_snapshot():
    manifest = {"sha256": "expected", "product_count": 2, "canonical_text_count": 2}
    with pytest.raises(ValueError, match="does not match"):
        validate_catalog_manifest(manifest, sha256="actual", product_count=2, canonical_text_count=2)


def test_combined_mode_requires_explicit_development_validated_weights():
    out = service({"p1": "product"}, method=RerankingMethod.COMBINED, scorer=FakeCrossEncoder([0.4])).rerank(
        q8(), q9(), result(cand("p1", 1))
    )
    assert out.status == RerankingStatus.INVALID_INPUT

