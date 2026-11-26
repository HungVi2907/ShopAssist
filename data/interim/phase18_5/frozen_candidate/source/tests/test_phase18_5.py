import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import create_model

from ollama_support import native_config,envelope,MODEL,DIGEST
from shopassist.llm_gateway.native_runtime import build_native_gateway,verify_native_gateway
from shopassist.llm_gateway.schemas import GatewayRequest,TaskType
from shopassist.llm_gateway.errors import GatewayError,ErrorCategory
from shopassist.llm_gateway.config import GatewayConfigurationError,GatewaySettings,load_gateway_config
from shopassist.llm.query_understanding import QueryUnderstandingEngine
from shopassist.llm.transformation import ExtractedShoppingIntent
from shopassist.llm.schemas import QueryUnderstandingResult
from shopassist.recommendation.local import LocalRecommendationGenerator,selection_schema,SelectionFamily
from shopassist.recommendation.context import EvidenceContextBuilder
from shopassist.recommendation.core import RecommendationService
from shopassist.reranking.core import RerankedProduct,RerankingResult,RerankingStatus,RerankingMethod


def fixtures():
    return json.loads(Path('data/interim/phase18_4/fixtures/dev.json').read_text(encoding='utf8'))['cases']


def prepared(case):
    q=QueryUnderstandingResult.model_validate(case['query_result']);pp=[RerankedProduct(**p) for p in case['products']]
    _,store,_=EvidenceContextBuilder().build_context(q,None,pp)
    supplied={p.product_id:[e for e in store[p.product_id] if e.source_field in ('product_name','brand','category','discounted_price','rating','specifications')] for p in pp}
    return q,pp,selection_schema(supplied)


def transport(seen,*,bad_selection=None):
    def handler(req):
        seen.append(req)
        if req.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':MODEL,'digest':DIGEST}]})
        body=json.loads(req.content);assert req.url.path=='/api/chat'
        if 'product' in body['format']['properties']:
            assert body['options']['num_predict']==512
            return httpx.Response(200,json=envelope({'product':'running shoes','brand':'Puma','budget':None,'rating':None,'preferences':['lightweight']}))
        assert body['options']['num_predict']==256
        value={key:[1] for key in body['format']['properties']}
        if bad_selection is not None:value=bad_selection
        return httpx.Response(200,json=envelope(value))
    return httpx.MockTransport(handler)


@pytest.mark.parametrize('index',[0,1,2],ids=['one','three','five'])
def test_shared_gateway_q1s_and_r3(tmp_path,index):
    async def run():
        cases=fixtures();schemas=[prepared(cases[i])[2] for i in [0,1,2]];seen=[]
        client=httpx.AsyncClient(transport=transport(seen));g=build_native_gateway(native_config(tmp_path,schemas=schemas),client=client)
        assert await verify_native_gateway(g)
        qu=QueryUnderstandingEngine(gateway=g,gateway_native=True,catalog_brands={'Puma'})
        parsed=await qu.parse_query_async('I need lightweight Puma running shoes under 2000 rupees.',request_id='req',task_id='qu')
        assert parsed.is_valid and parsed.output.hard_constraints.max_price==2000 and parsed.output.hard_constraints.min_price is None
        assert parsed.output.hard_constraints.category=='Footwear' and parsed.output.hard_constraints.brand=='Puma'
        q,pp,_=prepared(cases[index]);local=LocalRecommendationGenerator(gateway=g)
        service=RecommendationService(gateway=g,local_generator=local)
        result=await service.generate(q,None,RerankingResult(status=RerankingStatus.SUCCESS,method=RerankingMethod.RRF,products=pp),top_k=len(pp),request_id='req',task_id='rec')
        assert result.status.value=='SUCCESS' and result.model_name==MODEL
        assert [p.product_id for p in result.products]==[p.product_id for p in pp]
        for a,b in zip(result.products,pp):
            assert a.discounted_price==b.discounted_price and a.rating==b.rating and a.brand==b.brand
            assert a.strengths[0].claim=='Catalog lists: '+b.product_name
            assert a.strengths[0].evidence_ids==[b.product_id+'-E1']
        assert local.client is None and qu._client is None and qu.intent_extractor is None
        assert len([r for r in seen if r.url.path=='/api/chat'])==2
        assert g.quota.snapshot('ollama')['in_flight']==0
        await service.aclose();await qu.aclose();assert not g._closed
        await g.aclose();await g.aclose();await client.aclose()
        events=[json.loads(s) for s in (tmp_path/'telemetry/gateway.jsonl').read_text().splitlines()]
        assert sum(e['event']=='attempt' for e in events)==2
        assert all(e.get('provider','ollama')=='ollama' for e in events)
        assert all('system_prompt' not in e and 'raw_text' not in e for e in events)
    asyncio.run(run())


