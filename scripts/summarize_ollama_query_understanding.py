"""Summarize a native Ollama run without additional inference."""
import argparse
import json
import math
import statistics
from pathlib import Path

FIELDS = ('category','brand','min_price','max_price','min_rating','currency')

def norm(v):
    return v.strip().casefold() if isinstance(v, str) else v

def summarize(rows, stage):
    n = len(rows); counts = {k:0 for k in FIELDS}; counts.update(clarification=0, exact=0, inversion=0, hallucination=0, missing=0)
    tp=fp=fn=0
    for row in rows:
        expected=row['expected']; target=expected['hard_constraints']; actual=row.get(stage)
        if not actual:
            fn += len(expected.get('soft_preferences', [])); continue
        hc=actual.get('hard_constraints', {}); matches=[]
        for field in FIELDS:
            matched=norm(hc.get(field)) == norm(target.get(field)); counts[field] += matched; matches.append(matched)
        clar=actual.get('needs_clarification')==expected.get('needs_clarification',False); counts['clarification']+=clar
        exp={norm(x) for x in expected.get('soft_preferences',[])}; got={norm(x) for x in actual.get('soft_preferences',[])}
        tp+=len(exp&got); fp+=len(got-exp); fn+=len(exp-got)
        counts['exact']+=all(matches) and clar and exp==got
        counts['inversion']+=bool((target.get('max_price') is not None and target.get('min_price') is None and hc.get('min_price') is not None) or (target.get('min_price') is not None and target.get('max_price') is None and hc.get('max_price') is not None))
        counts['hallucination']+=any(target.get(k) is None and hc.get(k) is not None for k in ('min_price','max_price','min_rating','brand'))
        counts['missing']+=any(target.get(k) is not None and hc.get(k) is None for k in ('category','brand','min_price','max_price','min_rating'))
    precision=tp/(tp+fp) if tp+fp else None; recall=tp/(tp+fn) if tp+fn else None
    f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
    return {'n':n,'counts':counts,'preference':{'tp':tp,'fp':fp,'fn':fn,'precision':precision,'recall':recall,'f1':f1}}

def main():
    p=argparse.ArgumentParser(); p.add_argument('directory'); args=p.parse_args(); path=Path(args.directory)
    rows=[json.loads(x) for x in (path/'responses.jsonl').read_text(encoding='utf-8').splitlines()]
    results={}
    for variant in dict.fromkeys(r['variant'] for r in rows):
        group=[r for r in rows if r['variant']==variant]; lat=sorted(r['wall_ms'] for r in group)
        env=[r.get('envelope',{}) for r in group]
        throughput=[e['eval_count']/(e['eval_duration']/1e9) for e in env if e.get('eval_duration') and e.get('eval_count') is not None]
        results[variant]={'n':len(group),'json':sum('parsed' in r for r in group),'schema':sum('parsed' in r and not r.get('schema_errors') for r in group),'validated':sum('validated' in r for r in group),'missing_fields':sum(bool(r.get('missing_fields')) for r in group),'truncated':sum(e.get('done_reason')=='length' or e.get('done') is False for e in env),'request_errors':sum('request_error' in r for r in group),'first_wall_ms':lat[0] if False else group[0]['wall_ms'],'mean_wall_ms':statistics.mean(lat),'p50_wall_ms':statistics.median(lat),'p95_wall_ms':lat[max(0,math.ceil(.95*len(lat))-1)],'mean_prompt_tokens':statistics.mean([e.get('prompt_eval_count',0) for e in env]),'mean_completion_tokens':statistics.mean([e.get('eval_count',0) for e in env]),'mean_generation_tokens_s':statistics.mean(throughput) if throughput else None,'stages':{stage:summarize(group,stage) for stage in ('parsed','validated','normalized','experimental_refined')}}
    target=path/'summary.json'
    with target.open('x', encoding='utf-8') as handle:
        json.dump(results, handle, indent=2)
    print(json.dumps(results,indent=2))

if __name__=='__main__': main()
