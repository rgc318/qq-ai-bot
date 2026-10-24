"""Synthetic lifecycle regressions; no network, real model, or QQ sends."""
import asyncio
import json
from types import SimpleNamespace
from .model_logging import ModelActivityLogger,model_operation,event_trace
from uuid import uuid4


async def verify_model_logging():
    rows=[];checks={}
    extras={'user_policy_effective_persona_id':'A'}
    event=SimpleNamespace(get_extra=lambda k:extras.get(k),set_extra=lambda k,v:extras.update({k:v}),get_group_id=lambda:'group',message_obj=SimpleNamespace(message_id='fixture'))
    trace_id=event_trace(event)['trace'];extras['user_policy_effective_persona_id']='B'
    checks['stable_trace_and_final_persona']=event_trace(event)['trace']==trace_id and event_trace(event)['persona']=='B'
    observer=ModelActivityLogger({'heartbeat_seconds':.01,'heartbeat_repeat_seconds':.015},rows.append)
    class Provider:
        provider_config={'id':'fake-provider','model':'fake-model','api_key':'SECRET_KEY_SENTINEL'}
        def get_model(self):return self.provider_config['model']
        async def text_chat(self,**kwargs):
            if kwargs.get('delay'):await asyncio.sleep(kwargs['delay'])
            if kwargs.get('fail'):raise ValueError('SECRET_ERROR_SENTINEL')
            return SimpleNamespace(tools_call_name=['generate_image'],completion_text='SECRET_OUTPUT_SENTINEL',usage=SimpleNamespace(input_other=10,input_cached=2,output=3))
        async def text_chat_stream(self,**kwargs):
            yield SimpleNamespace(tools_call_name=[],completion_text='chunk')
            yield SimpleNamespace(tools_call_name=[],completion_text='final',usage=SimpleNamespace(input_other=2,input_cached=0,output=1))
        async def get_embedding(self,text):return await self.get_embeddings([text])
        async def get_embeddings(self,texts):return [[1.,2.] for _ in texts]
    original=Provider.text_chat
    for name,kind in [('text_chat','text'),('text_chat_stream','text'),('get_embedding','embedding'),('get_embeddings','embedding')]:observer.instrument(Provider,name,kind)
    provider=Provider()
    try:
        with model_operation('reply_judge',{'trace':'judge-trace','group':'test-group'}):
            result=await provider.text_chat(prompt='SECRET_PROMPT_SENTINEL',delay=.025)
        checks['result_unchanged']=result.completion_text=='SECRET_OUTPUT_SENTINEL'
        group=[r for r in rows if r.get('trace')=='judge-trace']
        checks['start_wait_and_success']=group[0]['event']=='start' and any(r['event']=='waiting' for r in group) and group[-1]['event']=='success'
        checks['model_and_purpose_every_stage']=all(r.get('model')=='fake-model' and r.get('purpose')=='reply_judge' for r in group)
        checks['tools_usage_and_duration']=group[-1].get('tool_calls')==['generate_image'] and group[-1].get('input_tokens')==12 and group[-1].get('seconds',0)>=.02
        try:await provider.text_chat(fail=True)
        except ValueError:pass
        checks['failure_preserved_and_sanitized']=rows[-1]['event']=='error' and rows[-1]['error_type']=='ValueError'
        class HTTPProvider:
            config=SimpleNamespace(id='http-provider',model='image-http')
            async def generate_image(self,prompt):raise RuntimeError('HTTP 400 SECRET_HTTP_BODY_SENTINEL')
        observer.instrument(HTTPProvider,'generate_image','image')
        try:await HTTPProvider().generate_image('secret')
        except RuntimeError:pass
        checks['http_error_code_without_body']=rows[-1]['http_status']==400 and rows[-1]['error_type']=='RuntimeError'
        try:
            with model_operation('reply_judge',{'trace':'timeout-trace'}):await asyncio.wait_for(provider.text_chat(delay=1),timeout=.02)
        except asyncio.TimeoutError:pass
        checks['timeout_cancellation_logged']=rows[-1]['event']=='cancelled' and rows[-1]['trace']=='timeout-trace' and not observer.active
        values=[v async for v in provider.text_chat_stream()]
        checks['stream_not_buffered_or_changed']=len(values)==2 and values[0].completion_text=='chunk'
        checks['stream_first_output_logged']=any(r['event']=='first_output' for r in rows) and 'first_output_seconds' in rows[-1]
        async def run(trace,delay):
            with model_operation('main_reply',{'trace':trace}):await provider.text_chat(delay=delay,model='override-'+trace)
        await asyncio.gather(run('A',.03),run('B',.015))
        checks['parallel_traces_do_not_mix']=all(r['model']=='override-'+r['trace'] for r in rows if r.get('trace') in ('A','B'))
        before=len(rows);embedding=await provider.get_embedding('SECRET_EMBEDDING_SENTINEL')
        checks['nested_embedding_logged_once']=embedding==[[1.,2.]] and len([r for r in rows[before:] if r['event']=='start'])==1
        class NativeEmbedding:
            provider_config={'id':'embedding-native','embedding_model':'Qwen-embedding'}
            def get_model(self):raise AttributeError('model_name')
            async def get_embedding(self,text):return [1.,2.]
        observer.instrument(NativeEmbedding,'get_embedding','embedding')
        await NativeEmbedding().get_embedding('probe')
        checks['embedding_native_model_field']=rows[-1]['model']=='Qwen-embedding'
        class ImageProvider:
            config=SimpleNamespace(id='image-node',model='image-model')
            async def generate_image(self,prompt,**kwargs):return 'SECRET_IMAGE_URL_SENTINEL'
        observer.instrument(ImageProvider,'generate_image','image')
        with model_operation('tool_execution',{'trace':'image-trace'}):
            url=await ImageProvider().generate_image('SECRET_IMAGE_PROMPT_SENTINEL',user_refs=['SECRET_REFERENCE_SENTINEL'])
        checks['image_node_model_and_edit_mode']=url=='SECRET_IMAGE_URL_SENTINEL' and rows[-1]['provider']=='image-node' and rows[-1]['model']=='image-model' and rows[-1]['mode']=='edit' and rows[-1]['purpose']=='image_generation'
        class Child(Provider):pass
        observer.instrument(Child,'text_chat','text')
        before=len(rows);await Child().text_chat()
        checks['inherited_wrappers_do_not_duplicate']=len([r for r in rows[before:] if r['event']=='start'])==1
        checks['no_payload_or_credentials']=not any(s in json.dumps(rows) for s in ('SECRET_','api_key','completion_text','prompt'))
        status=observer.status()
        checks['status_no_active_or_raw_payload']=not status['active'] and status['payload_logging'] is False
        checks['bounded_latency_summary']=bool(status['by_model']) and status['window_limit']==50
        await provider.text_chat()
        checks['operation_context_is_reset']=rows[-1]['purpose']=='text' and rows[-1]['trace'].startswith('bg-')
    finally:observer.restore()
    checks['unload_restores_original']=Provider.text_chat is original and 'text_chat' not in Child.__dict__
    disabled=[];ModelActivityLogger({'enabled':False},disabled.append).emit('start',model='fake')
    checks['logging_can_be_disabled']=not disabled
    return {'passed':all(checks.values()),'checks':checks,'model_calls':0,'image_generations':0,'qq_messages_sent':0}


