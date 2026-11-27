"""Prepare catalog-derived test shapes and preclassified cases; no inference."""
import os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
import asyncio
import hashlib
import json
from pathlib import Path
import time
import httpx
import pandas as pd
from shopassist.llm.schemas import QueryUnderstandingResult,QueryUnderstandingOutput
from shopassist.retrieval.tfidf import TFIDFIndex
from shopassist.reranking.core import RerankedProduct,load_local_cross_encoder
from shopassist.recommendation.context import EvidenceContextBuilder
from shopassist.recommendation.local import selection_schema,relevance_issue
from shopassist.retrieval.semantic import DenseQueryEncoder
from validate_phase18_5 import configuration,sha,fp,MODEL,DIGEST

OUT=Path('data/interim/phase18_6')


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)


def product(row,rank):
    return RerankedProduct(product_id=str(row.product_id),product_name=row.product_name,category=row.category,
        brand=None if pd.isna(row.brand) else row.brand,discounted_price=float(row.discounted_price),
        rating=None if pd.isna(row.rating) else float(row.rating),original_rank=rank,reranked_rank=rank,
        retrieval_text=row.retrieval_text,rrf_score=1/(60+rank),final_score=1/(60+rank),sources={},
        metadata={'retail_price':None if pd.isna(row.retail_price) else float(row.retail_price),
            'product_specifications':row.product_specifications,'product_description':row.description})


