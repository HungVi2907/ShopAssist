"""SDK boundary, telemetry, safe error output, and bounded retry tests."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from google.genai.errors import APIError
from shopassist.llm.config import LLMSettings
from shopassist.llm.gemini_client import GeminiClient
from shopassist.llm.query_understanding import QueryUnderstandingEngine
from shopassist.llm.schemas import QueryUnderstandingOutput


def settings(retries=0):
    return LLMSettings(_env_file=None, GEMINI_API_KEY="private-test-secret-value", GEMINI_MAX_RETRIES=retries)


def response(text):
    return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(prompt_token_count=50,candidates_token_count=20,total_token_count=70),model_version="test-version")


def client_with(side_effect=None, result=None, retries=0):
    client=GeminiClient(settings(retries))
    client._client=MagicMock()
    client._client.aio.models.generate_content=AsyncMock(side_effect=side_effect,return_value=result)
    return client


@pytest.mark.parametrize("code,retries,expected_attempts",[(429,2,3),(503,1,2),(401,2,1),(403,2,1),(400,2,1)])
def test_status_retry_exhaustion_is_bounded(code,retries,expected_attempts):
    client=client_with(side_effect=APIError(code,{"error":{"message":"private-test-secret-value"}}),retries=retries)
    attempts=[];diag={}
    with patch("shopassist.llm.gemini_client.asyncio.sleep",new_callable=AsyncMock):
        with pytest.raises(RuntimeError) as exc:
            asyncio.run(client.generate_structured_async("pen",QueryUnderstandingOutput,on_attempt=lambda:attempts.append(1),diagnostics=diag))
    assert len(attempts) == expected_attempts and diag["attempts"] == expected_attempts
    assert "private-test-secret-value" not in str(exc.value)


@pytest.mark.parametrize("text,json_valid,schema_valid",[("not json",False,None),('{"semantic_query":"pen","hard_constraints":{"max_price":-2}}',True,False),("",False,None)])
def test_usage_counted_even_when_response_validation_fails(text,json_valid,schema_valid):
    client=client_with(result=response(text)); diag={}; usages=[]
    with pytest.raises(ValueError):
        asyncio.run(client.generate_structured_async("pen",QueryUnderstandingOutput,on_response=usages.append,diagnostics=diag))
    assert usages[0].total_tokens == 70
    assert diag["response_received"] is True and diag["json_valid"] is json_valid and diag["schema_valid"] is schema_valid


def test_timeout_then_success_has_distinct_attempt_and_total_timings():
    client=client_with(side_effect=[asyncio.TimeoutError(),response('{"semantic_query":"pen"}')],retries=1);diag={}
    with patch("shopassist.llm.gemini_client.asyncio.sleep",new_callable=AsyncMock):
        result=asyncio.run(client.generate_structured_async("pen",QueryUnderstandingOutput,diagnostics=diag))
    assert diag["attempts"] == 2 and diag["retry_delay_ms"] > 0
    assert diag["schema_valid"] and diag["model_version"] == "test-version"
    assert diag["end_to_end_ms"] >= result[2]-.02


def test_decimal_retry_delay_is_observed():
    client=client_with(side_effect=[APIError(429,{"error":{"message":"retryDelay: 2.25s"}}),response('{"semantic_query":"pen"}')],retries=1)
    with patch("shopassist.llm.gemini_client.asyncio.sleep",new_callable=AsyncMock) as sleep:
        asyncio.run(client.generate_structured_async("pen",QueryUnderstandingOutput))
    assert sleep.call_args.args[0] >= 3.25


def test_credentials_excluded_from_settings_repr_and_serialization():
    s=settings()
    assert "private-test-secret-value" not in repr(s) and "private-test-secret-value" not in s.model_dump_json()


def test_engine_error_is_safe_for_public_output_and_logs(caplog):
    fake=MagicMock();fake.generate_structured_async=AsyncMock(side_effect=RuntimeError("private-test-secret-value; user-data; raw provider text"))
    engine=QueryUnderstandingEngine(client=fake,settings=settings(),catalog_brands=set())
    result=asyncio.run(engine.parse_query_async("private user query"))
    assert not result.is_valid and result.output.needs_clarification
    assert "private-test-secret-value" not in result.model_dump_json()
    assert "raw provider text" not in result.output.clarification_reason
    assert "private user query" not in caplog.text


@pytest.mark.parametrize("query",["x"*501,None,123,True,"   "])
def test_invalid_input_never_reaches_provider(query):
    fake=MagicMock();fake.generate_structured_async=AsyncMock()
    result=asyncio.run(QueryUnderstandingEngine(client=fake,settings=settings(),catalog_brands=set()).parse_query_async(query))
    assert not result.is_valid and fake.generate_structured_async.await_count == 0


def test_missing_configuration_and_invalid_key_do_not_leak():
    with pytest.raises(ValueError): GeminiClient(LLMSettings(_env_file=None,GEMINI_API_KEY=""))


def test_model_discovery_does_not_accept_substring_alias():
    client=client_with();client._client.models.list.return_value=[SimpleNamespace(name="models/gemini-3.1-flash-lite-preview")]
    assert client.verify_model_availability("gemini-3.1-flash-lite")["is_available"] is False


@pytest.mark.parametrize("failed",[False,True])
def test_sync_generation_closes_on_own_loop_even_on_failure(failed):
    client=GeminiClient(settings()); loops=[]
    async def generate(**kwargs):
        loops.append(asyncio.get_running_loop())
        if failed: raise ValueError("bad response")
        return "result"
    async def close(): loops.append(asyncio.get_running_loop())
    client.generate_structured_async=generate;client.aclose=close
    if failed:
        with pytest.raises(ValueError): client.generate_structured("pen",QueryUnderstandingOutput)
    else:
        assert client.generate_structured("pen",QueryUnderstandingOutput) == "result"
    assert len(loops) == 2 and loops[0] is loops[1] and loops[0].is_closed()


def test_sync_engine_closes_on_parse_loop():
    engine=QueryUnderstandingEngine(client=MagicMock(),settings=settings(),catalog_brands=set());loops=[]
    async def parse(query,**kwargs): loops.append(asyncio.get_running_loop());return "parsed"
    async def close(): loops.append(asyncio.get_running_loop())
    engine.parse_query_async=parse;engine.aclose=close
    assert engine.parse_query("pen") == "parsed"
    assert len(loops) == 2 and loops[0] is loops[1] and loops[0].is_closed()
