"""Metadata-only model lifecycle tracing; reversible, no inference or payload logs."""
import asyncio
from collections import Counter,deque
from contextlib import contextmanager
from contextvars import ContextVar
import functools
import importlib
import inspect
import json
import re
import time
from uuid import uuid4

_CURRENT=ContextVar('qq_model_operation',default={})
_ACTIVE=ContextVar('qq_model_logging_active',default=frozenset())


def event_trace(event):
    decision=event.get_extra('user_policy_decision')
    persona=str(event.get_extra('user_policy_effective_persona_id') or getattr(decision,'persona_id',''))
    trace=event.get_extra('qq_model_trace')
    if trace:
        if persona:trace['persona']=persona
        if event.get_extra('qq_diagnostic'):trace['diagnostic']=True
        return trace
    trace={'trace':uuid4().hex[:12],'group':str(event.get_group_id() or ''),
           'message':str(getattr(event.message_obj,'message_id','') or ''),
           'persona':persona,
           'diagnostic':bool(event.get_extra('qq_diagnostic'))}
    event.set_extra('qq_model_trace',trace)
    event.set_extra('qq_model_trace_started',time.monotonic())
    return trace


@contextmanager
def model_operation(purpose,trace=None):
    token=_CURRENT.set({**_CURRENT.get(),**(trace or {}),'purpose':purpose})
    try:yield
    finally:_CURRENT.reset(token)


async def scoped_iterator(source,purpose,trace=None):
    """Scope each pull/close, never hold a ContextVar token across a yield.

    Consumers may stop early and Python can finalize the generator in another
    task. Keeping a token live across yield leaks it into the consumer and
    makes reset fail when finalization happens in another Context.
    """
    iterator=source.__aiter__()
    try:
        while True:
            with model_operation(purpose,trace):
                try:value=await anext(iterator)
                except StopAsyncIteration:return
            yield value
    finally:
        close=getattr(iterator,'aclose',None)
        if close:
            with model_operation(purpose,trace):await close()


def _caller_purpose(kind):
    frame=inspect.currentframe()
    try:
        for _ in range(24):
            if frame is None:break
            module=frame.f_globals.get('__name__','')
            if 'astrbot_plugin_livingmemory' in module:return 'memory_embedding' if kind=='embedding' else 'memory_processing'
            if 'astrbot_plugin_self_initiated_reply' in module:return 'background_reply_judge'
            if frame.f_code.co_name in ('_get_image_caption','_ensure_img_caption'):return 'vision_caption'
            frame=frame.f_back
    finally:del frame
    return kind


def count_image_parts(contexts=(),image_urls=(),extra_parts=()):
    def count(parts):
        if not isinstance(parts,(list,tuple)):return 0
        return sum((p.get('type') if isinstance(p,dict) else getattr(p,'type',None)) in ('image','image_url','input_image') for p in parts)
    return len(image_urls or [])+count(extra_parts)+sum(count(r.get('content')) for r in contexts or [] if isinstance(r,dict))


