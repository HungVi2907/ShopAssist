"""Public Pydantic v2 data contracts and schemas for ShopAssist REST API (Phase 15)."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecommendationRequest(BaseModel):
    """Primary request payload for product recommendation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Natural language user shopping query in English or Vietnamese.",
        examples=["Puma running shoes under 3000 INR", "tai nghe chống ồn dưới 2000 INR pin trâu"],
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of recommendations to return (1 to 20).",
        examples=[5],
    )
    language: str = Field(
        default="auto",
        description="Preferred response language ('auto', 'en', 'vi').",
        examples=["en", "vi", "auto"],
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session or chat identifier for conversation continuity.",
        examples=["session-12345-telegram"],
    )

    @field_validator("query")
    @classmethod
    def validate_non_empty_query(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Query cannot be empty or whitespace-only.")
        return clean

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in {"auto", "en", "vi"}:
            raise ValueError("Language must be one of 'auto', 'en', 'vi'.")
        return clean


class ProductClaimItem(BaseModel):
    """Factual claim or caveat supported by evidence IDs."""

    model_config = ConfigDict(extra="ignore")

    claim: str = Field(description="Factual claim describing product strength, limitation, or caveat.")
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="List of verified evidence IDs supporting this claim.",
    )


class ProductEvidenceItem(BaseModel):
    """Verifiable piece of evidence extracted from catalog attributes."""

    model_config = ConfigDict(extra="ignore")

    evidence_id: str = Field(description="Unique identifier for the evidence item, e.g. 'P001-E1'.")
    source_field: str = Field(description="Catalog field origin, e.g. 'product_name', 'specifications'.")
    text: str = Field(description="Exact snippet or factual value from the catalog.")


class ProductResponseItem(BaseModel):
    """Grounded product recommendation item in public API response."""

    model_config = ConfigDict(extra="ignore")

    product_id: str = Field(description="Authoritative catalog product ID.")
    product_name: str = Field(description="Canonical product name.")
    brand: str | None = Field(default=None, description="Product brand name.")
    category: str = Field(description="Catalog product category.")
    discounted_price: float = Field(description="Discounted catalog price in INR.")
    currency: str = Field(default="INR", description="Price currency (INR).")
    rating: float | None = Field(default=None, description="Product rating (1.0 to 5.0 scale) or null.")
    summary_reason: str = Field(description="Evidence-grounded rationale explaining why this product matches the query.")
    strengths: list[ProductClaimItem] = Field(default_factory=list, description="Verified product strengths with citations.")
    limitations: list[ProductClaimItem] = Field(default_factory=list, description="Product limitations or caveats.")
    comparison_note: str | None = Field(default=None, description="Comparative note against other candidates.")
    available_evidence: list[ProductEvidenceItem] = Field(default_factory=list, description="Verifiable catalog evidence items.")
    product_url: str | None = Field(default=None, description="Authoritative catalog product link or null.")
    image: str | None = Field(default=None, description="Primary product image URL or null.")


class RecommendationMetadata(BaseModel):
    """Execution metadata and provenance."""

    model_config = ConfigDict(extra="ignore")

    recommended_count: int = Field(default=0, description="Number of products returned in response.")
    retrieval_method: str = Field(default="HYBRID_RRF", description="Candidate retrieval strategy used.")
    reranking_method: str = Field(default="RRF", description="Reranking method used.")
    fallback_used: bool = Field(default=False, description="True if deterministic fallback was activated due to LLM provider limits.")
    session_id: str | None = Field(default=None, description="Session ID if provided in request.")
    applied_constraints: dict[str, Any] = Field(default_factory=dict, description="Hard constraints extracted and satisfied.")


class RecommendationUsage(BaseModel):
    """Observability metrics for latency and token consumption."""

    model_config = ConfigDict(extra="ignore")

    total_tokens: int = Field(default=0, description="Total LLM tokens consumed across phases.")
    prompt_tokens: int = Field(default=0, description="Prompt tokens consumed.")
    completion_tokens: int = Field(default=0, description="Completion tokens generated.")
    estimated_cost_usd: float = Field(default=0.0, description="Estimated LLM API cost in USD.")
    total_latency_ms: float = Field(default=0.0, description="Total end-to-end request latency in milliseconds.")
    stage_latencies_ms: dict[str, float] = Field(default_factory=dict, description="Per-stage latency breakdown in ms.")


class RecommendationResponse(BaseModel):
    """Structured public response for POST /api/v1/recommend."""

    model_config = ConfigDict(extra="ignore")

    request_id: str = Field(description="Unique request tracing ID.")
    status: str = Field(description="Public business status: SUCCESS, NO_RESULTS, CLARIFICATION_REQUIRED, UNSUPPORTED_INTENT, DETERMINISTIC_FALLBACK, INVALID_INPUT, etc.")
    overview: str = Field(description="Natural language summary introducing the recommendations or explaining the status.")
    products: list[ProductResponseItem] = Field(default_factory=list, description="List of grounded product recommendations.")
    metadata: RecommendationMetadata = Field(default_factory=RecommendationMetadata, description="Recommendation pipeline metadata.")
    usage: RecommendationUsage = Field(default_factory=RecommendationUsage, description="Usage and latency telemetry.")


class HealthResponse(BaseModel):
    """Readiness and health status response for GET /api/v1/health."""

    status: str = Field(description="Overall application health status ('healthy', 'degraded', 'unhealthy').")
    components: dict[str, str] = Field(description="Component-level readiness and configuration indicators.")
    timestamp: str = Field(description="ISO 8601 UTC timestamp of health check.")


class LivenessResponse(BaseModel):
    """Lightweight liveness probe response for GET /api/v1/health/live."""

    status: str = Field(default="alive", description="Process liveness state.")
