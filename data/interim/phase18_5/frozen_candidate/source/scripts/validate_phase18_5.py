"""Supervised local Gateway validation. No production config or T17 writes.

Experimental route permission is tied to prior real native evidence, fresh tags,
passing offline tests and exact schema fingerprints through the normal loader.
"""
import argparse
import asyncio
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import time

import httpx
import yaml

from shopassist.llm_gateway.config import GatewaySettings,Options
from shopassist.llm_gateway.native_runtime import build_native_gateway,verify_native_gateway
from shopassist.llm.query_understanding import QueryUnderstandingEngine
from shopassist.llm.transformation import ExtractedShoppingIntent
from shopassist.llm.schemas import QueryUnderstandingResult
from shopassist.recommendation.context import EvidenceContextBuilder
from shopassist.recommendation.local import LocalRecommendationGenerator,selection_schema
from shopassist.recommendation.core import RecommendationService
from shopassist.reranking.core import (RerankedProduct,RerankingResult,RerankingStatus,RerankingMethod,
    RerankingService,MappingProductTextProvider)
from shopassist.retrieval.hybrid import HybridCandidate,HybridRetrievalResult,HybridRetrievalStatus
from shopassist.preferences.service import PreferenceRepresentationService

MODEL='qwen2.5:1.5b-instruct-local'
DIGEST='d010eb818583111cfafeb3523cc17802f85dcb7f4fe5e8ecdd4927dca40e3174'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
fp=lambda model:hashlib.sha256(json.dumps(model.model_json_schema(),sort_keys=True).encode()).hexdigest()


def fixture(case):
    query=QueryUnderstandingResult.model_validate(case['query_result']);products=[RerankedProduct(**p) for p in case['products']]
    _,store,_=EvidenceContextBuilder().build_context(query,None,products)
    supplied={p.product_id:[e for e in store[p.product_id] if e.source_field in ('product_name','brand','category','discounted_price','rating','specifications')] for p in products}
    return query,products,selection_schema(supplied)


