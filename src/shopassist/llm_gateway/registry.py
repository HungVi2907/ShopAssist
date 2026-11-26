"""Immutable routing metadata and static eligibility, without provider I/O."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from pydantic import BaseModel

from shopassist.llm_gateway.config import GatewayConfigurationError, GatewaySettings, load_gateway_config
from shopassist.llm_gateway.errors import ReasonCode
from shopassist.llm_gateway.schema_ids import ALL_SCHEMA_IDS, TASK_SCHEMA_IDS
from shopassist.llm_gateway.schemas import GatewayRequest, SCHEMA_IDS, TaskType


@dataclass(frozen=True)
class ProviderCapability:
    structured_modes: frozenset[str]
    reasoning_effort: bool = False


CAPABILITIES = MappingProxyType({
    "gemini": ProviderCapability(frozenset({"gemini_schema"})),
    "openrouter": ProviderCapability(frozenset({"json_schema", "json_object"})),
    "groq": ProviderCapability(frozenset({"json_schema", "json_object"}), True),
    "ollama": ProviderCapability(frozenset({'ollama_schema'})),
})


@dataclass(frozen=True)
class ResolvedRoute:
    route_id: str
    provider_profile: str
    provider: str
    endpoint: str
    credential_env: str
    model: str
    structured_mode: str
    schema_ids: frozenset[str]
    enabled: bool
    approval: str
    evidence_valid_until: datetime | None
    cost_class: str
    cost: Mapping
    options: Mapping
    limits: Mapping
    model_digest: str | None = None
    schema_fingerprints: tuple[str,...] = ()


class ProviderRegistry:
    """Build from the evidence-validating loader and trusted schema bindings.

    Credential, health, quota and request-budget admission belong to the
    later gateway stages. This registry supplies static eligibility only.
    """

    def __init__(self, settings: GatewaySettings, schema_bindings: Mapping[str, type[BaseModel]]):
        config = load_gateway_config(settings)
        if config is None:
            raise GatewayConfigurationError("Gateway registry requires enabled configuration")
        if not set(schema_bindings) <= ALL_SCHEMA_IDS or any(
            not isinstance(model, type) or not issubclass(model, BaseModel)
            for model in schema_bindings.values()
        ):
            raise GatewayConfigurationError("Invalid schema bindings")
        self._schemas = MappingProxyType(dict(schema_bindings))
        self._allow_paid = settings.allow_paid_models
        routes = {}
        for route_id, route in config.routes.items():
            provider = config.providers[route.provider]
            capability = CAPABILITIES[provider.kind]
            if route.structured_mode not in capability.structured_modes:
                raise GatewayConfigurationError("Unsupported route capability")
            options = route.options.model_dump()
            options["reported_model_aliases"] = tuple(options["reported_model_aliases"])
            routes[route_id] = ResolvedRoute(
                route_id=route_id, provider_profile=route.provider, provider=provider.kind,
                endpoint=provider.endpoint, credential_env=provider.credential_env,
                model=route.model, structured_mode=route.structured_mode,
                schema_ids=frozenset(route.schema_ids), enabled=route.enabled,
                approval=route.approval.status,
                evidence_valid_until=config._evidence_expiry.get(route_id),
                cost_class=route.cost.classification,
                cost=MappingProxyType(route.cost.model_dump()),
                options=MappingProxyType(options),
                limits=MappingProxyType(provider.limits.model_dump()),
                model_digest=provider.model_digest,
                schema_fingerprints=tuple(config._native_evidence[route_id].schema_fingerprints) if route_id in config._native_evidence else (),
            )
        self._routes = MappingProxyType(routes)
        self._profiles = MappingProxyType({
            (TaskType(task), name): (profile.schema_id, tuple(profile.route_ids), profile.allow_paid)
            for task, definition in config.tasks.items()
            for name, profile in definition.profiles.items()
        })

    def resolve(self, route_id: str) -> ResolvedRoute:
        try:
            return self._routes[route_id]
        except KeyError:
            raise GatewayConfigurationError("Unknown route") from None

    def profile_schema_id(self, task: TaskType, profile: str) -> str | None:
        """Return the configured schema for a declared task profile."""
        binding = self._profiles.get((task, profile))
        return binding[0] if binding else None

    def profiles(self, task: TaskType) -> tuple[str, ...]:
        """List declared profiles without exposing provider credentials."""
        return tuple(name for item_task, name in self._profiles if item_task == task)

    def primary_route(self, task: TaskType, profile: str = "default") -> ResolvedRoute | None:
        """Return the first configured route for readiness reporting only."""
        binding = self._profiles.get((task, profile))
        return self.resolve(binding[1][0]) if binding and binding[1] else None

    def routes_for(self, request: GatewayRequest) -> tuple[ResolvedRoute, ...]:
        profile = self._profiles.get((request.task, request.profile))
        binding=self._schemas.get(request.schema_id)
        valid=binding is request.response_schema
        if request.schema_id=='phase12.catalog-selection.v2':
            valid=self._selection_binding(request.response_schema,binding)
        if profile is None or profile[0] != request.schema_id or not valid:
            raise GatewayConfigurationError("Task profile or schema binding mismatch")
        routes=tuple(self.resolve(route_id) for route_id in profile[1])
        if any(r.provider=='ollama' and r.enabled and request.schema_fingerprint not in r.schema_fingerprints for r in routes):
            raise GatewayConfigurationError('Request schema shape lacks native route evidence')
        return routes

    @staticmethod
    def _selection_binding(schema,binding):
        from shopassist.recommendation.local import SelectionFamily,selection_schema
        try:
            if binding is not SelectionFamily or not issubclass(schema,SelectionFamily) or schema.model_config!=SelectionFamily.model_config:return False
            properties=schema.model_json_schema()['properties']
            if len(properties) not in (1,3,5) or list(properties)!=[f'p{i}' for i in range(1,len(properties)+1)]:return False
            sizes=[p['items']['maximum'] for p in properties.values()]
            if any(type(n) is not int or not 1<=n<=13 for n in sizes):return False
            trusted=selection_schema({str(i):[None]*n for i,n in enumerate(sizes)})
            return schema.model_json_schema()==trusted.model_json_schema()
        except (KeyError,TypeError,AttributeError):return False

    def ineligibility(self, route_id: str, task: TaskType, profile: str = "default") -> ReasonCode | None:
        route = self.resolve(route_id)
        binding = self._profiles.get((task, profile))
        if binding is None or route_id not in binding[1]:
            raise GatewayConfigurationError("Route is not bound to task profile")
        if not route.enabled:
            return ReasonCode.DISABLED
        if route.approval != "approved" or route.evidence_valid_until is None or route.evidence_valid_until <= datetime.now(timezone.utc):
            return ReasonCode.UNAPPROVED
        if route.cost_class == "unknown" or (
            route.cost_class == "paid" and not (self._allow_paid and binding[2])
        ) or (
            route.cost_class == "free" and any(
                route.cost[field] not in (None, 0)
                for field in ("input_per_million_usd", "output_per_million_usd")
            )
        ):
            return ReasonCode.COST_DENIED
        return None
