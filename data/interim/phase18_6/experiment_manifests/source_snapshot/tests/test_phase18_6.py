"""Offline refresh, numeric compatibility and canonical dynamic admission."""
import asyncio
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import time
from types import MappingProxyType
import httpx
import pytest
from ollama_support import native_config,envelope,MODEL,DIGEST
from test_llm_gateway_ollama_adapter import request,INTENT
from shopassist.llm_gateway.native_runtime import build_native_gateway,verify_native_gateway
from shopassist.llm_gateway.errors import GatewayError
from shopassist.preferences.safety import find_unsafe_query_exclusions,find_unsafe_negative_preferences
from shopassist.recommendation.local import selection_schema
from shopassist.llm_gateway.schemas import TaskType


@pytest.mark.parametrize('query',[
    'Shoes not exceeding 2000 rupees','Laptop under 50000 INR','Watch at least 1000 rupees',
])
def test_numeric_query_operators_are_not_exclusions(query):
    assert not find_unsafe_query_exclusions(query)


@pytest.mark.parametrize('query',[
    'Shoes without leather','Laptop but not gaming','Camera lens with no telephoto lenses',
    'Shoes not exceeding 2000 rupees without leather','Shoes not exceeding 16 GB',
    'Shoes not exceeding 2000 and not Nike',
])
def test_numeric_mask_retains_real_and_unverified_exclusions(query):
    assert find_unsafe_query_exclusions(query)==[query]
    assert find_unsafe_negative_preferences(['without leather'])


def test_budget_phrase_in_frozen_q1s_preferences_remains_encodable():
    from shopassist.llm.schemas import QueryUnderstandingResult,QueryUnderstandingOutput
    from shopassist.preferences.service import PreferenceRepresentationService
    class Encoder:
        model_name='BAAI/bge-small-en-v1.5';embedding_dimension=384
        def validate_model_compatibility(self):pass
        def encode(self,query):return [1.0]+[0.0]*383
    result=QueryUnderstandingResult(query='Shoes not exceeding 2000 rupees',output=QueryUnderstandingOutput(
        semantic_query='Shoes',hard_constraints={'category':'Footwear','max_price':2000},soft_preferences=['not exceeding 2000 rupees']))
    represented=PreferenceRepresentationService(encoder=Encoder()).represent(result)
    assert represented.status.value=='SUCCESS' and represented.normalized_preferences==['not exceeding 2000 rupees']
    assert result.output.hard_constraints.max_price==2000


@pytest.mark.parametrize('mode',['fresh','stale','unavailable','changed','concurrent','concurrent_failure','expired_parent','cancel','expired_approval'])
def test_identity_refresh_is_bounded_and_not_approval_renewal(tmp_path,mode):
    async def run():
        seen=[];entered=asyncio.Event();release=asyncio.Event()
        async def handler(req):
            seen.append(req.url.path)
            if req.url.path=='/api/chat':return httpx.Response(200,json=envelope(INTENT))
            entered.set()
            if mode in ('concurrent','concurrent_failure','cancel'):await release.wait()
            if mode in ('unavailable','concurrent_failure'):raise httpx.ConnectError('SENSITIVE detail')
            return httpx.Response(200,json={'models':[{'name':MODEL,'digest':'0'*64 if mode=='changed' else DIGEST}]})
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler));g=build_native_gateway(native_config(tmp_path),client=client)
        adapter=next(iter(g.adapters.values()))
        adapter.verified_at=adapter.clock()-(0 if mode=='fresh' else adapter.ttl+1)
        route=g.registry.primary_route(TaskType.QUERY_UNDERSTANDING)
        if mode=='expired_approval':
            g.registry._routes=MappingProxyType({**g.registry._routes,route.route_id:replace(route,evidence_valid_until=datetime.now(timezone.utc)-timedelta(seconds=1))})
        try:
            if mode in ('fresh','stale'):
                result=await g.complete(request());assert result.payload.product=='running shoes'
                assert seen==(['/api/chat'] if mode=='fresh' else ['/api/tags','/api/chat'])
            elif mode in ('concurrent','concurrent_failure'):
                first=asyncio.create_task(adapter.ensure_identity(route));await entered.wait()
                second=asyncio.create_task(adapter.ensure_identity(route));await asyncio.sleep(0)
                release.set();values=await asyncio.gather(first,second)
                assert values==[mode=='concurrent']*2 and seen==['/api/tags']
            elif mode=='cancel':
                task=asyncio.create_task(g.complete(request()));await entered.wait();task.cancel()
                with pytest.raises(asyncio.CancelledError):await task
                assert not adapter._identity_lock.locked() and g.quota.snapshot('ollama')['in_flight']==0
                release.set();assert await adapter.ensure_identity(route)
            else:
                with pytest.raises(GatewayError) as exc:
                    await g.complete(request(parent_deadline_mono=time.monotonic()-1 if mode=='expired_parent' else None))
                assert not exc.value.attempts
                assert seen==([] if mode in ('expired_parent','expired_approval') else ['/api/tags'])
                assert 'SENSITIVE' not in str(exc.value)
        finally:await g.aclose();await client.aclose()
    asyncio.run(run())


