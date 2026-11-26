"""Central in-process Gateway with bounded sequential automatic failover."""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Mapping

from pydantic import BaseModel, ValidationError

from shopassist.llm_gateway.adapters.base import AdapterResult, PreparedRequest, ProviderAdapter
from shopassist.llm_gateway.config import GatewayConfigurationError, GatewaySettings, Limits
from shopassist.llm_gateway.errors import (
    DispatchBudgetDenied,
    ErrorCategory,
    GatewayError,
    ProviderAttemptError,
    ReasonCode,
)
from shopassist.llm_gateway.failover import FailoverController
from shopassist.llm_gateway.health import HealthReservation, ProviderHealthManager
from shopassist.llm_gateway.policies import TaskAttemptPolicy, begin_task
from shopassist.llm_gateway.quota import ProviderQuotaManager, QuotaReservation
from shopassist.llm_gateway.registry import ProviderRegistry, ResolvedRoute
from shopassist.llm_gateway.router import TaskRouter
from shopassist.llm_gateway.schemas import (
    AttemptHistory,
    AttemptRecord,
    GatewayRequest,
    GatewayResponse,
    GatewayUsage,
    TaskType,
)
from shopassist.llm_gateway.telemetry import RouteSkip, TelemetrySink, build_task_summary
from shopassist.llm_gateway.json_utils import strict_json_loads


