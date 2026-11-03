"""Synthetic native runtime and latency checks. No network/model/QQ operations."""
import asyncio
import importlib
import importlib.util
import json
import gzip
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
                async def send(self,chain,*args,**kw):
                    self.set_extra('sent_fixture',True)
                    sent=self.get_extra('sent_texts') or [];sent.append(''.join(getattr(c,'text','') for c in getattr(chain,'chain',[])))
                    self.set_extra('sent_texts',sent);return None
            e=Event(text,raw,PlatformMetadata(name='aiocqhttp',description='synthetic',id='fixture'),'G')
            e.plugins_name=['astrbot_plugin_qq_persona_models'];e.set_extra('user_policy_effective_persona_id',persona)
            e.set_extra('user_policy_decision',SimpleNamespace(is_blocked=False,memory_isolation=True,persona_id=persona,identity=SimpleNamespace(is_private=False,platform='aiocqhttp',group_id='G',user_id=sender)))
            e.set_extra('qq_diagnostic',True)
            return e
        def picture(name,color):
            path=root/name;PILImage.new('RGB',(256,256),color).save(path);return path
        front=picture('front.png','red');side=picture('side.png','blue');output=picture('out.png','yellow')
        async def release(e):e.cleanup_temporary_local_files();await asyncio.sleep(0)
        def request(e):
            async def noop(*a,**kw):return 'fixture'
            return ProviderRequest(prompt=e.message_str,func_tool=ToolSet(tools=[FunctionTool(name='view_context_images',description='fixture',parameters={'type':'object','properties':{'attachment_ids':{'type':'array','items':{'type':'string'}}}},handler=noop)]))
        # Reproduce the real cold-start order: user plugins load before astrbot.
        cold_archive=AttachmentContext(probe,root/'cold'/'archive',{'enabled':True})
        cold=Runtime(probe,cold_archive,Path('/candidate'))
        cold.state_path.write_text(json.dumps({'mode':'contextaware'}),encoding='utf-8')
        registered.pop('astrbot')
        try:
            await cold.initialize()
            check('cold_start_keeps_plugin_loadable_until_native_plugin_arrives',cold.startup_pending and cold.coordinator.active=='builtin')
            check('cold_start_exposes_dependency_reason',bool(cold.status()['startup_issue']) and cold.status()['requested_backend']=='contextaware')
            early=event('arrived before dependency')
            try:await cold.capture(early);blocked=False
            except RuntimeError:blocked=True
            check('cold_start_does_not_dispatch_under_wrong_backend',blocked and early.is_stopped() and cold_archive.store.stats()['messages']==0)
            registered['astrbot']=builtin
            await cold.refresh_dependencies()
            check('native_plugin_loaded_restores_saved_contextaware',cold.coordinator.active=='contextaware' and not cold.startup_pending and not cold.startup_issue)
            first_wrapper=builtin.star_cls.group_chat_context.on_req_llm
            await cold.refresh_dependencies();await cold.refresh_dependencies()
            check('dependency_refresh_does_not_stack_native_wrappers',builtin.star_cls.group_chat_context.on_req_llm is first_wrapper)
            check('deferred_restore_does_not_rewrite_saved_choice',json.loads(cold.state_path.read_text())=={'mode':'contextaware'})
        finally:
            registered['astrbot']=builtin
            await cold.close()
        check('cold_start_close_restores_native_owner',builtin.star_cls.group_chat_context.on_req_llm is native_group)
        missing_archive=AttachmentContext(probe,root/'missing-source'/'archive',{'enabled':True})
        missing=Runtime(probe,missing_archive,root/'not-present')
        missing.state_path.write_text(json.dumps({'mode':'contextaware'}),encoding='utf-8')
        try:
            await missing.initialize()
            check('missing_candidate_source_keeps_recovery_ui_available',missing.startup_pending and not missing.status()['choices'][1]['available'])
            await missing.switch('builtin')
            check('explicit_local_choice_clears_pending_and_persists',not missing.startup_pending and json.loads(missing.state_path.read_text())=={'mode':'builtin'})
        finally:await missing.close()
        # Failing initialization/unload must still restore every adapter.
        partial=object.__new__(Main);restored=[]
        async def failing_init():raise ValueError('synthetic init failure')
        async def failing_close():raise RuntimeError('synthetic dependency cleanup failure')
        partial._initialize=failing_init;partial.attachments=SimpleNamespace(close=failing_close)
        for name,method in (('image_execution_guard','restore'),('image_batch_adapter','close'),('image_timeout_adapter','close'),('image_response_adapter','restore'),('model_activity','restore'),('image_upload_adapter','restore'),('image_quote_adapter','restore'),('group_permission_adapter','restore')):
            setattr(partial,name,SimpleNamespace(**{method:lambda n=name:restored.append(n)}))
        partial.history_job=asyncio.create_task(asyncio.Event().wait())
        try:await partial.initialize();failed=False
        except ValueError:failed=True
        check('failed_initialization_restores_all_other_adapters',failed and len(restored)==8 and partial.history_job.cancelled())
        # Reloaded logging modules must not multiply one actual provider call.
        log_module=importlib.import_module('runtime_fixture.model_logging')
        first_logger=log_module.ModelActivityLogger({'enabled':True})
        log_spec=importlib.util.spec_from_file_location('runtime_fixture.reloaded_model_logging',code/'model_logging.py')
        reloaded_logger_module=importlib.util.module_from_spec(log_spec);log_spec.loader.exec_module(reloaded_logger_module)
        second_logger=reloaded_logger_module.ModelActivityLogger({'enabled':True})
        provider_calls=[]
        class LocalProvider:
            provider_config={'id':'synthetic','model':'synthetic'}
            def get_model(self):return 'synthetic'
            async def text_chat(self,**kwargs):provider_calls.append(True);return SimpleNamespace(role='assistant',tools_call_name=[],usage=None)
        original_method=LocalProvider.text_chat
        first_logger.instrument(LocalProvider,'text_chat','text');second_logger.instrument(LocalProvider,'text_chat','text')
        try:
            await LocalProvider().text_chat(prompt='fixture')
            check('logging_reload_has_one_record_per_actual_call',len(provider_calls)==1 and first_logger.counts['started']==0 and second_logger.counts['started']==1)
            first_logger.restore()
            check('old_logger_cleanup_does_not_remove_new_owner',getattr(LocalProvider.text_chat,'_qq_model_activity_owner',None) is second_logger)
        finally:first_logger.restore();second_logger.restore()
        check('logging_reload_restores_original_method',LocalProvider.text_chat is original_method)
        # Named platform-message recovery restores missed inputs, without a
        # user quote, model replay, QQ send, or resetting the source timestamp.
        repair_module=importlib.import_module('runtime_fixture.group_context_repair')
        repair_archive=AttachmentContext(probe,root/'repair'/'archive',{'enabled':True})
        repair_runtime=Runtime(probe,repair_archive,Path('/candidate'))
        saved_policy=registered['astrbot_plugin_user_policy']
        saved_platform_manager=getattr(context,'platform_manager',None)
        saved_decoder=repair_module.native_event
        async def decode_fixture(platform,message,group):
            e=event('image fixture' if message['message_id']==101 else '请解读之前的图片',front if message['message_id']==101 else None)
            e.message_obj.message_id=str(message['message_id'])
            return e
        source_time=time.time()-600
        messages={101:{'message_id':101,'group_id':'G','time':source_time},102:{'message_id':102,'group_id':'G','time':source_time+10}}
        reads=[]
        class RepairBot:
            async def call_action(self,action,**kwargs):
                reads.append(action)
                if action=='get_login_info':return {'user_id':2354912009}
                if action=='get_msg':return dict(messages[kwargs['message_id']])
                raise AssertionError('Only read actions permitted')
        fake_platform=SimpleNamespace(meta=lambda:SimpleNamespace(id='qq-snowluma'),bot=RepairBot())
        context.platform_manager=SimpleNamespace(get_insts=lambda:[fake_platform])
        registered['astrbot_plugin_user_policy']=SimpleNamespace(star_cls=SimpleNamespace(
            memory_isolation=saved_policy.star_cls.memory_isolation,
            _decision_for_event=lambda e:e.get_extra('user_policy_decision'),
            matcher=SimpleNamespace(check_plugin_access=lambda *a:SimpleNamespace(allowed=True))))
        repair_module.native_event=decode_fixture;probe.attachments=repair_runtime
        try:
            messages[102]['group_id']='foreign'
            try:await repair_module.restore_group_messages(probe,{'group_id':'G','message_ids':[101,102]});denied=False
            except ValueError:denied=True
            check('repair_foreign_source_rejected_before_any_writes',denied and repair_archive.store.stats()['messages']==0)
            messages[102]['group_id']='G'
            result=await repair_module.restore_group_messages(probe,{'group_id':'G','message_ids':[101,102]})
            check('named_recovery_without_user_quote_succeeds',result['passed'] and sum(r.get('ready_images',0) for r in result['messages'])==1)
            check('named_recovery_never_sends_or_calls_model',set(reads)=={'get_login_info','get_msg'} and result['model_calls']==result['qq_messages_sent']==0)
            again=await repair_module.restore_group_messages(probe,{'group_id':'G','message_ids':[101,102]})
            check('named_recovery_is_idempotent',all(r.get('already_present') for r in again['messages']) and repair_archive.store.stats()['messages']==2)
            q=event('请解读之前的图片');rq=request(q);await repair_archive.prepare(q,rq)
            snap=q.get_extra('qq_attachment_snapshot')
            original=repair_archive.store.messages(snap,message_id='101')[0]
            check('named_recovery_preserves_original_message_time',original['received_at']==source_time)
            aid=next(r['id'] for r in snap['catalog'] if r['message_id']=='101')
            viewed=await repair_archive.view_images(q,[aid])
            import hashlib
            original_hash=hashlib.sha256(front.read_bytes()).hexdigest()
            check('named_recovery_read_tool_returns_original_source_and_image',any(c.type=='image' for c in viewed.content) and any(c.type=='text' and original_hash in c.text for c in viewed.content) and repair_archive.store.resolve(snap,[aid])[0]['digest']==original_hash)
            await repair_runtime.initialize();await repair_runtime.switch('contextaware')
            followup=event('解读之前的图片');followup_request=request(followup)
            await repair_runtime.prepare(followup,followup_request)
            recovered=next(r for r in repair_runtime.candidate.catalog(followup) if r['message_id']=='101')
            recovered_view=await repair_runtime.view_images(followup,[recovered['id']])
            check('named_recovery_appears_in_contextaware_next_request_without_quote',any(c.type=='image' for c in recovered_view.content) and '101' in followup_request.system_prompt)
        finally:
            repair_module.native_event=saved_decoder;probe.attachments=runtime
            registered['astrbot_plugin_user_policy']=saved_policy
            context.platform_manager=saved_platform_manager
            await repair_runtime.close()
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
            for alias in ('G','fixture:G','fixture:GroupMessage:G'):
                scope_event=event('alias scope fixture')
                scope_event.get_extra('user_policy_decision').identity.group_id=alias
                owner=probe.attachment_identity(scope_event);history_owner=probe.chat_history_identity(scope_event)
                check('native_alias_has_attachment_and_history_scope_'+alias,bool(owner) and bool(history_owner) and owner['scope']==history_owner['scope'])
            unscoped=event('scope denied fixture')
            unscoped.get_extra('user_policy_decision').identity.group_id='foreign:G'
            unscoped_req=request(unscoped)
            check('foreign_policy_group_does_not_gain_archive_access',probe.attachment_identity(unscoped) is None)
            runtime.filter_tools(unscoped,unscoped_req)
            check('unauthorized_scope_still_loses_history_image_tools','view_context_images' not in unscoped_req.func_tool.names())
            await builtin.star_cls.group_chat_context.on_req_llm(unscoped,unscoped_req)
            check('ineligible_scope_retains_native_group_history',len(native_calls)==1)
            native_calls.clear()
            upload=event('正面参考',front);await runtime.capture(upload);await release(upload)
            upload2=event('侧面补充',side);await runtime.capture(upload2);await release(upload2)
            q=event('结合之前的参考修改');rq=request(q);await runtime.prepare(q,rq)
            catalog=runtime.candidate.catalog(q)
            check('persistent_and_active_image_counts_match',len(catalog)==2 and archive.store.stats()['attachments']==2)
            check('current_text_does_not_guess_historical_image',not rq.image_urls)
            check('facts_and_catalog_have_source_ids','sender_id' in rq.system_prompt and all(r['id'] in rq.system_prompt for r in catalog))
            catalog_stats=q.get_extra('qq_context_catalog_stats')
            check('catalog_trace_counts_available_history_separately_from_pixels',catalog_stats['image_candidates']==catalog_stats['history_images']==2 and catalog_stats['current_images']==0 and set(catalog_stats['source_message_ids'])=={upload.message_obj.message_id,upload2.message_obj.message_id})
            contract=importlib.import_module('runtime_fixture.response_task_contract')
            before_prompt=rq.prompt;before_history=list(rq.contexts);before_tools=rq.func_tool
            q.set_extra('self_initiated_reply',True)
            contract.apply_response_task_contract(q,rq);once=rq.system_prompt
            contract.apply_response_task_contract(q,rq)
            check('proactive_task_contract_preserves_user_history_and_tool_permissions',rq.prompt==before_prompt and rq.contexts==before_history and rq.func_tool is before_tools and rq.system_prompt==once and contract.MARKER in once)
            await builtin.star_cls.group_chat_context.on_req_llm(q,rq)
            check('native_group_injection_skipped_in_candidate_mode',not native_calls)
            viewed=await runtime.view_images(q,[r['id'] for r in catalog]);check('view_tool_returns_two_images',sum(c.type=='image' for c in viewed.content)==2)
            check('image_read_trace_only_records_returned_image_sources',set(q.get_extra('qq_context_images_viewed'))=={r['id'] for r in catalog} and any(row.get('returned_images')==2 for row in logs))
            evicted=catalog[0]['id']
            runtime.candidate.plugin._image_index._remove(evicted)
            state=runtime.restorer.maps[runtime.candidate.scoped(q).scope]
            state['ids']={a:b for a,b in state['ids'].items() if b!=evicted}
            fallback=await runtime.view_images(q,[evicted])
            check('inflight_view_survives_cache_eviction',sum(c.type=='image' for c in fallback.content)==1 and evicted in ''.join(getattr(c,'text','') for c in fallback.content))
            try:await runtime.select_references(q,{'reference_ids':['ca_not_authorized'],'prompt':'fixture'});denied=False
            except ValueError as exc:
                denied=True
                check('stale_id_feedback_includes_current_catalog_without_reupload',getattr(exc,'code',None)=='stale_reference_ids' and '不要求用户重发' in str(exc) and catalog[1]['id'] in str(exc))
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
            restored_ids={r['message_id']:r['id'] for r in runtime.candidate.catalog(restored)}
            check('historical_image_ids_survive_backend_reload',all(restored_ids[r['message_id']]==r['id'] for r in catalog))
            same_args={'reference_ids':[r['id'] for r in catalog],'prompt':'恢复后仍用原来两图'}
            await runtime.select_references(restored,same_args)
            check('historical_refs_after_reload_use_exact_same_pixels',[Path(c.path).read_bytes() for c in restored.get_messages() if isinstance(c,Image)]==[front.read_bytes(),side.read_bytes()])
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
            from runtime_fixture.image_task_checks import verify_image_tasks
            pure=await verify_image_tasks()
            for name,value in pure['checks'].items():check('task_'+name,value)
            legacy=[{'role':'assistant','tool_calls':[{'id':'legacy','type':'function','function':{'name':'generate_image','arguments':json.dumps({'prompt':'保留红色角色与背景','_qq_image_guard_error':'internal only'})}}]}, {'role':'tool','tool_call_id':'legacy','content':'当时校验失败'}]
            old_cache=getattr(probe,'cache_path',None);probe.cache_path=root/'reply_context.json'
            fixture_request=SimpleNamespace(contexts=legacy,system_prompt='')
            probe.prepare_performance_context(event('继续改图'),fixture_request,image_contract=True)
            backups=[json.loads(gzip.decompress(p.read_bytes())) for p in (root/'history_archive').glob('*.json.gz')]
            check('legacy_raw_history_archived_before_request_normalization',any(r['history']==legacy for r in backups))
            check('legacy_request_normalization_keeps_task_facts','红色角色与背景' in json.dumps(fixture_request.contexts,ensure_ascii=False) and '_qq_image_guard_error' not in json.dumps(fixture_request.contexts))
            if old_cache is None:del probe.cache_path
            else:probe.cache_path=old_cache
            from runtime_fixture.image_response_adapter import ImageResponseAdapter
            adapter=ImageResponseAdapter();adapter.install()
            probe.config['image_pending_notice']={'enabled':True,'model_generated':True}
            try:
                for repair in (True,False):
                    e=event('把之前的图改成毛绒玩偶');e.set_extra('qq_diagnostic',False)
                    calls=[];seen_schemas=[];seen_contracts=[];seen_histories=[]
                    async def guarded_stub(ev,prompt):
                        calls.append({'prompt':prompt,'pixels':[Path(c.path).read_bytes() for c in ev.get_messages() if isinstance(c,Image)]})
                        return '合成图片执行已捕获，未调用图片模型或发图。'
                    tool=FunctionTool(name='generate_image',description='synthetic',parameters={'type':'object','properties':{'prompt':{'type':'string'}},'required':['prompt']},handler=guarded_stub)
                    from astrbot.core.provider.func_tool_manager import _PermissionGuardedTool
                    tool=_PermissionGuardedTool(tool,SimpleNamespace(_check_tool_permission=no_op))
                    req=ProviderRequest(prompt=e.message_str,func_tool=ToolSet(tools=[tool]))
                    await runtime.prepare(e,req)
                    chosen=next(r['id'] for r in runtime.candidate.catalog(e) if r['message_id']==upload.message_obj.message_id)
                    prepare_chat_image_tools(req,indexed_references=True,model_notice=True,task_contract=True)
                    e.set_extra('qq_image_task_contract_enabled',True);e.set_extra('qq_image_notice_defer_enabled',True)
                    probe.image_failure_policy.track(e,req)
                    class ContractProvider:
                        provider_config={'id':'synthetic','modalities':['text','tool_use']}
                        def get_model(self):return 'synthetic'
                        async def text_chat(self,**kw):
                            seen_schemas.append(kw['func_tool'].names() if kw.get('func_tool') else [])
                            seen_contracts.append(kw['func_tool'].openai_schema() if kw.get('func_tool') else [])
                            seen_histories.append(json.loads(json.dumps(kw.get('contexts') or [])))
                            n=len(seen_schemas)
                            if n>2 and repair:return LLMResponse(role='assistant',completion_text='当前资料未确认，先澄清。')
                            ids=[chosen] if repair and n==2 else []
                            return LLMResponse(role='assistant',result_chain=e.plain_result('我来保留原造型，把材质改成绒布。'),tools_call_name=['generate_image'],tools_call_args=[{'prompt':'fixture','image_task':{'operation':'edit','reason':'沿用既有角色图','independent_quote':''},'reference_ids':ids,'reference_notes':[{'image_id':i,'purpose':'角色底稿'} for i in ids],**({'_qq_image_guard_error':'replayed old server-only error'} if repair and n==2 else {})}],tools_call_ids=['contract-'+str(n)])
                    async def starts(ctx,t,args):
                        await probe.normalize_image_arguments(e,t,args)
                        await probe.announce_image_generation(e,t,args)
                    async def ends(ctx,t,args,result):await probe.track_image_tool_result(e,t,args,result)
                    runner=ToolLoopAgentRunner()
                    await runner.reset(provider=ContractProvider(),request=req,run_context=SimpleNamespace(context=SimpleNamespace(event=e),messages=[],tool_call_timeout=10),tool_executor=FunctionToolExecutor,agent_hooks=SimpleNamespace(on_tool_start=starts,on_tool_end=ends,on_agent_begin=no_op,on_agent_done=no_op))
                    public=[]
                    async for output_response in runner.step_until_done(5):
                        chain=getattr(getattr(output_response,'data',None),'chain',None)
                        public.append(''.join(getattr(c,'text','') for c in getattr(chain,'chain',[])))
                    if repair:
                        check('native_invalid_edit_never_executes_before_repair',len(calls)==1 and calls[0]['pixels']==[front.read_bytes()])
                        check('native_notice_sent_once_after_valid_selection',e.get_extra('sent_texts')==['我来保留原造型，把材质改成绒布。'])
                        check('native_early_promise_deferred',not any('保留原造型' in t for t in public))
                        check('native_roles_forwarded_helpers_stripped','reference_number' in calls[0]['prompt'])
                    else:
                        check('native_repeated_invalid_edit_has_zero_execution',not calls)
                        check('native_repeated_invalid_edit_has_no_notice',not e.get_extra('sent_texts'))
                        check('native_validation_budget_removes_tools',len(seen_schemas)==3 and 'generate_image' not in seen_schemas[-1])
                        check('native_blocked_retry_never_returns_tool_not_found','连续两次' in runner.get_final_llm_resp().completion_text and not runner.get_final_llm_resp().tools_call_name)
                    wire=next(t['function'] for t in seen_contracts[0] if t['function']['name']=='generate_image')
                    check('native_provider_has_required_image_task_fields',{'image_task','reference_ids','reference_notes'}.issubset(wire['parameters']['required']))
                    recorded=[json.loads(c['function']['arguments']) for row in seen_histories[-1] for c in row.get('tool_calls') or [] if c['function']['name']=='generate_image']
                    check('native_permission_proxy_keeps_model_task_args_'+str(repair),bool(recorded) and all('image_task' in a and 'reference_ids' in a and 'reference_notes' in a and 'pending_message' in a for a in recorded))
                    check('native_private_guard_error_never_enters_history_'+str(repair),all('_qq_image_guard_error' not in a for a in recorded))
                    await release(e)
            finally:adapter.restore()
            sys.path.insert(0,'/workspace/scripts')
            from importlib import util
            batch_spec=util.spec_from_file_location('batch_native','/workspace/scripts/verify-image-batch-native.py')
            batch_fixture=util.module_from_spec(batch_spec);batch_spec.loader.exec_module(batch_fixture)
            batch_result=await batch_fixture.verify_batch(probe,runtime,event,request,release,root)
            for name,value in batch_result['checks'].items():check('batch_'+name,value)
            from runtime_fixture.image_batch_checks import verify_image_batches
            batch_pure=await verify_image_batches()
            for name,value in batch_pure['checks'].items():check('batch_budget_'+name,value)
            evidence_spec=util.spec_from_file_location('evidence_native','/workspace/scripts/verify-task-evidence-native.py')
            evidence_fixture=util.module_from_spec(evidence_spec);evidence_spec.loader.exec_module(evidence_fixture)
            evidence_result=await evidence_fixture.verify_guard(probe,runtime,event,request,release,root)
            for name,value in evidence_result['checks'].items():check('evidence_'+name,value)
            delivery_spec=util.spec_from_file_location('delivery_native','/workspace/scripts/verify-reply-delivery-native.py')
            delivery_fixture=util.module_from_spec(delivery_spec);delivery_spec.loader.exec_module(delivery_fixture)
            delivery_result=await delivery_fixture.verify_delivery(probe,event,release)
            for name,value in delivery_result['checks'].items():check('delivery_'+name,value)
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
                    from runtime_fixture.task_evidence import TaskEvidenceGuard
                    TaskEvidenceGuard(probe).attach(e,r)
                    samples.append((time.perf_counter()-start)*1000);await release(e)
                measurements[mode]={'samples':40,'first_prepare_ms':round(samples[0],3),'max_ms':round(max(samples),3),'p50_ms':round(statistics.median(samples),3),'p95_ms':round(sorted(samples)[37],3)}
            delta=measurements['contextaware']['p95_ms']-measurements['builtin']['p95_ms']
            check('candidate_added_local_p95_under_200ms',delta<200)
            check('no_extra_caption_summary_or_model_calls',not runtime.candidate.plugin._image_caption_enabled and runtime.candidate.plugin._topic is None and runtime.metrics['model_calls_added']==0)
            print('RUNTIME_REPORT='+json.dumps({'passed':all(checks.values()),'checks':checks,'measurements':measurements,'task_evidence':evidence_result,'batch_native':{k:v for k,v in batch_result.items() if k!='checks'},'retained_image_bytes':retained,'delta_p95_ms':round(delta,3),'model_calls':0,'image_generations':0,'qq_messages_sent':0,'model_probes':probes},ensure_ascii=False),flush=True)
        finally:
            await runtime.close()


if __name__=='__main__':asyncio.run(run())
