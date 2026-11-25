"""Mock-only Gemini conformance and legacy transport tests."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from google.genai import types
from google.genai.errors import APIError
from shopassist.llm.config import LLMSettings
from shopassist.llm.gemini_client import GeminiClient

from shopassist.llm.schemas import QueryUnderstandingOutput
from shopassist.llm_gateway.adapters.gemini import GeminiAdapter
from shopassist.llm_gateway.config import GatewaySettings
from shopassist.llm_gateway.errors import ErrorCategory, ProviderAttemptError
from shopassist.llm_gateway.registry import ProviderRegistry
from shopassist.llm_gateway.schemas import GatewayRequest, SCHEMA_IDS


def setup_adapter(result=None, error=None):
    registry = ProviderRegistry(GatewaySettings(_env_file=None, enabled=True),
                                {schema: QueryUnderstandingOutput for schema in SCHEMA_IDS.values()})
    request = GatewayRequest[QueryUnderstandingOutput](
        task="query_understanding", request_id="req", task_id="task",
        schema_id="phase8.query.v1", response_schema=QueryUnderstandingOutput,
        system_prompt="system", user_prompt="running shoes",
    )
    client = MagicMock()
    client.generate_content_once = AsyncMock(return_value=result, side_effect=error)
    client.aclose = AsyncMock()
    adapter = GeminiAdapter(lambda: "synthetic-secret", client=client)
    prepared = adapter.prepare(request, registry.resolve("query_gemini"))
    return adapter, prepared, client


def response(usage=True, text='{"semantic_query":"running shoes"}'):
    return SimpleNamespace(
        text=text, model_version="gemini-3.5-flash-lite",
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=3,
                                       total_token_count=15, thoughts_token_count=2) if usage else None,
    )


def test_success_preserves_schema_and_usage():
    adapter, prepared, client = setup_adapter(response())
    hook = MagicMock()
    result = asyncio.run(adapter.complete_once(prepared, timeout_s=1, on_dispatch=hook))
    assert QueryUnderstandingOutput.model_validate_json(result.raw_text).semantic_query == "running shoes"
    assert result.usage.total_tokens == 15
    assert result.usage.reasoning_tokens == 2
    hook.assert_called_once()
    client.generate_content_once.assert_awaited_once()
    call = client.generate_content_once.call_args.kwargs
    assert call["model"] == "gemini-3.5-flash-lite"
    assert call["prompt"] == "running shoes"
    assert call["config"].response_json_schema == QueryUnderstandingOutput.model_json_schema()


def test_unknown_usage_stays_unknown():
    adapter, prepared, _ = setup_adapter(response(usage=False))
    result = asyncio.run(adapter.complete_once(prepared, timeout_s=1, on_dispatch=lambda: None))
    assert result.usage.input_tokens is None
    assert result.usage.total_tokens is None


@pytest.mark.parametrize("code,category", [
    (401, ErrorCategory.AUTHENTICATION), (403, ErrorCategory.PERMISSION_DENIED),
    (429, ErrorCategory.RATE_LIMITED), (503, ErrorCategory.PROVIDER_UNAVAILABLE),
    (400, ErrorCategory.PROVIDER_REJECTED),
])
def test_single_attempt_error_is_safe(code, category, caplog):
    adapter, prepared, client = setup_adapter(error=APIError(code, {"error": {"message": "synthetic-secret"}}))
    hook = MagicMock()
    with pytest.raises(ProviderAttemptError) as caught:
        asyncio.run(adapter.complete_once(prepared, timeout_s=1, on_dispatch=hook))
    assert caught.value.category == category
    assert "synthetic-secret" not in str(caught.value)
    assert "synthetic-secret" not in caplog.text
    hook.assert_called_once()
    client.generate_content_once.assert_awaited_once()


def test_empty_output_preserves_received_usage():
    adapter, prepared, _ = setup_adapter(response(text=""))
    with pytest.raises(ProviderAttemptError) as caught:
        asyncio.run(adapter.complete_once(prepared, timeout_s=1, on_dispatch=lambda: None))
    assert caught.value.usage.input_tokens == 10


def test_dispatch_denial_never_calls_provider():
    adapter, prepared, client = setup_adapter(response())
    with pytest.raises(ValueError):
        asyncio.run(adapter.complete_once(prepared, timeout_s=1, on_dispatch=MagicMock(side_effect=ValueError("denied"))))
    client.generate_content_once.assert_not_awaited()


@pytest.mark.parametrize("error,category", [
    (asyncio.TimeoutError(), ErrorCategory.ATTEMPT_TIMEOUT),
    (ConnectionError(), ErrorCategory.NETWORK_ERROR),
])
def test_timeout_and_connection_error(error, category):
    adapter, prepared, client = setup_adapter(error=error)
    with pytest.raises(ProviderAttemptError) as caught:
        asyncio.run(adapter.complete_once(prepared, timeout_s=1, on_dispatch=lambda: None))
    assert caught.value.category == category
    client.generate_content_once.assert_awaited_once()


def test_cancellation_propagates_and_close_is_idempotent():
    adapter, prepared, client = setup_adapter(error=asyncio.CancelledError())
    async def run():
        with pytest.raises(asyncio.CancelledError):
            await adapter.complete_once(prepared, timeout_s=1, on_dispatch=lambda: None)
        await adapter.aclose()
        await adapter.aclose()
    asyncio.run(run())
    client.aclose.assert_awaited_once()


def test_sdk_retry_configuration_and_lazy_credentials():
    adapter, prepared, _ = setup_adapter()
    key = MagicMock(return_value="synthetic-secret")
    adapter = GeminiAdapter(key)
    sdk = MagicMock()
    sdk.aio.models.generate_content = AsyncMock(return_value=response())
    with patch("shopassist.llm.gemini_client.genai.Client", return_value=sdk) as factory:
        assert key.call_count == 0
        asyncio.run(adapter.complete_once(prepared, timeout_s=1, on_dispatch=lambda: None))
    options = factory.call_args.kwargs["http_options"]
    assert options.retry_options.attempts == 1
    assert options.async_client_args["trust_env"] is False
    assert options.async_client_args["follow_redirects"] is False
    assert "transport" in options.async_client_args
    sdk.aio.models.generate_content.assert_awaited_once()


def test_real_sdk_mock_transport_sends_once_on_429():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": {"code": 429, "message": "synthetic-secret", "status": "RESOURCE_EXHAUSTED"}})
    client = GeminiClient(
        LLMSettings(_env_file=None, gemini_api_key="synthetic-secret"),
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1),
            async_client_args={"transport": httpx.MockTransport(handler), "trust_env": False, "follow_redirects": False},
        ),
    )
    _, prepared, _ = setup_adapter()
    adapter = GeminiAdapter(lambda: "synthetic-secret", client=client)
    async def run():
        try:
            with pytest.raises(ProviderAttemptError) as caught:
                await adapter.complete_once(prepared, timeout_s=1, on_dispatch=lambda: None)
            assert caught.value.category == ErrorCategory.RATE_LIMITED
        finally:
            await adapter.aclose()
    asyncio.run(run())
    assert len(calls) == 1
