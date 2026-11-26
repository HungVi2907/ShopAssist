"""Isolated T17 provider validation. Dry-run unless every live gate is explicit."""
from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

from shopassist.llm_gateway.config import GatewaySettings
from shopassist.llm_gateway.experiment_factory import experiment_schema_bindings
from shopassist.llm_gateway.registry import ProviderRegistry
from shopassist.llm_gateway.validation_harness import (
    ATTEMPT_TIMEOUT_SECONDS,
    MAX_OUTPUT_TOKENS,
    MAX_TOTAL_COST_USD,
    MAX_TOTAL_REQUESTS,
    MAX_TOTAL_TOKENS,
    RUN_DEADLINE_SECONDS,
    T17ValidationHarness,
    ValidationBudget,
    ValidationError,
    blocked_preflight_result,
    build_live_adapters,
    load_free_tier_evidence,
    write_result_artifact,
)

ROUTE_IDS = ("query_gemini", "recommendation_gemini", "recommendation_groq")


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("Cost must be a decimal amount") from None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", default="query_gemini,recommendation_gemini,recommendation_groq",
                        help="Comma-separated exact T17 route IDs")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Permit live provider dispatch after all gates pass")
    mode.add_argument("--dry-run", action="store_true", help="Show candidates and local preflight state without dispatch")
    parser.add_argument("--operator-approved", action="store_true",
                        help="Confirm the operator approved this exact run scope and budget")
    parser.add_argument("--zero-paid-spend-approved", action="store_true",
                        help="Confirm Free Tier only with no paid fallback or tier upgrade")
    parser.add_argument("--entitlement-evidence", type=Path,
                        help="Operator evidence JSON binding accounts to free-tier provider/model eligibility")
    parser.add_argument("--max-requests", type=int, help="Explicit aggregate request ceiling (1..8)")
    parser.add_argument("--max-tokens", type=int, help="Explicit aggregate token ceiling (1..50000)")
    parser.add_argument("--max-cost-usd", type=_decimal,
                        help="Explicit maximum spend; must be 0 for this Free Tier only run")
    parser.add_argument("--attempt-timeout", type=float,
                        help="Explicit approved attempt timeout in seconds (maximum 25)")
    parser.add_argument("--deadline", type=float,
                        help="Explicit approved total run deadline in seconds (maximum 120)")
    parser.add_argument("--budget-ledger", type=Path, default=ROOT / "data/interim/phase18_t17/budget.json")
    parser.add_argument("--artifact", type=Path, default=ROOT / "data/interim/phase18_t17/validation.json")
    args = parser.parse_args(argv)
    routes = [part.strip() for part in args.routes.split(",") if part.strip()]
    if not routes or len(routes) != len(set(routes)) or any(route not in ROUTE_IDS for route in routes):
        parser.error("Select unique route IDs from the fixed T17 candidate allowlist")
    args.route_ids = routes
    if args.live:
        if not args.operator_approved or not args.zero_paid_spend_approved:
            parser.error("Live dispatch requires explicit operator and zero-paid-spend approvals")
        if args.entitlement_evidence is None:
            parser.error("Live dispatch requires verified Free Tier entitlement evidence")
        if args.max_requests is None or not 1 <= args.max_requests <= MAX_TOTAL_REQUESTS:
            parser.error("Live dispatch requires an explicit aggregate request ceiling no greater than 8")
        if args.max_tokens is None or not 1 <= args.max_tokens <= MAX_TOTAL_TOKENS:
            parser.error("Live dispatch requires an explicit aggregate token ceiling no greater than 50000")
        if args.max_cost_usd is None or args.max_cost_usd != MAX_TOTAL_COST_USD:
            parser.error("Live dispatch requires an explicit zero USD cost ceiling")
        if args.attempt_timeout is None or not 0 < args.attempt_timeout <= ATTEMPT_TIMEOUT_SECONDS:
            parser.error("Live dispatch requires an explicit attempt timeout no greater than 25 seconds")
        if args.deadline is None or not 0 < args.deadline <= RUN_DEADLINE_SECONDS:
            parser.error("Live dispatch requires an explicit total run deadline no greater than 120 seconds")
    else:
        args.attempt_timeout = ATTEMPT_TIMEOUT_SECONDS if args.attempt_timeout is None else args.attempt_timeout
        args.deadline = RUN_DEADLINE_SECONDS if args.deadline is None else args.deadline
        if not 0 < args.attempt_timeout <= ATTEMPT_TIMEOUT_SECONDS:
            parser.error("Attempt timeout must be positive and at most 25 seconds")
        if not 0 < args.deadline <= RUN_DEADLINE_SECONDS:
            parser.error("Run deadline must be positive and at most 120 seconds")
    return args


