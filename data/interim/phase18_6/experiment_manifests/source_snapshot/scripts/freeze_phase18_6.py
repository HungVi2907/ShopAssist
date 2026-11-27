"""Finalize source/artifact integrity and read-only price/index consistency."""
import os
os.environ.update(PGCONNECT_TIMEOUT='5',PGOPTIONS='-c default_transaction_read_only=on')
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from datetime import datetime,timezone
import pandas as pd
from sqlalchemy import text
from shopassist.db.connection import get_async_engine
from shopassist.retrieval.tfidf import TFIDFIndex
from shopassist.llm.extraction import EXTRACTION_PROMPT
from shopassist.recommendation.local import SELECTION_PROMPT

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/interim/phase18_6'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)


async def main():
    catalog=pd.read_parquet(ROOT/'data/processed/products.parquet').set_index('product_id')
    idx=TFIDFIndex.load();meta=idx.metadata_df.set_index('product_id')
    consistency={}
    for field in ('product_name','category','brand','discounted_price','rating'):
        if field not in meta.columns:continue
        count=0
        for pid in catalog.index:
            a,b=catalog.loc[pid,field],meta.loc[pid,field]
            if pd.isna(a) and pd.isna(b):continue
            if a!=b:count+=1
        consistency[field]=count
    engine=get_async_engine(pool_size=1,max_overflow=0)
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION READ ONLY'))
            counts=dict((await conn.execute(text('''SELECT
                COUNT(*) FILTER (WHERE discounted_price<=0) AS nonpositive_discounted_prices,
                COUNT(*) FILTER (WHERE retail_price<discounted_price) AS discount_above_retail,
                COUNT(*) FILTER (WHERE rating<1 OR rating>5) AS out_of_range_ratings
                FROM public.products'''))).mappings().one())
    finally:await engine.dispose()
    save(OUT/'runtime_validation/catalog_quality_detail.json',{'database_read_only':True,'database_counts':counts,'tfidf_catalog_metadata_mismatches':consistency})
    protected=['config/llm_gateway.yaml','config/llm_gateway_ollama_experimental.yaml',
        'src/shopassist/llm/extraction.py','src/shopassist/llm/transformation.py','src/shopassist/llm/constraints.py',
        'src/shopassist/llm/normalization.py','src/shopassist/llm/schemas.py','src/shopassist/api/schemas.py',
        'src/shopassist/recommendation/schemas.py','src/shopassist/recommendation/context.py','src/shopassist/recommendation/validation.py',
        'data/interim/phase18_t17','data/interim/phase18_3','data/interim/phase18_4','data/interim/phase18_5','docs/phase18_5']
    subprocess.run(['git','diff','--exit-code','HEAD','--',*protected],cwd=ROOT,check=True,capture_output=True)
    changed=subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=ROOT,text=True).splitlines()
    new=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
    sources=sorted({p for p in changed+new if p.startswith(('src/','tests/','scripts/'))})
    folder=OUT/'experiment_manifests/source_snapshot';folder.mkdir(parents=True,exist_ok=False)
    for name in sources:
        target=folder/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    raw=(OUT/'offline_regression_05.txt').read_bytes()
    assert '765 passed, 1 warning' in raw.decode('utf16' if raw.startswith(b'\xff\xfe') else 'utf8')
    review=json.loads((OUT/'performance_results/review_02.json').read_text(encoding='utf8'))
    assert review['counts']['successful_requests']==7
    assert all(row['at_most_two_calls'] and row['public_usage_matches_reported_counts'] for row in review['checks'])
    manifest={'date_local':'2026-11-27 Asia/Saigon','frozen_utc':datetime.now(timezone.utc).isoformat(),
        'starting_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_sha256':{p:sha(ROOT/p) for p in sources},'protected_git_paths_unchanged':protected,
        'model':'qwen2.5:1.5b-instruct-local','digest':'d010eb818583111cfafeb3523cc17802f85dcb7f4fe5e8ecdd4927dca40e3174',
        'q1s_prompt_sha256':hashlib.sha256(EXTRACTION_PROMPT.encode()).hexdigest(),
        'r3_prompt_sha256':hashlib.sha256(SELECTION_PROMPT.encode()).hexdigest(),
        'backend_integration':'validated experimental scope','telegram':'ready for supervised testing; no live Telegram network test',
        'production_approved':False,'phase18_status':'IMPLEMENTED_PENDING_BACKUP_VALIDATION',
        'failed_runs_preserved':True,'committed_or_pushed':False}
    save(OUT/'experiment_manifests/final_manifest.json',manifest)
    paths=sorted(p for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    documents=sorted((ROOT/'docs/phase18_6').glob('*.md'))
    save(OUT/'experiment_manifests/index.json',{'sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in paths},
        'documents_sha256':{p.relative_to(ROOT).as_posix():sha(p) for p in documents},
        'index_scope':'Self-excluding, immutable final snapshot; raw evaluation artifacts are separate from production telemetry.'})
    print(json.dumps({'sources_frozen':len(sources),'artifacts_indexed':len(paths),'quality':counts,'tfidf_mismatches':consistency}))


if __name__=='__main__':asyncio.run(main())
