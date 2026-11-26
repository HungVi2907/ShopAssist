"""Explicit Ollama-only composition through the existing Gateway and loader."""
import os
from shopassist.llm_gateway.adapters.ollama import OllamaAdapter
from shopassist.llm_gateway.config import GatewayConfigurationError,load_gateway_config
from shopassist.llm_gateway.experiment_factory import experiment_schema_bindings
from shopassist.llm_gateway.gateway import Gateway
from shopassist.llm_gateway.registry import ProviderRegistry
from shopassist.llm_gateway.telemetry import TelemetrySink


def build_native_gateway(settings,*,client=None):
    if not settings.enabled or settings.runtime!='ollama_experimental':
        raise GatewayConfigurationError('Native experimental runtime must be explicitly enabled')
    registry=ProviderRegistry(settings,experiment_schema_bindings())
    config=load_gateway_config(settings)
    name,provider=next(iter(config.providers.items()))
    models={r.model for r in registry._routes.values()}
    if len(models)!=1:raise GatewayConfigurationError('One native identity is required per shared provider')
    adapter=OllamaAdapter(provider,next(iter(models)),credential=lambda:os.environ.get(provider.credential_env,''),
        client=client,identity_ttl_s=settings.ollama_identity_ttl_seconds)
    return Gateway(settings,registry,{name:adapter},telemetry=TelemetrySink(settings))


async def verify_native_gateway(gateway):
    """Control-plane digest verification; never an inference or route approval."""
    return all([await adapter.verify_model() for adapter in gateway.adapters.values()])
