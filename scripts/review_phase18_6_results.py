"""Deterministic catalog/citation/call-count audit, no inference or DB writes."""
import os
os.environ.update(PGCONNECT_TIMEOUT='5',PGOPTIONS='-c default_transaction_read_only=on')
import asyncio
from collections import Counter,defaultdict
import json
from pathlib import Path
from sqlalchemy import text
import numpy as np
from shopassist.db.connection import get_async_engine
from shopassist.api.services.orchestrator import _sanitize_url,_extract_primary_image_url
from shopassist.api.price_adapter import PriceBoundaryAdapter
from shopassist.retrieval.hybrid import HardConstraintFilters,product_matches_filters

OUT=Path('data/interim/phase18_6')


def lines(path):return [json.loads(s) for s in path.read_text(encoding='utf8').splitlines()]


async def main():
    api=[r for r in lines(OUT/'api_test_results/live_api_02.jsonl') if 'case' in r]
    observations=lines(OUT/'api_test_results/server_02/observations.jsonl')
    telemetry=lines(OUT/'api_test_results/server_02/telemetry/gateway.jsonl')
    attempts=[r for r in telemetry if r['event']=='attempt']
    posts=[r for r in observations if r['stage']=='native_http' and r['method']=='POST']
    assert len(posts)==len(attempts)
    correlated=defaultdict(list)
    # One worker, serial requests and one dispatch per task: both sequences are ordered.
    for post,attempt in zip(posts,attempts):correlated[post['request_id']].append(attempt)
    engine=get_async_engine(pool_size=1,max_overflow=0)
    try:
        ids=sorted({p['product_id'] for row in api for p in row['body'].get('products',[])})
        async with engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION READ ONLY'))
            rows=(await conn.execute(text('SELECT product_id,product_name,category,brand,discounted_price,rating,product_url,image FROM public.products WHERE product_id=ANY(:ids)'),{'ids':ids})).mappings()
            catalog={row['product_id']:dict(row) for row in rows}
    finally:await engine.dispose()
    checks=[];product_count=0;claim_count=0;timings=defaultdict(list)
    source_by_request=defaultdict(dict)
    for obs in observations:
        if obs.get('request_id'):source_by_request[obs['request_id']][obs['stage']]=obs
        if 'elapsed_ms' in obs:timings[obs['stage']].append(obs['elapsed_ms'])
    for row in api:
        body=row['body'];rid=body['request_id'];events=correlated[rid]
        result={'case':row['case']['id'],'status':body['status'],'inference_calls':len(events),
            'at_most_two_calls':len(events)<=2,'public_usage_matches_reported_counts':body['usage']['total_tokens']==sum(e['usage']['total_tokens'] for e in events)}
        assert result['at_most_two_calls'] and result['public_usage_matches_reported_counts']
        if body['status']=='SUCCESS':
            qu=source_by_request[rid]['query_understanding']['result'];hc=qu['output']['hard_constraints']
            semantics=PriceBoundaryAdapter.resolve(qu['query'],hc['min_price'],hc['max_price']).semantics
            filters=HardConstraintFilters(category=hc['category'],brand=hc['brand'],min_price=hc['min_price'],max_price=hc['max_price'],
                min_rating=hc['min_rating'],min_price_inclusive=semantics.get('min_inclusive'),max_price_inclusive=semantics.get('max_inclusive'))
            ranked=source_by_request[rid]['reranking']['result']['products']
            result.update(two_calls=len(events)==2,order=[p['product_id'] for p in body['products']]==[p['product_id'] for p in ranked],
                metadata=True,owned_exact_quotes=True,mandatory_filters=True,presentation_urls=True)
            for product in body['products']:
                product_count+=1;authoritative=catalog[product['product_id']]
                for field in ('product_name','category','brand','discounted_price','rating'):
                    expected=authoritative[field];actual=product[field]
                    if field in ('discounted_price','rating') and expected is not None:expected=float(expected)
                    result['metadata'] &= actual==expected
                result['mandatory_filters'] &= product_matches_filters(product,filters)
                result['presentation_urls'] &= product['product_url']==_sanitize_url(authoritative['product_url']) and product['image']==_extract_primary_image_url(authoritative['image'])
                facts={e['evidence_id']:e for e in product['available_evidence']}
                for claim in product['strengths']:
                    claim_count+=1
                    if len(claim['evidence_ids'])!=1 or claim['evidence_ids'][0] not in facts:result['owned_exact_quotes']=False;continue
                    key=claim['evidence_ids'][0]
                    result['owned_exact_quotes'] &= key.startswith(product['product_id']+'-E') and claim['claim']=='Catalog lists: '+facts[key]['text']
            assert all(result[k] for k in ('two_calls','order','metadata','owned_exact_quotes','mandatory_filters','presentation_urls'))
        checks.append(result)
    metrics={stage:{'n':len(values),'p50_ms':float(np.percentile(values,50)),'p95_ms':float(np.percentile(values,95))} for stage,values in timings.items()}
    success=[r['wall_ms'] for r in api if r['body']['status']=='SUCCESS']
    warm=[r['wall_ms'] for r in api if r['body']['status']=='SUCCESS' and r['case']['id']!='E01']
    counters={'inference_posts':len(posts),'identity_gets':sum(r['stage']=='native_http' and r['method']=='GET' for r in observations),
        'successful_requests':len(success),'accepted_product_occurrences':product_count,'selected_claims':claim_count,
        'input_tokens':sum(a['usage']['input_tokens'] for a in attempts),'output_tokens':sum(a['usage']['output_tokens'] for a in attempts)}
    first_start=next(r['monotonic'] for r in observations if r['stage']=='startup')
    refresh_times=[r['monotonic']-first_start for r in observations if r['stage']=='native_http' and r['method']=='GET' and r.get('request_id')]
    output={'checks':checks,'counts':counters,'executed_stage_metrics':metrics,
        'successful_http_wall':{'n':len(success),'p50_ms':float(np.percentile(success,50)),'p95_ms':float(np.percentile(success,95))},
        'warm_successful_http_wall':{'n':len(warm),'p50_ms':float(np.percentile(warm,50)),'p95_ms':float(np.percentile(warm,95))},
        'identity_stress_ttl_seconds':2,'refresh_offsets_since_start_seconds':refresh_times,
        'correlation_method':'Sequential one-worker native HTTP observations paired with ordered Gateway attempts; public request IDs remain unmodified and internal IDs server-generated.',
        'not_separately_measured':['pure input validation','evidence preparation','recommendation assembly','pure HTTP serialization; client/server residual contains middleware and network'],
        'assessment_scope':'Deterministic source/constraint fidelity; relevance/usefulness review remains provisional.'}
    with (OUT/'performance_results/review_02.json').open('x',encoding='utf8') as f:json.dump(output,f,indent=2)
    print(json.dumps(counters));print(json.dumps(output['warm_successful_http_wall']))


if __name__=='__main__':asyncio.run(main())