async def verify_live_model_logging(plugin):
    observer=plugin.model_activity;trace='diagnostic-'+uuid4().hex[:12]
    judge=plugin.context.get_provider_by_id(plugin.router.settings['judge_provider_id'])
    checks={};models=[]
    with model_operation('logging_probe',{'trace':trace,'diagnostic':True}):
        await asyncio.wait_for(judge.text_chat(prompt='Return JSON only: {"ok":true}',contexts=[],max_tokens=16),timeout=40)
        models.append(judge.get_model())
        embeddings=plugin.context.provider_manager.embedding_provider_insts
        if embeddings:
            result=await asyncio.wait_for(embeddings[0].get_embedding('model activity logging diagnostic'),timeout=40)
            checks['embedding_returned']=bool(result);models.append(observer.identity(embeddings[0],{},'embedding')['model'])
    rows=[r for r in observer.recent if r.get('trace')==trace]
    checks['text_completion_logged']=any(r.get('kind')=='text' and r['event']=='success' for r in rows)
    checks['embedding_completion_logged']=not embeddings or any(r.get('kind')=='embedding' and r['event']=='success' for r in rows)
    checks['all_finished_and_model_identified']=len(rows)==len(models) and all(r.get('model') in models for r in rows) and not any(r['meta'].get('trace')==trace for r in observer.active.values())
    return {'passed':all(checks.values()),'checks':checks,'models':models,'trace':trace,'model_calls':len(models),'qq_messages_sent':0,'image_generations':0,'production_conversation_writes':0}
