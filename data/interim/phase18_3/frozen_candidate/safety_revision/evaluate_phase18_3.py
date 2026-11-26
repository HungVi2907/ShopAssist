"""Local Phase 18.3 comparison, including paired deterministic replay."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys
import time

import httpx
from jsonschema import Draft202012Validator
from shopassist.llm.extraction import PREFERENCE_PROMPTS
from shopassist.llm.query_understanding import QueryUnderstandingEngine, load_catalog_brands_set
from shopassist.llm.schemas import QueryUnderstandingOutput
from shopassist.llm.transformation import ExtractedShoppingIntent, transform_extraction

try:
    from scripts.summarize_ollama_query_understanding import summarize
except ModuleNotFoundError:
    from summarize_ollama_query_understanding import summarize

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = {'temperature':0,'seed':42,'num_ctx':4096,'num_predict':512}


def frozen_transform():
    def module(name,file):
        spec=importlib.util.spec_from_file_location(name,file);m=importlib.util.module_from_spec(spec)
        sys.modules[name]=m;spec.loader.exec_module(m);return m
    folder=ROOT/'data/interim/phase18_2/frozen_sources'
    constraints=module('_phase182_constraints',folder/'constraints.py')
    transform=module('_phase182_transform',folder/'transformation.py')
    transform.parse_constraints=constraints.parse_constraints
    return transform


def summarize_rows(rows):
    results={}
    for candidate in dict.fromkeys(r['variant'] for r in rows):
        group=[r for r in rows if r['variant']==candidate];n=len(group)
        answered=[r for r in group if 'normalized' in r and not r['normalized']['needs_clarification']]
        clarified=[r for r in group if r.get('normalized',{}).get('needs_clarification')]
        answerable=[r for r in group if not r['expected'].get('needs_clarification',False)]
        latency=sorted(r['wall_ms'] for r in group)
        changed=false=0
        for r in group:
            if 'paired_baseline' not in r or 'normalized' not in r:continue
            before=r['paired_baseline']['hard_constraints'];after=r['normalized']['hard_constraints']
            for key in ('category','brand','min_price','max_price','min_rating','currency'):
                target=r['expected']['hard_constraints'].get(key)
                if before.get(key)!=after.get(key):
                    changed+=1;false+=before.get(key)==target and after.get(key)!=target
        results[candidate]={**summarize(group,'normalized'),
            'json_valid':sum('parsed' in r for r in group),
            'internal_schema_valid':sum(r.get('internal_schema_valid',False) for r in group),
            'final_schema_valid':sum('normalized' in r for r in group),
            'clarified':len(clarified),'correct_clarifications':sum(r['expected'].get('needs_clarification',False) for r in clarified),
            'unnecessary_clarifications':sum(not r['expected'].get('needs_clarification',False) for r in clarified),
            'answerable':len(answerable),'answerable_served':sum('normalized' in r and not r['normalized']['needs_clarification'] for r in answerable),
            'answered':len(answered),'answered_exact':summarize(answered,'normalized')['counts']['exact'],
            'false_corrections':false if candidate=='Q1' else None,'changed_hard_slots':changed if candidate=='Q1' else None,
            'p50_ms':statistics.median(latency),'p95_ms':latency[math.ceil(.95*n)-1],
            'prompt_tokens_mean':statistics.mean(r.get('envelope',{}).get('prompt_eval_count',0) for r in group),
            'completion_tokens_mean':statistics.mean(r.get('envelope',{}).get('eval_count',0) for r in group)}
    return results


def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',required=True);p.add_argument('--out',required=True)
    p.add_argument('--prompts',nargs='+',choices=PREFERENCE_PROMPTS,default=['P0','P1','P2'])
    p.add_argument('--replay',help='Phase18.2 responses.jsonl (E2 rows); only P0 is replayed')
    args=p.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    dataset=Path(args.dataset);cases=json.loads(dataset.read_text(encoding='utf8'))['cases']
    brands=load_catalog_brands_set();old=frozen_transform();rows=[]
    schema=ExtractedShoppingIntent.model_json_schema();validator=Draft202012Validator(schema)
    sha=lambda b:hashlib.sha256(b).hexdigest()
    replay={r['id']:r for r in map(json.loads,Path(args.replay).read_text(encoding='utf8').splitlines()) if r['variant']=='E2'} if args.replay else None
    with httpx.Client(base_url='http://localhost:11434',trust_env=False,timeout=120) as client:
        model='qwen2.5:1.5b-instruct-local'
        meta=next(m for m in client.get('/api/tags').json()['models'] if m['name']==model)
        manifest={'created_utc':datetime.now(timezone.utc).isoformat(),'dataset':str(dataset),'dataset_sha256':sha(dataset.read_bytes()),
            'model':meta,'version':client.get('/api/version').json(),'options':OPTIONS,'replay':args.replay,
            'schema_sha256':sha(json.dumps(schema,sort_keys=True).encode()),'prompts':{},
            'sources':{str(f.relative_to(ROOT)):sha(f.read_bytes()) for f in (ROOT/'src/shopassist/llm').glob('*.py')},
            'catalog_brand_sha256':sha(json.dumps(sorted(brands)).encode())}
        (out/'schema.json').write_text(json.dumps(schema,indent=2),encoding='utf8')
        for key in args.prompts:
            prompt=PREFERENCE_PROMPTS[key];manifest['prompts'][key]=sha(prompt.encode());(out/f'{key}.txt').write_bytes(prompt.encode())
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
        with (out/'responses.jsonl').open('x',encoding='utf8') as handle:
            for key in args.prompts:
                for case in cases:
                    q=QueryUnderstandingEngine.validate_input_query(None,case['query']);start=time.perf_counter()
                    base={'id':case['test_id'],'query':q,'expected':case['expected'],'prompt_variant':key}
                    try:
                        if replay is not None:
                            if key!='P0':raise ValueError('Replay only supports P0')
                            saved=replay[case['test_id']];assert q==saved['query'];envelope=saved['envelope']
                        else:
                            response=client.post('/api/chat',json={'model':model,'messages':[{'role':'system','content':PREFERENCE_PROMPTS[key]},{'role':'user','content':q}],
                                'format':schema,'options':OPTIONS,'stream':False});response.raise_for_status();envelope=response.json()
                        base['envelope']=envelope;base['raw']=envelope['message']['content'];base['parsed']=json.loads(base['raw'])
                        base['internal_schema_valid']=validator.is_valid(base['parsed']);extracted=ExtractedShoppingIntent.model_validate(base['parsed'])
                        if not envelope.get('done') or envelope.get('done_reason')=='length':raise ValueError('Incomplete output')
                    except Exception as e:
                        base['error']=f'{type(e).__name__}: {e}'
                    inference_ms=(time.perf_counter()-start)*1000 if replay is None else replay[case['test_id']]['wall_ms']
                    variants=['Q0','Q1'] if key=='P0' else [key]
                    baseline=None
                    for variant in variants:
                        row={**base,'variant':variant};transform_start=time.perf_counter()
                        if 'error' not in base:
                            try:
                                validation=old.transform_extraction(q,old.ExtractedShoppingIntent.model_validate(base['parsed']),brands) if variant=='Q0' else transform_extraction(q,extracted,brands)
                                row['transformed']=validation.transformed.model_dump()
                                row['semantic_validation']={'status':validation.status,'issues':validation.issues,'corrections':validation.corrections}
                                row['normalized']=QueryUnderstandingOutput.model_validate(validation.output.model_dump()).model_dump()
                                if variant=='Q0':baseline=row['normalized']
                                if variant=='Q1' and baseline:row['paired_baseline']=baseline
                            except Exception as e:row['error']=f'{type(e).__name__}: {e}'
                        row['wall_ms']=inference_ms+(time.perf_counter()-transform_start)*1000
                        rows.append(row);handle.write(json.dumps(row,ensure_ascii=False)+'\n');handle.flush()
                    print(key,case['test_id'],base.get('error','ok'),flush=True)
    (out/'summary.json').write_text(json.dumps(summarize_rows(rows),indent=2),encoding='utf8')

if __name__=='__main__':main()
