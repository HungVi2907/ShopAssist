"""Apply the final safety correction to identical stored native extractions."""
import hashlib
import json
from pathlib import Path
import time

from shopassist.llm.query_understanding import load_catalog_brands_set
from shopassist.llm.transformation import ExtractedShoppingIntent, transform_extraction
try:
    from scripts.evaluate_phase18_3 import summarize_rows
except ModuleNotFoundError:
    from evaluate_phase18_3 import summarize_rows


def main():
    root=Path('data/interim/phase18_3');brands=load_catalog_brands_set()
    for run in ('dev_01','regression_01','provisional_01'):
        source=root/'evaluation_results'/run;out=root/'evaluation_results'/(run+'_safety')
        out.mkdir(exist_ok=False)
        rows=[json.loads(s) for s in (source/'responses.jsonl').read_text(encoding='utf8').splitlines()]
        baseline={r['id']:r['normalized'] for r in rows if r['variant']=='Q0' and 'normalized' in r}
        manifest={'source_run':str(source),'source_responses_sha256':hashlib.sha256((source/'responses.jsonl').read_bytes()).hexdigest(),
            'transformation_sha256':hashlib.sha256(Path('src/shopassist/llm/transformation.py').read_bytes()).hexdigest(),
            'timing':'Inherited live wall time plus measured offline revalidation; conservative estimate, not a fresh end-to-end benchmark.',
            'independence':'Post-provisional safety repair. All datasets now seen; no independent human review.'}
        for row in rows:
            if row['variant']=='Q0' or 'parsed' not in row:continue
            start=time.perf_counter();validation=transform_extraction(row['query'],ExtractedShoppingIntent.model_validate(row['parsed']),brands)
            row['normalized']=validation.output.model_dump();row['transformed']=validation.transformed.model_dump()
            row['semantic_validation']={'status':validation.status,'issues':validation.issues,'corrections':validation.corrections}
            if row['variant']=='Q1' and row['id'] in baseline:row['paired_baseline']=baseline[row['id']]
            row['wall_ms']+=(time.perf_counter()-start)*1000
        with (out/'responses.jsonl').open('x',encoding='utf8') as f:
            for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        (out/'summary.json').write_text(json.dumps(summarize_rows(rows),indent=2),encoding='utf8')
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
        print(out)

if __name__=='__main__':main()
