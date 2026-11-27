"""Single-dispatch Ollama Native transport; no business logic or repair calls."""
from __future__ import annotations
import asyncio
import json
import math
import re
import time

import httpx
from shopassist.llm_gateway.adapters.base import AdapterResult,PreparedRequest
from shopassist.llm_gateway.errors import ErrorCategory,ReasonCode,ProviderAttemptError
from shopassist.llm_gateway.json_utils import strict_json_loads
from shopassist.llm_gateway.schemas import GatewayUsage,GatewayTimings

MAX_BYTES=1_000_000


def failure(category,*,status=None,usage=None,reported_model=None,timings=None):
    return ProviderAttemptError(category=category,reason_code=ReasonCode(category.value),http_status=status,usage=usage,
        reported_model=reported_model,timings=timings)


class OllamaAdapter:
    def __init__(self,provider,model,*,credential=lambda:'',client=None,identity_ttl_s=300,clock=time.monotonic):
        self.provider=provider;self.model=model;self.credential=credential
        self.client=client or httpx.AsyncClient(trust_env=False,follow_redirects=False,transport=httpx.AsyncHTTPTransport(retries=0))
        self.owns_client=client is None;self.clock=clock;self.ttl=identity_ttl_s
        self.verified_at=None;self.closed=False
        self._identity_lock=asyncio.Lock()
        self._identity_generation=0

    def ready_for(self,route):
        return (not self.closed and self.verified_at is not None and 0<=self.clock()-self.verified_at<self.ttl
            and route.model==self.model and route.endpoint==self.provider.endpoint and route.model_digest==self.provider.model_digest)

    def headers(self):
        if not self.provider.credential_env:return {'Content-Type':'application/json'}
        key=self.credential()
        if not isinstance(key,str) or not key.strip():raise failure(ErrorCategory.AUTHENTICATION)
        return {'Content-Type':'application/json','Authorization':'Bearer '+key}

    async def _read(self,method,path,*,timeout_s,body=None):
        try:
            async with self.client.stream(method,self.provider.endpoint.rstrip('/')+path,content=body,headers=self.headers(),
                    timeout=timeout_s,follow_redirects=False,auth=None) as response:
                status=response.status_code
                if not 200<=status<300:
                    category={401:ErrorCategory.AUTHENTICATION,403:ErrorCategory.PERMISSION_DENIED,408:ErrorCategory.ATTEMPT_TIMEOUT,
                        429:ErrorCategory.RATE_LIMITED,404:ErrorCategory.INCOMPATIBLE_ROUTE}.get(status,
                        ErrorCategory.PROVIDER_UNAVAILABLE if status>=500 else ErrorCategory.PROVIDER_REJECTED)
                    raise failure(category,status=status)
                data=bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>MAX_BYTES:raise failure(ErrorCategory.INVALID_OUTPUT,status=status)
                try:return strict_json_loads(data.decode('utf8'))
                except (ValueError,UnicodeError):raise failure(ErrorCategory.INVALID_OUTPUT,status=status) from None
        except asyncio.CancelledError:raise
        except ProviderAttemptError:raise
        except httpx.TimeoutException:raise failure(ErrorCategory.ATTEMPT_TIMEOUT) from None
        except httpx.NetworkError:raise failure(ErrorCategory.NETWORK_ERROR) from None
        except httpx.HTTPError:raise failure(ErrorCategory.PROVIDER_REJECTED) from None

    async def verify_model(self,*,timeout_s=5):
        self.verified_at=None
        if self.closed:return False
        try:
            data=await self._read('GET','/api/tags',timeout_s=timeout_s)
            matches=[m for m in data['models'] if m.get('name')==self.model]
            if len(matches)!=1:return False
            match=matches[0]
            if match.get('digest')!=self.provider.model_digest:return False
            self.verified_at=self.clock();return True
        except asyncio.CancelledError:raise
        except (ProviderAttemptError,KeyError,TypeError,StopIteration,AttributeError):return False
        finally:self._identity_generation+=1

    async def ensure_identity(self,route,*,timeout_s=5):
        """Coalesce stale checks; permission and fingerprint approval stay in Gateway."""
        if self.ready_for(route):return True
        generation=self._identity_generation
        async with self._identity_lock:
            if self.ready_for(route):return True
            # Another concurrent waiter already observed this failed verification.
            if self._identity_generation!=generation:return False
            if not await self.verify_model(timeout_s=timeout_s):return False
            return self.ready_for(route)

    def prepare(self,request,route):
        if route.provider!='ollama' or route.structured_mode!='ollama_schema' or not self.ready_for(route):
            raise failure(ErrorCategory.INCOMPATIBLE_ROUTE)
        cap={'phase8.intent.flat.v1':512,'phase12.catalog-selection.v2':256}.get(request.schema_id)
        if cap is None or route.options['max_output_tokens']!=cap or route.options['context_limit_tokens']!=4096 or route.options['seed']!=42 or route.options['temperature']!=0:
            raise failure(ErrorCategory.INCOMPATIBLE_ROUTE)
        # Conservative admission of explicit messages; never truncate requirements.
        if len((request.system_prompt+request.user_prompt).encode('utf8'))+cap+256>4096:
            raise failure(ErrorCategory.INVALID_REQUEST)
        body=json.dumps({'model':route.model,'messages':[{'role':'system','content':request.system_prompt},{'role':'user','content':request.user_prompt}],
            'format':request.response_schema.model_json_schema(),'stream':False,
            'options':{'temperature':0,'seed':42,'num_ctx':4096,'num_predict':cap}},ensure_ascii=False).encode('utf8')
        if len(body)>MAX_BYTES:raise failure(ErrorCategory.INVALID_REQUEST)
        return PreparedRequest(route,request,body)

    async def complete_once(self,prepared,*,timeout_s,on_dispatch):
        if not math.isfinite(timeout_s) or timeout_s<=0 or not self.ready_for(prepared.route):raise failure(ErrorCategory.INVALID_REQUEST)
        on_dispatch()
        data=await self._read('POST','/api/chat',body=prepared.body,timeout_s=timeout_s)
        if not isinstance(data,dict):raise failure(ErrorCategory.INVALID_OUTPUT)
        reported=data.get('model')
        # Only bounded model identifiers may enter content-free telemetry.
        safe_model=reported if isinstance(reported,str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,128}',reported) else None
        def count(key):
            n=data.get(key)
            if n is not None and (type(n) is not int or n<0):raise failure(ErrorCategory.INVALID_OUTPUT)
            return n
        a,b=count('prompt_eval_count'),count('eval_count')
        total=a+b if a is not None and b is not None else None
        if 'total_tokens' in data and count('total_tokens')!=total:raise failure(ErrorCategory.INVALID_OUTPUT)
        usage=GatewayUsage(input_tokens=a,output_tokens=b,total_tokens=total)
        durations={k:count(k) for k in ('total_duration','load_duration','prompt_eval_duration','eval_duration')}
        if durations['total_duration'] is not None and sum(v or 0 for k,v in durations.items() if k!='total_duration')>durations['total_duration']:
            raise failure(ErrorCategory.INVALID_OUTPUT,usage=usage)
        timings=GatewayTimings(**{name:(durations[key]/1e6 if durations[key] is not None else None) for name,key in
            [('total_ms','total_duration'),('load_ms','load_duration'),('prompt_eval_ms','prompt_eval_duration'),('eval_ms','eval_duration')]})
        if reported!=prepared.route.model:
            raise failure(ErrorCategory.INCOMPATIBLE_ROUTE,usage=usage,reported_model=safe_model,timings=timings)
        content=data.get('message',{}).get('content') if isinstance(data.get('message'),dict) else None
        if data.get('done') is not True or data.get('done_reason')!='stop' or not isinstance(content,str) or not content.strip() or len(content.encode('utf8'))>MAX_BYTES:
            raise failure(ErrorCategory.INVALID_OUTPUT,usage=usage,reported_model=safe_model,timings=timings)
        if a is not None and a+prepared.route.options['max_output_tokens']>4096:
            raise failure(ErrorCategory.INVALID_OUTPUT,usage=usage,reported_model=safe_model,timings=timings)
        return AdapterResult(raw_text=content,usage=usage,http_status=200,reported_model=data['model'],timings=timings)

    async def aclose(self):
        if self.closed:return
        self.closed=True;self.verified_at=None
        if self.owns_client:await self.client.aclose()
