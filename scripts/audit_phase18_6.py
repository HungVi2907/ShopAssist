"""Read-only runtime audit. Never records DSNs or exception messages."""
import os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
import asyncio
import hashlib
import importlib.metadata
import json
import platform
import argparse
from pathlib import Path
import time
import httpx
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import make_url
from shopassist.db.connection import get_async_engine,get_async_database_url
from shopassist.core.config import PROCESSED_DATA_DIR
from shopassist.retrieval.tfidf import TFIDFIndex, DEFAULT_TFIDF_ARTIFACT_DIR

OUT=Path('data/interim/phase18_6/runtime_validation')


async def main(name):
    OUT.mkdir(parents=True,exist_ok=True)
    report={'python':platform.python_version(),'packages':{p:importlib.metadata.version(p) for p in
        ['fastapi','uvicorn','httpx','pydantic','sqlalchemy','psycopg','pgvector','torch','sentence-transformers','scikit-learn']}}
    catalog=pd.read_parquet(PROCESSED_DATA_DIR/'products.parquet')
    report['catalog']={'count':len(catalog),'columns':list(catalog.columns),'duplicate_ids':int(catalog.product_id.duplicated().sum()),
        'sha256':hashlib.sha256((PROCESSED_DATA_DIR/'products.parquet').read_bytes()).hexdigest()}
    idx=TFIDFIndex.load()
    report['tfidf']={'count':len(idx.product_ids),'id_symmetric_difference':len(set(idx.product_ids)^set(catalog.product_id.astype(str))),
        'artifacts':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in DEFAULT_TFIDF_ARTIFACT_DIR.iterdir() if p.is_file()},
        'metadata_columns':list(idx.metadata_df.columns)}
    async with httpx.AsyncClient(trust_env=False,timeout=5) as client:
        try:
            response=await client.get('http://127.0.0.1:11434/api/tags');response.raise_for_status()
            report['ollama']={'tags':response.json(),'version':(await client.get('http://127.0.0.1:11434/api/version')).json()}
        except Exception as exc:report['ollama']={'blocker':type(exc).__name__}
    engine=None
    step='connect'
    try:
        url=make_url(get_async_database_url()).update_query_dict({'connect_timeout':'10','options':'-c default_transaction_read_only=on'})
        engine=get_async_engine(url=url.render_as_string(hide_password=False),pool_size=1,max_overflow=0)
        async def inspect():
            async with engine.connect() as conn:
                await conn.execute(text('SET TRANSACTION READ ONLY'))
                await conn.execute(text("SET LOCAL statement_timeout = '15000'"))
                report['database']={'server_version':(await conn.execute(text('SHOW server_version'))).scalar(),
                    'read_only':(await conn.execute(text('SHOW transaction_read_only'))).scalar(),
                    'vector_extension':(await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))).scalar(),
                    'columns':list((await conn.execute(text("SELECT column_name,data_type,udt_name FROM information_schema.columns WHERE table_schema='public' AND table_name='products' ORDER BY ordinal_position"))).mappings()),
                    'indexes':list((await conn.execute(text("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND tablename='products'"))).mappings())}
                rows=list((await conn.execute(text('SELECT product_id,product_name,brand,category,discounted_price,rating,embedding_model,vector_dims(embedding) AS dimension FROM public.products'))).mappings())
                db=pd.DataFrame(rows);local=catalog.set_index('product_id');dbids=db.product_id.astype(str)
                report['database'].update(count=len(db),duplicate_ids=int(dbids.duplicated().sum()),missing_embeddings=int(db.dimension.isna().sum()),
                    dimensions={str(k):int(v) for k,v in db.dimension.value_counts(dropna=False).items()},
                    embedding_models={str(k):int(v) for k,v in db.embedding_model.value_counts(dropna=False).items()},
                    id_symmetric_difference=len(set(dbids)^set(local.index)),
                    missing_names=int(db.product_name.isna().sum()),missing_categories=int(db.category.isna().sum()),
                    missing_prices=int(db.discounted_price.isna().sum()),missing_brands=int(db.brand.isna().sum()),missing_ratings=int(db.rating.isna().sum()))
                mismatch=[]
                for row in rows:
                    if row['product_id'] not in local.index:continue
                    old=local.loc[row['product_id']]
                    for key in ('product_name','category','brand','discounted_price','rating'):
                        a,b=row[key],old[key]
                        if pd.isna(a) and pd.isna(b):continue
                        if a!=b:mismatch.append({'product_id':row['product_id'],'field':key})
                report['database']['metadata_mismatches']=mismatch
        started=time.perf_counter();await asyncio.wait_for(inspect(),timeout=40)
        report['database']['audit_ms']=(time.perf_counter()-started)*1000
    except Exception as exc:
        original=getattr(exc,'orig',exc)
        reason=str(original).lower()
        report['database']={**report.get('database',{}),'blocker':type(exc).__name__,
            'driver_error_type':type(original).__name__,'sqlstate':getattr(original,'sqlstate',None),
            'reason_flags':{word:word in reason for word in ('timeout','password authentication failed','ssl','resolve','refused','tenant','pool')},
            'connection_timeout_seconds':10}
    finally:
        if engine:await engine.dispose()
    path=OUT/name
    with path.open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2,default=dict)
    print(json.dumps({'catalog':report['catalog']['count'],'tfidf':report['tfidf']['count'],'db':{k:v for k,v in report['database'].items() if k not in ('columns','indexes','metadata_mismatches')},'ollama':report['ollama'].get('blocker','available')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--name',default='audit_02.json')
    asyncio.run(main(parser.parse_args().name))
