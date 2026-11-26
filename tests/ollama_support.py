"""Synthetic evidence for offline tests only; never production approval."""
import hashlib
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import yaml
from shopassist.llm_gateway.config import GatewaySettings,Options
from shopassist.llm.transformation import ExtractedShoppingIntent
from shopassist.recommendation.local import selection_schema

MODEL='qwen2.5:1.5b-instruct-local'
DIGEST='d010eb818583111cfafeb3523cc17802f85dcb7f4fe5e8ecdd4927dca40e3174'


def fingerprint(schema):return hashlib.sha256(json.dumps(schema.model_json_schema(),sort_keys=True).encode()).hexdigest()


def native_config(folder,*,schemas=None,artifact=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    data=yaml.safe_load(Path('config/llm_gateway_ollama_experimental.yaml').read_text(encoding='utf8'))
    if artifact is None:artifact={'kind':'SYNTHETIC OFFLINE TEST EVIDENCE - NOT PRODUCTION APPROVAL'}
    blob=json.dumps(artifact,sort_keys=True).encode();(folder/'artifact.json').write_bytes(blob)
    schemas=schemas or [selection_schema({str(i):[None]*4 for i in range(n)}) for n in (1,3,5)]
    for name,task,schema_id,fps in [('native_query','query_understanding','phase8.intent.flat.v1',[fingerprint(ExtractedShoppingIntent)]),
        ('native_recommendation','recommendation_generation','phase12.catalog-selection.v2',[fingerprint(s) for s in schemas])]:
        route=data['routes'][name];ref=name+'.yaml';route['enabled']=True;route['approval']={'status':'approved','evidence_ref':ref}
        route['cost']={'class':'free','evidence_ref':ref}
        evidence={'route_id':name,'task':task,'provider':'ollama','endpoint':data['providers']['ollama']['endpoint'],'model':MODEL,
            'schema_id':schema_id,'structured_mode':'ollama_schema','status':'valid','approval':'approved','scope':'experimental',
            'cost_class':'free','model_digest':DIGEST,'schema_fingerprints':fps,'inference_options':Options.model_validate(route['options']).model_dump(),
            'artifact_ref':'artifact.json','artifact_sha256':hashlib.sha256(blob).hexdigest(),'valid_until':(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()}
        if task=='recommendation_generation':evidence['dynamic_schema_family']='r3.required-keys.v2'
        (folder/ref).write_text(yaml.safe_dump(evidence),encoding='utf8')
    path=folder/'gateway.yaml';path.write_text(yaml.safe_dump(data,sort_keys=False),encoding='utf8')
    return GatewaySettings(_env_file=None,enabled=True,runtime='ollama_experimental',config_path=path.resolve(),
        auto_failover=False,max_attempts_per_task=1,telemetry_enabled=True,telemetry_dir=folder/'telemetry')


def envelope(content,**updates):
    value={'model':MODEL,'done':True,'done_reason':'stop','message':{'content':json.dumps(content)},
        'prompt_eval_count':12,'eval_count':9,'total_duration':1000000,'load_duration':10000,'prompt_eval_duration':10000,'eval_duration':900000}
    value.update(updates);return value