async def main():
    catalog=pd.read_parquet('data/processed/products.parquet');index=TFIDFIndex.load();by_id=catalog.set_index('product_id',drop=False)
    lexical=index.search('running shoes',top_k=len(catalog))
    rows=[by_id.loc[r.product_id] for r in lexical if 'running shoes' in r.product_name.lower() and r.discounted_price<2000][:5]
    products=[product(row,i) for i,row in enumerate(rows,1)]
    query=QueryUnderstandingResult(query='running shoes under 2000 INR',output=QueryUnderstandingOutput(
        semantic_query='running shoes',hard_constraints={'category':'Footwear','max_price':2000}))
    shapes=[];fixtures=[]
    for n in range(1,6):
        pp=products[:n];assert relevance_issue(query,pp) is None
        _,store,_=EvidenceContextBuilder().build_context(query,None,pp)
        supplied={p.product_id:[e for e in store[p.product_id] if e.source_field in
            ('product_name','brand','category','discounted_price','rating','specifications')] for p in pp}
        schema=selection_schema(supplied);schema.model_validate({f'p{i}':[1] for i in range(1,n+1)})
        shapes.append(schema);fixtures.append({'candidate_count':n,'schema_fingerprint':fp(schema),
            'fact_counts':[len(f) for f in supplied.values()],'products':[p.__dict__ for p in pp]})
    cases=[
        ('running shoes under 2000 INR','Successful recommendation',3),
        ('AMCO running shoes under 2000 INR','Successful recommendation',2),
        ('comfortable running shoes for daily jogging under 2000 INR','Successful recommendation',4),
        ('headphones under 1000 INR','Successful recommendation if product type is verified',5),
        ('cheap headphones','Clarification or guarded recommendation; no invented numeric budget',3),
        ('headphones with at least 4 stars','Successful recommendation if catalog rating/type are verified',3),
        ('laptop between 20000 and 40000 INR','No relevant results; catalog laptop accessories do not establish actual laptops',3),
        ('laptop with 16 GB RAM','Clarification or validation failure unless mandatory specification is established',3),
        ('laptop under 500 dollars','Clarification or unsupported currency',3),
        ('pet food','Clarification or unsupported category',3),
        ('I need something nice','Clarification required',3),
        ('shoes without leather','Unsupported exclusion',3),
        ('laptop but not gaming','Unsupported exclusion',3),
        ('camera lens with no telephoto lenses','Unsupported exclusion',3),
        ('Nike or Puma shoes','Clarification for conflicting manufacturers',3),
        ('wireless charging pad','No verified relevant product; never accept cable as substitute',3),
        ('Bluetooth speaker','No verified relevant product; never accept headphones as substitute',3),
        ('Honda City body cover','No verified compatible body cover; never accept steering cover',3),
        ('Shoes not exceeding 2000 rupees','Numeric expression passes exclusion guards; guarded recommendation if relevant candidates exist',3),
        ('Tôi cần giày chạy bộ dưới 2000 INR','Vietnamese clarification or catalog-backed guarded recommendation',3),
        ('running shoes under 1 INR','No matching products',3),
    ]
    save(OUT/'api_test_results/cases_preclassified.json',{'scope':'Classified before API execution; database outage is an integration blocker, not an expected functional pass.',
        'cases':[{'id':f'E{i:02d}','query':q,'expected':expected,'top_k':k,'language':'vi' if i==20 else 'en'} for i,(q,expected,k) in enumerate(cases,1)]})
    analysis=[]
    for query_text in ['wireless charging pad','Bluetooth speaker','Honda City body cover','Puma running shoes']:
        found=catalog[catalog.product_name.str.contains(query_text,case=False,regex=False)]
        lexical_rows=index.search(query_text,top_k=10)
        analysis.append({'query':query_text,'exact_type_name_matches':found[['product_id','product_name','category','discounted_price']].to_dict('records'),
            'lexical_top':[{'product_id':r.product_id,'name':r.product_name,'score':r.tfidf_score} for r in lexical_rows],
            'finding':'No name evidence for exact requested type/compatibility; absence of exact name alone does not prove absence from all specifications.'})
    save(OUT/'retrieval_results/local_catalog_baseline.json',{'scope':'Actual local TF-IDF/catalog inspection only; database hybrid baseline remains blocked.',
        'catalog_rows':len(catalog),'analysis':analysis,'tested_selection_shapes':fixtures,
        'catalog_product_id_duplicates':int(catalog.product_id.duplicated().sum()),
        'tfidf_ids_match':set(catalog.product_id.astype(str))==set(index.product_ids)})
    resource={};start=time.perf_counter();encoder=DenseQueryEncoder();vector=encoder.encode_query('running shoes')
    resource['bge']={'model':encoder._model.model_name,'dimension':len(vector),'device':encoder._model.device,
        'load_and_encode_ms':(time.perf_counter()-start)*1000,'offline':True}
    model_dir=Path('.models/phase11/ms-marco-MiniLM-L2-v2');start=time.perf_counter()
    scorer=load_local_cross_encoder(model_path=str(model_dir),device='cpu',local_files_only=True)
    scores=scorer.predict([('running shoes',p.retrieval_text) for p in products],batch_size=5)
    resource['reranker']={'offline':True,'existing_model_only':True,'device':'cpu','load_and_score_ms':(time.perf_counter()-start)*1000,
        'scores':[float(s) for s in scores],'artifacts_sha256':{p.name:sha(p) for p in model_dir.iterdir() if p.is_file()}}
    save(OUT/'runtime_validation/neural_resources.json',resource)
    async with httpx.AsyncClient(trust_env=False,timeout=5) as client:
        tags=(await client.get('http://127.0.0.1:11434/api/tags')).json()
    identity=next(m for m in tags['models'] if m['name']==MODEL);assert identity['digest']==DIGEST
    report=OUT/'offline_focused_03.txt';raw=report.read_bytes();decoded=raw.decode('utf16' if raw.startswith(b'\xff\xfe') else 'utf8')
    assert 'passed' in decoded and ' failed' not in decoded
    artifact={'authorization':'User Phase18.6 supervised experimental integration tests only; not production approval',
        'verified_tags':identity,'catalog_sha256':sha(Path('data/processed/products.parquet')),
        'offline_report':str(report),'offline_sha256':sha(report),
        'prior_native_index_sha256':sha(Path('data/interim/phase18_5/experiment_manifests/index.json')),
        'catalog_fixtures_sha256':sha(OUT/'retrieval_results/local_catalog_baseline.json'),
        'schemas':{fp(s):s.model_json_schema() for s in shapes},'production_semantic_approval':False,
        'database_acceptance':'Blocked by connection timeout; these shapes are from actual local catalog evidence, not database acceptance.'}
    configuration(OUT/'route_validation',artifact,shapes)
    save(OUT/'route_validation/catalog_task_fixtures.json',{'query_result':query.model_dump(mode='json'),'shapes':fixtures})
    print(json.dumps({'shapes':[f['fact_counts'] for f in fixtures],'prepared_cases':len(cases),'local_models':'verified offline'}))


if __name__=='__main__':asyncio.run(main())
