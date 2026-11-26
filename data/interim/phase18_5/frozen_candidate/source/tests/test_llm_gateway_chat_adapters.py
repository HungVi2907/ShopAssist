"""OpenRouter/Groq conformance tests using HTTPX mock transports only."""
import asyncio
import json
from dataclasses import replace
from unittest.mock import MagicMock

import httpx
import pytest

from shopassist.llm_gateway.adapters.groq import GroqAdapter
from shopassist.llm_gateway.adapters.openrouter import OpenRouterAdapter
from shopassist.llm_gateway.config import GatewaySettings, Options
from shopassist.llm_gateway.errors import ErrorCategory, ProviderAttemptError
from shopassist.llm_gateway.registry import ProviderRegistry, ResolvedRoute
from shopassist.llm_gateway.schemas import GatewayRequest, SCHEMA_IDS
from shopassist.recommendation.schemas import LLMRecommendationPayload


@pytest.fixture(params=[("openrouter", OpenRouterAdapter), ("groq", GroqAdapter)])
def provider(request):
    return request.param


def prepared(adapter, kind):
    # Adapter conformance must not depend on an enabled/removed production route.
    route=ResolvedRoute(route_id='synthetic_'+kind,provider_profile=kind,provider=kind,
        endpoint={'groq':'https://api.groq.com/openai/v1','openrouter':'https://openrouter.ai/api/v1'}[kind],
        credential_env={'groq':'GROQ_API_KEY','openrouter':'OPENROUTER_API_KEY'}[kind],model='test-model',
        structured_mode='json_schema',schema_ids=frozenset({'phase12.recommendation.v1'}),enabled=False,
        approval='pending',evidence_valid_until=None,cost_class='unknown',cost={},limits={},
        options=Options(max_output_tokens=2048,reasoning_effort='low' if kind=='groq' else None).model_dump())
    request = GatewayRequest[LLMRecommendationPayload](
        task="recommendation_generation", request_id="req", task_id="task",
        schema_id="phase12.recommendation.v1", response_schema=LLMRecommendationPayload,
        system_prompt="system prompt", user_prompt="evidence context",
    )
    return adapter.prepare(request, route)


def envelope(content='{"overview":"ok","products":[]}'):
    return {"model": "test-model", "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
                      "completion_tokens_details": {"reasoning_tokens": 2}}}


def run_call(provider, handler):
    kind, cls = provider
    adapter = cls(lambda: "synthetic-secret", transport=httpx.MockTransport(handler))
    payload = prepared(adapter, kind)
    hook = MagicMock()
    async def run():
        try:
            return await adapter.complete_once(payload, timeout_s=1, on_dispatch=hook)
        finally:
            await adapter.aclose()
            await adapter.aclose()
    return asyncio.run(run()), hook


def test_wire_contract_and_success(provider):
    kind, _ = provider
    calls = []
    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["messages"] == [{"role": "system", "content": "system prompt"},
                                     {"role": "user", "content": "evidence context"}]
        schema = body["response_format"]["json_schema"]["schema"]
        assert schema["additionalProperties"] is False
        assert "comparison_note" in schema["$defs"]["LLMProductExplanation"]["required"]
        assert body["max_completion_tokens" if kind == "groq" else "max_tokens"] == 2048
        if kind == "groq":
            assert body["reasoning_effort"] == "low"
        else:
            assert "reasoning_effort" not in body
            assert body["provider"]["allow_fallbacks"] is False
        return httpx.Response(200, json=envelope())
    result, hook = run_call(provider, handler)
    assert LLMRecommendationPayload.model_validate_json(result.raw_text).overview == "ok"
    assert result.usage.total_tokens == 14
    assert result.usage.reasoning_tokens == 2
    assert len(calls) == hook.call_count == 1


