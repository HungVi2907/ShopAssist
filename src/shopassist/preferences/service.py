"""Phase 9 orchestration over accepted Phase 8 v1 outputs."""

from __future__ import annotations

import logging
from typing import Sequence

from pydantic import ValidationError

from shopassist.llm.schemas import QueryUnderstandingResult
from shopassist.preferences.embedding import PreferenceQueryEncoder
from shopassist.preferences.normalization import (
    PreferenceInputError,
    normalize_preferences,
    normalize_semantic_query,
)
from shopassist.preferences.query_composer import build_preference_query
from shopassist.preferences.safety import find_unsafe_negative_preferences
from shopassist.preferences.schemas import (
    PreferenceRepresentationResult,
    RepresentationStatus,
)

logger = logging.getLogger(__name__)


class PreferenceRepresentationService:
    """Represent accepted v1 soft preferences without calling an LLM or database."""

    def __init__(self, encoder: PreferenceQueryEncoder | None = None) -> None:
        self.encoder = encoder

    def _get_encoder(self) -> PreferenceQueryEncoder:
        if self.encoder is None:
            self.encoder = PreferenceQueryEncoder()
        return self.encoder

    def represent(self, query_result: QueryUnderstandingResult) -> PreferenceRepresentationResult:
        if not isinstance(query_result, QueryUnderstandingResult):
            return PreferenceRepresentationResult(
                semantic_query="",
                has_preferences=False,
                status=RepresentationStatus.INVALID_INPUT,
                diagnostic_reason="Expected a Phase 8 QueryUnderstandingResult",
            )
        try:
            result = QueryUnderstandingResult.model_validate(query_result.model_dump())
            semantic_query = normalize_semantic_query(result.output.semantic_query)
            preferences = normalize_preferences(result.output.soft_preferences)
        except (ValidationError, PreferenceInputError, TypeError, ValueError) as exc:
            return PreferenceRepresentationResult(
                semantic_query="",
                has_preferences=False,
                status=RepresentationStatus.INVALID_INPUT,
                diagnostic_reason=str(exc),
            )

        if not result.is_valid:
            return self._stopped(
                semantic_query,
                preferences,
                RepresentationStatus.INVALID_INPUT,
                "Phase 8 marked the query invalid",
            )
        if result.output.needs_clarification:
            return self._stopped(
                semantic_query,
                preferences,
                RepresentationStatus.CLARIFICATION_REQUIRED,
                result.output.clarification_reason or "Phase 8 requires clarification",
            )
        currency = (result.output.hard_constraints.currency or "INR").upper()
        if currency != "INR":
            return self._stopped(
                semantic_query,
                preferences,
                RepresentationStatus.UNSUPPORTED_INTENT,
                f"Catalog prices use INR; query currency {currency} requires clarification",
            )

        unsafe = find_unsafe_negative_preferences(preferences)
        if unsafe:
            return self._stopped(
                semantic_query,
                preferences,
                RepresentationStatus.UNSUPPORTED_INTENT,
                "Negative or exclusion semantics cannot safely be encoded as positive preferences: "
                + ", ".join(unsafe),
            )

        if not preferences:
            return PreferenceRepresentationResult(
                semantic_query=semantic_query,
                normalized_preferences=[],
                preference_query=None,
                preference_embedding=None,
                embedding_model=None,
                embedding_dimension=None,
                has_preferences=False,
                status=RepresentationStatus.NO_PREFERENCES,
                warnings=["No preference vector was generated; use Phase 7 for base-query encoding."],
            )

        preference_query = build_preference_query(semantic_query, preferences)
        try:
            encoder = self._get_encoder()
            encoder.validate_model_compatibility()
            vector = encoder.encode(preference_query)
            return PreferenceRepresentationResult(
                semantic_query=semantic_query,
                normalized_preferences=preferences,
                preference_query=preference_query,
                preference_embedding=vector,
                embedding_model=encoder.model_name,
                embedding_dimension=encoder.embedding_dimension,
                has_preferences=True,
                status=RepresentationStatus.SUCCESS,
            )
        except Exception as exc:  # model load/runtime errors become explicit result states
            logger.warning("Phase 9 embedding failed: %s", type(exc).__name__)
            return self._stopped(
                semantic_query,
                preferences,
                RepresentationStatus.EMBEDDING_FAILURE,
                f"Embedding failed ({type(exc).__name__})",
                preference_query=preference_query,
            )

    def represent_batch(self, query_results: Sequence[QueryUnderstandingResult]) -> list[PreferenceRepresentationResult]:
        """Explicit batch interface; representation statuses remain per-query."""
        return [self.represent(item) for item in query_results]

    @staticmethod
    def _stopped(
        semantic_query: str,
        preferences: list[str],
        status: RepresentationStatus,
        reason: str,
        preference_query: str | None = None,
    ) -> PreferenceRepresentationResult:
        return PreferenceRepresentationResult(
            semantic_query=semantic_query,
            normalized_preferences=preferences,
            preference_query=preference_query,
            preference_embedding=None,
            embedding_model=None,
            embedding_dimension=None,
            has_preferences=bool(preferences),
            status=status,
            diagnostic_reason=reason,
        )
