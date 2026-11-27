"""Add branch timing/resource hashes and freeze audit metadata; no inference."""
import hashlib
import json
from pathlib import Path
import numpy as np
from dotenv import dotenv_values
from huggingface_hub import try_to_load_from_cache

OUT=Path('data/interim/phase18_6')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    observations=[json.loads(s) for s in (OUT/'api_test_results/server_02/observations.jsonl').read_text(encoding='utf8').splitlines()]
    stages={}
    for row in observations:
        if row['stage'] not in ('hybrid_retrieval','reranking'):continue
        for name,value in row['result'].get('stage_latency_ms',{}).items():stages.setdefault(row['stage']+'.'+name,[]).append(value)
    metrics={k:{'n':len(v),'p50_ms':float(np.percentile(v,50)),'p95_ms':float(np.percentile(v,95))} for k,v in stages.items()}
    telemetry=[json.loads(s) for s in (OUT/'api_test_results/server_02/telemetry/gateway.jsonl').read_text().splitlines()]
    attempts=[r for r in telemetry if r['event']=='attempt']
    for task in ('query_understanding','recommendation_generation'):
        for key in ('latency_ms','timings.total_ms','timings.load_ms'):
            values=[a['latency_ms'] if key=='latency_ms' else a['timings'][key.split('.')[1]] for a in attempts if a['task']==task]
            metrics[task+'.'+key]={'n':len(values),'p50_ms':float(np.percentile(values,50)),'p95_ms':float(np.percentile(values,95))}
    params=dotenv_values('.env')
    safe_runtime={k:params.get(k) for k in ('API_REQUEST_TIMEOUT_SECONDS','BOT_REQUEST_TIMEOUT_SECONDS','API_DEFAULT_TOP_K','BOT_DEFAULT_TOP_K','API_RETRIEVAL_TOP_N','API_RERANKING_METHOD')}
    cache={}
    for name in ('model.safetensors','pytorch_model.bin','config.json','tokenizer.json','modules.json'):
        path=try_to_load_from_cache('BAAI/bge-small-en-v1.5',name)
        if isinstance(path,str) and Path(path).is_file():cache[name]={'snapshot':str(Path(path).parent.name),'sha256':sha(Path(path))}
    runs={}
    for name in ('server_01','server_02','server_03'):
        p=OUT/f'api_test_results/{name}/telemetry/gateway.jsonl'
        events=[json.loads(s) for s in p.read_text().splitlines()]
        runs[name]={'inference_attempts':sum(e['event']=='attempt' for e in events),'outcomes':{e['outcome'] for e in events if e['event']=='attempt'}}
        runs[name]['outcomes']=sorted(runs[name]['outcomes'])
    value={'stage_metrics':metrics,'safe_runtime_settings':safe_runtime,'bge_cached_artifacts':cache,'inference_runs':runs,
        'interpretation':'Branch timings cover executed SQL/filter, dense, lexical, fusion and reranking work. HTTP admission/serialization and R3 evidence/assembly are not independently isolated in this run.'}
    path=OUT/'performance_results/branch_and_resource_summary.json'
    with path.open('x',encoding='utf8') as stream:json.dump(value,stream,indent=2)
    print(json.dumps({'stage_metrics':metrics,'runtime':safe_runtime,'bge_hashed_files':list(cache),'inference_runs':runs}))


if __name__=='__main__':main()
