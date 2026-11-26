"""Offline native recommendation contracts and source-backed assembly checks."""
import asyncio
import copy
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from shopassist.llm.schemas import QueryUnderstandingResult,QueryUnderstandingOutput
from shopassist.reranking.core import RerankedProduct,RerankingResult,RerankingStatus
from shopassist.recommendation.local import LocalRecommendationGenerator,MODEL
from shopassist.recommendation.core import RecommendationService
from shopassist.recommendation.schemas import RecommendationStatus


def fixture():
    q=QueryUnderstandingResult(query='running shoes',output=QueryUnderstandingOutput(semantic_query='running shoes'))
    p=RerankedProduct(product_id='P001',product_name='Puma Running Shoes',category='Footwear',brand='Puma',
        discounted_price=1900,rating=None,original_rank=1,reranked_rank=1,rrf_score=.1,
        sources={},metadata={},retrieval_text='',final_score=.1,score_components={})
    return q,[p]


def run(payload=None,*,candidate='R3',error=None,alter=None,query=None,products=None):
    async def task():
        q,pp=fixture();q=query or q;pp=products or pp;requests=[]
        def handler(request):
            requests.append(request)
            assert request.url.path=='/api/chat'
            body=json.loads(request.content)
            assert body['options']['temperature']==0 and body['options']['seed']==42
            assert body['stream'] is False
            if error:raise error
            default={'p1':[1]} if candidate=='R3' else {'explanations':[{'product_index':1,'evidence_indices':[1],'reason':'Puma Running Shoes'}]}
            data={'model':MODEL,'done':True,'done_reason':'stop','message':{'content':json.dumps(payload if payload is not None else default)},'prompt_eval_count':100,'eval_count':30}
            if alter:data.update(alter)
            return httpx.Response(200,json=data)
        client=httpx.AsyncClient(base_url='http://localhost:11434',transport=httpx.MockTransport(handler))
        generator=LocalRecommendationGenerator(client,candidate=candidate)
        result,diag=await generator.evaluate(q,pp)
        await generator.aclose();assert not client.is_closed
        await client.aclose()
        return result,diag,requests
    return asyncio.run(task())


def test_authoritative_metadata_order_evidence_and_one_call():
    result,diag,requests=run()
    assert result.status==RecommendationStatus.SUCCESS and len(requests)==1
    p=result.products[0]
    assert (p.product_id,p.product_name,p.brand,p.category,p.discounted_price,p.rating,p.currency,p.original_rank,p.reranked_rank,p.rrf_score)==('P001','Puma Running Shoes','Puma','Footwear',1900,None,'INR',1,1,.1)
    assert p.strengths[0].evidence_ids==['P001-E1']
    assert p.strengths[0].claim=='Catalog lists: Puma Running Shoes'
    assert result.usage.total_tokens==130 and result.model_name==MODEL
    assert any('does not specify a rating' in c.claim for c in p.limitations)
    assert not any('poor' in c.claim for c in p.limitations)


@pytest.mark.parametrize('payload',[
    {'explanations':[]}, {'explanations':[{'product_index':2,'evidence_indices':[1]}]},
    {'explanations':[{'product_index':1,'evidence_indices':[]}]},
    {'explanations':[{'product_index':1,'evidence_indices':[999]}]},
    {'explanations':[{'product_index':1,'evidence_indices':[1,1]}]},
    {'explanations':[{'product_index':1,'evidence_indices':[1]},{'product_index':1,'evidence_indices':[1]}]},
    {}, {'p1':[]}, {'p1':[999]}, {'p1':[1,1]}, {'p2':[1]}, {'p1':[1,2,3,4]},
])
def test_invalid_selection_falls_back_without_second_call(payload):
    result,diag,requests=run(payload)
    assert result.status==RecommendationStatus.DETERMINISTIC_FALLBACK and len(requests)==1
    assert 'generation_error' in diag
    text=result.model_dump_json().lower()
    assert 'authentic' not in text and 'meeting query retrieval criteria' not in text


@pytest.mark.parametrize('claim',['Highly durable','Excellent battery life','Authentic product','Waterproof','Best performance','Compatible with all devices','This costs less than all others','This product is not waterproof'])
def test_free_unsupported_claims_are_not_released(claim):
    result,diag,_=run({'explanations':[{'product_index':1,'evidence_indices':[1],'reason':claim}]},candidate='R2')
    assert result.status==RecommendationStatus.DETERMINISTIC_FALLBACK
    assert claim not in result.model_dump_json()


def test_exact_fact_reason_can_be_accepted():
    result,_,_=run({'explanations':[{'product_index':1,'evidence_indices':[1],'reason':'Puma Running Shoes'}]},candidate='R2')
    assert result.status==RecommendationStatus.SUCCESS


def test_vietnamese_type_guard_is_bounded():
    from shopassist.recommendation.local import relevance_issue
    q,pp=fixture();q.query='Tôi muốn xem giày chạy bộ';q.output.semantic_query=q.query
    assert relevance_issue(q,pp) is None
    pp[0].product_name='Lightning Cable'
    assert relevance_issue(q,pp)


def test_duplicate_keys_are_rejected():
    result,_,_=run(alter={'message':{'content':'{"p1":[1],"p1":[2]}'}})
    assert result.status==RecommendationStatus.DETERMINISTIC_FALLBACK


