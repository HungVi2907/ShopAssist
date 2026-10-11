"""Typed Phase 11 reranking over the fixed Phase 10 candidate set.

Phase 11 never queries the catalog.  It validates the Phase 10 result, obtains
canonical product text keyed by product_id, scores those candidates, and emits
a stable Top-K subset with original metadata and retrieval provenance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import inspect
import math
import time
from typing import Any, Mapping, Protocol, Sequence

from shopassist.llm.schemas import QueryUnderstandingResult
from shopassist.preferences.safety import find_unsafe_negative_preferences
from shopassist.preferences.schemas import PreferenceRepresentationResult, RepresentationStatus
from shopassist.preferences.normalization import normalize_preferences, normalize_semantic_query
from shopassist.preferences.query_composer import build_preference_query
from shopassist.retrieval.hybrid import CandidateSource, HybridCandidate, HybridRetrievalResult, HybridRetrievalStatus


class RerankingMethod(str, Enum):
    RRF = "RRF"
    MULTI_SIGNAL = "MULTI_SIGNAL"
    CROSS_ENCODER = "CROSS_ENCODER"
    COMBINED = "COMBINED"


class RerankingStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_RESULTS = "NO_RESULTS"
    INVALID_INPUT = "INVALID_INPUT"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    UNSUPPORTED_INTENT = "UNSUPPORTED_INTENT"
    EMBEDDING_FAILURE = "EMBEDDING_FAILURE"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_FAILURE = "MODEL_FAILURE"
    CONSTRAINT_VIOLATION = "CONSTRAINT_VIOLATION"


class ProductTextProvider(Protocol):
    def get(self, product_id: str) -> str | None: ...


class PairScorer(Protocol):
    def predict(self, pairs: Sequence[tuple[str, str]], *, batch_size: int) -> Any: ...


@dataclass(frozen=True)
class MappingProductTextProvider:
    """Canonical Phase 5.2 retrieval_text mapping indexed by stable product ID."""

    texts: Mapping[str, str]
    manifest: Mapping[str, Any] = field(default_factory=dict)

    def get(self, product_id: str) -> str | None:
        value = self.texts.get(str(product_id))
        return value if isinstance(value, str) and value.strip() else None


def validate_catalog_manifest(
    manifest: Mapping[str, Any], *, sha256: str, product_count: int, canonical_text_count: int
) -> None:
    """Fail closed when a local catalog differs from its declared Phase 11 snapshot."""
    expected = (manifest.get("sha256"), manifest.get("product_count"), manifest.get("canonical_text_count"))
    actual = (sha256, product_count, canonical_text_count)
    if expected != actual:
        raise ValueError("Canonical catalog artifact does not match the pinned Phase 11 manifest")


def load_canonical_product_texts(path: str, *, manifest_path: str | None = None) -> MappingProductTextProvider:
    """Load and fingerprint the local canonical catalog artifact; performs no DB IO."""
    import pandas as pd
    from pathlib import Path

    artifact = Path(path)
    frame = pd.read_parquet(artifact, columns=["product_id", "retrieval_text"])
    if frame["product_id"].isna().any() or frame["product_id"].astype(str).duplicated().any():
        raise ValueError("Canonical product text artifact has missing or duplicate product IDs")
    if frame["retrieval_text"].isna().any() or (frame["retrieval_text"].astype(str).str.strip() == "").any():
        raise ValueError("Canonical product text artifact has empty retrieval_text values")
    digest = hashlib.sha256()
    with artifact.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    texts = {str(row.product_id): str(row.retrieval_text) for row in frame.itertuples(index=False)}
    manifest: dict[str, Any] = {
        "artifact_name": artifact.name,
        "sha256": digest.hexdigest(),
        "product_count": len(texts),
        "unique_product_ids": len(texts),
        "canonical_text_count": len(texts),
    }
    expected_manifest_path = Path(manifest_path) if manifest_path else artifact.parent.parent / "interim/phase11/phase11_catalog_manifest.json"
    if expected_manifest_path.exists():
        import json

        expected = json.loads(expected_manifest_path.read_text(encoding="utf-8"))
        validate_catalog_manifest(
            expected,
            sha256=manifest["sha256"],
            product_count=manifest["product_count"],
            canonical_text_count=manifest["canonical_text_count"],
        )
        manifest["manifest_version"] = expected.get("manifest_version")
        manifest["snapshot_id"] = expected.get("snapshot_id")
    return MappingProductTextProvider(texts, manifest)


@dataclass(frozen=True)
class RerankingConfig:
    top_k: int = 5
    max_top_k: int = 20
    batch_size: int = 16
    model_name: str = "cross-encoder/ms-marco-MiniLM-L2-v2"
    model_revision: str = "1b5cd67b15209f24824c50370e0397743aa9b787"
    max_length: int = 512
    method: RerankingMethod = RerankingMethod.RRF
    cross_encoder_weight: float | None = None
    multi_signal_weight: float | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.top_k <= self.max_top_k:
            raise ValueError("top_k must be within [1, max_top_k]")
        if self.batch_size <= 0 or self.max_length <= 0 or self.max_length > 512:
            raise ValueError("batch_size and max_length must be positive")
        weights = (self.cross_encoder_weight, self.multi_signal_weight)
        if (weights[0] is None) != (weights[1] is None):
            raise ValueError("both combined method weights must be supplied together")
        if weights[0] is not None:
            if any(not math.isfinite(v) or v < 0 for v in weights if v is not None) or sum(weights) <= 0:
                raise ValueError("combined method weights must be finite, non-negative, and not both zero")


@dataclass
class RerankedProduct:
    product_id: str
    original_rank: int
    reranked_rank: int
    product_name: str
    retrieval_text: str
    category: str
    brand: str | None
    discounted_price: float
    rating: float | None
    rrf_score: float
    sources: dict[str, dict[str, float | int]]
    metadata: dict[str, Any]
    final_score: float
    score_components: dict[str, float] = field(default_factory=dict)


@dataclass
class RerankingResult:
    status: RerankingStatus
    method: str
    products: list[RerankedProduct] = field(default_factory=list)
    total_candidates: int = 0
    returned_count: int = 0
    model_name: str | None = None
    stage_latency_ms: dict[str, float] = field(default_factory=dict)
    applied_constraints: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    diagnostic_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "1.0.0",
            "status": self.status.value,
            "method": self.method,
            "products": [asdict(product) for product in self.products],
            "total_candidates": self.total_candidates,
            "returned_count": self.returned_count,
            "model_name": self.model_name,
            "stage_latency_ms": dict(self.stage_latency_ms),
            "applied_constraints": dict(self.applied_constraints),
            "warnings": list(self.warnings),
            "diagnostic_reason": self.diagnostic_reason,
        }


class RerankingService:
    """Rerank Phase 10's candidates without widening or re-fetching them."""

    def __init__(
        self,
        text_provider: ProductTextProvider,
        *,
        config: RerankingConfig | None = None,
        cross_encoder: PairScorer | None = None,
    ) -> None:
        self.text_provider = text_provider
        self.config = config or RerankingConfig()
        self.cross_encoder = cross_encoder

    def rerank(
        self,
        query_result: QueryUnderstandingResult,
        preference_result: PreferenceRepresentationResult,
        retrieval_result: HybridRetrievalResult,
        *,
        top_k: int | None = None,
        method: RerankingMethod | None = None,
    ) -> RerankingResult:
        started = time.perf_counter()
        selected_method = method or self.config.method
        k = self.config.top_k if top_k is None else top_k
        if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= self.config.max_top_k:
            return self._failure(RerankingStatus.INVALID_INPUT, selected_method, "top_k is out of range")
        if not isinstance(query_result, QueryUnderstandingResult) or not isinstance(
            preference_result, PreferenceRepresentationResult
        ) or not isinstance(retrieval_result, HybridRetrievalResult):
            return self._failure(RerankingStatus.INVALID_INPUT, selected_method, "Expected typed Phase 8, 9, and 10 results")
        status_map = {
            HybridRetrievalStatus.NO_RESULTS: RerankingStatus.NO_RESULTS,
            HybridRetrievalStatus.INVALID_INPUT: RerankingStatus.INVALID_INPUT,
            HybridRetrievalStatus.CLARIFICATION_REQUIRED: RerankingStatus.CLARIFICATION_REQUIRED,
            HybridRetrievalStatus.UNSUPPORTED_INTENT: RerankingStatus.UNSUPPORTED_INTENT,
            HybridRetrievalStatus.EMBEDDING_FAILURE: RerankingStatus.EMBEDDING_FAILURE,
            HybridRetrievalStatus.RETRIEVAL_FAILURE: RerankingStatus.RETRIEVAL_FAILURE,
        }
        if retrieval_result.status != HybridRetrievalStatus.SUCCESS:
            return self._failure(
                status_map.get(retrieval_result.status, RerankingStatus.RETRIEVAL_FAILURE),
                selected_method,
                "Phase 10 did not return a successful candidate set",
                candidates=len(retrieval_result.candidates),
            )
        if not query_result.is_valid:
            return self._failure(RerankingStatus.INVALID_INPUT, selected_method, "Phase 8 marked the query invalid")
        if query_result.output.needs_clarification or preference_result.status == RepresentationStatus.CLARIFICATION_REQUIRED:
            return self._failure(RerankingStatus.CLARIFICATION_REQUIRED, selected_method, "Input requires clarification")
        if (query_result.output.hard_constraints.currency or "INR").upper() != "INR":
            return self._failure(RerankingStatus.UNSUPPORTED_INTENT, selected_method, "Catalog prices are in INR")
        if find_unsafe_negative_preferences([query_result.query]):
            return self._failure(RerankingStatus.UNSUPPORTED_INTENT, selected_method, "Exclusion intent cannot be reranked safely")
        if preference_result.status not in (RepresentationStatus.SUCCESS, RepresentationStatus.NO_PREFERENCES):
            status = RerankingStatus.UNSUPPORTED_INTENT if preference_result.status == RepresentationStatus.UNSUPPORTED_INTENT else RerankingStatus.EMBEDDING_FAILURE
            if preference_result.status == RepresentationStatus.INVALID_INPUT:
                status = RerankingStatus.INVALID_INPUT
            return self._failure(status, selected_method, "Phase 9 did not provide a usable query representation")
        try:
            same_semantic_query = normalize_semantic_query(preference_result.semantic_query) == normalize_semantic_query(
                query_result.output.semantic_query
            )
            source_preferences = normalize_preferences(query_result.output.soft_preferences)
            represented_preferences = normalize_preferences(preference_result.normalized_preferences)
            expected_preference_query = build_preference_query(query_result.output.semantic_query, query_result.output.soft_preferences)
        except (TypeError, ValueError):
            return self._failure(RerankingStatus.INVALID_INPUT, selected_method, "Phase 8/9 contains invalid query or preference fields")
        if not same_semantic_query:
            return self._failure(RerankingStatus.INVALID_INPUT, selected_method, "Phase 8/9 semantic query mismatch")
        if preference_result.status == RepresentationStatus.SUCCESS and (
            not source_preferences
            or source_preferences != represented_preferences
            or preference_result.preference_query != expected_preference_query
            or not preference_result.has_preferences
        ):
            return self._failure(RerankingStatus.INVALID_INPUT, selected_method, "Phase 8/9 positive preference data do not match")
        if preference_result.status == RepresentationStatus.NO_PREFERENCES and (
            source_preferences
            or represented_preferences
            or preference_result.preference_query is not None
            or preference_result.has_preferences
            or preference_result.preference_embedding is not None
        ):
            return self._failure(RerankingStatus.INVALID_INPUT, selected_method, "Phase 9 no-preference status conflicts with Phase 8 data")

        candidates = retrieval_result.candidates
        if not candidates or any(not isinstance(c, HybridCandidate) for c in candidates) or len({c.product_id for c in candidates}) != len(candidates):
            return self._failure(RerankingStatus.INVALID_INPUT, selected_method, "Candidate set is empty or has duplicate product IDs", candidates=len(candidates))
        invalid_candidate_ids = [c.product_id for c in candidates if not _candidate_is_finite(c)]
        if invalid_candidate_ids:
            return self._failure(
                RerankingStatus.INVALID_INPUT,
                selected_method,
                "Candidate metadata contains invalid numerical values: " + ", ".join(invalid_candidate_ids),
                candidates=len(candidates),
                constraints=retrieval_result.applied_constraints,
            )
        violation_ids = [c.product_id for c in candidates if _candidate_violates(c, query_result)]
        if violation_ids:
            return self._failure(
                RerankingStatus.CONSTRAINT_VIOLATION,
                selected_method,
                "Phase 10 candidate metadata conflicts with a hard constraint: " + ", ".join(violation_ids),
                candidates=len(candidates),
                constraints=retrieval_result.applied_constraints,
            )

        text_started = time.perf_counter()
        texts: list[str] = []
        for candidate in candidates:
            text = self.text_provider.get(candidate.product_id)
            if not text:
                return self._failure(
                    RerankingStatus.RETRIEVAL_FAILURE,
                    selected_method,
                    f"Canonical product retrieval_text is missing for candidate {candidate.product_id}",
                    candidates=len(candidates),
                )
            texts.append(text)
        text_lookup_ms = round((time.perf_counter() - text_started) * 1000, 4)

        try:
            query_text = _positive_query(query_result, preference_result)
        except (TypeError, ValueError):
            return self._failure(RerankingStatus.INVALID_INPUT, selected_method, "Phase 9 query text is missing or invalid")
        branch_scores = [_multi_signal_scores(candidates), _rrf_scores(candidates)]
        components: list[dict[str, float]] = []
        model_name: str | None = None
        model_inference_ms = 0.0
        if selected_method in (RerankingMethod.CROSS_ENCODER, RerankingMethod.COMBINED):
            if self.cross_encoder is None:
                return self._failure(
                    RerankingStatus.MODEL_UNAVAILABLE,
                    selected_method,
                    "Cross-Encoder is not configured; no model was downloaded",
                    candidates=len(candidates),
                    model=self.config.model_name,
                )
            try:
                inference_started = time.perf_counter()
                raw = self.cross_encoder.predict(list(zip([query_text] * len(candidates), texts)), batch_size=self.config.batch_size)
                model_inference_ms = round((time.perf_counter() - inference_started) * 1000, 4)
                scores = _finite_scalar_scores(raw, len(candidates))
                encoder_scores = _minmax(scores)
                model_name = self.config.model_name
            except Exception as exc:
                return self._failure(
                    RerankingStatus.MODEL_FAILURE,
                    selected_method,
                    f"Cross-Encoder scoring failed ({type(exc).__name__})",
                    candidates=len(candidates),
                    model=self.config.model_name,
                )
            if selected_method == RerankingMethod.CROSS_ENCODER:
                components = [{"cross_encoder_raw": float(s), "cross_encoder_minmax": n} for s, n in zip(scores, encoder_scores)]
                final_scores = encoder_scores
            else:
                if self.config.cross_encoder_weight is None or self.config.multi_signal_weight is None:
                    return self._failure(
                        RerankingStatus.INVALID_INPUT,
                        selected_method,
                        "Combined scoring requires explicitly configured weights validated on development data",
                        candidates=len(candidates),
                        model=self.config.model_name,
                    )
                sw = self.config.cross_encoder_weight + self.config.multi_signal_weight
                cw = self.config.cross_encoder_weight / sw
                mw = self.config.multi_signal_weight / sw
                mscores = branch_scores[0]
                final_scores = [cw * cs + mw * ms for cs, ms in zip(encoder_scores, mscores)]
                components = [
                    {"cross_encoder_raw": float(raw_score), "cross_encoder_minmax": ce, "multi_signal_rank_utility": ms}
                    for raw_score, ce, ms in zip(scores, encoder_scores, mscores)
                ]
        elif selected_method == RerankingMethod.MULTI_SIGNAL:
            final_scores = branch_scores[0]
            components = [{"multi_signal_rank_utility": score} for score in final_scores]
        else:
            final_scores = branch_scores[1]
            components = [{"phase10_rrf_score": float(c.rrf_score)} for c in candidates]

        ordering_started = time.perf_counter()
        ordered = sorted(
            zip(candidates, final_scores, components),
            key=lambda item: (-item[1], item[0].rank, item[0].product_id),
        )[:k]
        candidate_texts = {candidate.product_id: text for candidate, text in zip(candidates, texts)}
        output = [
            _to_product(candidate, candidate_texts[candidate.product_id], score, component, position)
            for position, (candidate, score, component) in enumerate(ordered, start=1)
        ]
        catalog_manifest = getattr(self.text_provider, "manifest", {})
        if catalog_manifest:
            for product in output:
                product.metadata.setdefault("phase11_canonical_text_snapshot", dict(catalog_manifest))
        ordering_ms = round((time.perf_counter() - ordering_started) * 1000, 4)
        warnings = list(retrieval_result.warnings)
        if not catalog_manifest:
            warnings.append("Canonical text provider has no artifact checksum; Phase 10/local snapshot consistency is unverified.")
        if selected_method in (RerankingMethod.CROSS_ENCODER, RerankingMethod.COMBINED):
            warnings.append(
                f"Cross-Encoder truncates token pairs at max_length={self.config.max_length}; confirm important product fields survive with the pinned model tokenizer."
            )
        return RerankingResult(
            status=RerankingStatus.SUCCESS,
            method=selected_method.value,
            products=output,
            total_candidates=len(candidates),
            returned_count=len(output),
            model_name=model_name,
            stage_latency_ms={
                "canonical_text_lookup_ms": text_lookup_ms,
                "cross_encoder_inference_ms": model_inference_ms,
                "ordering_top_k_ms": ordering_ms,
                "reranking_ms": round((time.perf_counter() - started) * 1000, 4),
            },
            applied_constraints=dict(retrieval_result.applied_constraints),
            warnings=warnings,
        )

    @staticmethod
    def _failure(
        status: RerankingStatus,
        method: RerankingMethod,
        reason: str,
        *,
        candidates: int = 0,
        constraints: Mapping[str, Any] | None = None,
        model: str | None = None,
    ) -> RerankingResult:
        return RerankingResult(
            status=status,
            method=method.value,
            total_candidates=candidates,
            model_name=model,
            applied_constraints=dict(constraints or {}),
            diagnostic_reason=reason,
        )