@pytest.mark.parametrize('bad',[{}, {'p9':[1]}, {'p1':[1,1]}, {'p1':[999]}, {'p1':[True]}, {'p1':[1.0]}])
def test_gateway_structural_failure_falls_back_safely(tmp_path,bad):
    async def run():
        q,pp,schema=prepared(fixtures()[0]);seen=[]
        client=httpx.AsyncClient(transport=transport(seen,bad_selection=bad));g=build_native_gateway(native_config(tmp_path,schemas=[schema]),client=client)
        await verify_native_gateway(g);r,diag=await LocalRecommendationGenerator(gateway=g).evaluate(q,pp,request_id='req',task_id='rec')
        assert r.status.value=='DETERMINISTIC_FALLBACK' and 'gateway_error' in diag
        assert len([r for r in seen if r.url.path=='/api/chat'])==1
        assert g.quota.snapshot('ollama')['in_flight']==0
        await g.aclose();await client.aclose()
        events=[json.loads(s) for s in (tmp_path/'telemetry/gateway.jsonl').read_text().splitlines()]
        assert any(e['event']=='fallback' for e in events)
    asyncio.run(run())


def test_binding_rejects_unrelated_and_unapproved_dynamic_shapes(tmp_path):
    async def run():
        q,pp,schema=prepared(fixtures()[0]);seen=[];client=httpx.AsyncClient(transport=transport(seen))
        g=build_native_gateway(native_config(tmp_path,schemas=[schema]),client=client);await verify_native_gateway(g)
        for other in [create_model('Unrelated',p1=(list[int],...)),selection_schema({'one':[None]*2}),selection_schema({'one':[None]*4,'two':[None]*4})]:
            req=GatewayRequest(task=TaskType.RECOMMENDATION_GENERATION,request_id='req',task_id='rec',schema_id='phase12.catalog-selection.v2',response_schema=other,system_prompt='select',user_prompt='facts')
            with pytest.raises(GatewayError):await g.complete(req)
        assert len(seen)==1;await g.aclose();await client.aclose()
    asyncio.run(run())


def test_upstream_relevance_and_parent_gates_have_no_inference(tmp_path):
    async def run():
        q,pp,schema=prepared(fixtures()[0]);seen=[];client=httpx.AsyncClient(transport=transport(seen))
        g=build_native_gateway(native_config(tmp_path,schemas=[schema]),client=client);await verify_native_gateway(g)
        local=LocalRecommendationGenerator(gateway=g)
        for idx in [14,15,16,17,18,19]:
            cq,cp,_=prepared(fixtures()[idx]);result=await local.generate(cq,cp)
            assert result.status.value!='SUCCESS'
        with pytest.raises(GatewayError) as exc:await local.generate(q,pp,parent_deadline_mono=time.monotonic()-1)
        assert exc.value.deadline_scope=='parent' and not exc.value.attempts
        oversized=q.model_copy(update={'query':q.query+' '+('x'*6000)})
        with pytest.raises(GatewayError) as exc:await local.generate(oversized,pp,parent_deadline_mono=time.monotonic()-1)
        assert exc.value.deadline_scope=='parent'
        assert len(seen)==1;await g.aclose();await client.aclose()
    asyncio.run(run())


def test_quota_release_after_cancellation_and_no_cloud_dispatch(tmp_path):
    async def run():
        from test_llm_gateway_ollama_adapter import request
        event=asyncio.Event();release=asyncio.Event();seen=[]
        async def handler(req):
            seen.append(req.url.path)
            if req.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':MODEL,'digest':DIGEST}]})
            event.set();await release.wait();return httpx.Response(200,json=envelope({}))
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler));g=build_native_gateway(native_config(tmp_path),client=client);await verify_native_gateway(g)
        task=asyncio.create_task(g.complete(request()));await event.wait()
        with pytest.raises(GatewayError) as exc:await g.complete(request(task_id='other'))
        assert not exc.value.attempts
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert g.quota.snapshot('ollama')['in_flight']==0 and seen==['/api/tags','/api/chat']
        await g.aclose();await client.aclose()
    asyncio.run(run())


def test_app_explicit_native_composition_and_shutdown(tmp_path,monkeypatch):
    from test_phase18_lifecycle import patch_local_dependencies
    async def run():
        main,engine,cloud,_=patch_local_dependencies(monkeypatch,tmp_path)
        settings=native_config(tmp_path/'native');seen=[];client=httpx.AsyncClient(transport=transport(seen))
        gateway=build_native_gateway(settings,client=client)
        # Adapter is startup owned in the real path. Simulate that with MockTransport.
        next(iter(gateway.adapters.values())).owns_client=True
        monkeypatch.setattr(main,'GatewaySettings',lambda:settings)
        monkeypatch.setattr(main,'_build_gateway',lambda _:gateway)
        app=main.create_app()
        async with main.lifespan(app):
            assert app.state.query_engine.gateway is gateway and app.state.query_engine.gateway_native
            assert app.state.recommendation_service.gateway is gateway
            assert app.state.recommendation_service.local_generator.gateway is gateway
            assert app.state.recommendation_service.local_generator.client is None
        assert client.is_closed and gateway._closed and all(a.close_count==0 for a in cloud.values())
        engine.dispose.assert_awaited_once()
    asyncio.run(run())