class Gateway:
    """Coordinates trusted routes, single-dispatch adapters and task policy.

    Business prompts and fallback remain caller-owned. This object never
    discovers models, retries a route, repairs JSON, or performs provider I/O
    outside an adapter's one `complete_once` call.
    """

    def __init__(
        self,
        settings: GatewaySettings,
        registry: ProviderRegistry,
        adapters: Mapping[str, ProviderAdapter],
        *,
        health: ProviderHealthManager | None = None,
        quota: ProviderQuotaManager | None = None,
        telemetry: TelemetrySink | None = None,
        credential_available: Callable[[ResolvedRoute], bool] | None = None,
        budget_estimator: Callable[[ResolvedRoute, GatewayRequest], tuple[int | None, Decimal | None]] | None = None,
        attempt_accounting=None,
        decoders: Mapping[str, Callable[[str], str]] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if not settings.enabled:
            raise GatewayConfigurationError("Gateway must be enabled before construction")
        self.settings = settings
        self.registry = registry
        self.router = TaskRouter(registry)
        self.adapters = dict(adapters)
        self.health = health or ProviderHealthManager(default_cooldown_s=settings.default_cooldown_seconds, clock=monotonic)
        self.quota = quota or ProviderQuotaManager(monotonic=monotonic, utc_now=utc_now)
        self.telemetry = telemetry
        self.credential_available = credential_available or (
            lambda route: (bool(getattr(self._adapter_for_route(route),'ready_for',lambda _:False)(route)) and
                (not route.credential_env or bool(os.environ.get(route.credential_env)))) if route.provider=='ollama' else bool(os.environ.get(route.credential_env))
        )
        self.budget_estimator = budget_estimator or (lambda _route, _request: (None, None))
        self.attempt_accounting = attempt_accounting
        self.decoders = dict(decoders or {})
        self.monotonic = monotonic
        self.utc_now = utc_now
        self.failover = FailoverController(enabled=settings.auto_failover)
        self._closed = False
        if self.telemetry is not None:
            self.telemetry.start()

    async def complete(self, request: GatewayRequest) -> GatewayResponse:
        if self._closed:
            raise GatewayError(
                request_id=request.request_id, task_id=request.task_id,
                category=ErrorCategory.CONFIGURATION_ERROR,
                reason_code=ReasonCode.CONFIGURATION_ERROR, source="gateway",
            )
        started = self.monotonic()
        try:
            routes = self.router.routes_for(request)
        except Exception:
            await self._emit_summary(request,[],[],'failure',started)
            raise GatewayError(
                request_id=request.request_id, task_id=request.task_id,
                category=ErrorCategory.CONFIGURATION_ERROR,
                reason_code=ReasonCode.CONFIGURATION_ERROR, source="request",
            ) from None

        policy = begin_task(
            self.settings, task=request.task, task_id=request.task_id,
            request_id=request.request_id, parent_deadline_mono=request.parent_deadline_mono,
            clock=self.monotonic,
        )
        skips: list[RouteSkip] = []
        attempts: list[AttemptRecord] = []
        last_failure: ProviderAttemptError | GatewayError | None = None
        last_outcome = "skipped"

        for route_index, route in enumerate(routes):
            if route_index > 0 and not self.failover.enabled:
                break
            if policy.attempt_count >= policy.max_attempts:
                break
            try:
                policy.timeout_for_attempt()
            except GatewayError as error:
                await self._emit_summary(request, attempts, skips, "failure", started)
                raise self._copy_gateway_error(error, request, attempts, started) from None

            static_reason = self.registry.ineligibility(route.route_id, request.task, request.profile)
            if static_reason is not None:
                skips.append(RouteSkip(route_id=route.route_id, reason=static_reason))
                continue
            adapter = self._adapter_for_route(route)
            if adapter is None:
                skips.append(RouteSkip(route_id=route.route_id, reason=ReasonCode.UNCONFIGURED))
                continue
            try:
                if not self.credential_available(route):
                    skips.append(RouteSkip(route_id=route.route_id, reason=ReasonCode.UNCONFIGURED))
                    continue
            except Exception:
                skips.append(RouteSkip(route_id=route.route_id, reason=ReasonCode.UNCONFIGURED))
                continue

            try:
                prepared = adapter.prepare(request, route)
            except ProviderAttemptError as exc:
                await self._emit_summary(request,attempts,skips,'failure',started)
                native=route.provider=='ollama'
                raise GatewayError(request_id=request.request_id,task_id=request.task_id,attempts=tuple(attempts),
                    category=exc.category if native else ErrorCategory.CONFIGURATION_ERROR,
                    reason_code=exc.reason_code if native else ReasonCode.CONFIGURATION_ERROR,source='request' if native else 'gateway') from None
            except Exception:
                # Local preparation is not an outbound attempt.
                raise GatewayError(
                    request_id=request.request_id, task_id=request.task_id,
                    attempts=tuple(attempts), category=ErrorCategory.CONFIGURATION_ERROR,
                    reason_code=ReasonCode.CONFIGURATION_ERROR, source="gateway",
                    elapsed_ms=self._elapsed_ms(started),
                ) from None

            health_lease = self.health.reserve(route.provider_profile, route.route_id, request.schema_id)
            if isinstance(health_lease, ReasonCode):
                skips.append(RouteSkip(route_id=route.route_id, reason=health_lease))
                continue

            try:
                estimated_tokens, estimated_cost = self.budget_estimator(route, request)
                if route.cost_class == "free" and estimated_cost is None:
                    estimated_cost = Decimal(0)
                limits = Limits.model_validate(dict(route.limits))
                quota_lease = self.quota.reserve(
                    route.provider_profile, limits,
                    estimated_max_tokens=estimated_tokens,
                    estimated_max_cost_usd=estimated_cost,
                )
            except Exception:
                self.health.release(health_lease)
                raise GatewayError(
                    request_id=request.request_id, task_id=request.task_id,
                    attempts=tuple(attempts), category=ErrorCategory.CONFIGURATION_ERROR,
                    reason_code=ReasonCode.CONFIGURATION_ERROR, source="admission",
                    elapsed_ms=self._elapsed_ms(started),
                ) from None
            if isinstance(quota_lease, ReasonCode):
                self.health.release(health_lease)
                skips.append(RouteSkip(route_id=route.route_id, reason=quota_lease))
                continue

            dispatch: dict[str, object] = {}

            def on_dispatch() -> None:
                if dispatch.get("started_mono") is not None:
                    raise GatewayError(
                        request_id=request.request_id, task_id=request.task_id,
                        attempts=tuple(attempts), category=ErrorCategory.INTERNAL_ERROR,
                        reason_code=ReasonCode.INTERNAL_ERROR, source="gateway",
                        elapsed_ms=self._elapsed_ms(started),
                    )
                policy.before_dispatch(route.route_id)
                budget_token = None
                if self.attempt_accounting is not None:
                    estimated_tokens, _ = self.budget_estimator(route, request)
                    budget_token = self.attempt_accounting.reserve(
                        request.task_id, route.route_id, estimated_tokens
                    )
                    dispatch["budget_token"] = budget_token
                policy.record_dispatch(route.route_id)
                if not self.quota.mark_dispatched(quota_lease):
                    policy.rollback_uncommitted_dispatch(route.route_id)
                    if budget_token is not None:
                        self.attempt_accounting.release(budget_token)
                    raise GatewayError(
                        request_id=request.request_id, task_id=request.task_id,
                        attempts=tuple(attempts), category=ErrorCategory.NO_ELIGIBLE_ROUTE,
                        reason_code=ReasonCode.CAPACITY_EXHAUSTED, source="admission",
                        elapsed_ms=self._elapsed_ms(started),
                    )
                if budget_token is not None:
                    self.attempt_accounting.mark_dispatched(budget_token)
                dispatch["started_mono"] = self.monotonic()
                dispatch["started_at_utc"] = self.utc_now().astimezone(timezone.utc)
                dispatch["attempt_number"] = policy.attempt_count

            async def execute_and_validate() -> tuple[AdapterResult, BaseModel]:
                timeout = policy.timeout_for_attempt()
                result = await adapter.complete_once(prepared, timeout_s=timeout, on_dispatch=on_dispatch)
                if dispatch.get("started_mono") is None:
                    raise ProviderAttemptError(
                        category=ErrorCategory.INTERNAL_ERROR,
                        reason_code=ReasonCode.INTERNAL_ERROR,
                        usage=result.usage,
                    )
                reported = result.reported_model
                allowed_aliases = route.options.get("reported_model_aliases", ())
                if reported is not None and reported != route.model and reported not in allowed_aliases:
                    raise ProviderAttemptError(
                        category=ErrorCategory.INCOMPATIBLE_ROUTE,
                        reason_code=ReasonCode.INCOMPATIBLE_ROUTE,
                        http_status=result.http_status, usage=result.usage,
                        reported_model=result.reported_model, timings=result.timings,
                    )
                try:
                    decoder = self.decoders.get(request.schema_id)
                    output_text = decoder(result.raw_text) if decoder is not None else result.raw_text
                    if not isinstance(output_text, str):
                        raise ValueError("Decoder returned an invalid value")
                    value = strict_json_loads(output_text)
                    payload = request.response_schema.model_validate(value)
                except Exception:
                    raise ProviderAttemptError(
                        category=ErrorCategory.INVALID_OUTPUT,
                        reason_code=ReasonCode.INVALID_OUTPUT,
                        http_status=result.http_status, usage=result.usage,
                        reported_model=result.reported_model, timings=result.timings,
                    ) from None
                policy.timeout_for_attempt()  # Reject synchronous validation that crossed the deadline.
                return result, payload

            try:
                result, payload = await policy.run_attempt(route.route_id, execute_and_validate())
            except asyncio.CancelledError:
                if dispatch.get("started_mono") is not None:
                    record = self._attempt_record(
                        request, route, route_index, policy, dispatch,
                        outcome="cancelled", category=ErrorCategory.CANCELLED,
                        reason=ReasonCode.CANCELLED, usage=GatewayUsage(),
                    )
                    attempts.append(record)
                    self.quota.release(quota_lease, usage=None)
                    self._settle_budget(dispatch, None)
                    self.health.release(health_lease)
                    last_outcome = "cancelled"
                    await self._emit_attempt(record)
                else:
                    self.quota.release(quota_lease)
                    self._release_budget(dispatch)
                    self.health.release(health_lease)
                await self._emit_summary(request, attempts, skips, "cancelled", started)
                raise
            except DispatchBudgetDenied:
                self.quota.release(quota_lease)
                self._release_budget(dispatch)
                self.health.release(health_lease)
                await self._emit_summary(request, attempts, skips, "skipped", started)
                raise
            except ProviderAttemptError as error:
                if dispatch.get("started_mono") is None:
                    self.quota.release(quota_lease)
                    self._release_budget(dispatch)
                    self.health.release(health_lease)
                    reason = ReasonCode.UNCONFIGURED if error.category == ErrorCategory.AUTHENTICATION else error.reason_code
                    skips.append(RouteSkip(route_id=route.route_id, reason=reason))
                    if self.failover.may_consider_next(policy, error.category):
                        continue
                    last_failure = error
                    last_outcome = "failure"
                    break
                record = self._attempt_record(
                    request, route, route_index, policy, dispatch,
                    outcome="error", category=error.category,
                    reason=error.reason_code, status=error.http_status,
                    usage=error.usage or GatewayUsage(),
                    reported_model=error.reported_model, timings=error.timings,
                )
                attempts.append(record)
                self.quota.release(quota_lease, usage=error.usage)
                self._settle_budget(dispatch, error.usage)
                retry_deadline = None
                if error.retry_after_s is not None:
                    retry_deadline = self.monotonic() + error.retry_after_s
                self.health.record_failure(
                    health_lease, error.category,
                    retry_after_deadline_mono=retry_deadline,
                )
                await self._emit_attempt(record)
                last_failure = error
                last_outcome = "failure"
                if self.failover.may_consider_next(policy, error.category):
                    continue
                break
            except GatewayError as error:
                if dispatch.get("started_mono") is not None:
                    record = self._attempt_record(
                        request, route, route_index, policy, dispatch,
                        outcome="error", category=error.category,
                        reason=error.reason_code, usage=GatewayUsage(),
                    )
                    attempts.append(record)
                    self.quota.release(quota_lease, usage=None)
                    self._settle_budget(dispatch, None)
                    if error.category == ErrorCategory.DEADLINE_EXCEEDED:
                        self.health.release(health_lease)
                    else:
                        self.health.record_failure(health_lease, error.category)
                    await self._emit_attempt(record)
                else:
                    self.quota.release(quota_lease)
                    self._release_budget(dispatch)
                    self.health.release(health_lease)
                await self._emit_summary(request, attempts, skips, "failure", started)
                raise self._copy_gateway_error(error, request, attempts, started) from None
            except Exception:
                if dispatch.get("started_mono") is not None:
                    record = self._attempt_record(
                        request, route, route_index, policy, dispatch,
                        outcome="error", category=ErrorCategory.INTERNAL_ERROR,
                        reason=ReasonCode.INTERNAL_ERROR, usage=GatewayUsage(),
                    )
                    attempts.append(record)
                    self.quota.release(quota_lease, usage=None)
                    self._settle_budget(dispatch, None)
                    self.health.release(health_lease)
                    await self._emit_attempt(record)
                else:
                    self.quota.release(quota_lease)
                    self._release_budget(dispatch)
                    self.health.release(health_lease)
                await self._emit_summary(request, attempts, skips, "failure", started)
                raise GatewayError(
                    request_id=request.request_id, task_id=request.task_id,
                    attempts=tuple(attempts), category=ErrorCategory.INTERNAL_ERROR,
                    reason_code=ReasonCode.INTERNAL_ERROR, source="gateway",
                    elapsed_ms=self._elapsed_ms(started),
                ) from None

            # Only a validated provider result reaches this branch.
            record = self._attempt_record(
                request, route, route_index, policy, dispatch,
                outcome="success", usage=result.usage, reported_model=result.reported_model,
                status=result.http_status,
                timings=result.timings,
            )
            attempts.append(record)
            self.quota.release(quota_lease, usage=result.usage)
            self._settle_budget(dispatch, result.usage)
            self.health.record_success(health_lease)
            await self._emit_attempt(record)
            await self._emit_summary(request, attempts, skips, "success", started)
            return GatewayResponse[request.response_schema](
                request_id=request.request_id,
                task_id=request.task_id,
                attempts=tuple(attempts),
                task=request.task,
                schema_id=request.schema_id,
                payload=payload,
                raw_text=result.raw_text,
                route_id=route.route_id,
                provider=route.provider,
                model=route.model,
                reported_model=result.reported_model,
                usage=result.usage,
                latency_ms=self._elapsed_ms(started),
                failover_used=route_index > 0,
            )

        try:
            policy.timeout_for_attempt()
        except GatewayError as error:
            await self._emit_summary(request, attempts, skips, "failure", started)
            raise self._copy_gateway_error(error, request, attempts, started) from None
        await self._emit_summary(request, attempts, skips, last_outcome, started)
        if last_failure is not None:
            if isinstance(last_failure, GatewayError):
                raise self._copy_gateway_error(last_failure, request, attempts, started) from None
            raise GatewayError(
                request_id=request.request_id, task_id=request.task_id,
                attempts=tuple(attempts), category=last_failure.category,
                reason_code=last_failure.reason_code, source="provider",
                elapsed_ms=self._elapsed_ms(started),
            ) from None
        raise GatewayError(
            request_id=request.request_id, task_id=request.task_id,
            attempts=tuple(attempts), category=ErrorCategory.NO_ELIGIBLE_ROUTE,
            reason_code=ReasonCode.NO_ELIGIBLE_ROUTE, source="admission",
            elapsed_ms=self._elapsed_ms(started),
        )

    def primary_provider(self, task: TaskType, profile: str = "default") -> str | None:
        """Return configured primary provider without probing it."""
        route = self.registry.primary_route(task, profile)
        return route.provider if route is not None else None

    def readiness_snapshot(self) -> dict[str, dict[str, object]]:
        """Return safe local routing/health/quota state for internal readiness."""
        snapshot: dict[str, dict[str, object]] = {}
        for route_id in self.registry._routes:
            route = self.registry.resolve(route_id)
            health = self.health.snapshot(route.provider_profile)
            quota = self.quota.snapshot(route.provider_profile)
            snapshot[route_id] = {
                "provider": route.provider,
                "enabled": route.enabled,
                "approval": route.approval,
                "health": health.status,
                "cooldown_remaining_s": health.cooldown_remaining_s,
                "quota": quota,
                **({'identity_verified_recently':bool(getattr(self._adapter_for_route(route),'ready_for',lambda _:False)(route)),
                    'route_health':self.health.snapshot(route.provider_profile,route_id,next(iter(route.schema_ids))).status} if route.provider=='ollama' else {}),
            }
        return snapshot

    @staticmethod
    def _reject_json_constant(_value: str):
        raise ValueError("Non-standard JSON constant")

    def _elapsed_ms(self, started: float) -> float:
        return max(0.0, (self.monotonic() - started) * 1000)

    def _release_budget(self, dispatch: dict) -> None:
        token = dispatch.get("budget_token")
        if token is not None and not dispatch.get("budget_settled"):
            self.attempt_accounting.release(token)
            dispatch["budget_settled"] = True

    def _settle_budget(self, dispatch: dict, usage: GatewayUsage | None) -> None:
        token = dispatch.get("budget_token")
        if token is not None and not dispatch.get("budget_settled"):
            self.attempt_accounting.settle(token, usage)
            dispatch["budget_settled"] = True

    def _attempt_record(
        self, request: GatewayRequest, route: ResolvedRoute, route_index: int,
        policy: TaskAttemptPolicy, dispatch: dict, *, outcome: str,
        category: ErrorCategory | None = None, reason: ReasonCode | None = None,
        usage: GatewayUsage, reported_model: str | None = None, status: int | None = None, timings=None,
    ) -> AttemptRecord:
        started_mono = float(dispatch["started_mono"])
        started_utc = dispatch["started_at_utc"]
        return AttemptRecord(
            request_id=request.request_id, task_id=request.task_id, task=request.task,
            profile=request.profile, schema_id=request.schema_id,
            attempt_number=int(dispatch["attempt_number"]), route_index=route_index,
            route_id=route.route_id, provider=route.provider, model=route.model,
            reported_model=reported_model, started_at_utc=started_utc,
            latency_ms=max(0.0, (self.monotonic() - started_mono) * 1000),
            http_status=status, outcome=outcome, error_category=category,
            reason_code=reason, usage=usage,
            system_chars=len(request.system_prompt), user_chars=len(request.user_prompt),
            context_chars=len(request.system_prompt) + len(request.user_prompt),
            is_failover_route=route_index > 0,
            schema_fingerprint=request.schema_fingerprint,timings=timings,
            model_digest=route.model_digest,
        )

    async def _emit_attempt(self, record: AttemptRecord) -> None:
        if self.telemetry is not None:
            self.telemetry.emit_attempt(record)

    def record_fallback(self,request_id,task_id,schema_id,reason_code=ReasonCode.INVALID_OUTPUT):
        if self.telemetry is not None:
            try:self.telemetry.emit_fallback(request_id,task_id,schema_id,reason_code)
            except (ValueError,TypeError):return False

    async def _emit_summary(self, request: GatewayRequest, attempts: list[AttemptRecord],
                            skips: list[RouteSkip], outcome: str, started: float) -> None:
        if self.telemetry is None:
            return
        history = AttemptHistory(
            request_id=request.request_id, task_id=request.task_id, attempts=tuple(attempts)
        )
        summary = build_task_summary(
            history, task=request.task, profile=request.profile, schema_id=request.schema_id,
            outcome=outcome, elapsed_ms=self._elapsed_ms(started),
            skip_reasons=tuple(skips),
            schema_fingerprint=request.schema_fingerprint,
        )
        self.telemetry.emit_task(summary)

    def _adapter_for_route(self, route: ResolvedRoute) -> ProviderAdapter | None:
        """Prefer a profile-specific adapter, then fall back to the provider-kind adapter."""
        return self.adapters.get(route.provider_profile) or self.adapters.get(route.provider)

    def _copy_gateway_error(self, error: GatewayError, request: GatewayRequest,
                            attempts: list[AttemptRecord], started: float) -> GatewayError:
        details = error.record.error
        return GatewayError(
            request_id=request.request_id, task_id=request.task_id,
            attempts=tuple(attempts), category=details.category,
            reason_code=details.reason_code, source=details.source,
            deadline_scope=details.deadline_scope, elapsed_ms=self._elapsed_ms(started),
        )

    async def aclose(self) -> None:
        """Close owned adapters and telemetry sink once, on the caller loop."""
        if self._closed:
            return
        self._closed = True
        seen_adapters: set[int] = set()
        for adapter in self.adapters.values():
            if id(adapter) in seen_adapters:
                continue
            seen_adapters.add(id(adapter))
            try:
                await adapter.aclose()
            except Exception:
                # Cleanup is best effort; never expose transport internals.
                continue
        if self.telemetry is not None:
            await self.telemetry.aclose()
