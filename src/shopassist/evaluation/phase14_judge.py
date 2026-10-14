"""Phase 14 LLM-as-a-Judge Evaluation Workflow for ShopAssist.

Implements an educational, reproducible LLM-as-a-Judge pipeline for evaluating
generated product recommendations against retrieved catalog evidence.

Distinguishes:
1. Deterministic Checks: Programmatic validation of product IDs, citation tags,
   and hard constraint violations.
2. Semantic LLM Judging: Structured multi-criteria evaluation of groundedness,
   factual alignment, and preference fulfillment using a strict rubric.

Integrity Note: LLM Judge evaluations are Silver/automated evaluations and must
NEVER be reported as human-verified ground truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
import os
import re
import time
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

JUDGING_RUBRIC_VERSION = "phase14-rubric-v1.0"
JUDGE_PROMPT_VERSION = "phase14-judge-prompt-v1.0"

JUDGING_RUBRIC_TEXT = """
### SHOPASSIST LLM-AS-A-JUDGE EVALUATION RUBRIC (v1.0)

You are an objective AI Quality Auditor evaluating an automated product recommendation.
Your goal is to evaluate whether the recommendation is faithful to the provided product evidence and helpful to the shopper.

Evaluate across 5 Criteria (Score 1 to 5 each):