class ModelActivityLogger:
    METHODS={'text_chat':'text','text_chat_stream':'text','get_embedding':'embedding',
             'get_embeddings':'embedding','get_embeddings_batch':'embedding','rerank':'rerank',
             'get_text':'speech_to_text','get_audio':'text_to_speech','get_audio_stream':'text_to_speech'}

    def __init__(self,settings=None,sink=None):
        self.settings=settings or {};self.sink=sink
        self.patches=[];self.active={};self.recent=deque(maxlen=50);self.counts=Counter()

    def emit(self,state,**fields):
        # Whitelist metadata: never serialize prompts, tool args, exception
        # strings, images, API URLs, completions, or credentials.
        if not self.settings.get('enabled',True):return {}
        allowed={'trace','group','message','persona','diagnostic','purpose','call','parent',
                 'kind','provider','model','seconds','first_output_seconds','stream','outcome',
                 'error_type','http_status','tool_calls','input_tokens','output_tokens',
                 'context_messages','image_count','tool_count','input_chars','node','mode',
                 'reason','next','route','image_tool_calls','configured_timeout_seconds',
                 'selected_previous_reference','available_reference_count','attached_reference_count'}
        row={'event':state,**{k:v for k,v in fields.items() if k in allowed and v is not None}}
        for k,v in list(row.items()):
            if isinstance(v,str):row[k]=v.replace('\n',' ').replace('\r',' ')[:240]
        try:
            if self.sink:self.sink(row)
            else:
                from astrbot.api import logger
                labels={'start':'开始请求','waiting':'仍在等待模型接口','first_output':'收到首个输出',
                        'success':'调用完成','error':'调用失败','cancelled':'调用取消或超时中断',
                        'request_ready':'正文请求已准备','routing_done':'接话路由结束',
                        'reply_done':'本轮模型回复结束','sent':'消息发送完成'}
                labels['image_reference_check']='绘图参考图检查'
                if state=='routing_done' and row.get('next')=='main_reply_not_started':
                    labels[state]='判断超时，未进入正文生成' if row.get('error_type')=='TimeoutError' else '判断失败，未进入正文生成' if row.get('reason')=='judge_unavailable' else '本条未进入正文生成'
                if state=='routing_done' and str(row.get('reason','')).startswith('context_review_'):labels[state]='判断未完成，转主模型核对上下文'
                method=logger.warning if state in ('error','cancelled') else logger.info
                method('[AI调用] %s %s',labels.get(state,state),json.dumps(row,ensure_ascii=False,separators=(',',':')))
        except Exception:
            # Observability must never break the real model request.
            pass
        return row

    def patch(self,owner,name,build):
        if any(o is owner and n==name for o,n,*_ in self.patches):return
        original=getattr(owner,name,None)
        if original is None:return
        owned=name in owner.__dict__
        wrapper=build(original)
        setattr(owner,name,wrapper);self.patches.append((owner,name,wrapper,original,owned))

    def restore(self):
        for owner,name,wrapper,original,owned in reversed(self.patches):
            if getattr(owner,name,None) is wrapper:
                if owned:setattr(owner,name,original)
                else:delattr(owner,name)
        self.patches.clear()

    @staticmethod
    def identity(instance,kwargs,kind):
        provider=model=None
        try:
            cfg=getattr(instance,'provider_config',None) or getattr(instance,'config',None)
            def field(name):return cfg.get(name) if isinstance(cfg,dict) else getattr(cfg,name,None)
            provider=field('id');model=kwargs.get('model')
            if not model:
                getter=getattr(instance,'get_model',None)
                try:model=getter() if callable(getter) else None
                except Exception:pass
            if not model:model=getattr(instance,'model',None) or field('embedding_model') or field('model') or field('stt_model') or field('tts_model') or field('rerank_model')
        except Exception:pass
        return {'provider':str(provider or type(instance).__name__),'model':str(model or 'unknown'),'kind':kind}

    def begin(self,instance,kwargs,kind,stream):
        meta={**_CURRENT.get(),**self.identity(instance,kwargs,kind)}
        if not meta.get('trace'):meta['trace']='bg-'+uuid4().hex[:12]
        inferred=_caller_purpose(kind)
        if kind=='image':meta['purpose']='image_generation'
        elif inferred in ('memory_processing','memory_embedding','background_reply_judge','vision_caption'):meta['purpose']=inferred
        elif not meta.get('purpose') or kind=='embedding':meta['purpose']=inferred
        meta['call']=uuid4().hex[:10];meta['stream']=stream
        if kind=='text':
            meta['context_messages']=len(kwargs.get('contexts') or [])
            meta['image_count']=count_image_parts(kwargs.get('contexts'),kwargs.get('image_urls'),kwargs.get('extra_user_content_parts'))
            tools=kwargs.get('func_tool')
            meta['tool_count']=len(tools.names()) if tools and callable(getattr(tools,'names',None)) else 0
        if kind=='image':
            meta['mode']='edit' if kwargs.get('refs') or kwargs.get('user_refs') else 'generate'
            meta['node']=meta['provider']
        record={'meta':meta,'started':time.monotonic(),'first':None,'result':None}
        self.active[meta['call']]=record;self.counts['started']+=1
        self.emit('start',**meta)
        return record

    async def waiting(self,record):
        interval=float(self.settings.get('heartbeat_seconds',10))
        if interval<=0:return
        interval=max(.01,interval)
        while True:
            await asyncio.sleep(interval)
            self.emit('waiting',**record['meta'],seconds=round(time.monotonic()-record['started'],3),outcome='awaiting_interface_not_server_inference_confirmation')
            interval=max(interval,float(self.settings.get('heartbeat_repeat_seconds',30)))

    def finish(self,record,state,exc=None):
        meta={**record['meta'],'seconds':round(time.monotonic()-record['started'],3)}
        result=record.get('result')
        if state=='success' and getattr(result,'role',None)=='err':
            state='error';meta['error_type']='ProviderErrorResponse'
        if state=='success':
            if meta['kind']=='text':
                calls=list(getattr(result,'tools_call_name',[]) or [])
                meta['tool_calls']=calls[:20]
                meta['outcome']='tool_calls_returned' if calls else 'text_returned'
            usage=getattr(result,'usage',None)
            if usage:
                meta['input_tokens']=(getattr(usage,'input_other',0) or 0)+(getattr(usage,'input_cached',0) or 0)
                meta['output_tokens']=getattr(usage,'output',0) or 0
        elif exc is not None:
            meta['error_type']=type(exc).__name__
            status=getattr(exc,'status_code',None)
            if not isinstance(status,int):
                match=re.search(r'\bHTTP\s+(\d{3})\b',str(exc)[:500])
                if match:status=int(match[1])
            if isinstance(status,int):meta['http_status']=status
        if record['first'] is not None:meta['first_output_seconds']=record['first']
        self.active.pop(meta['call'],None);self.counts[state]+=1
        self.recent.append(self.emit(state,**meta))

    def instrument(self,cls,name,kind):
        def build(original):
            if inspect.isasyncgenfunction(original):
                @functools.wraps(original)
                async def stream(instance,*args,**kwargs):
                    key=(id(instance),kind)
                    if key in _ACTIVE.get():
                        async for value in original(instance,*args,**kwargs):yield value
                        return
                    record=self.begin(instance,kwargs,kind,True)
                    iterator=original(instance,*args,**kwargs).__aiter__()
                    heartbeat=asyncio.create_task(self.waiting(record));state='cancelled';error=None
                    try:
                        while True:
                            token=_ACTIVE.set(_ACTIVE.get()|{key})
                            try:
                                try:value=await anext(iterator)
                                except StopAsyncIteration:state='success';break
                            finally:_ACTIVE.reset(token)
                            record['result']=value
                            if record['first'] is None:
                                record['first']=round(time.monotonic()-record['started'],3)
                                self.emit('first_output',**record['meta'],first_output_seconds=record['first'])
                            yield value
                    except asyncio.CancelledError as exc:error=exc;raise
                    except Exception as exc:state='error';error=exc;raise
                    finally:
                        try:
                            close=getattr(iterator,'aclose',None)
                            if close:
                                token=_ACTIVE.set(_ACTIVE.get()|{key})
                                try:await close()
                                except Exception as exc:state='error';error=exc;raise
                                finally:_ACTIVE.reset(token)
                        finally:
                            heartbeat.cancel()
                            try:await heartbeat
                            except (asyncio.CancelledError,Exception):pass
                            try:self.finish(record,state,error)
                            except Exception:self.active.pop(record['meta']['call'],None)
                return stream
            @functools.wraps(original)
            async def call(instance,*args,**kwargs):
                key=(id(instance),kind)
                if key in _ACTIVE.get():return await original(instance,*args,**kwargs)
                token=_ACTIVE.set(_ACTIVE.get()|{key});record=self.begin(instance,kwargs,kind,False)
                heartbeat=asyncio.create_task(self.waiting(record));state='cancelled';error=None
                try:
                    record['result']=await original(instance,*args,**kwargs);state='success';return record['result']
                except asyncio.CancelledError as exc:error=exc;raise
                except Exception as exc:state='error';error=exc;raise
                finally:
                    heartbeat.cancel()
                    try:await heartbeat
                    except (asyncio.CancelledError,Exception):pass
                    try:self.finish(record,state,error)
                    except Exception:self.active.pop(record['meta']['call'],None)
                    finally:_ACTIVE.reset(token)
            return call
        self.patch(cls,name,build)

    def refresh_providers(self,context):
        for instance in context.provider_manager.inst_map.values():
            for name,kind in self.METHODS.items():
                if callable(getattr(instance,name,None)):self.instrument(type(instance),name,kind)

    def install(self,context):
        if not self.settings.get('enabled',True):return
        self.refresh_providers(context)
        manager=context.provider_manager
        def loaded(original):
            @functools.wraps(original)
            async def wrapped(instance,*a,**kw):
                result=await original(instance,*a,**kw)
                if instance is manager:self.refresh_providers(context)
                return result
            return wrapped
        self.patch(type(manager),'load_provider',loaded)
        from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
        def runner_scope(purpose):
            def build(original):
                @functools.wraps(original)
                async def wrapped(instance,*a,**kw):
                    event=getattr(getattr(instance.run_context,'context',None),'event',None)
                    iterator=scoped_iterator(original(instance,*a,**kw),purpose,event_trace(event) if event else None)
                    try:
                        async for value in iterator:yield value
                    finally:await iterator.aclose()
                return wrapped
            return build
        self.patch(ToolLoopAgentRunner,'_iter_llm_responses',runner_scope('main_reply'))
        self.patch(ToolLoopAgentRunner,'_handle_function_tools',runner_scope('tool_execution'))
        metadata=context.get_registered_star('astrbot_plugin_self_initiated_reply')
        background=getattr(metadata,'star_cls',None)
        if background:
            root=background.__class__.__module__.rsplit('.',1)[0]
            cls=importlib.import_module(root+'.decision').DecisionMaker
            def background_scope(original):
                @functools.wraps(original)
                async def wrapped(instance,umo,*a,**kw):
                    trace={'trace':'bg-'+uuid4().hex[:12],'group':str(umo).split(':GroupMessage:',1)[-1] if ':GroupMessage:' in str(umo) else ''}
                    with model_operation('background_reply_judge',trace):return await original(instance,umo,*a,**kw)
                return wrapped
            self.patch(cls,'ask_decision_model',background_scope)
        metadata=context.get_registered_star('astrbot_plugin_omnidraw')
        plugin=getattr(metadata,'star_cls',None)
        if plugin:
            root=plugin.__class__.__module__.rsplit('.',1)[0]
            chain=importlib.import_module(root+'.core.chain_manager').ChainManager
            def chain_scope(original):
                @functools.wraps(original)
                async def wrapped(instance,*a,**kw):
                    trace={**_CURRENT.get(),'parent':'chain-'+uuid4().hex[:10]}
                    if not trace.get('trace'):trace['trace']='bg-'+uuid4().hex[:12]
                    with model_operation('image_generation',trace):return await original(instance,*a,**kw)
                return wrapped
            self.patch(chain,'run_chain_with_metadata',chain_scope)
            module=importlib.import_module(root+'.providers')
            for name in ('OpenAIProvider','OpenAIChatProvider','GeminiOfficialProvider','CustomEndpointProvider'):
                cls=getattr(module,name,None)
                if cls:self.instrument(cls,'generate_image','image')

    def status(self):
        buckets={}
        for row in self.recent:
            key=(row.get('model'),row.get('purpose'))
            buckets.setdefault(key,[]).append(row)
        summary=[]
        for (model,purpose),rows in buckets.items():
            seconds=sorted(r['seconds'] for r in rows)
            summary.append({'model':model,'purpose':purpose,'window_calls':len(rows),
                            'mean_seconds':round(sum(seconds)/len(seconds),3),
                            'p50_seconds':seconds[(len(seconds)-1)//2],
                            'p95_seconds':seconds[max(0,(95*len(seconds)+99)//100-1)],
                            'errors':sum(r['event']=='error' for r in rows),
                            'cancelled':sum(r['event']=='cancelled' for r in rows)})
        return {'enabled':self.settings.get('enabled',True),'patched_methods':len(self.patches),
                'counts':dict(self.counts),'active':[{**r['meta'],'seconds':round(time.monotonic()-r['started'],3)} for r in self.active.values()],
                'recent':list(self.recent),'by_model':summary,'window_limit':50,'payload_logging':False}
