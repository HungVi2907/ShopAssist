"""Call the actual loopback FastAPI server, retaining unsuccessful observations."""
import asyncio
import argparse
import json
from pathlib import Path
import time
import httpx
import numpy as np
from shopassist.api.schemas import RecommendationRequest,RecommendationResponse

OUT=Path('data/interim/phase18_6')


async def main(args):
    cases=json.loads((OUT/'api_test_results/cases_preclassified.json').read_text(encoding='utf8'))['cases']
    if args.additional_cases:
        cases+=json.loads(Path(args.additional_cases).read_text(encoding='utf8'))['cases']
    target=OUT/f'api_test_results/{args.run_id}.jsonl'
    if target.exists():raise ValueError('Use a new run ID; historical results must be preserved')
    records=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',trust_env=False,timeout=95) as client:
        for path in ('/api/v1/health/live','/api/v1/health'):
            start=time.perf_counter();response=await client.get(path)
            row={'kind':'health','path':path,'http_status':response.status_code,'body':response.json(),'wall_ms':(time.perf_counter()-start)*1000}
            with target.open('a',encoding='utf8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        for case in cases:
            payload=RecommendationRequest(query=case['query'],top_k=case['top_k'],language=case['language'])
            start=time.perf_counter()
            try:
                path='/recommend' if case['id']=='E02' else '/api/v1/recommend'
                response=await client.post(path,json=payload.model_dump(),headers={'X-Request-ID':'p186-'+case['id']})
                body=response.json()
                if response.status_code==200:RecommendationResponse.model_validate(body)
                row={'case':case,'path':path,'http_status':response.status_code,'body':body,
                    'wall_ms':(time.perf_counter()-start)*1000,'headers':{k:v for k,v in response.headers.items() if k.startswith('x-')}}
            except Exception as exc:row={'case':case,'error_type':type(exc).__name__,'wall_ms':(time.perf_counter()-start)*1000}
            records.append(row)
            with target.open('a',encoding='utf8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            print(json.dumps({'case':case['id'],'http':row.get('http_status'),'status':row.get('body',{}).get('status'),'wall_ms':round(row['wall_ms'])}),flush=True)
    times=[r['wall_ms'] for r in records]
    summary={'count':len(records),'p50_wall_ms':float(np.percentile(times,50)),'p95_wall_ms':float(np.percentile(times,95)),
        'statuses':{s:sum(r.get('body',{}).get('status')==s for r in records) for s in sorted({r.get('body',{}).get('status','ERROR') for r in records})},
        'scope':'Actual loopback HTTP/FastAPI, local Ollama and existing pipeline; DB timeout may block genuine catalog-backed completion. No mocked replacement.'}
    with (OUT/'performance_results').joinpath(args.run_id+'.json').open('x',encoding='utf8') as f:json.dump(summary,f,indent=2)
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    (OUT/'performance_results').mkdir(parents=True,exist_ok=True)
    p=argparse.ArgumentParser();p.add_argument('--run-id',default='live_api_02')
    p.add_argument('--additional-cases')
    asyncio.run(main(p.parse_args()))