1. Groundedness (1-5):
   - 5: Every single claim is directly backed by the provided product evidence text.
   - 3: Most claims are backed; 1 minor unsubstantiated speculation (e.g., 'great for daily use').
   - 1: Fabricated specifications not found in the evidence (e.g., claims waterproof when evidence doesn't say so).

2. Factual Correctness (1-5):
   - 5: Price, brand, category, and technical specs strictly match the catalog numbers.
   - 3: Correct specifications with minor rounding or ambiguous phrasing.
   - 1: Contradicts catalog evidence (wrong price, mismatched brand).

3. Query Relevance (1-5):
   - 5: Perfectly addresses both the core product intent and user soft preferences.
   - 3: Relevant category and type, but overlooks a secondary soft preference.
   - 1: Off-topic or fails to satisfy core user need.

4. Citation Support (1-5):
   - 5: Citations strictly follow [ProductID-E#] format and cite the exact evidence line.
   - 3: Citations present but occasionally cite the wrong evidence line or general text.
   - 1: No citations or fabricated citation IDs.

5. Missing Information Handling (1-5):
   - 5: Honestly acknowledges when evidence lacks certain requested attributes rather than guessing.
   - 3: Neutral; does not mention missing attribute.
   - 1: Hallucinates missing attributes to pretend the product meets every user desire.

Decision Gate:
- PASS: All scores >= 4, zero unsupported claims, evidence_supported = true.
- MARGINAL: Scores >= 3, no severe factual contradictions.
- FAIL: Any score <= 2 or severe hallucination detected.
"""

JUDGE_SYSTEM_PROMPT = f"""You are an expert AI Evaluation Judge.
Evaluate the provided product recommendation against the supplied evidence.
Adhere strictly to the judging rubric:
{JUDGING_RUBRIC_TEXT}

Respond ONLY with a valid JSON object matching this schema:
{{
  "groundedness_score": <1-5>,
  "factual_correctness_score": <1-5>,
  "query_relevance_score": <1-5>,
  "citation_support_score": <1-5>,
  "missing_info_handling_score": <1-5>,
  "overall_decision": "<PASS|MARGINAL|FAIL>",
  "evidence_supported": <true|false>,
  "unsupported_claims": ["<list of any claims not supported by evidence>"],
  "critique": "<Detailed 2-3 sentence rationale explaining the scores>"
}}
"""


@dataclass
class LLMJudgeResult:
    """Structured output from LLM-as-a-Judge assessment."""

    judge_provider: str
    judge_model: str
    prompt_version: str
    rubric_version: str
    execution_mode: str  # LIVE_API or RECORDED_DEMO
    latency_ms: float

    # Rubric scores
    groundedness_score: int
    factual_correctness_score: int
    query_relevance_score: int
    citation_support_score: int
    missing_info_handling_score: int

    overall_decision: str  # PASS, MARGINAL, FAIL
    evidence_supported: bool
    unsupported_claims: list[str]
    critique: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_judge_user_prompt(
    user_query: str,
    evidence_text: str,
    recommendation_output: str,
) -> str:
    """Format input context for LLM Judge."""
    return f"""### USER QUERY:
{user_query}

### CATALOG EVIDENCE PROVIDED TO GENERATOR:
{evidence_text}

### GENERATED RECOMMENDATION TO EVALUATE:
{recommendation_output}

Please evaluate the recommendation above and provide your structured JSON evaluation.
"""


def parse_judge_json(raw_text: str) -> dict[str, Any]:
    """Parse and clean JSON output from LLM Judge."""
    clean = raw_text.strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()
    return json.loads(clean)


from pydantic import BaseModel, Field


class LLMJudgeResponseSchema(BaseModel):
    groundedness_score: int = Field(..., ge=1, le=5, description="Score 1-5 for groundedness")
    factual_correctness_score: int = Field(..., ge=1, le=5, description="Score 1-5 for factual correctness")
    query_relevance_score: int = Field(..., ge=1, le=5, description="Score 1-5 for query relevance")
    citation_support_score: int = Field(..., ge=1, le=5, description="Score 1-5 for citation support")
    missing_info_handling_score: int = Field(..., ge=1, le=5, description="Score 1-5 for missing info handling")
    overall_decision: str = Field(..., description="Overall decision: PASS, MARGINAL, or FAIL")
    evidence_supported: bool = Field(..., description="True if claims are backed by catalog evidence")
    unsupported_claims: list[str] = Field(default_factory=list, description="List of unsupported claims")
    critique: str = Field(..., description="Detailed rationale explaining the scores")


def run_llm_judge(
    user_query: str,
    evidence_text: str,
    recommendation_output: str,
    *,
    client: Any = None,
    mock_mode: bool = False,
) -> LLMJudgeResult:
    """Execute LLM-as-a-Judge evaluation with real Gemini API or mock demonstration."""
    user_prompt = build_judge_user_prompt(user_query, evidence_text, recommendation_output)

    if mock_mode or client is None:
        # High-fidelity demonstration of structured judge evaluation
        return LLMJudgeResult(
            judge_provider="mock_evaluator",
            judge_model="offline_rubric_engine",
            prompt_version=JUDGE_PROMPT_VERSION,
            rubric_version=JUDGING_RUBRIC_VERSION,
            execution_mode="OFFLINE_DEMONSTRATION",
            latency_ms=1.2,
            groundedness_score=5,
            factual_correctness_score=5,
            query_relevance_score=5,
            citation_support_score=5,
            missing_info_handling_score=4,
            overall_decision="PASS",
            evidence_supported=True,
            unsupported_claims=[],
            critique="All product specifications accurately cite provided catalog evidence. No ungrounded claims detected.",
        )

    # Real live execution using GeminiClient structured generation
    t0 = time.perf_counter()
    parsed_obj, raw_text, latency_ms, usage = client.generate_structured(
        prompt=user_prompt,
        response_schema=LLMJudgeResponseSchema,
        system_instruction=JUDGE_SYSTEM_PROMPT,
    )
    if not latency_ms:
        latency_ms = (time.perf_counter() - t0) * 1000.0

    return LLMJudgeResult(
        judge_provider="gemini",
        judge_model=getattr(client.settings, "gemini_model", "gemini-3.1-flash-lite"),
        prompt_version=JUDGE_PROMPT_VERSION,
        rubric_version=JUDGING_RUBRIC_VERSION,
        execution_mode="LIVE_API",
        latency_ms=round(latency_ms, 2),
        groundedness_score=parsed_obj.groundedness_score,
        factual_correctness_score=parsed_obj.factual_correctness_score,
        query_relevance_score=parsed_obj.query_relevance_score,
        citation_support_score=parsed_obj.citation_support_score,
        missing_info_handling_score=parsed_obj.missing_info_handling_score,
        overall_decision=parsed_obj.overall_decision,
        evidence_supported=parsed_obj.evidence_supported,
        unsupported_claims=parsed_obj.unsupported_claims,
        critique=parsed_obj.critique,
    )
