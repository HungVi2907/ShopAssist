"""Paired E0/E1 and one-call E2 local evaluation; all artifacts are isolated."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import math
import statistics

import httpx
from jsonschema import Draft202012Validator
from shopassist.llm.extraction import EXTRACTION_PROMPT
from shopassist.llm.transformation import ExtractedShoppingIntent, transform_extraction, validate_against_query
from shopassist.llm.query_understanding import QueryUnderstandingEngine, load_catalog_brands_set
from shopassist.llm.prompts import build_user_prompt
from shopassist.llm.schemas import QueryUnderstandingOutput
from shopassist.llm.normalization import validate_and_normalize_output
try:
    from scripts.summarize_ollama_query_understanding import summarize
except ModuleNotFoundError:
    from summarize_ollama_query_understanding import summarize

ROOT = Path(__file__).resolve().parents[1]


def report(rows):
    result = {}
    for candidate in ('E0','E1','E2'):
        group = [r for r in rows if r['variant']==candidate]
        if not group:
            continue
        score = summarize(group,'normalized'); n=len(group)
        answerable=[r for r in group if not r['expected'].get('needs_clarification')]
        clarified=[r for r in group if r.get('normalized',{}).get('needs_clarification')]
        false=total=0
        if candidate=='E1':
            for r in group:
                for field,exp in r['expected']['hard_constraints'].items():
                    if field not in ('min_price','max_price','min_rating','currency') or 'before' not in r or 'normalized' not in r:
                        continue
                    a=r['before']['hard_constraints'].get(field);b=r['normalized']['hard_constraints'].get(field)
                    if a!=b:
                        total+=1;false+=a==exp and b!=exp
        latency=sorted(r['wall_ms'] for r in group)
        result[candidate]={**score,'json_valid':sum('parsed' in r for r in group),
            'internal_schema_valid':sum(r.get('internal_schema_valid',False) for r in group),
            'final_schema_valid':sum('normalized' in r for r in group),
            'clarified':len(clarified),'correct_clarifications':sum(r['expected'].get('needs_clarification',False) for r in clarified),
            'answerable_count':len(answerable),'answerable_served':sum('normalized' in r and not r['normalized']['needs_clarification'] for r in answerable),
            'false_corrections':false if candidate=='E1' else None,'corrections_checked':total if candidate=='E1' else None,
            'p50_ms':statistics.median(latency),'p95_ms':latency[math.ceil(.95*n)-1],
            'prompt_tokens_mean':statistics.mean(r.get('envelope',{}).get('prompt_eval_count',0) for r in group),
            'completion_tokens_mean':statistics.mean(r.get('envelope',{}).get('eval_count',0) for r in group)}
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',required=True);p.add_argument('--out',required=True);args=p.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    dataset=Path(args.dataset);cases=json.loads(dataset.read_text(encoding='utf8'))['cases']
    p4=(ROOT/'data/interim/phase18_1/dev_run_02/P4.prompt.txt').read_text(encoding='utf8')
    options={'temperature':0,'seed':42,'num_ctx':4096,'num_predict':512}
    brands=load_catalog_brands_set();rows=[]
    digest=lambda b:hashlib.sha256(b).hexdigest()
    with httpx.Client(base_url='http://localhost:11434',trust_env=False,timeout=120) as client:
        model='qwen2.5:1.5b-instruct-local'
        meta=next(m for m in client.get('/api/tags').json()['models'] if m['name']==model)
        manifest={'created_utc':datetime.now(timezone.utc).isoformat(),'dataset':str(dataset),'dataset_sha256':digest(dataset.read_bytes()),'model':meta,
            'options':options,'version':client.get('/api/version').json(),'pairing':'E0 and E1 share a single raw response; E1 timing includes transformation',
            'source_sha256':{str(f.relative_to(ROOT)):digest(f.read_bytes()) for f in (ROOT/'src/shopassist/llm').glob('*.py')},
            'catalog_brands_sha256':digest(json.dumps(sorted(brands)).encode()),'schemas':{},'prompts':{}}
        for candidate,schema,prompt in [('E0',QueryUnderstandingOutput,p4),('E2',ExtractedShoppingIntent,EXTRACTION_PROMPT)]:
            (out/f'{candidate}.prompt.txt').write_bytes(prompt.encode())
            schema_data=schema.model_json_schema();(out/f'{candidate}.schema.json').write_text(json.dumps(schema_data,indent=2),encoding='utf8')
            manifest['schemas'][candidate]=digest(json.dumps(schema_data,sort_keys=True).encode())
            manifest['prompts'][candidate]=digest(prompt.encode())
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
        with (out/'responses.jsonl').open('x',encoding='utf8') as handle:
            for candidate,schema,prompt in [('E0',QueryUnderstandingOutput,p4),('E2',ExtractedShoppingIntent,EXTRACTION_PROMPT)]:
                for case in cases:
                    q=QueryUnderstandingEngine.validate_input_query(None,case['query']);start=time.perf_counter()
                    row={'variant':candidate,'id':case['test_id'],'query':q,'expected':case['expected']}
                    try:
                        response=client.post('/api/chat',json={'model':model,'messages':[{'role':'system','content':prompt},{'role':'user','content':build_user_prompt(q) if candidate=='E0' else q}], 'format':schema.model_json_schema(),'options':options,'stream':False})
                        response.raise_for_status();env=response.json();row['envelope']=env;row['raw']=env['message']['content']
                        row['parsed']=json.loads(row['raw']);row['internal_schema_valid']=Draft202012Validator(schema.model_json_schema()).is_valid(row['parsed'])
                        if not env.get('done') or env.get('done_reason')=='length':raise ValueError('Incomplete response')
                        valid=schema.model_validate(row['parsed'])
                        if candidate=='E0':
                            output,warnings=validate_and_normalize_output(valid,brands);row['normalized']=output.model_dump();row['warnings']=warnings
                        else:
                            validation=transform_extraction(q,valid,brands);row['transformed']=validation.transformed.model_dump()
                            row['semantic_validation']={'status':validation.status,'issues':validation.issues,'corrections':validation.corrections}
                            row['normalized']=QueryUnderstandingOutput.model_validate(validation.output.model_dump()).model_dump()
                    except Exception as e:row['error']=f'{type(e).__name__}: {e}'
                    row['wall_ms']=(time.perf_counter()-start)*1000
                    rows.append(row);handle.write(json.dumps(row,ensure_ascii=False)+'\n');handle.flush()
                    if candidate=='E0':
                        paired_start=time.perf_counter()
                        paired={**row,'variant':'E1'}
                        if 'normalized' in row:
                            before=QueryUnderstandingOutput.model_validate(row['normalized']);validation=validate_against_query(q,before,brands)
                            paired['before']=row['normalized'];paired['transformed']=validation.transformed.model_dump()
                            paired['semantic_validation']={'status':validation.status,'issues':validation.issues,'corrections':validation.corrections}
                            paired['normalized']=QueryUnderstandingOutput.model_validate(validation.output.model_dump()).model_dump()
                        paired['wall_ms']=row['wall_ms']+(time.perf_counter()-paired_start)*1000
                        rows.append(paired);handle.write(json.dumps(paired,ensure_ascii=False)+'\n');handle.flush()
                    print(candidate,case['test_id'],row.get('error','ok'),flush=True)
    (out/'summary.json').write_text(json.dumps(report(rows),indent=2),encoding='utf8')

if __name__=='__main__':main()
