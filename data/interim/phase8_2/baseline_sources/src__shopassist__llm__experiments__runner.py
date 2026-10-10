"""Experiment runner with quota budget controls, persistent caching, and metrics aggregation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Sequence

from shopassist.core.config import PROJECT_ROOT
from shopassist.llm.config import LLMSettings, llm_settings
from shopassist.llm.experiments.metrics import compute_experiment_metrics, evaluate_refined_case
from shopassist.llm.experiments.registry import ExperimentConfig
from shopassist.llm.gemini_client import GeminiClient
from shopassist.llm.prompt_variants import get_prompt_by_variant
from shopassist.llm.prompts import build_user_prompt
from shopassist.llm.refinement_rules import (
    apply_rule_based_refinement_v1,
    apply_rule_based_refinement_v2,
)
from shopassist.llm.schema_variants import RefinedQueryUnderstandingOutput
from shopassist.llm.schemas import QueryUnderstandingOutput, TokenUsageMetadata

logger = logging.getLogger(__name__)

CACHE_PATH = PROJECT_ROOT / "data" / "interim" / "phase8_1" / "gemini_response_cache.json"


class ExperimentRunner:
    """Production experiment runner enforcing API quota and reproducibility guarantees."""

    def __init__(
        self,
        settings: LLMSettings | None = None,
        max_requests: int = 200,
        max_tokens: int = 300_000,
        pacing_delay_sec: float = 0.5,
        cache_path: Path | str = CACHE_PATH,
    ) -> None:
        self.settings = settings or llm_settings
        self.max_requests = max_requests
        self.max_tokens = max_tokens
        self.pacing_delay_sec = pacing_delay_sec
        self.cache_path = Path(cache_path).resolve()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        self._client: GeminiClient | None = None
        self._cache: dict[str, Any] = self._load_cache()
        self.requests_made = 0
        self.tokens_consumed = 0

    @property
    def client(self) -> GeminiClient:
        if self._client is None:
            self._client = GeminiClient(settings=self.settings)
        return self._client

    def _load_cache(self) -> dict[str, Any]:
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Could not read cache at %s: %s", self.cache_path, exc)
        return {}

    def _save_cache(self) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as exc:
            logger.warning("Could not persist cache at %s: %s", self.cache_path, exc)

    def _compute_cache_key(self, config: ExperimentConfig, query: str) -> str:
        payload = f"{config.model}|{config.prompt_variant}|{config.schema_version}|{config.temperature:.2f}|{query.strip()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def execute_experiment(
        self,
        config: ExperimentConfig,
        cases: Sequence[dict[str, Any]],
        catalog_brands: set[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Execute a single experiment across the specified cases."""
        target_cases = cases[:limit] if limit and limit > 0 else cases
        logger.info(
            "Executing experiment %s ('%s') on %d cases...",
            config.id,
            config.name,
            len(target_cases),
        )

        system_instruction = get_prompt_by_variant(config.prompt_variant)
        response_schema = (
            RefinedQueryUnderstandingOutput
            if config.schema_version == "v2.0.0"
            else QueryUnderstandingOutput
        )

        case_results: list[dict[str, Any]] = []

        for idx, c in enumerate(target_cases, start=1):
            q = c["query"]
            tid = c.get("test_id", f"CASE_{idx:03d}")
            cache_key = self._compute_cache_key(config, q)

            # Check cache
            cached_entry = self._cache.get(cache_key)
            if cached_entry:
                raw_json = cached_entry["raw_json"]
                latency_ms = cached_entry.get("latency_ms", 10.0)
                tok_dict = cached_entry.get("token_usage", {})
                tok_usage = TokenUsageMetadata(**tok_dict) if tok_dict else None
                is_valid = cached_entry.get("is_valid", True)
                parsed_dict = cached_entry["parsed_output"]
            else:
                # Quota safety check
                if self.requests_made >= self.max_requests:
                    raise RuntimeError(f"API request budget exhausted ({self.requests_made}/{self.max_requests}).")
                if self.tokens_consumed >= self.max_tokens:
                    raise RuntimeError(f"API token budget exhausted ({self.tokens_consumed}/{self.max_tokens}).")

                user_prompt = build_user_prompt(q)
                try:
                    (
                        parsed_inst,
                        raw_json,
                        latency_ms,
                        tok_usage,
                    ) = await self.client.generate_structured_async(
                        prompt=user_prompt,
                        response_schema=response_schema,
                        system_instruction=system_instruction,
                        temperature=config.temperature,
                    )
                    parsed_dict = parsed_inst.model_dump()
                    is_valid = True
                except Exception as exc:
                    logger.error("Generation error on [%s]: %s", tid, exc)
                    parsed_dict = {
                        "semantic_query": q,
                        "hard_constraints": {},
                        "soft_preferences": [],
                        "needs_clarification": True,
                        "clarification_reason": str(exc),
                    }
                    raw_json = json.dumps(parsed_dict)
                    latency_ms = 0.0
                    tok_usage = TokenUsageMetadata()
                    is_valid = False

                self.requests_made += 1
                if tok_usage:
                    self.tokens_consumed += tok_usage.total_tokens

                # Cache response
                self._cache[cache_key] = {
                    "raw_json": raw_json,
                    "parsed_output": parsed_dict,
                    "latency_ms": latency_ms,
                    "token_usage": tok_usage.model_dump() if tok_usage else {},
                    "is_valid": is_valid,
                }
                self._save_cache()

                if self.pacing_delay_sec > 0:
                    await asyncio.sleep(self.pacing_delay_sec)

            # Apply deterministic business rules if enabled
            if config.apply_rules:
                if config.schema_version == "v2.0.0":
                    refined_obj = RefinedQueryUnderstandingOutput(**parsed_dict)
                    refined_obj, _ = apply_rule_based_refinement_v2(
                        output=refined_obj,
                        raw_query=q,
                        catalog_brands=catalog_brands,
                    )
                    final_actual_dict = refined_obj.model_dump()
                else:
                    v1_obj = QueryUnderstandingOutput(**parsed_dict)
                    v1_obj, _ = apply_rule_based_refinement_v1(
                        output=v1_obj,
                        raw_query=q,
                        catalog_brands=catalog_brands,
                    )
                    final_actual_dict = v1_obj.model_dump()
            else:
                final_actual_dict = parsed_dict

            # Evaluate metrics against expected
            case_metrics = evaluate_refined_case(
                actual=final_actual_dict,
                expected=c.get("expected", {}),
            )

            case_results.append({
                "test_id": tid,
                "query": q,
                "expected": c.get("expected", {}),
                "actual": final_actual_dict,
                "is_valid": is_valid,
                "latency_ms": latency_ms,
                "token_usage": tok_usage.model_dump() if tok_usage else {},
                "metrics": case_metrics,
            })

        # Compute aggregate metrics
        agg_metrics = compute_experiment_metrics(case_results)

        return {
            "experiment_id": config.id,
            "experiment_name": config.name,
            "config": config.model_dump(),
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cases_evaluated_count": len(case_results),
            "metrics": agg_metrics,
            "per_case_results": case_results,
        }

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