async def _run(args) -> int:
    load_dotenv(ROOT / ".env", override=False)
    if os.environ.get("LLM_GATEWAY_ALLOW_PAID_MODELS", "false").strip().lower() not in {"false", "0", "no", "off"}:
        raise ValidationError("LLM_GATEWAY_ALLOW_PAID_MODELS must remain false for T17")
    settings = GatewaySettings(_env_file=None, enabled=True, allow_paid_models=False,
                               config_path=ROOT / "config/llm_gateway.yaml")
    registry = ProviderRegistry(settings, experiment_schema_bindings())
    routes = [registry.resolve(route_id) for route_id in args.route_ids]
    print("T17 mode:", "LIVE (gated)" if args.live else "DRY RUN")
    print("Paid models allowed: false")
    print("Approved ceiling: 10 total requests / 50,000 tokens / USD 0; active provider caps Gemini 4/10,000, Groq 3/20,000")
    print("Historical OpenRouter counters remain in the ledger for audit; OpenRouter is not a dispatch candidate.")
    print(f"Output cap: {MAX_OUTPUT_TOKENS}; attempt timeout: {args.attempt_timeout}s; run deadline: {args.deadline}s")
    for route in routes:
        print(f"Candidate: {route.route_id} | {route.provider} | {route.model} | enabled={route.enabled} | approval={route.approval} | configured_cost={route.cost_class}")
        print(f"  credential_present={bool(os.environ.get(route.credential_env))}; endpoint={route.endpoint}; max_output_tokens={route.options['max_output_tokens']}")
    if not args.live:
        print("No provider requests sent. Live mode requires operator approval, zero-cost confirmation, entitlement evidence, and explicit budgets.")
        return 0

    try:
        evidence = load_free_tier_evidence(args.entitlement_evidence)
    except ValidationError:
        evidence = {}
    budget = ValidationBudget(args.budget_ledger, max_total_requests=args.max_requests,
                              max_total_tokens=args.max_tokens, max_cost_usd=args.max_cost_usd)
    selected_providers = {route.provider for route in routes} | {route.provider_profile for route in routes}
    adapters = {}
    try:
        adapters = build_live_adapters(selected_providers)
        harness = T17ValidationHarness(
            registry, adapters, budget, evidence,
            credential_available=lambda route: bool(os.environ.get(route.credential_env)),
            live_authorized=args.operator_approved and args.zero_paid_spend_approved,
            paid_models_allowed=settings.allow_paid_models,
        )
        # Preflight every selected candidate before the first dispatch.
        blocked = []
        for route_id in args.route_ids:
            try:
                harness.preflight(route_id)
            except ValidationError as exc:
                blocked.append(blocked_preflight_result(registry, route_id, str(exc)))
        if blocked:
            write_result_artifact(args.artifact, blocked, budget)
            print("T17 preflight blocked; zero provider requests sent.")
            for item in blocked:
                print(f"  {item.route_id}: BLOCKED ({item.safe_error})")
            return 2
        deadline = time.monotonic() + args.deadline
        results = []
        for route_id in args.route_ids:
            result = await harness.validate_one(route_id, attempt_timeout_s=args.attempt_timeout,
                                                deadline_mono=deadline)
            results.append(result)
            write_result_artifact(args.artifact, results, budget)
            if result.status != "passed":
                print(f"Validation stopped: {route_id} status={result.status}, diagnostic={result.safe_error}")
                return 2
    finally:
        await asyncio.gather(*(adapter.aclose() for adapter in adapters.values()), return_exceptions=True)
        budget.close()
    print(f"Validation artifact written: {args.artifact}")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except ValidationError as exc:
        print(f"T17 preflight blocked: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print("T17 stopped with a sanitized internal error", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