def test_parent_expiry_during_verification_cancels_control_request(tmp_path):
    async def run():
        cancelled=asyncio.Event()
        async def handler(req):
            try:await asyncio.sleep(2)
            finally:cancelled.set()
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler));g=build_native_gateway(native_config(tmp_path),client=client)
        with pytest.raises(GatewayError) as exc:await g.complete(request(parent_deadline_mono=time.monotonic()+.02))
        assert exc.value.deadline_scope=='parent' and cancelled.is_set() and not exc.value.attempts
        assert not next(iter(g.adapters.values()))._identity_lock.locked()
        await g.aclose();await client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('count',[2,4])
def test_additional_cardinalities_need_exact_approved_fingerprint(tmp_path,count):
    async def run():
        schema=selection_schema({str(i):[None]*4 for i in range(count)})
        async def handler(req):
            if req.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':MODEL,'digest':DIGEST}]})
            return httpx.Response(200,json=envelope({f'p{i}':[1] for i in range(1,count+1)}))
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler));g=build_native_gateway(native_config(tmp_path,schemas=[schema]),client=client)
        try:
            result=await g.complete(request(task=TaskType.RECOMMENDATION_GENERATION,schema_id='phase12.catalog-selection.v2',response_schema=schema))
            assert len(result.payload.model_dump())==count
            bad=selection_schema({str(i):[None]*5 for i in range(count)})
            with pytest.raises(GatewayError):await g.complete(request(task=TaskType.RECOMMENDATION_GENERATION,schema_id='phase12.catalog-selection.v2',response_schema=bad))
        finally:await g.aclose();await client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('mode,expected',[
    ('numeric','SUCCESS'),('qu_unavailable','INVALID_INPUT'),('qu_malformed','INVALID_INPUT'),
    ('qu_truncated','INVALID_INPUT'),('wrong_model','INVALID_INPUT'),('r3_malformed','DETERMINISTIC_FALLBACK'),
    ('unapproved_shape','DETERMINISTIC_FALLBACK'),('database','RETRIEVAL_FAILURE'),
    ('irrelevant','VALIDATION_FAILURE'),('exclusion','UNSUPPORTED_INTENT'),('parent','timeout'),
    ('cancel','CANCELLED'),('quota','INVALID_INPUT'),('reranking_failure','RETRIEVAL_FAILURE'),('no_results','NO_RESULTS'),
])
def test_real_api_boundary_with_controlled_failures(tmp_path,mode,expected):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from test_phase18_5 import prepared,fixtures
    from test_hybrid_retrieval import FakeEngine,FakeTFIDF,FakeEncoder
    from shopassist.api.main import create_app
    from shopassist.api.config import APISettings
    from shopassist.api.services.orchestrator import RecommendationOrchestrator
    from shopassist.llm.query_understanding import QueryUnderstandingEngine
    from shopassist.preferences.service import PreferenceRepresentationService
    from shopassist.retrieval.hybrid import HybridRetrievalService,HybridRetrievalResult,HybridRetrievalStatus
    from shopassist.reranking.core import RerankingService,MappingProductTextProvider
    from shopassist.recommendation.local import LocalRecommendationGenerator
    from shopassist.recommendation.core import RecommendationService
    async def run():
        q,pp,schema=prepared(fixtures()[0]);p=pp[0];seen=[];entered=asyncio.Event()
        async def handler(req):
            seen.append(req.url.path)
            if req.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':MODEL,'digest':DIGEST}]})
            import json
            body=json.loads(req.content);is_qu='product' in body['format']['properties']
            if mode=='cancel':entered.set();await asyncio.sleep(60)
            if mode=='parent':await asyncio.sleep(1)
            if is_qu and mode=='qu_unavailable':raise httpx.ConnectError('SENSITIVE')
            value={'product':'running shoes','brand':None,'budget':None,'rating':None,'preferences':[]} if is_qu else {'p1':[1]}
            changes={}
            if is_qu and mode=='qu_malformed' or not is_qu and mode=='r3_malformed':value={}
            if is_qu and mode=='qu_truncated':changes['done_reason']='length'
            if is_qu and mode=='wrong_model':changes['model']='wrong'
            return httpx.Response(200,json=envelope(value,**changes))
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        approved=selection_schema({'x':[None]*13}) if mode=='unapproved_shape' else schema
        g=build_native_gateway(native_config(tmp_path,schemas=[approved]),client=client)
        qu=QueryUnderstandingEngine(gateway=g,gateway_native=True)
        name='Lightning cable' if mode=='irrelevant' else p.product_name
        row=(p.product_id,name,p.category,p.brand,p.discounted_price,p.rating,.1,
            p.metadata.get('retail_price'),p.metadata.get('product_specifications'),p.metadata.get('product_description'))
        hybrid=HybridRetrievalService(FakeEngine([row]),FakeTFIDF(),query_encoder=FakeEncoder())
        if mode=='no_results':hybrid=HybridRetrievalService(FakeEngine([]),FakeTFIDF(),query_encoder=FakeEncoder())
        if mode=='database':hybrid.retrieve=AsyncMock(return_value=HybridRetrievalResult(status=HybridRetrievalStatus.RETRIEVAL_FAILURE))
        settings=APISettings(_env_file=None,api_request_timeout_seconds=.02 if mode=='parent' else 90)
        service=RecommendationService(gateway=g,local_generator=LocalRecommendationGenerator(gateway=g))
        orchestrator=RecommendationOrchestrator(qu,PreferenceRepresentationService(),hybrid,
            RerankingService(text_provider=MappingProductTextProvider(texts={p.product_id:p.retrieval_text})),service,settings=settings)
        orchestrator._enrich_product_presentation=AsyncMock(return_value={})
        if mode=='reranking_failure':
            from shopassist.reranking.core import RerankingResult,RerankingStatus
            orchestrator.reranking_service.rerank=lambda **kw:RerankingResult(status=RerankingStatus.RETRIEVAL_FAILURE,method='RRF')
        held=None
        if mode=='quota':
            from shopassist.llm_gateway.config import Limits
            held=g.quota.reserve('ollama',Limits(max_in_flight=1))
        app=create_app(settings);app.state.orchestrator=orchestrator
        from shopassist.api.dependencies import get_settings
        app.dependency_overrides[get_settings]=lambda:settings
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as api:
            pending=api.post('/api/v1/recommend',json={'query':'running shoes without leather' if mode=='exclusion' else 'running shoes not exceeding 2000 rupees','top_k':1})
            if mode=='cancel':
                task=asyncio.create_task(pending);await entered.wait();task.cancel()
                with pytest.raises(asyncio.CancelledError):await task
                assert g.quota.snapshot('ollama')['in_flight']==0
                await g.aclose();await client.aclose();return
            response=await pending
        if mode=='parent':assert response.status_code==504
        else:assert response.status_code==200 and response.json()['status']==expected
        assert 'SENSITIVE' not in response.text
        if held is not None:g.quota.release(held)
        assert seen.count('/api/chat')<=2 and g.quota.snapshot('ollama')['in_flight']==0
        if mode=='database':assert response.json()['usage']['total_tokens']==21
        if mode in ('exclusion','irrelevant'):assert seen.count('/api/chat')==(0 if mode=='exclusion' else 1)
        await g.aclose();await client.aclose()
    asyncio.run(run())
