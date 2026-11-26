import asyncio
import json
import copy
import pytest
import httpx
from pydantic import ValidationError
from ollama_support import native_config,envelope,MODEL,DIGEST
from shopassist.llm_gateway.config import Provider,GatewaySettings,GatewayConfigurationError,load_gateway_config
from shopassist.llm_gateway.native_runtime import build_native_gateway,verify_native_gateway
from shopassist.llm_gateway.errors import GatewayError,ProviderAttemptError,ErrorCategory
from shopassist.llm_gateway.schemas import GatewayRequest,TaskType
from shopassist.llm.transformation import ExtractedShoppingIntent

INTENT={'product':'running shoes','brand':'Puma','budget':'under 2000','rating':None,'preferences':['lightweight']}


def request(**changes):
    values=dict(task=TaskType.QUERY_UNDERSTANDING,profile='default',request_id='request',task_id='query',
        schema_id='phase8.intent.flat.v1',response_schema=ExtractedShoppingIntent,system_prompt='extract',user_prompt='shoes under 2000')
    values.update(changes);return GatewayRequest(**values)


def exercise(tmp_path,*,response=None,error=None,raw=None):
    async def run():
        seen=[]
        def handler(req):
            seen.append(req)
            if req.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':MODEL,'digest':DIGEST}]})
            if error:raise error
            return httpx.Response(200,content=raw) if raw is not None else httpx.Response(200,json=response or envelope(INTENT))
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway=build_native_gateway(native_config(tmp_path),client=client)
        assert await verify_native_gateway(gateway)
        try:result=await gateway.complete(request());return result,seen
        finally:await gateway.aclose();assert not client.is_closed;await client.aclose()
    return asyncio.run(run())


def test_exact_native_payload_usage_and_schema(tmp_path):
    result,seen=exercise(tmp_path)
    body=json.loads(seen[1].content)
    assert str(seen[1].url)=='http://127.0.0.1:11434/api/chat'
    assert body['format']==ExtractedShoppingIntent.model_json_schema()
    assert body['options']=={'temperature':0,'seed':42,'num_ctx':4096,'num_predict':512}
    assert not body['stream'] and 'Authorization' not in seen[1].headers
    assert result.provider=='ollama' and result.reported_model==MODEL
    assert result.usage.total_tokens==21 and result.usage.estimated_cost_usd is None
    assert result.attempts[0].timings.total_ms==1
    assert result.attempts[0].schema_fingerprint==request().schema_fingerprint


@pytest.mark.parametrize('change',[
    {'message':{}},{'message':{'content':None}},{'message':{'content':5}},{'message':{'content':''}},
    {'done':False},{'done_reason':'length'},{'done':1},{'model':'wrong'},
    {'prompt_eval_count':True},{'eval_count':-1},{'total_tokens':999},{'eval_duration':-1},
    {'total_duration':1},{'message':{'content':'{"product":null}'}},
    {'message':{'content':'{"product":"shoe","product":"boot"}'}},
    {'message':{'content':'NaN'}},{'prompt_eval_count':4096},
])
def test_native_invalid_responses_fail_once(tmp_path,change):
    with pytest.raises(GatewayError) as exc:exercise(tmp_path,response=envelope(INTENT,**change))
    assert len(exc.value.attempts)==1
    assert exc.value.category in (ErrorCategory.INVALID_OUTPUT,ErrorCategory.INCOMPATIBLE_ROUTE)


@pytest.mark.parametrize('raw',[b'not json',b'{"done":true,"done":false}',b'[]',b'{"error":"x"}',b'x'*1000001],ids=['invalid','duplicate','list','error','oversized'])
def test_bad_envelopes_and_limits(tmp_path,raw):
    with pytest.raises(GatewayError):exercise(tmp_path,raw=raw)


@pytest.mark.parametrize('error',[httpx.ReadTimeout('secret'),httpx.ConnectError('secret')])
def test_typed_failures_do_not_expose_details(tmp_path,error):
    with pytest.raises(GatewayError) as exc:exercise(tmp_path,error=error)
    assert 'secret' not in str(exc.value) and len(exc.value.attempts)==1


def test_missing_usage_is_unknown(tmp_path):
    data=envelope(INTENT);data.pop('prompt_eval_count');data.pop('eval_count')
    result,_=exercise(tmp_path,response=data)
    assert result.usage.input_tokens is None and result.usage.output_tokens is None and result.usage.total_tokens is None


@pytest.mark.parametrize('change,reported',[({'model':'wrong'},'wrong'),({'message':{'content':'{}'}},MODEL)])
def test_failed_response_retains_known_attribution_and_timing(tmp_path,change,reported):
    with pytest.raises(GatewayError) as exc:exercise(tmp_path,response=envelope(INTENT,**change))
    attempt=exc.value.attempts[0]
    assert attempt.reported_model==reported and attempt.timings.total_ms==1
    assert attempt.usage.total_tokens==21


