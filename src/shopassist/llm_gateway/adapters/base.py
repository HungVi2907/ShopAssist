"""Single-dispatch interface for later provider adapter implementations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from pydantic import Field

from shopassist.llm_gateway.registry import ResolvedRoute
from shopassist.llm_gateway.schemas import ContractModel, GatewayRequest, GatewayUsage, HttpStatus, Identifier


@dataclass(frozen=True)
class PreparedRequest:
    route: ResolvedRoute
    request: GatewayRequest = field(repr=False)
    body: bytes = field(repr=False)


class AdapterResult(ContractModel):
    raw_text: str = Field(repr=False, exclude=True, max_length=1_000_000)
    usage: GatewayUsage = Field(default_factory=GatewayUsage)
    http_status: HttpStatus | None = None
    reported_model: Identifier | None = None


class ProviderAdapter(Protocol):
    def prepare(self, request: GatewayRequest, route: ResolvedRoute) -> PreparedRequest:
        """Prepare locally without network I/O."""
        ...

    async def complete_once(self, prepared: PreparedRequest, *, timeout_s: float,
                            on_dispatch: Callable[[], None]) -> AdapterResult:
        """Dispatch once, with hook immediately before transport submission.

        No retry, redirect or JSON repair request is permitted. Extract usage
        before parsing output. Propagate caller cancellation unchanged.
        """
        ...

    async def aclose(self) -> None:
        """Idempotently close resources owned by this adapter on their loop."""
        ...