def configuration(folder,artifact,schemas):
    """No synthetic inference evidence; this permission is explicitly test-only."""
    folder.mkdir(parents=True,exist_ok=False)
    blob=json.dumps(artifact,sort_keys=True).encode();(folder/'artifact.json').write_bytes(blob)
    config=yaml.safe_load(Path('config/llm_gateway_ollama_experimental.yaml').read_text(encoding='utf8'))
    for name,task,schema,hashes in [('native_query','query_understanding','phase8.intent.flat.v1',[fp(ExtractedShoppingIntent)]),
        ('native_recommendation','recommendation_generation','phase12.catalog-selection.v2',sorted({fp(s) for s in schemas}))]:
        route=config['routes'][name];ref=name+'.yaml'
        route['enabled']=True;route['approval']={'status':'approved','evidence_ref':ref};route['cost']={'class':'free','evidence_ref':ref}
        evidence={'route_id':name,'task':task,'provider':'ollama','endpoint':config['providers']['ollama']['endpoint'],'model':MODEL,
            'schema_id':schema,'structured_mode':'ollama_schema','status':'valid','approval':'approved','scope':'experimental',
            'cost_class':'free','model_digest':DIGEST,'schema_fingerprints':hashes,'inference_options':Options.model_validate(route['options']).model_dump(),
            'artifact_ref':'artifact.json','artifact_sha256':hashlib.sha256(blob).hexdigest(),'valid_until':(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()}
        if task=='recommendation_generation':evidence['dynamic_schema_family']='r3.required-keys.v2'
        (folder/ref).write_text(yaml.safe_dump(evidence),encoding='utf8')
    path=folder/'gateway.yaml';path.write_text(yaml.safe_dump(config,sort_keys=False),encoding='utf8');return path


async def main(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False);results=out/'integration_results';results.mkdir()
    offline=Path(args.offline_report)
    report=offline.read_bytes().decode('utf16' if offline.read_bytes().startswith(b'\xff\xfe') else 'utf-8-sig')
    if 'passed' not in report or ' failed' in report or ' error' in report:raise ValueError('Passing offline report required')
    calls=[]
    async def observe(request):
        if request.url.host!='127.0.0.1' or request.url.port!=11434 or request.url.path not in ('/api/tags','/api/chat'):
            raise RuntimeError('Validation permits only local native endpoints')
        calls.append({'path':request.url.path,'method':request.method})
    client=httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=30,event_hooks={'request':[observe]})
    gateway=None;records=[]
    try:
        tags=(await client.get('http://127.0.0.1:11434/api/tags')).json()
        model=next(m for m in tags['models'] if m['name']==MODEL)
        if model['digest']!=DIGEST:raise ValueError('Native digest differs from frozen evidence')
        cases=json.loads(Path('data/interim/phase18_4/fixtures/dev.json').read_text(encoding='utf8'))['cases']
        selected=[cases[i] for i in (0,1,2)];schemas=[fixture(c)[2] for c in selected]
        sources=['data/interim/phase18_3/frozen_candidate/final/manifest.json','data/interim/phase18_4/evaluation_results/final_dev/responses.jsonl']
        artifact={'kind':'Phase18.5 isolated integration-test permission, not production approval','authorization':'User Phase18.5 request authorizes supervised local smoke tests only',
            'prior_native_evidence':{p:sha(p) for p in sources},'offline_report':str(offline),'offline_report_sha256':sha(offline),
            'verified_tags':model,'verified_utc':datetime.now(timezone.utc).isoformat(),
            'structural_correction':'Duplicate fact indices rejected in schema binding; accepted frozen R3 outputs remain unchanged.',
            'schemas':{fp(s):s.model_json_schema() for s in schemas},'production_semantic_approval':False,
            'local_cost_scope':'No external per-request API fee; hardware/electricity costs are not measured.'}
        config=configuration(out/'route_validation',artifact,schemas)
        settings=GatewaySettings(_env_file=None,enabled=True,runtime='ollama_experimental',config_path=config.resolve(),auto_failover=False,
            max_attempts_per_task=1,attempt_timeout_seconds=30,telemetry_dir=results/'telemetry')
        gateway=build_native_gateway(settings,client=client)
        if not await verify_native_gateway(gateway):raise ValueError('Gateway startup digest verification failed')
        query_engine=QueryUnderstandingEngine(gateway=gateway,gateway_native=True)
        generator=LocalRecommendationGenerator(gateway=gateway)
        recommendation=RecommendationService(gateway=gateway,local_generator=generator)
        posts=lambda:sum(c['path']=='/api/chat' for c in calls)
        before=posts();start=time.perf_counter()
        parsed=await query_engine.parse_query_async('I need lightweight Puma running shoes under 2000 rupees.',request_id='live-a',task_id='live-qu')
        checks={'valid':parsed.is_valid,'category':parsed.output.hard_constraints.category=='Footwear','brand':parsed.output.hard_constraints.brand=='Puma',
            'upper_bound':parsed.output.hard_constraints.max_price==2000,'lower_absent':parsed.output.hard_constraints.min_price is None,'one_call':posts()-before==1}
        records.append({'test':'A','kind':'live native Gateway Q1S','checks':checks,'result':parsed.model_dump(mode='json'),'wall_ms':(time.perf_counter()-start)*1000})
        for case in selected:
            q,pp,schema=fixture(case);before=posts();start=time.perf_counter()
            result,diagnostic=await generator.evaluate(q,pp,language='en',request_id='live-b-'+case['id'],task_id='rec-'+case['id'])
            checks={'success':result.status.value=='SUCCESS','one_call':posts()-before==1,'order':[p.product_id for p in result.products]==[p.product_id for p in pp],
                'metadata':all(a.discounted_price==b.discounted_price and a.rating==b.rating and a.brand==b.brand for a,b in zip(result.products,pp))}
            quotes=True
            for p in result.products:
                supplied={e['evidence_id']:e for e in diagnostic.get('provided_evidence',{}).get(p.product_id,[])}
                for claim in p.strengths:
                    if len(claim.evidence_ids)!=1 or claim.evidence_ids[0] not in supplied:quotes=False;continue
                    e=supplied[claim.evidence_ids[0]];quotes &= e['product_id']==p.product_id and claim.claim=='Catalog lists: '+e['text']
            checks['source_quotes']=quotes
            records.append({'test':'B','candidate_count':len(pp),'kind':'live native Gateway R3','schema_fingerprint':fp(schema),
                'checks':checks,'diagnostic':diagnostic,'result':result.model_dump(mode='json'),'wall_ms':(time.perf_counter()-start)*1000})
        # Combined live inference with actual typed contracts, but mock candidate
        # retrieval and preference vectors. No DB/pgvector/dense acceptance claim.
        before=posts();start=time.perf_counter()
        qu=await query_engine.parse_query_async('running shoes under 2000',request_id='combined',task_id='combined-qu')
        _,pp,_=fixture(selected[1])
        candidates=[HybridCandidate(rank=i,product_id=p.product_id,product_name=p.product_name,category=p.category,brand=p.brand,
            discounted_price=p.discounted_price,rating=p.rating,rrf_score=p.rrf_score,metadata=p.metadata) for i,p in enumerate(pp,1)]
        retrieved=HybridRetrievalResult(status=HybridRetrievalStatus.SUCCESS,candidates=candidates,applied_constraints=qu.output.hard_constraints.model_dump())
        class FakeEncoder:
            model_name='BAAI/bge-small-en-v1.5';embedding_dimension=384
            def validate_model_compatibility(self):pass
            def encode(self,_):return [1.0]+[0.0]*383
        pref=PreferenceRepresentationService(encoder=FakeEncoder()).represent(qu)
        ranked=RerankingService(text_provider=MappingProductTextProvider(texts={p.product_id:p.retrieval_text for p in pp})).rerank(
            qu,pref,retrieved,method=RerankingMethod.RRF,top_k=3)
        result=await recommendation.generate(qu,pref,ranked,top_k=3,language='en',request_id='combined',task_id='combined-rec')
        records.append({'test':'D','kind':'Live Gateway Q1S/R3; mocked catalog candidate retrieval/preference vectors; real RRF reranking contracts',
            'checks':{'success':result.status.value=='SUCCESS','maximum_two_calls':posts()-before<=2,'two_calls_for_eligible_request':posts()-before==2},
            'query':qu.model_dump(mode='json'),'reranking_status':ranked.status.value,'result':result.model_dump(mode='json'),
            'wall_ms':(time.perf_counter()-start)*1000})
        records.append({'test':'C','kind':'Mocked failures, not server shutdown','offline_report':str(offline),
            'covered':['unavailable','timeout','invalid response','unexpected model','ineligible route','invalid upstream','relevance failure','parent deadline','quota release','cancellation']})
        await gateway.telemetry.flush()
    except Exception as exc:
        records.append({'test':'BLOCKER','type':type(exc).__name__,'message':str(exc)})
    finally:
        if gateway is not None:await gateway.aclose()
        await client.aclose()
        with (results/'results.json').open('x',encoding='utf8') as stream:json.dump({'records':records,'http_calls':calls,'scope':'No production routing changes; no live database/dense retrieval validation.'},stream,ensure_ascii=False,indent=2)
    print(json.dumps([{'test':r['test'],'checks':r.get('checks'),'type':r.get('type')} for r in records]))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--offline-report',required=True)
    asyncio.run(main(p.parse_args()))