def _positive_query(query: QueryUnderstandingResult, preferences: PreferenceRepresentationResult) -> str:
    if preferences.status == RepresentationStatus.SUCCESS:
        value = preferences.preference_query
        if not value or not value.strip():
            raise ValueError("Phase 9 success requires preference_query")
        return value.strip()
    return query.output.semantic_query.strip()


def _candidate_violates(candidate: HybridCandidate, query: QueryUnderstandingResult) -> bool:
    constraints = query.output.hard_constraints
    if constraints.category and candidate.category.strip().casefold() != constraints.category.strip().casefold():
        return True
    if constraints.brand and (candidate.brand is None or candidate.brand.strip().casefold() != constraints.brand.strip().casefold()):
        return True
    if constraints.min_rating is not None and (candidate.rating is None or candidate.rating < constraints.min_rating):
        return True
    # Phase 10's successful status is trusted for strict/inclusive equality;
    # inequalities outside the boundary are still independently detectable.
    if constraints.min_price is not None and candidate.discounted_price < constraints.min_price:
        return True
    if constraints.max_price is not None and candidate.discounted_price > constraints.max_price:
        return True
    return False


def _candidate_is_finite(candidate: HybridCandidate) -> bool:
    if (
        not isinstance(candidate.product_id, str)
        or not candidate.product_id.strip()
        or not isinstance(candidate.product_name, str)
        or not candidate.product_name.strip()
        or not isinstance(candidate.category, str)
        or not candidate.category.strip()
        or not isinstance(candidate.metadata, Mapping)
        or not isinstance(candidate.sources, Mapping)
        or not isinstance(candidate.rank, int)
        or isinstance(candidate.rank, bool)
        or candidate.rank <= 0
    ):
        return False
    if candidate.brand is not None and not isinstance(candidate.brand, str):
        return False
    numbers = [candidate.discounted_price, candidate.rrf_score]
    if candidate.rating is not None:
        numbers.append(candidate.rating)
    for source in candidate.sources.values():
        if not isinstance(source, CandidateSource):
            return False
        if not isinstance(source.rank, int) or isinstance(source.rank, bool) or source.rank <= 0:
            return False
        numbers.append(source.score)
    try:
        if not all(math.isfinite(float(value)) for value in numbers):
            return False
    except (TypeError, ValueError, OverflowError):
        return False
    if candidate.discounted_price < 0 or candidate.rrf_score < 0 or (candidate.rating is not None and not 1 <= candidate.rating <= 5):
        return False
    return True