@pytest.mark.parametrize('url',['http://evil.example:11434','http://localhost.evil:11434','http://user:pass@127.0.0.1:11434',
    'http://127.0.0.1:11434?key=x','http://127.0.0.1:11434/v1','http://127.0.0.1:11434/#x','https://unapproved.example','http://127.0.0.1:11434\\@evil'])
def test_unsafe_endpoint_rejection(url):
    with pytest.raises(ValidationError):Provider(kind='ollama',endpoint=url,model_digest=DIGEST)


def test_remote_endpoint_requires_explicit_approval_and_fixed_credential():
    data={'kind':'ollama','endpoint':'https://ollama.example.test','credential_env':'OLLAMA_API_KEY','model_digest':DIGEST}
    with pytest.raises(ValidationError):Provider.model_validate(data)
    assert Provider.model_validate(data,context={'ollama_approved_endpoints':[data['endpoint']]}).kind=='ollama'
    data['credential_env']='GEMINI_API_KEY'
    with pytest.raises(ValidationError):Provider.model_validate(data,context={'ollama_approved_endpoints':[data['endpoint']]})


def test_digest_mismatch_and_staleness_prevent_dispatch(tmp_path):
    async def run():
        seen=[];bad=True
        def handler(req):
            seen.append(req.url.path)
            return httpx.Response(200,json={'models':[{'name':MODEL,'digest':'0'*64 if bad else DIGEST}]})
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler));g=build_native_gateway(native_config(tmp_path),client=client)
        assert not await verify_native_gateway(g)
        with pytest.raises(GatewayError) as exc:await g.complete(request())
        assert not exc.value.attempts
        bad=False;assert await verify_native_gateway(g)
        adapter=next(iter(g.adapters.values()));adapter.verified_at-=adapter.ttl+1
        with pytest.raises(GatewayError):await g.complete(request())
        assert seen==['/api/tags','/api/tags'];await g.aclose();await client.aclose()
    asyncio.run(run())


def test_remote_authentication_is_bound_and_redirects_are_not_followed(tmp_path):
    async def run():
        from dataclasses import replace
        from shopassist.llm_gateway.adapters.ollama import OllamaAdapter
        from shopassist.llm_gateway.registry import ProviderRegistry
        from shopassist.llm_gateway.experiment_factory import experiment_schema_bindings
        provider=Provider.model_validate({'kind':'ollama','endpoint':'https://ollama.example.test','credential_env':'OLLAMA_API_KEY','model_digest':DIGEST},
            context={'ollama_approved_endpoints':['https://ollama.example.test']})
        seen=[]
        def handler(req):
            seen.append(req);assert req.url.host=='ollama.example.test'
            assert req.headers['authorization']=='Bearer synthetic-native-key'
            if req.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':MODEL,'digest':DIGEST}]})
            return httpx.Response(307,headers={'location':'https://evil.example/api/chat'})
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=True)
        adapter=OllamaAdapter(provider,MODEL,credential=lambda:'synthetic-native-key',client=client)
        assert await adapter.verify_model()
        route=ProviderRegistry(native_config(tmp_path),experiment_schema_bindings()).primary_route(TaskType.QUERY_UNDERSTANDING)
        route=replace(route,endpoint=provider.endpoint,credential_env=provider.credential_env)
        prepared=adapter.prepare(request(),route)
        with pytest.raises(ProviderAttemptError) as exc:await adapter.complete_once(prepared,timeout_s=1,on_dispatch=lambda:None)
        assert exc.value.category==ErrorCategory.PROVIDER_REJECTED and len(seen)==2
        await adapter.aclose();await client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('status,category',[(401,ErrorCategory.AUTHENTICATION),(429,ErrorCategory.RATE_LIMITED),(500,ErrorCategory.PROVIDER_UNAVAILABLE)])
def test_http_error_classification(tmp_path,status,category):
    async def run():
        def handler(req):
            return httpx.Response(200,json={'models':[{'name':MODEL,'digest':DIGEST}]}) if req.url.path=='/api/tags' else httpx.Response(status,json={'error':'private-provider-text'})
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler));g=build_native_gateway(native_config(tmp_path),client=client);await verify_native_gateway(g)
        with pytest.raises(GatewayError) as exc:await g.complete(request())
        assert exc.value.category==category and len(exc.value.attempts)==1 and 'private-provider-text' not in str(exc.value)
        assert g.quota.snapshot('ollama')['in_flight']==0
        await g.aclose();await client.aclose()
    asyncio.run(run())
