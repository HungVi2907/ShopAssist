"""Trusted task/profile routing facade."""
from shopassist.llm_gateway.registry import ProviderRegistry, ResolvedRoute
from shopassist.llm_gateway.schemas import GatewayRequest


class TaskRouter:
    """Resolve immutable configured routes in YAML order."""

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def routes_for(self, request: GatewayRequest) -> tuple[ResolvedRoute, ...]:
        return self.registry.routes_for(request)