def _rrf_scores(candidates: Sequence[HybridCandidate]) -> list[float]:
    return [float(candidate.rrf_score) for candidate in candidates]


def _multi_signal_scores(candidates: Sequence[HybridCandidate]) -> list[float]:
    """Mean normalized rank utility across dense and lexical branches.

    Missing branch evidence contributes zero; each branch receives equal weight.
    This is an untrained rank aggregation policy, not a tuned relevance model.
    """
    dense_max = max((source.rank for candidate in candidates if (source := candidate.sources.get("dense"))), default=1)
    lexical_max = max((source.rank for candidate in candidates if (source := candidate.sources.get("lexical"))), default=1)
    result: list[float] = []
    for candidate in candidates:
        utilities = []
        for key, max_rank in (("dense", dense_max), ("lexical", lexical_max)):
            source = candidate.sources.get(key)
            utilities.append((max_rank - source.rank + 1) / max_rank if source is not None else 0.0)
        result.append(sum(utilities) / 2.0)
    return result


def _finite_scalar_scores(raw: Any, expected_count: int) -> list[float]:
    import numpy as np

    arr = np.asarray(raw, dtype=np.float64)
    if arr.ndim == 2 and arr.shape[1] == 1:
        arr = arr[:, 0]
    if arr.ndim != 1 or arr.shape[0] != expected_count or not np.isfinite(arr).all():
        raise ValueError("Cross-Encoder returned invalid scores")
    return [float(value) for value in arr]


