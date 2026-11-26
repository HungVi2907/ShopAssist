"""Local catalog/lexical/reranking ablation; not a dense retrieval acceptance run."""
import os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
import hashlib
import json
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from shopassist.llm.query_understanding import CANONICAL_PARQUET_PATH
from shopassist.llm.schemas import QueryUnderstandingOutput
from shopassist.preferences.query_composer import build_preference_query
from shopassist.preferences.safety import find_unsafe_negative_preferences
from shopassist.retrieval.hybrid import HardConstraintFilters, product_matches_filters
from shopassist.retrieval.tfidf import TFIDFIndex
from shopassist.reranking.core import load_local_cross_encoder


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--final',action='store_true');args=parser.parse_args()
    folder=Path('data/interim/phase18_3');rows=[]
    for source in (['dev_01_final','regression_01_final'] if args.final else ['dev_01','regression_01']):
        rows.extend(json.loads(s) for s in (folder/'evaluation_results'/source/'responses.jsonl').read_text(encoding='utf8').splitlines())
    ids=['QU002','QU004','QU005','QU050','HELD007','HELD010','HELD014','HELD018','HELD020']
    catalog=pd.read_parquet(CANONICAL_PARQUET_PATH).set_index('product_id');index=TFIDFIndex.load()
    scorer=None;model_error=None
    try:scorer=load_local_cross_encoder(model_path='.models/phase11/ms-marco-MiniLM-L2-v2',device='cpu',local_files_only=True)
    except Exception as e:model_error=f'{type(e).__name__}: {e}'
    results=[]
    for case in ids:
        records=[r for r in rows if r['id']==case and r['variant'] in ('Q0','Q1' if args.final else 'P1')]
        if not records:continue
        exp=records[0]['expected']
        # Fixture reference is not independently human reviewed.
        reference=QueryUnderstandingOutput(semantic_query=exp.get('semantic_query',records[0]['query']),
            hard_constraints=exp['hard_constraints'],soft_preferences=exp.get('soft_preferences',[]),
            needs_clarification=exp.get('needs_clarification',False))
        sources=[(r['variant'],QueryUnderstandingOutput.model_validate(r['normalized'])) for r in records]+[('fixture_reference',reference)]
        for name,out in sources:
            hc=out.hard_constraints
            filters=HardConstraintFilters(category=hc.category,brand=hc.brand,min_price=hc.min_price,
                min_price_inclusive=True if hc.min_price is not None else None,max_price=hc.max_price,
                max_price_inclusive=True if hc.max_price is not None else None,min_rating=hc.min_rating)
            pref_query=build_preference_query(out.semantic_query,out.soft_preferences)
            gated=out.needs_clarification or hc.currency!='INR' or bool(find_unsafe_negative_preferences([records[0]['query']]))
            record={'id':case,'variant':name,'raw_query':records[0]['query'],'semantic_input':out.semantic_query,
                'preference_input':pref_query,'gated':gated,'filters':filters.__dict__,'lexical_top':[],'reranked_top':[]}
            if not gated:
                candidates=[c for c in index.search(out.semantic_query,top_k=len(catalog))
                    if product_matches_filters(catalog.loc[c.product_id].to_dict(),filters)][:10]
                record['lexical_top']=[{'id':c.product_id,'name':c.product_name,'score':c.tfidf_score} for c in candidates[:5]]
                record['constraint_violations']=sum(not product_matches_filters(catalog.loc[c.product_id].to_dict(),filters) for c in candidates)
                if candidates and scorer:
                    pairs=[(pref_query or out.semantic_query,str(catalog.loc[c.product_id,'retrieval_text'])) for c in candidates]
                    scores=np.asarray(scorer.predict(pairs,batch_size=16)).reshape(-1)
                    record['reranked_top']=[{'id':candidates[i].product_id,'name':candidates[i].product_name,'score':float(scores[i])} for i in np.argsort(-scores)[:5]]
            results.append(record)
    payload={'catalog_rows':len(catalog),'catalog_sha256':hashlib.sha256(CANONICAL_PARQUET_PATH.read_bytes()).hexdigest(),
        'reranker_error':model_error,'scope':'Existing TF-IDF with actual local catalog and existing local CrossEncoder pair scorer. No database/dense branch; no reviewed product qrels. Explicit inclusive v1 prices for this ablation.',
        'results':results}
    target='downstream_final.json' if args.final else 'downstream.json'
    with (folder/'evaluation_results'/target).open('x',encoding='utf8') as f:json.dump(payload,f,ensure_ascii=False,indent=2)
    print('records',len(results),'reranker_error',model_error,'constraint violations',sum(r.get('constraint_violations',0) for r in results))

if __name__=='__main__':main()
