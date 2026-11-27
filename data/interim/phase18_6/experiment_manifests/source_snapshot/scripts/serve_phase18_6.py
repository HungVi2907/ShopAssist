"""Instrument the actual FastAPI entry point; never replace pipeline results.

Raw query/results are captured only in this isolated supervised test harness.
The normal runtime telemetry remains content-free.
"""
import argparse
import os
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--config',required=True)
p.add_argument('--out',required=True)
p.add_argument('--port',type=int,default=8000)
p.add_argument('--identity-ttl',type=float,default=300)
args=p.parse_args()
out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PGCONNECT_TIMEOUT='5',
    PGOPTIONS='-c default_transaction_read_only=on',API_HOST='127.0.0.1',API_PORT=str(args.port),
    LLM_GATEWAY_ENABLED='true',LLM_GATEWAY_RUNTIME='ollama_experimental',
    LLM_GATEWAY_CONFIG_PATH=str(Path(args.config).resolve()),LLM_GATEWAY_AUTO_FAILOVER='false',
    LLM_GATEWAY_MAX_ATTEMPTS_PER_TASK='1',LLM_GATEWAY_ATTEMPT_TIMEOUT_SECONDS='30',
    LLM_GATEWAY_OLLAMA_IDENTITY_TTL_SECONDS=str(args.identity_ttl),
    LLM_GATEWAY_TELEMETRY_DIR=str((out/'telemetry').resolve()))

import contextvars
from contextlib import asynccontextmanager
import dataclasses
import json
import time
import threading
from pydantic import BaseModel
import shopassist.api.main as main

current=contextvars.ContextVar('phase18_6_request',default=None)
profile=contextvars.ContextVar('phase18_6_profile',default=None)
lock=threading.Lock()


def convert(value):
    if isinstance(value,BaseModel):return value.model_dump(mode='json')
    if dataclasses.is_dataclass(value):return dataclasses.asdict(value)
    if hasattr(value,'tolist'):return value.tolist()
    return str(value)


def event(stage,**fields):
    value={'request_id':current.get(),'stage':stage,'monotonic':time.monotonic(),**fields}
    with lock:
        with (out/'observations.jsonl').open('a',encoding='utf8') as stream:
            stream.write(json.dumps(value,ensure_ascii=False,default=convert)+'\n')


def observe(obj,name,stage,asynchronous):
    original=getattr(obj,name)
    if asynchronous:
        async def wrapped(*a,**kw):
            started=time.perf_counter()
            if stage in ('query_understanding','recommendation'):
                event('gateway_correlation',gateway_request_id=kw.get('request_id'),task_id=kw.get('task_id'),task_stage=stage)
            try:
                result=await original(*a,**kw)
                event(stage,elapsed_ms=(time.perf_counter()-started)*1000,result=result)
                return result
            except BaseException as exc:
                event(stage,elapsed_ms=(time.perf_counter()-started)*1000,error_type=type(exc).__name__)
                raise
    else:
        def wrapped(*a,**kw):
            started=time.perf_counter()
            try:
                result=original(*a,**kw)
                event(stage,elapsed_ms=(time.perf_counter()-started)*1000,result=result)
                return result
            except BaseException as exc:
                event(stage,elapsed_ms=(time.perf_counter()-started)*1000,error_type=type(exc).__name__)
                raise
    setattr(obj,name,wrapped)


build=main._build_gateway
def build_observed(settings):
    gateway=build(settings)
    assert settings.runtime=='ollama_experimental'
    async def request_hook(request):
        if request.url.host!='127.0.0.1' or request.url.port!=11434 or request.url.path not in ('/api/chat','/api/tags'):
            raise RuntimeError('Supervised native validation permits local Ollama only')
        event('native_http',method=request.method,path=request.url.path)
    for adapter in gateway.adapters.values():adapter.client.event_hooks['request'].append(request_hook)
    complete=gateway.complete
    async def complete_profiled(request):
        state=profile.get()
        recommendation=request.task.value=='recommendation_generation'
        if state is not None and recommendation and 'r3_start' in state:
            event('evidence_preparation',elapsed_ms=(time.perf_counter()-state['r3_start'])*1000,
                scope='R3 admission, evidence projection, dynamic schema and request preparation before Gateway')
        result=await complete(request)
        if state is not None and recommendation:state['r3_gateway_finished']=time.perf_counter()
        return result
    gateway.complete=complete_profiled
    return gateway
