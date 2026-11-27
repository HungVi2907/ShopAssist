"""Reference-query ablation of the three known product-type failures, no LLM."""
import os
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PGCONNECT_TIMEOUT='5',PGOPTIONS='-c default_transaction_read_only=on')
import asyncio
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import pandas as pd
from shopassist.db.connection import get_async_engine
from shopassist.llm.schemas import QueryUnderstandingResult,QueryUnderstandingOutput
from shopassist.preferences.service import PreferenceRepresentationService
from shopassist.retrieval.semantic import DenseQueryEncoder
from shopassist.retrieval.tfidf import TFIDFIndex
from shopassist.retrieval.hybrid import HybridRetrievalService
from shopassist.reranking.core import RerankingService,load_canonical_product_texts,load_local_cross_encoder,RerankingMethod
from shopassist.recommendation.local import relevance_issue


async def main(args):
    catalog=pd.read_parquet('data/processed/products.parquet');encoder=DenseQueryEncoder();index=TFIDFIndex.load()
    engine=get_async_engine(pool_size=1,max_overflow=0)
    service=HybridRetrievalService(engine,index,query_encoder=encoder)
    scorer=load_local_cross_encoder(model_path='.models/phase11/ms-marco-MiniLM-L2-v2',device='cpu',local_files_only=True)
    reranker=RerankingService(load_canonical_product_texts('data/processed/products.parquet'),cross_encoder=scorer)
    records=[]
    try:
        for query,category in [('wireless charging pad','Mobiles & Accessories'),('Bluetooth speaker','Mobiles & Accessories'),('Honda City body cover','Automotive')]:
            if args.query and query!=args.query:continue
            q=QueryUnderstandingResult(query=query,output=QueryUnderstandingOutput(semantic_query=query,hard_constraints={'category':category}))
            pref=PreferenceRepresentationService().represent(q)
            result=await service.retrieve(q,pref)
            ranked=[]
            for method in [RerankingMethod.RRF,RerankingMethod.MULTI_SIGNAL,RerankingMethod.CROSS_ENCODER]:
                r=reranker.rerank(q,pref,result,top_k=5,method=method)
                ranked.append({'method':method.value,'result':r.to_dict(),'r3_relevance_issue':relevance_issue(q,r.products) if r.products else 'No products'})
            text=catalog.product_name.str.casefold()
            if query.startswith('wireless'):mask=text.str.contains('wireless',regex=False)&text.str.contains('charg',regex=False)
            elif query.startswith('Bluetooth'):mask=text.str.contains('bluetooth',regex=False)&text.str.contains('speaker',regex=False)
            else:mask=text.str.contains('honda',regex=False)&text.str.contains('city',regex=False)&text.str.contains('cover',regex=False)
            records.append({'query':query,'scope':'Manual correct-type reference QU for retrieval diagnosis only; actual Q1S clarification is preserved separately.',
                'catalog_name_cooccurrence':catalog[mask][['product_id','product_name','category']].to_dict('records'),
                'retrieval':asdict(result),'reranking':ranked})
    finally:await engine.dispose()
    out=Path(args.out)
    with out.open('x',encoding='utf8') as f:json.dump({'scope':'Real hybrid branches and existing rerankers; reference QU, no inference and no route permission generated','records':records},f,ensure_ascii=False,indent=2,default=str)
    print(json.dumps([{'query':r['query'],'matches':len(r['catalog_name_cooccurrence']),'retrieval':r['retrieval']['status']} for r in records]))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--query');p.add_argument('--out',default='data/interim/phase18_6/retrieval_results/relevance_reference_ablation_01.json')
    asyncio.run(main(p.parse_args()))
