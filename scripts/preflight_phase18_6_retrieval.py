"""Real read-only hybrid/reranking baseline from captured frozen Q1S results.

This supervised preparation produces exact evidence shapes before subsequent
API requests. It never approves schemas during ordinary application requests.
"""
import os
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PGCONNECT_TIMEOUT='5',PGOPTIONS='-c default_transaction_read_only=on')
import asyncio
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import pandas as pd
from sqlalchemy import text
from shopassist.db.connection import get_async_engine
from shopassist.llm.schemas import QueryUnderstandingResult
from shopassist.preferences.service import PreferenceRepresentationService
from shopassist.preferences.embedding import PreferenceQueryEncoder
from shopassist.retrieval.semantic import DenseQueryEncoder
from shopassist.retrieval.tfidf import TFIDFIndex
from shopassist.retrieval.hybrid import HybridRetrievalService
from shopassist.reranking.core import RerankingService,load_canonical_product_texts,RerankingMethod
from shopassist.api.price_adapter import PriceBoundaryAdapter
from shopassist.recommendation.context import EvidenceContextBuilder
from shopassist.recommendation.local import selection_schema,relevance_issue
from validate_phase18_5 import fp

OUT=Path('data/interim/phase18_6')


async def main(args):
    observations=[json.loads(s) for s in Path(args.observations).read_text(encoding='utf8').splitlines()]
    captured=[r for r in observations if r['stage']=='query_understanding' and r['result']['is_valid'] and not r['result']['output']['needs_clarification']]
    encoder=DenseQueryEncoder();prefs=PreferenceRepresentationService(encoder=PreferenceQueryEncoder(dense_query_encoder=encoder))
    idx=TFIDFIndex.load();engine=get_async_engine(pool_size=1,max_overflow=0)
    hybrid=HybridRetrievalService(engine,idx,query_encoder=encoder)
    reranker=RerankingService(text_provider=load_canonical_product_texts('data/processed/products.parquet'))
    results=[];schemas={};trace={}
    original_fetch=hybrid._fetch_dense_rows
    async def fetch(*a,**kw):
        result=await original_fetch(*a,**kw);trace['dense_rows']=result[0];return result
    hybrid._fetch_dense_rows=fetch
    search=idx.search
    def lexical(*a,**kw):
        rows=search(*a,**kw);trace['lexical_before_filter_top20']=[r.__dict__ for r in rows[:20]];return rows
    idx.search=lexical
    try:
        for capture in captured:
            q=QueryUnderstandingResult.model_validate(capture['result']);trace={}
            preference=await asyncio.to_thread(prefs.represent,q)
            hc=q.output.hard_constraints;semantics=PriceBoundaryAdapter.resolve(q.query,hc.min_price,hc.max_price)
            retrieval=await hybrid.retrieve(q,preference,price_boundary_semantics=semantics.semantics)
            row={'request_id':capture['request_id'],'query':q.model_dump(mode='json'),'preference':preference.model_dump(mode='json'),
                'price_semantics':semantics.semantics,'retrieval':asdict(retrieval),'branch_trace':trace,'reranking_by_top_k':[]}
            for n in range(1,6):
                ranked=reranker.rerank(q,preference,retrieval,top_k=n,method=RerankingMethod.RRF)
                issue=relevance_issue(q,ranked.products) if ranked.products else 'No candidates'
                binding=None
                if ranked.status.value=='SUCCESS' and issue is None:
                    _,store,_=EvidenceContextBuilder().build_context(q,preference,ranked.products)
                    supplied={p.product_id:[e for e in store[p.product_id] if e.source_field in
                        ('product_name','brand','category','discounted_price','rating','specifications')] for p in ranked.products}
                    schema=selection_schema(supplied);schemas[fp(schema)]=schema
                    binding={'fingerprint':fp(schema),'fact_counts':[len(f) for f in supplied.values()]}
                row['reranking_by_top_k'].append({'top_k':n,'status':ranked.status.value,'products':[p.__dict__ for p in ranked.products],
                    'stage_latency_ms':ranked.stage_latency_ms,'relevance_issue':issue,'binding':binding})
            results.append(row)
            print(json.dumps({'request':capture['request_id'],'retrieval':retrieval.status.value,'candidates':len(retrieval.candidates),'eligible_shapes':sum(r['binding'] is not None for r in row['reranking_by_top_k'])}),flush=True)
        # Explain observed metadata differences without changing database values.
        catalog=pd.read_parquet('data/processed/products.parquet').set_index('product_id')
        async with engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION READ ONLY'))
            db=list((await conn.execute(text('SELECT product_id,rating FROM public.products WHERE rating IS NOT NULL'))).mappings())
        diffs=[abs(float(r['rating'])-float(catalog.loc[r['product_id'],'rating'])) for r in db]
        precision={'non_null_ratings':len(db),'exact_float_mismatches':sum(d>0 for d in diffs),'max_abs_difference':max(diffs),
            'within_1e_6':all(d<1e-6 for d in diffs),'policy':'Keep authoritative DB values; compare numeric catalog agreement with explicit tolerance. No DB mutation.'}
    finally:await engine.dispose()
    path=Path(args.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8') as f:json.dump({'scope':'Real database/pgvector + local BGE/TF-IDF + RRF, reusing captured Q1S; no additional inference','results':results,'rating_precision':precision},f,ensure_ascii=False,indent=2,default=str)
    print(json.dumps({'observed_fingerprints':len(schemas),'rating_precision':precision,'approval':'No routes approved by this collection step'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    parser.add_argument('--observations',default='data/interim/phase18_6/api_test_results/server_01/observations.jsonl')
    asyncio.run(main(parser.parse_args()))