def _minmax(scores: Sequence[float]) -> list[float]:
    low, high = min(scores), max(scores)
    if math.isclose(low, high, rel_tol=1e-12, abs_tol=1e-12):
        return [0.5] * len(scores)
    return [(value - low) / (high - low) for value in scores]


def _to_product(candidate: HybridCandidate, retrieval_text: str, score: float, components: dict[str, float], rank: int) -> RerankedProduct:
    sources = {
        name: {"rank": source.rank, "score": float(source.score)}
        for name, source in candidate.sources.items()
    }
    return RerankedProduct(
        product_id=candidate.product_id,
        original_rank=candidate.rank,
        reranked_rank=rank,
        product_name=candidate.product_name,
        retrieval_text=retrieval_text,
        category=candidate.category,
        brand=candidate.brand,
        discounted_price=float(candidate.discounted_price),
        rating=candidate.rating,
        rrf_score=float(candidate.rrf_score),
        sources=sources,
        metadata=dict(candidate.metadata),
        final_score=float(score),
        score_components=components,
    )


def load_local_cross_encoder(
    model_name: str = "cross-encoder/ms-marco-MiniLM-L2-v2",
    *,
    max_length: int = 512,
    revision: str = "1b5cd67b15209f24824c50370e0397743aa9b787",
    model_path: str | None = None,
    device: str = "cpu",
    local_files_only: bool = True,
) -> CrossEncoderScorer:
    """Load one pinned model revision; offline/local loading is the safe default."""
    from sentence_transformers import CrossEncoder

    source = model_path or model_name
    constructor_params = inspect.signature(CrossEncoder).parameters
    load_options: dict[str, Any]
    if "revision" in constructor_params and "local_files_only" in constructor_params:
        load_options = {"revision": revision, "local_files_only": local_files_only}
    else:
        # Sentence Transformers 3.x forwards these legacy dictionaries to
        # AutoModel/AutoTokenizer; newer releases expose both options directly.
        load_options = {
            "automodel_args": {"revision": revision, "local_files_only": local_files_only},
            "tokenizer_args": {"revision": revision, "local_files_only": local_files_only},
        }
    model = CrossEncoder(source, max_length=max_length, device=device, **load_options)
    return CrossEncoderScorer(model, model_name=model_name, revision=revision, max_length=max_length, device=device)


