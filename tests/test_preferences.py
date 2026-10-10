"""Offline tests for Phase 9 preference representation."""

from __future__ import annotations

import math

import numpy as np
import pytest

from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput, QueryUnderstandingResult
from shopassist.preferences.embedding import validate_preference_vector
from shopassist.preferences.embedding import PreferenceQueryEncoder
from shopassist.preferences.normalization import (
    PreferenceInputError,
    normalize_preferences,
    normalize_semantic_query,
)
from shopassist.preferences.query_composer import build_preference_query
from shopassist.preferences.safety import find_unsafe_negative_preferences
from shopassist.preferences.schemas import RepresentationStatus
from shopassist.preferences.service import PreferenceRepresentationService


class FakeEncoder:
    model_name = "BAAI/bge-small-en-v1.5"
    embedding_dimension = 384

    def __init__(self) -> None:
        self.queries: list[str] = []

    def validate_model_compatibility(self) -> None:
        assert self.model_name == "BAAI/bge-small-en-v1.5"
        assert self.embedding_dimension == 384

    def encode(self, query: str) -> list[float]:
        self.queries.append(query)
        vector = np.zeros(384, dtype=np.float32)
        vector[0] = 1
        return vector.tolist()


def make_result(
    preferences: list[str],
    *,
    valid: bool = True,
    clarification: bool = False,
    reason: str | None = None,
    currency: str = "INR",
) -> QueryUnderstandingResult:
    return QueryUnderstandingResult(
        query="find a product",
        output=QueryUnderstandingOutput(
            semantic_query="running shoes",
            hard_constraints=HardConstraints(currency=currency),
            soft_preferences=preferences,
            needs_clarification=clarification,
            clarification_reason=reason,
        ),
        is_valid=valid,
    )


def test_normalization_trims_casefolds_collapses_space_and_stably_deduplicates() -> None:
    assert normalize_preferences(
        [" Lightweight ", "good   battery life", "LIGHTWEIGHT", "  comfortable  ", ""]
    ) == ["lightweight", "good battery life", "comfortable"]


def test_normalization_preserves_unicode_and_meaningful_phrases() -> None:
    assert normalize_preferences(["café-ready", "for daily jogging", "not too heavy"]) == [
        "café-ready",
        "for daily jogging",
        "not too heavy",
    ]


@pytest.mark.parametrize("value", [None, "lightweight", ["ok", 4]])
def test_normalization_rejects_invalid_container_or_item(value: object) -> None:
    with pytest.raises(PreferenceInputError):
        normalize_preferences(value)


def test_normalization_enforces_count_and_length_limits() -> None:
    with pytest.raises(PreferenceInputError):
        normalize_preferences(["x"] * 11)
    with pytest.raises(PreferenceInputError):
        normalize_preferences(["x" * 201])


def test_semantic_query_validation() -> None:
    assert normalize_semantic_query("  wireless   keyboard ") == "wireless keyboard"
    with pytest.raises(PreferenceInputError):
        normalize_semantic_query("  ")


def test_composer_keeps_context_all_phrases_and_is_deterministic() -> None:
    prefs = ["comfortable", "breathable", "for daily jogging"]
    first = build_preference_query("running shoes", prefs)
    assert first == "comfortable; breathable; for daily jogging — running shoes"
    assert build_preference_query("running shoes", prefs) == first
    assert all(phrase in first for phrase in prefs)


def test_composer_returns_none_for_empty_preferences() -> None:
    assert build_preference_query("Nike running shoes", []) is None


def test_negative_guard_catches_exclusion_and_preserves_safe_phrasing() -> None:
    assert find_unsafe_negative_preferences(
        ["without leather", "anything except Nike", "not running", "avoid Nike", "no leather"]
    ) == ["without leather", "anything except Nike", "not running", "avoid Nike", "no leather"]
    assert find_unsafe_negative_preferences(["not only running shoes", "not too heavy"]) == []


def test_vector_validation_checks_shape_finiteness_norm_and_serialization() -> None:
    vector = np.zeros(384, dtype=np.float32)
    vector[0] = 1
    serialized = validate_preference_vector(vector)
    assert len(serialized) == 384 and all(math.isfinite(x) for x in serialized)
    with pytest.raises(ValueError):
        validate_preference_vector(np.zeros(383, dtype=np.float32))
    vector[0] = np.nan
    with pytest.raises(ValueError):
        validate_preference_vector(vector)
    with pytest.raises(ValueError):
        validate_preference_vector(np.zeros(384, dtype=np.float32))
    with pytest.raises(ValueError):
        validate_preference_vector(np.ones(384, dtype=np.float32))


