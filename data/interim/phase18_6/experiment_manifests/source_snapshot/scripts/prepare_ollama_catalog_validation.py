"""Explicit supervised test permission from real retrieval evidence, never wildcard approval."""
import argparse
import asyncio
import json
from pathlib import Path
import httpx
from shopassist.recommendation.local import selection_schema
from validate_phase18_5 import configuration,sha,fp,MODEL,DIGEST


async def main(args):
    evidence=Path(args.retrieval_evidence);offline=Path(args.offline_report)
    raw=offline.read_bytes();report=raw.decode('utf16' if raw.startswith(b'\xff\xfe') else 'utf8')
    if 'passed' not in report or ' failed' in report or ' error' in report:raise ValueError('Passing guarded offline report required')
    data=json.loads(evidence.read_text(encoding='utf8'));schemas={}
    for result in data['results']:
        for row in result['reranking_by_top_k']:
            binding=row['binding']
            if not binding:continue
            sizes=binding['fact_counts']
            if not 1<=len(sizes)<=5 or any(type(n) is not int or not 1<=n<=13 for n in sizes):raise ValueError('Unsupported catalog shape')
            schema=selection_schema({str(i):[None]*n for i,n in enumerate(sizes)})
            if fp(schema)!=binding['fingerprint']:raise ValueError('Shape fingerprint mismatch')
            schemas[fp(schema)]=schema
    async with httpx.AsyncClient(trust_env=False,timeout=5) as client:
        response=await client.get('http://127.0.0.1:11434/api/tags');response.raise_for_status();tags=response.json()
    matches=[m for m in tags['models'] if m['name']==MODEL]
    if len(matches)!=1 or matches[0]['digest']!=DIGEST:raise ValueError('Frozen model mismatch')
    artifact={'authorization':'User-authorized supervised catalog-backed experimental tests only; no production semantic approval',
        'verified_tags':matches[0],'retrieval_evidence':str(evidence),'retrieval_evidence_sha256':sha(evidence),
        'offline_report':str(offline),'offline_report_sha256':sha(offline),
        'catalog_sha256':sha(Path('data/processed/products.parquet')),
        'schemas':{key:s.model_json_schema() for key,s in schemas.items()},'production_semantic_approval':False,
        'runtime_sources_sha256':{str(p):sha(p) for p in sorted(Path('src/shopassist/llm_gateway').rglob('*.py'))}}
    configuration(Path(args.out),artifact,list(schemas.values()))
    print(json.dumps({'test_fingerprints':len(schemas),'configuration':str(Path(args.out)/'gateway.yaml'),'approval_scope':'experimental tests only; expires in 24 hours'}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--retrieval-evidence',required=True);p.add_argument('--offline-report',required=True)
    asyncio.run(main(p.parse_args()))
