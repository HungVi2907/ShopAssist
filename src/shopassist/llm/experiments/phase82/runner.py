"""Budgeted, resumable research runner. Defaults to planning, never implicit live work."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time
import uuid
import uuid

from shopassist.llm.config import LLMSettings
from shopassist.llm.gemini_client import GeminiClient
from shopassist.llm.prompts import build_user_prompt
from shopassist.llm.query_understanding import MAX_QUERY_LENGTH
from shopassist.llm.refinement_rules import apply_rule_based_refinement_v2
from .candidates import Candidate
from .rules import apply
from .scoring import POLICY_VERSION, aggregate, score
from shopassist.llm_gateway.errors import GatewayError
from shopassist.llm_gateway.schema_ids import EXPERIMENTAL_SCHEMA_IDS
from shopassist.llm_gateway.schemas import GatewayRequest, TaskType


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def atomic_write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf8")
    tmp.replace(path)


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    path: Path
    max_requests: int
    max_tokens: int
    requests: int = 0
    charged_tokens: int = 0
    observed_tokens: int = 0

    def __post_init__(self):
        if self.max_requests < 0 or self.max_tokens < 0:
            raise ValueError("Budgets must be nonnegative")
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf8"))
            self.requests, self.charged_tokens, self.observed_tokens = (data[k] for k in ("requests", "charged_tokens", "observed_tokens"))

    def save(self):
        atomic_write(self.path, {"requests": self.requests, "charged_tokens": self.charged_tokens,
                                "observed_tokens": self.observed_tokens, "max_requests": self.max_requests,
                                "max_tokens": self.max_tokens, "unknown_usage_policy": "retain reservation"})

    def reserve(self, amount: int):
        if self.requests >= self.max_requests or self.charged_tokens + amount > self.max_tokens:
            raise BudgetExceeded("Request/token reservation budget exhausted; no further call submitted")
        self.requests += 1
        self.charged_tokens += amount
        self.save()  # Persist before submission: crash recovery never forgets a call.

    def settle(self, reserved: int, usage):
        if usage is not None:
            self.charged_tokens += usage.total_tokens - reserved
            self.observed_tokens += usage.total_tokens
        self.save()


def fingerprint(candidate: Candidate, settings: LLMSettings | None, query: str, *, profile="legacy", route=None,
                schema_id=None) -> dict:
    route_identity = None if route is None else {
        "provider": route.provider, "endpoint": route.endpoint, "model": route.model,
        "route_id": route.route_id, "enabled": route.enabled, "approval": route.approval,
        "options": dict(route.options),
    }
    return {
        "task": "query_understanding", "profile": profile,
        "schema_id": schema_id or candidate.schema.__name__,
        "system_prompt_hash": digest(candidate.prompt),
        "user_prompt_hash": digest(build_user_prompt(query)),
        "schema_hash": digest(candidate.schema.model_json_schema()),
        "candidate_version": digest(candidate.metadata()),
        "routing": route_identity,
        "model": route.model if route is not None else (settings.model if settings is not None else None),
        "temperature": route.options.get("temperature") if route is not None else candidate.temperature,
        "max_output_tokens": route.options.get("max_output_tokens") if route is not None else settings.max_output_tokens,
        "timeout_seconds": settings.timeout_seconds if settings is not None else None,
        "max_retries": settings.max_retries if settings is not None else None,
        "sdk_retry_attempts": 1, "sdk_version": version("google-genai"), "query_hash": digest(query),
    }


class ResearchRunner:
    def __init__(self, settings: LLMSettings | None, output_dir: Path, max_requests: int = 0,
                 max_tokens: int = 0, pacing: float = 4.0, use_cache: bool = False,
                 gateway=None, profile: str | None = None):
        if pacing < 0:
            raise ValueError("Pacing must be nonnegative")
        self.settings, self.output_dir = settings, Path(output_dir)
        self.budget = None if gateway is not None else Budget(self.output_dir / "budget.json", max_requests, max_tokens)
        self.pacing, self.use_cache = pacing, use_cache
        self.gateway, self.profile = gateway, profile
        self.client = None
        self.last_attempt = None

    async def run_case(self, candidate: Candidate, case: dict, dataset: dict, repetition: int = 0,
                       resume: bool = False, profile: str | None = None) -> dict:
        query = case["query"]
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > MAX_QUERY_LENGTH:
            raise ValueError("Research input violates production query bounds")
        schema_id = None
        request = None
        route = None
        profile = profile or self.profile or "legacy"
        if self.gateway is not None:
            if profile == "legacy":
                raise ValueError("Gateway experiment requires a declared YAML profile")
            schema_id = EXPERIMENTAL_SCHEMA_IDS["query_understanding"][
                "query_required_v2_v1"
                if candidate.schema.__name__ == "RequiredV2"
                else "query_refined_v1"
            ]
            request = GatewayRequest[candidate.schema](
                task=TaskType.QUERY_UNDERSTANDING, profile=profile,
                request_id=uuid.uuid4().hex, task_id=uuid.uuid4().hex,
                system_prompt=candidate.prompt, user_prompt=build_user_prompt(query),
                schema_id=schema_id, response_schema=candidate.schema,
            )
            routes = self.gateway.registry.routes_for(request)
            if len(routes) != 1 or routes[0].options.get("temperature") != candidate.temperature:
                raise ValueError("Phase 8.2 candidate parameters do not match YAML profile")
            route = routes[0]
        fp = fingerprint(candidate, self.settings, query, profile=profile, route=route, schema_id=schema_id)
        task = digest({"fingerprint": fp, "candidate": candidate.metadata(), "dataset": dataset,
                       "expected": case["expected"], "test_id": case["test_id"], "repetition": repetition,
                       "scoring": POLICY_VERSION, "rule_version": "phase82-1.0"})
        destination = self.output_dir / "records" / (task + ".json")
        if resume and destination.exists():
            return json.loads(destination.read_text(encoding="utf8"))
        cached_path = self.output_dir / "cache" / (digest(fp) + ".json")
        start = time.perf_counter()
        diag, warnings, raw = {}, [], None
        cache_status, lookup_ms = "live", None
        valid, actual, error = False, None, None
        usage = None
        provenance = {}
        historical_usage = None
        try:
            if self.use_cache and cached_path.exists():
                cached = json.loads(cached_path.read_text(encoding="utf8"))
                if cached.get("fingerprint") != fp:
                    raise ValueError("Cache fingerprint mismatch")
                raw = candidate.schema.model_validate(cached["raw_output"])
                provenance = cached.get("provenance", {})
                historical_usage = cached.get("historical_usage")
                cache_status = "hit"
                lookup_ms = (time.perf_counter()-start)*1000
                diag = {"attempts": 0, "response_received": None, "json_valid": None,
                        "schema_valid": True, "usage_known": False}
            else:
                # UTF-8 bytes deliberately overestimate visible input tokens. This is a
                # reservation, not a provider guarantee about hidden/billable tokens.
                reservation = len((candidate.prompt + build_user_prompt(query) +
                                   json.dumps(candidate.schema.model_json_schema())).encode()) + (
                                       route.options["max_output_tokens"] if route is not None else self.settings.max_output_tokens
                                   ) + 512
                def before_attempt():
                    if self.last_attempt is not None:
                        delay = self.pacing - (time.perf_counter()-self.last_attempt)
                        if delay > 0:
                            time.sleep(delay)
                            diag["pacing_ms"] = diag.get("pacing_ms", 0.0) + delay*1000
                    if self.gateway is None:
                        self.budget.reserve(reservation)
                    self.last_attempt = time.perf_counter()
                def received(metadata):
                    if self.gateway is None:
                        self.budget.settle(reservation, metadata)
                if self.gateway is not None:
                    if self.last_attempt is not None:
                        delay = self.pacing - (time.perf_counter() - self.last_attempt)
                        if delay > 0:
                            await asyncio.sleep(delay)
                            diag["pacing_ms"] = delay * 1000
                    self.last_attempt = time.perf_counter()
                    response = await self.gateway.complete(request)
                    raw, usage = response.payload, response.usage
                    provenance = {"provider": response.provider, "model": response.model, "route_id": response.route_id}
                    diag["attempts"] = len(response.attempts)
                    diag["response_usages"] = [{
                        "prompt_tokens": a.usage.input_tokens,
                        "candidates_tokens": a.usage.output_tokens,
                        "total_tokens": a.usage.total_tokens,
                    } for a in response.attempts]
                else:
                    if self.client is None:
                        self.client = GeminiClient(self.settings)
                    raw, _, _, usage = await self.client.generate_structured_async(
                        prompt=build_user_prompt(query), response_schema=candidate.schema,
                        system_instruction=candidate.prompt, model_name=self.settings.model,
                        temperature=candidate.temperature, on_attempt=before_attempt,
                        on_response=received, diagnostics=diag)
                    provenance = {"provider": "gemini", "model": self.settings.model, "route_id": None}
                # Only successful validated raw responses are cached. No error poisoning.
                if self.use_cache:
                    atomic_write(cached_path, {"fingerprint": fp, "raw_output": raw.model_dump(),
                                              "provenance": provenance,
                                              "historical_usage": usage.model_dump() if usage else None,
                                              "created_utc": datetime.now(timezone.utc).isoformat()})
            normalization_start = time.perf_counter()
            if candidate.rules == "historical":
                final, warnings = apply_rule_based_refinement_v2(raw.model_copy(deep=True), query)
            elif candidate.rules == "conservative":
                final, warnings = apply(raw, query)
            elif candidate.rules == "none":
                final = raw
            else:
                raise ValueError("Unknown rule variant")
            actual, valid = final.model_dump(), True
            diag["normalization_ms"] = (time.perf_counter()-normalization_start)*1000
        except BudgetExceeded:
            raise  # Do not manufacture a completed row for a request that was never sent.
        except GatewayError:
            raise
        except Exception as exc:
            error = {"type": type(exc).__name__, "status": diag.get("last_status_code"),
                     "stage": "postprocessing" if raw is not None else "schema" if diag.get("json_valid") else "json" if diag.get("response_received") else "api"}
        known_usages = [u for u in diag.get("response_usages",[]) if u is not None]
        recorded_usage = ({k: sum(u.get(k,0) for u in known_usages)
                           for k in ("prompt_tokens","candidates_tokens","total_tokens")}
                          if known_usages else (usage.model_dump() if usage else diag.get("token_usage")) or {})
        row = {"test_id": case["test_id"], "query": query, "expected": case["expected"],
               "raw_output": raw.model_dump() if raw is not None else None, "actual": actual,
               "is_valid": valid, "error": error, "warnings": warnings, "candidate": candidate.metadata(),
               "fingerprint": fp, "dataset": dataset, "repetition": repetition,
               "timestamp_utc": datetime.now(timezone.utc).isoformat(), "cache_status": cache_status,
               "cache_lookup_ms": lookup_ms, "end_to_end_ms": (time.perf_counter()-start)*1000,
               "diagnostics": diag, "token_usage": recorded_usage,
               "provenance": (cached.get("provenance") if cache_status == "hit" else provenance),
               "historical_token_usage": historical_usage if cache_status == "hit" else None,
               "unknown_usage_attempts": max(0,diag.get("attempts",0)-len(known_usages)),
               "score": score(actual, case["expected"], valid)}
        atomic_write(destination, row)
        return row

    async def close(self):
        if self.client is not None:
            await self.client.aclose()