main._build_gateway=build_observed

lifespan=main.lifespan
@asynccontextmanager
async def observed_lifespan(app):
    start=time.perf_counter()
    try:
        async with lifespan(app):
            for obj,name,stage,asynchronous in [
                (app.state.query_engine,'parse_query_async','query_understanding',True),
                (app.state.preference_service,'represent','preferences',False),
                (app.state.hybrid_service,'retrieve','hybrid_retrieval',True),
                (app.state.reranking_service,'rerank','reranking',False),
                (app.state.recommendation_service,'generate','recommendation',True),
            ]:observe(obj,name,stage,asynchronous)
            import shopassist.llm.transformation as transformation
            observe(transformation,'transform_extraction','python_transformation',False)
            local=app.state.recommendation_service.local_generator
            evaluate=local.evaluate
            async def evaluate_profiled(*a,**kw):
                state=profile.get()
                if state is not None:state['r3_start']=time.perf_counter()
                result=await evaluate(*a,**kw)
                if state is not None and 'r3_gateway_finished' in state:
                    event('recommendation_assembly',elapsed_ms=(time.perf_counter()-state['r3_gateway_finished'])*1000,
                        scope='Validated selection mapping, ownership checks and Python recommendation assembly')
                return result
            local.evaluate=evaluate_profiled
            original=app.state.orchestrator.orchestrate
            async def orchestrate(*a,**kw):
                token=current.set(kw.get('request_id'));started=time.perf_counter()
                try:
                    result=await original(*a,**kw)
                    event('pipeline',elapsed_ms=(time.perf_counter()-started)*1000,result=result)
                    return result
                finally:current.reset(token)
            app.state.orchestrator.orchestrate=orchestrate
            cfg=app.state.settings
            event('startup',elapsed_ms=(time.perf_counter()-start)*1000,
                settings={'api_timeout':cfg.api_request_timeout_seconds,'top_k':cfg.api_default_top_k,
                    'retrieval_top_n':cfg.api_retrieval_top_n,'reranking':cfg.api_reranking_method,
                    'identity_ttl':args.identity_ttl,'workers':1,'database_read_only':True},
                gateway=app.state.gateway.readiness_snapshot())
            yield
    finally:event('shutdown',elapsed_since_start_ms=(time.perf_counter()-start)*1000)
main.lifespan=observed_lifespan

# Local harness instrumentation of installed FastAPI 0.138/Pydantic v2. No
# production schema or validation function is replaced with a different result.
from fastapi._compat.v2 import ModelField
from shopassist.api.schemas import RecommendationRequest
import fastapi.routing
from starlette.responses import JSONResponse
validate=ModelField.validate
def validate_profiled(self,*a,**kw):
    start=time.perf_counter();result=validate(self,*a,**kw)
    if self.field_info.annotation is RecommendationRequest and profile.get() is not None:
        event('input_validation',elapsed_ms=(time.perf_counter()-start)*1000,scope='Pydantic request model validation; excludes body transport/JSON decoding')
    return result
ModelField.validate=validate_profiled
serialize=fastapi.routing.serialize_response
async def serialize_profiled(*a,**kw):
    start=time.perf_counter();result=await serialize(*a,**kw)
    if profile.get() is not None:event('response_model_serialization',elapsed_ms=(time.perf_counter()-start)*1000)
    return result
fastapi.routing.serialize_response=serialize_profiled
render=JSONResponse.render
def render_profiled(self,content):
    start=time.perf_counter();result=render(self,content)
    if profile.get() is not None:event('json_response_render',elapsed_ms=(time.perf_counter()-start)*1000)
    return result
JSONResponse.render=render_profiled

class ProfiledHTTP:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        headers=dict(scope.get('headers',[]))
        token=current.set(headers.get(b'x-request-id',b'profiling-health').decode('ascii','replace'))
        state=profile.set({})
        try:return await self.app(scope,receive,send)
        finally:profile.reset(state);current.reset(token)

main.app=ProfiledHTTP(main.create_app())
main.main()