def test_phase7_adapter_batch_uses_shared_query_convention() -> None:
    class Config:
        model_name = "BAAI/bge-small-en-v1.5"
        embedding_dim = 384
        query_instruction = "query instruction: "
        normalize_embeddings = True

    class SharedEmbeddingModel:
        device = "cpu"

        def __init__(self) -> None:
            self.calls: list[tuple[list[str], dict]] = []

        def encode_queries(self, queries: list[str], **kwargs: object) -> np.ndarray:
            self.calls.append((queries, kwargs))
            vectors = np.zeros((len(queries), 384), dtype=np.float32)
            vectors[:, 0] = 1
            return vectors

    class DenseEncoder:
        config = Config()

        def __init__(self) -> None:
            self.model = SharedEmbeddingModel()

    dense = DenseEncoder()
    adapter = PreferenceQueryEncoder(dense)  # type: ignore[arg-type]
    batch = adapter.encode_batch(["one", "two"], batch_size=2)
    assert len(batch) == 2 and all(len(row) == 384 for row in batch)
    assert dense.model.calls[0][0] == ["one", "two"]
    assert dense.model.calls[0][1]["instruction"] == "query instruction: "
    assert dense.model.calls[0][1]["batch_size"] == 2


def test_v1_integration_uses_injected_phase7_encoder_without_mutating_input() -> None:
    encoder = FakeEncoder()
    service = PreferenceRepresentationService(encoder=encoder)  # type: ignore[arg-type]
    source = make_result([" comfortable ", "breathable"])
    before = source.model_dump()
    represented = service.represent(source)
    assert represented.status is RepresentationStatus.SUCCESS
    assert represented.preference_query == "comfortable; breathable — running shoes"
    assert represented.embedding_model == "BAAI/bge-small-en-v1.5"
    assert represented.embedding_dimension == 384
    assert len(represented.preference_embedding or []) == 384
    serialized = represented.model_dump_json()
    restored = type(represented).model_validate_json(serialized)
    assert restored.status is RepresentationStatus.SUCCESS
    assert restored.preference_embedding == represented.preference_embedding
    assert source.model_dump() == before
    assert encoder.queries == [represented.preference_query]


def test_no_preferences_does_not_encode_empty_or_general_query_as_preference() -> None:
    encoder = FakeEncoder()
    represented = PreferenceRepresentationService(encoder=encoder).represent(make_result([]))  # type: ignore[arg-type]
    assert represented.status is RepresentationStatus.NO_PREFERENCES
    assert represented.preference_query is None
    assert represented.preference_embedding is None
    assert represented.semantic_query == "running shoes"
    assert encoder.queries == []


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"valid": False}, RepresentationStatus.INVALID_INPUT),
        ({"clarification": True, "reason": "unsupported item"}, RepresentationStatus.CLARIFICATION_REQUIRED),
        ({"currency": "USD"}, RepresentationStatus.UNSUPPORTED_INTENT),
    ],
)
def test_unsafe_phase8_states_stop_before_embedding(kwargs: dict, expected: RepresentationStatus) -> None:
    encoder = FakeEncoder()
    result = PreferenceRepresentationService(encoder=encoder).represent(  # type: ignore[arg-type]
        make_result(["durable"], **kwargs)
    )
    assert result.status is expected
    assert result.preference_embedding is None
    assert encoder.queries == []


@pytest.mark.parametrize("negative", ["not running", "without leather", "anything except Nike", "no less than 2000"])
def test_negative_preferences_never_reach_encoder(negative: str) -> None:
    encoder = FakeEncoder()
    result = PreferenceRepresentationService(encoder=encoder).represent(  # type: ignore[arg-type]
        make_result([negative])
    )
    assert result.status is RepresentationStatus.UNSUPPORTED_INTENT
    assert result.preference_embedding is None
    assert encoder.queries == []


def test_embedding_errors_return_explicit_status_without_sensitive_exception_text() -> None:
    class FailingEncoder(FakeEncoder):
        def encode(self, query: str) -> list[float]:
            raise RuntimeError("private provider details")

    represented = PreferenceRepresentationService(encoder=FailingEncoder()).represent(make_result(["durable"]))  # type: ignore[arg-type]
    assert represented.status is RepresentationStatus.EMBEDDING_FAILURE
    assert represented.diagnostic_reason == "Embedding failed (RuntimeError)"
    assert "private provider details" not in (represented.diagnostic_reason or "")