def test_native_mode_never_silently_uses_legacy_when_disabled():
    from shopassist.api.main import _build_gateway
    with pytest.raises(GatewayConfigurationError):_build_gateway(GatewaySettings(_env_file=None,runtime='ollama_experimental',enabled=False))


@pytest.mark.parametrize('parent',[False,True],ids=['attempt_timeout','parent_deadline'])
def test_inflight_timeout_contract_and_quota_release(tmp_path,parent):
    async def run():
        from test_llm_gateway_ollama_adapter import request
        async def handler(req):
            if req.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':MODEL,'digest':DIGEST}]})
            await asyncio.sleep(1);return httpx.Response(200,json=envelope({}))
        settings=native_config(tmp_path);settings.attempt_timeout_seconds=1 if parent else .02
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler));g=build_native_gateway(settings,client=client);await verify_native_gateway(g)
        with pytest.raises(GatewayError) as exc:await g.complete(request(parent_deadline_mono=time.monotonic()+.02 if parent else None))
        if parent:assert exc.value.deadline_scope=='parent'
        else:assert exc.value.category==ErrorCategory.ATTEMPT_TIMEOUT
        assert g.quota.snapshot('ollama')['in_flight']==0 and len(exc.value.attempts)==1
        await g.aclose();await client.aclose()
    asyncio.run(run())


def test_ineligible_and_tampered_evidence_fail_without_cloud(tmp_path):
    import yaml
    from test_llm_gateway_ollama_adapter import request
    async def run():
        settings=native_config(tmp_path);path=settings.config_path;data=yaml.safe_load(path.read_text())
        data['routes']['native_query']['enabled']=False;path.write_text(yaml.safe_dump(data))
        seen=[];client=httpx.AsyncClient(transport=transport(seen));g=build_native_gateway(settings,client=client);await verify_native_gateway(g)
        with pytest.raises(GatewayError) as exc:await g.complete(request())
        assert not exc.value.attempts and len(seen)==1
        await g.aclose();await client.aclose()
        (tmp_path/'artifact.json').write_text('tampered')
        with pytest.raises(GatewayConfigurationError):build_native_gateway(settings)
    asyncio.run(run())


def test_native_profile_rejects_failover_and_extra_provider(tmp_path):
    import yaml
    settings=native_config(tmp_path);settings.auto_failover=True
    with pytest.raises(GatewayConfigurationError):load_gateway_config(settings)
    settings.auto_failover=False;settings.max_attempts_per_task=2
    with pytest.raises(GatewayConfigurationError):load_gateway_config(settings)
    settings.max_attempts_per_task=1
    data=yaml.safe_load(settings.config_path.read_text());data['providers']['external']={'kind':'groq','credential_env':'GROQ_API_KEY','endpoint':'https://api.groq.com/openai/v1'}
    settings.config_path.write_text(yaml.safe_dump(data))
    with pytest.raises(GatewayConfigurationError):load_gateway_config(settings)


def test_native_health_reports_configuration_and_identity_separately(tmp_path,monkeypatch):
    from test_phase18_lifecycle import patch_local_dependencies
    from types import SimpleNamespace
    from shopassist.api.routes import health
    async def run():
        main,_,_,_=patch_local_dependencies(monkeypatch,tmp_path)
        settings=native_config(tmp_path/'native');seen=[];client=httpx.AsyncClient(transport=transport(seen));g=build_native_gateway(settings,client=client)
        monkeypatch.setattr(main,'GatewaySettings',lambda:settings);monkeypatch.setattr(main,'_build_gateway',lambda _:g)
        monkeypatch.setattr(health,'_probe_database',AsyncMock(return_value=True))
        app=main.create_app()
        async with main.lifespan(app):
            app.state.tfidf_index=SimpleNamespace(is_fitted=True)
            result=await health.check_health(SimpleNamespace(app=app));body=json.loads(result.body)
            assert body['components']['ollama_identity']=='verified_recently' and body['components']['ollama_routes']=='eligible_experimental'
            next(iter(g.adapters.values())).verified_at-=settings.ollama_identity_ttl_seconds+1
            result=await health.check_health(SimpleNamespace(app=app))
            assert result.status_code==503 and json.loads(result.body)['components']['ollama_identity']=='unverified_or_stale'
        assert len(seen)==1;await client.aclose()
    asyncio.run(run())
