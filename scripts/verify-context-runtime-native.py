"""Synthetic native runtime and latency checks. No network/model/QQ operations."""
import asyncio
import importlib
import json
from pathlib import Path
import shutil
import statistics
import sys
from tempfile import TemporaryDirectory
import time
from types import ModuleType,SimpleNamespace

sys.path.insert(0,'/AstrBot')


async def run():
    from PIL import Image as PILImage
    from astrbot.api.message_components import Image,Plain
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage,MessageMember,Group
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.provider.entities import ProviderRequest
    from astrbot.core.agent.tool import ToolSet,FunctionTool
    from astrbot.core.star.register.star_handler import llm_tools
    checks={};counter=[0];models=[]
    def check(k,v):
        checks[k]=bool(v)
        assert v,k
    with TemporaryDirectory(dir='/AstrBot/data',prefix='runtime-fixture-') as temp:
        root=Path(temp);code=root/'plugin'
        shutil.copytree('/workspace/extensions/astrbot_plugin_qq_persona_models',code,ignore=shutil.ignore_patterns('__pycache__','_ca_runtime'))
        shutil.copytree('/workspace/integrations/contextaware',code/'_ca_runtime',ignore=shutil.ignore_patterns('__pycache__'))
        package=ModuleType('runtime_fixture');package.__path__=[str(code)];sys.modules[package.__name__]=package
        Main=importlib.import_module('runtime_fixture.main').PersonaModelBindings
        AttachmentContext=importlib.import_module('runtime_fixture.attachment_context').AttachmentContext
        Runtime=importlib.import_module('runtime_fixture.context_runtime').ContextRuntime
        ReplyRouter=importlib.import_module('runtime_fixture.reply_routing').ReplyRouter
        policy=SimpleNamespace(star_cls=SimpleNamespace(memory_isolation=SimpleNamespace(_scope=lambda d:('public:'+d.identity.group_id,'group'))))
        native_calls=[]
        async def native_group(event,request):native_calls.append(True)
        builtin=SimpleNamespace(star_cls=SimpleNamespace(group_chat_context=SimpleNamespace(on_req_llm=native_group)))
        class Omni:
            def _get_event_images(self,e):return [c.path for c in e.get_messages() if isinstance(c,Image)]
            async def _send_generated_images(self,e,results):
                for path in results:await e.send(e.chain_result([Image.fromFileSystem(str(path))]))
                return len(results)
        omni=Omni()
        provider=SimpleNamespace(provider_config={'modalities':['text','image','tool_use']})
        registered={'astrbot_plugin_user_policy':policy,'astrbot':builtin,'astrbot_plugin_omnidraw':SimpleNamespace(star_cls=omni)}
        context=SimpleNamespace(get_registered_star=lambda n:registered.get(n),get_config=lambda **kw:{'wake_prefix':[]},get_using_provider=lambda **kw:provider)
        probe=object.__new__(Main);probe.context=context;probe.config={'multimodal_context':{'enabled':True},'performance':{'enabled':False}}
        async def no_judge(_):raise AssertionError('No model judge')
        probe.router=ReplyRouter({'allowed_groups':['G']},no_judge)
        probe.routing_persona=lambda e:e.get_extra('user_policy_effective_persona_id')
        logs=[];probe.model_activity=SimpleNamespace(active={},emit=lambda *args,**kw:logs.append(kw))
        archive=AttachmentContext(probe,root/'archive',{'enabled':True,'auto_attach':True,'documents':True})
        runtime=Runtime(probe,archive,Path('/candidate'));probe.attachments=runtime
        def event(text='',image=None,sender='A',persona='whale'):
            counter[0]+=1
            raw=AstrBotMessage();raw.type=MessageType.GROUP_MESSAGE;raw.self_id='bot';raw.session_id='G'
            raw.group=Group(group_id='G',group_name='fixture');raw.message_id='fixture-'+str(counter[0]);raw.sender=MessageMember(user_id=sender,nickname=sender)
            raw.message_str=text;raw.message=[Plain(text=text)];raw.raw_message={}
            if image:raw.message.append(Image.fromFileSystem(str(image)))
            class Event(AstrMessageEvent):
                async def send(self,chain,*args,**kw):self.set_extra('sent_fixture',True);return None
            e=Event(text,raw,PlatformMetadata(name='aiocqhttp',description='synthetic',id='fixture'),'G')
            e.plugins_name=['astrbot_plugin_qq_persona_models'];e.set_extra('user_policy_effective_persona_id',persona)
            e.set_extra('user_policy_decision',SimpleNamespace(is_blocked=False,memory_isolation=True,identity=SimpleNamespace(is_private=False,group_id='fixture:G',user_id=sender)))
            e.set_extra('qq_diagnostic',True)
            return e
        def picture(name,color):
            path=root/name;PILImage.new('RGB',(256,256),color).save(path);return path
        front=picture('front.png','red');side=picture('side.png','blue');output=picture('out.png','yellow')
        async def release(e):e.cleanup_temporary_local_files();await asyncio.sleep(0)
        def request(e):
            async def noop(*a,**kw):return 'fixture'
            return ProviderRequest(prompt=e.message_str,func_tool=ToolSet(tools=[FunctionTool(name='view_context_images',description='fixture',parameters={'type':'object','properties':{'attachment_ids':{'type':'array','items':{'type':'string'}}}},handler=noop)]))
        await runtime.initialize();runtime.start();runtime.install_outgoing()
        try:
            check('candidate_available',runtime.status()['choices'][1]['available'])
            before=len(llm_tools.func_list)
            maintenance=asyncio.create_task(asyncio.Event().wait())
            scheduler=SimpleNamespace(_background_tasks={maintenance},_image_cleanup_task=maintenance,_delay_tasks={},_running_check_tasks={})
            registered['astrbot_plugin_self_initiated_reply']=SimpleNamespace(star_cls=SimpleNamespace(_scheduler=scheduler))
            await runtime.switch('contextaware')
            check('permanent_cache_cleanup_does_not_block_switch',runtime.coordinator.active=='contextaware')
            waiting=asyncio.create_task(asyncio.Event().wait());scheduler._delay_tasks['G']=waiting
            try:await runtime.switch('builtin');busy=False
            except RuntimeError:busy=True
            check('queued_self_reply_still_blocks_switch',busy)
            waiting.cancel();maintenance.cancel();await asyncio.gather(waiting,maintenance,return_exceptions=True)
            registered.pop('astrbot_plugin_self_initiated_reply')
            check('no_upstream_tools_registered_globally',len(llm_tools.func_list)==before)
            upload=event('正面参考',front);await runtime.capture(upload);await release(upload)
            upload2=event('侧面补充',side);await runtime.capture(upload2);await release(upload2)
            q=event('结合之前的参考修改');rq=request(q);await runtime.prepare(q,rq)
            catalog=runtime.candidate.catalog(q)
            check('persistent_and_active_image_counts_match',len(catalog)==2 and archive.store.stats()['attachments']==2)
            check('current_text_does_not_guess_historical_image',not rq.image_urls)
            check('facts_and_catalog_have_source_ids','sender_id' in rq.system_prompt and all(r['id'] in rq.system_prompt for r in catalog))
            await builtin.star_cls.group_chat_context.on_req_llm(q,rq)
            check('native_group_injection_skipped_in_candidate_mode',not native_calls)
            viewed=await runtime.view_images(q,[r['id'] for r in catalog]);check('view_tool_returns_two_images',sum(c.type=='image' for c in viewed.content)==2)
            evicted=catalog[0]['id']
            runtime.candidate.plugin._image_index._remove(evicted)
            state=runtime.restorer.maps[runtime.candidate.scoped(q).scope]
            state['ids']={a:b for a,b in state['ids'].items() if b!=evicted}
            fallback=await runtime.view_images(q,[evicted])
            check('inflight_view_survives_cache_eviction',sum(c.type=='image' for c in fallback.content)==1 and evicted in ''.join(getattr(c,'text','') for c in fallback.content))
            try:await runtime.select_references(q,{'reference_ids':['ca_not_authorized'],'prompt':'fixture'});denied=False
            except ValueError:denied=True
            check('unseen_or_future_image_id_rejected',denied)
            args={'reference_ids':[r['id'] for r in catalog],'prompt':'synthetic edit','reference_notes':[{'image_id':r['id'],'purpose':'source fixture'} for r in catalog]}
            await runtime.select_references(q,args)
            selected=[Path(c.path).read_bytes() for c in q.get_messages() if isinstance(c,Image)]
            check('normal_omni_route_receives_exact_selected_bytes',selected==[front.read_bytes(),side.read_bytes()])
            check('inflight_selection_survives_cache_eviction',evicted in q.get_extra('qq_ca_selected_ids'))
            check('helper_arguments_removed_before_omni','reference_ids' not in args and 'reference_notes' not in args and '参考图用途' in args['prompt'])
            await omni._send_generated_images(q,[output])
            check('one_successful_send_one_archived_result',archive.store.stats()['attachments']==3 and q.get_extra('sent_fixture'))
            await q.send(q.plain_result('合成回复：已结合两张参考图完成。'))
            await runtime.note_sent(q,'合成回复：已结合两张参考图完成。')
            try:await runtime.switch('builtin');busy=False
            except RuntimeError:busy=True
            check('inflight_request_prevents_switch',busy)
            await release(q)
            next_event=event('继续');nr=request(next_event);await runtime.prepare(next_event,nr)
            result=[r for r in runtime.candidate.catalog(next_event) if r['kind']=='generated']
            check('generated_result_reenters_catalog_once',len(result)==1 and len(result[0]['parent_ids'])==2)
            await release(next_event)
            await runtime.switch('builtin')
            check('switch_back_removes_candidate_instance',runtime.candidate is None)
            plain=event('你好');pr=request(plain);await runtime.prepare(plain,pr)
            await builtin.star_cls.group_chat_context.on_req_llm(plain,pr)
            check('builtin_native_group_injection_restored',len(native_calls)==1)
            await release(plain)
            builtin_note=event('independent new image');bn=request(builtin_note);await runtime.prepare(builtin_note,bn)
            builtin_args={'reference_ids':[],'reference_notes':[],'prompt':'fixture'}
            await runtime.select_references(builtin_note,builtin_args)
            check('fallback_removes_candidate_helper_arguments','reference_notes' not in builtin_args)
            await release(builtin_note)
            await runtime.switch('contextaware')
            restored=event('切换后继续');rr=request(restored);await runtime.prepare(restored,rr)
            check('switching_retains_archive_and_lineage',len(runtime.candidate.catalog(restored))==3)
            check('switching_restores_actual_sent_text_context','合成回复：已结合两张参考图完成' in json.dumps(await rr.assemble_context(),ensure_ascii=False))
            await release(restored)
            reused=request(q);await runtime.prepare(q,reused)
            check('retained_event_gets_new_backend_view',q.get_extra('qq_ca_evaluation_view').owner is runtime.candidate)
            await release(q)
            manual=event('synthetic proactive reply');manual.set_extra('self_initiated_reply',True)
            async def proactive():
                await runtime.prepare(manual,request(manual))
                manual.set_extra('qq_image_failure_state',{'blocked':True,'request':None})
                manual.set_extra('qq_image_pending_notice_attempted',True)
            await asyncio.create_task(proactive());await asyncio.sleep(0);await asyncio.sleep(0)
            check('proactive_task_done_releases_dispatch',runtime.status()['active_requests']==0 and manual.get_extra('qq_ca_evaluation_view') is None)
            check('finished_proactive_event_does_not_keep_failure_or_notice',manual.get_extra('qq_image_failure_state') is None and manual.get_extra('qq_image_pending_notice_attempted') is None)
            foreign=event('其他人格',persona='dragon');fr=request(foreign);await runtime.prepare(foreign,fr)
            check('live_mode_preserves_persona_isolation',not runtime.candidate.catalog(foreign))
            runtime.store.invalidate(runtime.archive.snapshot(foreign)['scope'])
            try:await runtime.view_images(foreign,[]);denied=False
            except ValueError:denied=True
            check('cleared_epoch_cannot_read_old_snapshot',denied)
            await release(foreign)
            # Cursor history must include image-only messages and cannot cross
            # persona, epoch, request boundary or filter set.
            history=event('浏览历史');hr=request(history);await runtime.prepare(history,hr)
            page=await runtime.browse(history,limit=2)
            check('history_cursor_created',bool(page['next_cursor']))
            next_page=await runtime.browse(history,limit=2,cursor=page['next_cursor'])
            check('history_pages_do_not_duplicate_messages',not(set(r['message_id'] for r in page['messages'])&set(r['message_id'] for r in next_page['messages'])))
            text_search=await runtime.browse(history,query='正面',limit=5)
            check('historical_image_id_is_translated_to_active_backend',bool(text_search['messages']) and text_search['messages'][0]['attachments'][0]['id'].startswith('ca_'))
            await release(history)
            from runtime_fixture.image_failure_policy import ImageFailurePolicy
            from runtime_fixture.model_logging import ModelActivityLogger,model_operation,event_trace
            from mcp.types import CallToolResult,TextContent
            budget=ImageFailurePolicy();logger=ModelActivityLogger(sink=lambda row:None)
            logger.image_failure_observer=budget.record_failure
            pe=event('合成失败检查');pq=request(pe)
            pq.func_tool.tools.append(FunctionTool(name='generate_image',description='fixture',parameters={'type':'object'}))
            budget.track(pe,pq);budget.started(pe)
            with model_operation('image_generation',event_trace(pe)):
                operation=logger.begin(SimpleNamespace(provider_config={'id':'fixture','model':'fixture'}),{},'image',False)
                logger.finish(operation,'error',RuntimeError('HTTP 400 moderation_blocked'))
            failure=CallToolResult(content=[TextContent(type='text',text='generic failure')])
            budget.feedback(pe,failure)
            check('real_model_logger_classifies_nonretryable_image_failure',pe.get_extra('qq_image_failure_state')['blocked'])
            check('moderation_failure_feedback_is_specific','moderation_blocked' in failure.content[0].text and failure.isError)
            check('nonretryable_image_tools_removed_from_request',all(t.name!='generate_image' for t in pq.func_tool.tools))
            try:budget.check(pe);denied=False
            except ValueError:denied=True
            check('nonretryable_failure_blocks_later_execution',denied)
            budget.forget(pe);check('completed_request_does_not_retain_prompt',not budget.states and pe.get_extra('qq_image_failure_state')['request'] is None)
            te=event('合成瞬时失败');budget.track(te,request(te));budget.started(te)
            budget.record_failure(event_trace(te),RuntimeError('HTTP 503 temporary'))
            check('transient_failure_allows_one_retry',not te.get_extra('qq_image_failure_state')['blocked'])
            budget.started(te);budget.record_failure(event_trace(te),RuntimeError('HTTP 503 temporary'))
            check('transient_retry_budget_is_bounded',te.get_extra('qq_image_failure_state')['blocked'])
            ne=event('合成新请求');budget.track(ne,request(ne));check('new_user_request_has_new_failure_budget',not ne.get_extra('qq_image_failure_state')['blocked'])
            from astrbot.core.provider.entities import LLMResponse
            from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
            from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
            from runtime_fixture.image_tool_compat import prepare_chat_image_tools
            native_failure=event('native nonretryable failure');native_failure.set_extra('qq_diagnostic',False)
            probe.image_failure_policy=ImageFailurePolicy();probe.record_dialogue_progress=lambda *a,**kw:True
            called=[];schemas=[]
            async def image_handler(e,prompt):
                called.append(prompt)
                probe.image_failure_policy.record_failure(event_trace(e),RuntimeError('HTTP 400 moderation_blocked'))
                return '系统提示：画图失败（所有绘图节点请求失败）。'
            image_tool=FunctionTool(name='generate_image',description='synthetic',parameters={'type':'object','properties':{'prompt':{'type':'string'}},'required':['prompt']},handler=image_handler)
            native_request=ProviderRequest(prompt='synthetic',func_tool=ToolSet(tools=[image_tool]))
            prepare_chat_image_tools(native_request,indexed_references=True)
            await runtime.prepare(native_failure,native_request)
            probe.image_failure_policy.track(native_failure,native_request)
            async def start(ctx,tool,args):await probe.normalize_image_arguments(native_failure,tool,args)
            async def end(ctx,tool,args,result):await probe.track_image_tool_result(native_failure,tool,args,result)
            async def no_op(*a):pass
            class FailureProvider:
                provider_config={'id':'synthetic','modalities':['text','tool_use']}
                def get_model(self):return 'synthetic'
                async def text_chat(self,**kw):
                    tools=kw.get('func_tool');schemas.append(tools.names() if tools else [])
                    if len(schemas)==1:return LLMResponse(role='assistant',tools_call_name=['generate_image'],tools_call_args=[{'prompt':'fixture','reference_ids':[]}],tools_call_ids=['failure-fixture'])
                    return LLMResponse(role='assistant',completion_text='上游拒绝，本轮已停止。')
            runner=ToolLoopAgentRunner()
            await runner.reset(provider=FailureProvider(),request=native_request,
                run_context=SimpleNamespace(context=SimpleNamespace(event=native_failure),messages=[],tool_call_timeout=10),tool_executor=FunctionToolExecutor,
                agent_hooks=SimpleNamespace(on_tool_start=start,on_tool_end=end,on_agent_begin=no_op,on_agent_done=no_op))
            async for _ in runner.step_until_done(4):pass
            check('native_runner_sees_image_tools_removed_after_fatal_failure',len(schemas)==2 and 'generate_image' not in schemas[1])
            check('fatal_failure_has_only_one_actual_image_attempt',called==['fixture'])
            await release(native_failure)
            probes={}
            for mode in ('builtin','contextaware'):
                await runtime.switch(mode)
                for sender,text in [('A','活动计划：10人，地点A厅。'),('B','人数改成12人，地点保持。'),('C','时间明天下午，不改人数和地点。')]:
                    part=event(text,sender=sender);await runtime.capture(part);await release(part)
                plain=event('请只总结最终人数和地点。');prepared=request(plain);await runtime.prepare(plain,prepared)
                assembled=await prepared.assemble_context()
                probes[mode]=[{'role':'system','content':'你是群聊助手。结合最近发言和明确修改回答，只说结论。\n'+prepared.system_prompt}]+(assembled if isinstance(assembled,list) else [assembled])
                await release(plain)
            # A realistic retained-byte load: ordinary text must not rehash or
            # read every old image merely to render a source catalog.
            for i in range(20):
                path=root/('load-'+str(i)+'.png');PILImage.effect_noise((768,768),70).convert('RGB').save(path)
                image_event=event('合成历史素材 '+str(i),path);await runtime.capture(image_event);await release(image_event)
            retained=archive.store.stats()['ready_bytes']
            measurements={}
            for mode in ('builtin','contextaware'):
                await runtime.switch(mode)
                samples=[]
                for i in range(40):
                    e=event('普通文字问候 '+str(i));r=request(e);start=time.perf_counter()
                    await runtime.capture(e);await runtime.prepare(e,r)
                    samples.append((time.perf_counter()-start)*1000);await release(e)
                measurements[mode]={'samples':40,'first_prepare_ms':round(samples[0],3),'max_ms':round(max(samples),3),'p50_ms':round(statistics.median(samples),3),'p95_ms':round(sorted(samples)[37],3)}
            delta=measurements['contextaware']['p95_ms']-measurements['builtin']['p95_ms']
            check('candidate_added_local_p95_under_200ms',delta<200)
            check('no_extra_caption_summary_or_model_calls',not runtime.candidate.plugin._image_caption_enabled and runtime.candidate.plugin._topic is None and runtime.metrics['model_calls_added']==0)
            print('RUNTIME_REPORT='+json.dumps({'passed':all(checks.values()),'checks':checks,'measurements':measurements,'retained_image_bytes':retained,'delta_p95_ms':round(delta,3),'model_calls':0,'image_generations':0,'qq_messages_sent':0,'model_probes':probes},ensure_ascii=False),flush=True)
        finally:
            await runtime.close()


if __name__=='__main__':asyncio.run(run())