@pytest.mark.parametrize("status,category", [
    (400, ErrorCategory.PROVIDER_REJECTED), (401, ErrorCategory.AUTHENTICATION),
    (403, ErrorCategory.PERMISSION_DENIED), (429, ErrorCategory.RATE_LIMITED),
    (503, ErrorCategory.PROVIDER_UNAVAILABLE), (302, ErrorCategory.PROVIDER_REJECTED),
])
def test_status_never_retries_or_repairs(provider, status, category, caplog):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"retry-after": "2.5", "location": "https://other.invalid"},
                              json={"error": "synthetic-secret"})
    with pytest.raises(ProviderAttemptError) as error:
        run_call(provider, handler)
    assert len(calls) == 1
    assert error.value.category == category
    assert error.value.retry_after_s == 2.5
    assert "synthetic-secret" not in str(error.value)
    assert "synthetic-secret" not in caplog.text


def test_missing_usage_and_zero_are_distinct(provider):
    def handler(request):
        body = envelope()
        body["usage"] = {"prompt_tokens": 0}
        return httpx.Response(200, json=body)
    result, _ = run_call(provider, handler)
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None


def test_empty_output_keeps_usage(provider):
    with pytest.raises(ProviderAttemptError) as error:
        run_call(provider, lambda request: httpx.Response(200, json=envelope("")))
    assert error.value.category == ErrorCategory.INVALID_OUTPUT
    assert error.value.usage.input_tokens == 10


def test_invalid_generated_json_keeps_usage_for_gateway_validation(provider):
    result, _ = run_call(provider, lambda request: httpx.Response(200, json=envelope("invalid json")))
    assert result.raw_text == "invalid json"
    assert result.usage.total_tokens == 14


def test_invalid_envelope_is_safe(provider):
    with pytest.raises(ProviderAttemptError) as error:
        run_call(provider, lambda request: httpx.Response(200, text="synthetic-secret"))
    assert error.value.category == ErrorCategory.INVALID_OUTPUT
    assert "synthetic-secret" not in str(error.value)


def test_explicit_json_object_mode(provider):
    kind, cls = provider
    adapter = cls(lambda: "synthetic-secret", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=envelope())))
    initial = prepared(adapter, kind)
    route = replace(initial.route, structured_mode="json_object")
    payload = adapter.prepare(initial.request, route)
    assert json.loads(payload.body)["response_format"] == {"type": "json_object"}
    asyncio.run(adapter.aclose())


def test_refusal_keeps_usage_and_does_not_retry(provider):
    calls = []
    def handler(request):
        calls.append(request)
        body = envelope()
        body["choices"][0]["message"]["refusal"] = "policy"
        return httpx.Response(200, json=body)
    with pytest.raises(ProviderAttemptError) as error:
        run_call(provider, handler)
    assert error.value.category == ErrorCategory.PROVIDER_REJECTED
    assert error.value.usage.total_tokens == 14
    assert len(calls) == 1


@pytest.mark.parametrize("error,category", [
    (httpx.ReadTimeout("synthetic-secret"), ErrorCategory.ATTEMPT_TIMEOUT),
    (httpx.ConnectError("synthetic-secret"), ErrorCategory.NETWORK_ERROR),
])
def test_transport_failure_once(provider, error, category):
    calls = []
    def handler(request):
        calls.append(request)
        raise error
    with pytest.raises(ProviderAttemptError) as caught:
        run_call(provider, handler)
    assert len(calls) == 1
    assert caught.value.category == category


def test_dispatch_denial_and_cancel(provider):
    kind, cls = provider
    calls = []
    def handler(request):
        calls.append(request)
        raise asyncio.CancelledError()
    adapter = cls(lambda: "synthetic-secret", transport=httpx.MockTransport(handler))
    payload = prepared(adapter, kind)
    async def run():
        try:
            with pytest.raises(ValueError):
                await adapter.complete_once(payload, timeout_s=1, on_dispatch=MagicMock(side_effect=ValueError("denied")))
            assert not calls
            with pytest.raises(asyncio.CancelledError):
                await adapter.complete_once(payload, timeout_s=1, on_dispatch=lambda: None)
        finally:
            await adapter.aclose()
        assert adapter._client.is_closed
    asyncio.run(run())
    assert len(calls) == 1