class CrossEncoderScorer:
    """Small adapter that exposes batched pair scoring for Sentence Transformers."""

    def __init__(
        self,
        model: Any,
        *,
        model_name: str | None = None,
        revision: str | None = None,
        max_length: int | None = None,
        device: str | None = None,
    ):
        self.model = model
        self.model_name = model_name or getattr(model, "model_name_or_path", model.__class__.__name__)
        self.revision = revision
        self.max_length = max_length
        self.device = device or str(getattr(model, "device", "cpu"))

    def predict(self, pairs: Sequence[tuple[str, str]], *, batch_size: int) -> Any:
        if not pairs:
            return []
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        return self.model.predict(list(pairs), batch_size=batch_size, show_progress_bar=False)

    def token_length(self, query: str, text: str, *, truncation: bool = False) -> int:
        """Count pair tokens with this model's actual tokenizer and truncation policy."""
        tokenizer = getattr(self.model, "tokenizer", None) or getattr(self.model, "processor", None)
        if tokenizer is None:
            raise RuntimeError("Loaded Cross-Encoder does not expose its tokenizer")
        encoded = tokenizer(
            query,
            text,
            truncation=truncation,
            max_length=self.max_length if truncation else None,
            add_special_tokens=True,
        )
        return len(encoded["input_ids"])