def test_missing_explanation_fallback_does_not_imply_authenticity_or_suitability():
    from shopassist.recommendation.context import EvidenceContextBuilder
    from shopassist.recommendation.validation import GroundednessValidator
    from shopassist.recommendation.schemas import LLMRecommendationPayload
    q,pp=fixture();p2=copy.deepcopy(pp[0]);p2.product_id='P002';pp.append(p2)
    _,store,flat=EvidenceContextBuilder().build_context(q,None,pp)
    payload=LLMRecommendationPayload(overview='Catalog candidates',products=[{'product_id':'P001','summary_reason':'Catalog item','strengths':[],'limitations':[]}])
    result=GroundednessValidator().validate_and_merge(payload,pp,store,flat)
    missing=result.products[1]
    assert 'authentic' not in missing.model_dump_json().casefold()
    assert missing.strengths[0].evidence_ids==['P002-E4']
    assert 'matches the requested' not in missing.summary_reason


@pytest.mark.parametrize('alter',[
    {'done_reason':'length'}, {'done':False}, {'model':'wrong-model'},
    {'message':{'content':'{invalid'}},{'message':{'content':''}},
])
def test_malformed_truncated_and_reported_model_failure(alter):
    result,diag,requests=run(alter=alter)
    assert result.status==RecommendationStatus.DETERMINISTIC_FALLBACK and len(requests)==1


@pytest.mark.parametrize('error',[httpx.ConnectError('unavailable'),httpx.ReadTimeout('timed out')])
def test_transport_fallback(error):
    result,_,requests=run(error=error)
    assert result.status==RecommendationStatus.DETERMINISTIC_FALLBACK and len(requests)==1
    assert result.model_name is None


@pytest.mark.parametrize('kind',['invalid','clarify','foreign','wrong_type','hard_price','rating','mandatory_feature','context'])
def test_upstream_and_mandatory_gates_do_not_call_model(kind):
    q,pp=fixture()
    if kind=='invalid':q.is_valid=False
    if kind=='clarify':q.output.needs_clarification=True
    if kind=='foreign':q.output.hard_constraints.currency='USD'
    if kind=='wrong_type':pp[0].product_name='Lightning Cable';q.output.semantic_query='wireless charging pad'
    if kind=='hard_price':q.output.hard_constraints.max_price=500
    if kind=='rating':q.output.hard_constraints.min_rating=4
    if kind=='mandatory_feature':q.query='running shoes must be waterproof'
    if kind=='context':q.query+=' x'*5000
    result,_,requests=run(query=q,products=pp)
    assert not requests and result.status!=RecommendationStatus.SUCCESS


def test_reordered_or_cross_product_indices_fail_and_metadata_order_survives():
    q,pp=fixture();second=copy.deepcopy(pp[0]);second.product_id='P002';second.reranked_rank=2;pp.append(second)
    payload={'explanations':[{'product_index':2,'evidence_indices':[1]},{'product_index':1,'evidence_indices':[1]}]}
    result,_,_=run(payload,query=q,products=pp)
    assert result.status==RecommendationStatus.DETERMINISTIC_FALLBACK
    assert [p.product_id for p in result.products]==['P001','P002']


def test_parent_deadline_cancellation_and_lifecycle():
    async def task():
        q,pp=fixture();client=httpx.AsyncClient(base_url='http://localhost:11434',transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(asyncio.CancelledError())))
        generator=LocalRecommendationGenerator(client)
        with pytest.raises(asyncio.TimeoutError):await generator.generate(q,pp,parent_deadline_mono=time.monotonic()-1)
        with pytest.raises(asyncio.CancelledError):await generator.generate(q,pp)
        await client.aclose()
        owned=LocalRecommendationGenerator();await owned.aclose();assert owned.client.is_closed
    asyncio.run(task())


def test_service_local_selection_and_upstream_invalid_do_not_create_legacy_provider():
    async def task():
        q,pp=fixture();local=AsyncMock();local.generate.return_value='sentinel'
        service=RecommendationService(local_generator=local)
        from shopassist.reranking.core import RerankingMethod
        rr=RerankingResult(status=RerankingStatus.SUCCESS,products=pp,method=RerankingMethod.RRF)
        assert service.provider is None
        assert await service.generate(q,None,rr)=='sentinel'
        q.is_valid=False
        assert (await service.generate(q,None,rr)).status==RecommendationStatus.INVALID_INPUT
        local.generate.assert_awaited_once()
        await service.aclose();local.aclose.assert_awaited_once()
    asyncio.run(task())


def test_preference_failure_is_terminal_even_if_reranking_is_inconsistent():
    from types import SimpleNamespace
    from shopassist.reranking.core import RerankingMethod
    async def task():
        q,pp=fixture();local=AsyncMock();service=RecommendationService(local_generator=local)
        rr=RerankingResult(status=RerankingStatus.SUCCESS,method=RerankingMethod.RRF,products=pp)
        pref=SimpleNamespace(status='EMBEDDING_FAILURE')
        result=await service.generate(q,pref,rr)
        assert result.status==RecommendationStatus.GENERATION_FAILURE
        local.generate.assert_not_awaited()
    asyncio.run(task())
