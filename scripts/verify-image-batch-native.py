"""Called inside the existing network-disabled native fixture, with synthetic data."""
import asyncio
import base64
import importlib
from io import BytesIO
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace


class SirGraceFixture:
    async def _run_agent_with_grace(self,run):
        await asyncio.wait_for(asyncio.shield(run.work()),timeout=self.settings.generation_timeout_sec)


async def verify_batch(probe,runtime,event,request,release,root,package_name='runtime_fixture'):
    from aiohttp import web
    from PIL import Image as PILImage
    from astrbot.api.message_components import Image
    from mcp.types import CallToolResult,TextContent
    package=ModuleType('native_omni');package.__path__=['/omni-source'];sys.modules[package.__name__]=package
    module=importlib.import_module('native_omni.main')
    cls=next(v for v in vars(module).values() if isinstance(v,type) and v.__module__==module.__name__ and hasattr(v,'tool_generate_image'))
    models=importlib.import_module('native_omni.models')
    optimizer=importlib.import_module('native_omni.core.prompt_optimizer')
    personas=importlib.import_module('native_omni.core.persona_manager')
    local=importlib.import_module(package_name+'.image_batch')
    policy_module=importlib.import_module(package_name+'.image_failure_policy')
    logging=importlib.import_module(package_name+'.model_logging')
    timeouts=importlib.import_module(package_name+'.image_batch_timeout')
    checks={};received=[];active=0;peak=0;failure_label=None;failure_status=503;response_pixels={}
    async def image_api(req):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        try:
            refs=[]
            if req.content_type=='multipart/form-data':
                form=await req.multipart();payload={}
                async for part in form:
                    data=await part.read()
                    if part.name=='image[]':refs.append(bytes(data))
                    else:payload[part.name]=data.decode()
            else:payload=await req.json()
            index=len(received)+1;received.append({'prompt':payload['prompt'],'n':str(payload.get('n')),'refs':refs,'path':req.path})
            await asyncio.sleep(.005 if failure_status==400 and failure_label and failure_label in payload['prompt'] else .025*(1+index%3))
            if failure_label and failure_label in payload['prompt']:return web.json_response({'error':{'message':'moderation_blocked' if failure_status==400 else 'synthetic transient failure'}},status=failure_status)
            buf=BytesIO();PILImage.new('RGB',(16,16),(index,10,20)).save(buf,format='PNG');response_pixels[index]=(index,10,20)
            return web.json_response({'data':[{'b64_json':base64.b64encode(buf.getvalue()).decode()}]})
        finally:active-=1
    app=web.Application();app.router.add_post('/v1/images/generations',image_api);app.router.add_post('/v1/images/edits',image_api)
    server=web.AppRunner(app);await server.setup();site=web.TCPSite(server,'127.0.0.1',0);await site.start()
    port=site._server.sockets[0].getsockname()[1]
    cfg={'providers':[{'id':'wire-fixture','api_type':'openai','base_url':'http://127.0.0.1:'+str(port)+'/v1','api_keys':'fixture-only','model':'synthetic-image','timeout':5}],
         'router_config':{'text2img_chain':['wire-fixture'],'selfie_chain':['wire-fixture']},'optimizer_config':{'enable_optimizer':False,'max_batch_count':4}}
    omni=object.__new__(cls);omni.data_dir=str(root/'omni-data');Path(omni.data_dir).mkdir()
    omni.plugin_config=models.PluginConfig.from_dict(cfg,omni.data_dir,cleanup_persona_refs=False)
    # Match the installed router mapping explicitly; no real provider config.
    omni.plugin_config.chains['text2img']=['wire-fixture'];omni.plugin_config.chains['selfie']=['wire-fixture']
    omni.prompt_optimizer=optimizer.PromptOptimizer(omni.plugin_config)
    omni.persona_manager=personas.PersonaManager(omni.plugin_config)
    quota=[];omni._permission_denied_message=lambda e:'denied' if e.get_extra('deny_batch') else ''
    omni._reserve_image_quota=lambda e,n:('quota',0) if e.get_extra('deny_quota') else (quota.append(('reserve',n)) or ('',n))
    omni._complete_image_quota=lambda e,reserved,sent:quota.append(('complete',reserved,sent))
    omni._release_image_quota=lambda e,n:quota.append(('release',n))
    omni._prune_cache_if_needed=lambda *a,**kw:None
    omni._lease_cache_paths=lambda paths:[];omni._release_cache_paths=lambda paths:None
    previous=probe.context.get_registered_star('astrbot_plugin_omnidraw');old_activity=probe.model_activity
    registered_get=probe.context.get_registered_star
    sir_module=ModuleType('synthetic_batch_sir.generation');sir_module.SirGraceFixture=SirGraceFixture
    old_sir_module=SirGraceFixture.__module__;SirGraceFixture.__module__=sir_module.__name__;sys.modules[sir_module.__name__]=sir_module
    sir=type('SirFixture',(),{'__module__':'synthetic_batch_sir.main'})()
    sir_wait_original=SirGraceFixture._run_agent_with_grace
    probe.context.get_registered_star=lambda name:SimpleNamespace(star_cls=omni) if name=='astrbot_plugin_omnidraw' else registered_get(name)
    probe.context.provider_manager=SimpleNamespace(inst_map={})
    logger=logging.ModelActivityLogger(sink=lambda row:None);probe.model_activity=logger
    probe.image_failure_policy=policy_module.ImageFailurePolicy();logger.image_failure_observer=probe.image_failure_policy.record_failure
    adapter=local.ImageBatchAdapter(probe);probe.image_batch_adapter=adapter
    timeout_adapter=timeouts.ImageTimeoutAdapter()
    logger.install(probe.context);adapter.install(probe.context)
    probe.context.get_registered_star=lambda name:SimpleNamespace(star_cls=omni) if name=='astrbot_plugin_omnidraw' else SimpleNamespace(star_cls=sir) if name=='astrbot_plugin_self_initiated_reply' else registered_get(name)
    timeout_adapter.install(probe.context);runtime.install_outgoing()
    check=lambda name,value:checks.__setitem__(name,bool(value))
    async def call(e,count,prompts,refs=(),selfie=False):
        await runtime.prepare(e,request(e));catalog=runtime.candidate.catalog(e)
        selected=[next(r['id'] for r in catalog if r['message_id']==mid) for mid in refs]
        e.set_extra('qq_diagnostic',False);e.set_extra('qq_image_task_contract_enabled',True);e.set_extra('qq_image_batch_enabled',True)
        req=request(e);probe.image_failure_policy.track(e,req)
        args={'action' if selfie else 'prompt':'共享风格与约束','count':count,'image_prompts':prompts,'pending_message':'我来把这几张分别画出来。','image_task':{'operation':'edit' if selected else 'independent','reason':'合成任务','independent_quote':'' if selected else e.message_str},'reference_ids':selected,'reference_notes':[{'image_id':i,'purpose':'保持原始设定'} for i in selected]}
        tool=SimpleNamespace(name='generate_selfie' if selfie else 'generate_image')
        await probe.normalize_image_arguments(e,tool,args);await probe.announce_image_generation(e,tool,args)
        from importlib import import_module
        guard=import_module(package_name+'.image_tool_compat').guard_image_handler(omni.tool_generate_selfie if selfie else omni.tool_generate_image)
        text=await guard(e,**args)
        result=CallToolResult(content=[TextContent(type='text',text=text)])
        await probe.track_image_tool_result(e,tool,args,result)
        return result,e.get_extra('qq_image_failure_state'),e.get_extra('qq_image_batch_report')
    try:
        from astrbot.core.agent.tool import FunctionTool
        from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
        check('executor_and_sir_timeout_adapters_installed_together',timeout_adapter.ready and len(timeout_adapter.patches)==2 and SirGraceFixture._run_agent_with_grace is not sir_wait_original)
        async def slow_handler(ev):await asyncio.sleep(.025);return 'synthetic completed'
        e=event('图片工具等待边界');e.set_extra('qq_image_batch_enabled',True)
        ctx=SimpleNamespace(context=SimpleNamespace(event=e),tool_call_timeout=.005)
        image_tool=FunctionTool(name='generate_image',description='fixture',parameters={'type':'object','properties':{}},handler=slow_handler)
        normal_tool=FunctionTool(name='ordinary_fixture',description='fixture',parameters={'type':'object','properties':{}},handler=slow_handler)
        image_res=[r async for r in FunctionToolExecutor.execute(image_tool,ctx)]
        try:
            normal_res=[r async for r in FunctionToolExecutor.execute(normal_tool,ctx)];ordinary_timed_out=False
        except Exception as exc:ordinary_timed_out='timeout' in str(exc).lower()
        check('image_tool_gets_scoped_timeout_override','synthetic completed' in ''.join(getattr(c,'text','') for r in image_res if hasattr(r,'content') for c in r.content))
        check('ordinary_tool_keeps_original_timeout',ordinary_timed_out and ctx.tool_call_timeout==.005)
        await release(e)
        original_assets=runtime.store.stats()['attachments']
        e=event('生成四张不同画面');result,state,report=await call(e,4,['早餐','午餐','晚餐','甜点'])
        check('four_native_single_image_http_requests',len(received)==4 and all(r['n']=='1' for r in received))
        check('native_http_concurrency_bounded_at_two',peak==2)
        check('per_image_prompts_preserve_order',all(p in r['prompt'] for p,r in zip(('早餐','午餐','晚餐','甜点'),received)))
        check('four_images_really_sent_and_counted',state['delivered_images']==4 and all(i['status']=='sent' for i in report['items']))
        check('all_successful_images_archived',runtime.store.stats()['attachments']==original_assets+4)
        snapshot=runtime.archive.snapshot(e)
        with runtime.store.db() as db:
            rows=db.execute('SELECT source FROM assets WHERE scope=? AND seq>? ORDER BY seq',(snapshot['scope'],snapshot['seq'])).fetchall()
        sources=[json.loads(r['source']) for r in rows]
        check('batch_positions_and_descriptions_archived',[(s.get('batch_index'),s.get('image_prompt_excerpt')) for s in sources]==list(enumerate(['早餐','午餐','晚餐','甜点'],1)))
        check('native_quota_reserved_and_finalized_by_images',('reserve',4) in quota and ('complete',4,4) in quota)
        await release(e)
        before=len(received);e=event('同一主题给我四个版本');result,state,report=await call(e,4,[])
        variants=received[before:]
        check('same_theme_batch_uses_four_independent_requests',len(variants)==4 and len(set(r['prompt'] for r in variants))==1 and state['delivered_images']==4)
        await release(e)
        # Use a new source in this scoped archive to test actual multipart bytes.
        source=root/'batch-source.png';PILImage.new('RGB',(32,32),'purple').save(source)
        upload=event('批量修改的角色底稿',source);await runtime.capture(upload);await release(upload)
        before=len(received);e=event('沿用底稿分别画四个表情');result,state,report=await call(e,4,['开心','生气','疑惑','困倦'],[upload.message_obj.message_id])
        edits=received[before:]
        check('batch_edits_use_native_multipart_endpoint',len(edits)==4 and all(r['path'].endswith('/images/edits') for r in edits))
        check('every_edit_receives_exact_same_frozen_reference',all(r['refs']==[source.read_bytes()] for r in edits))
        await release(e)
        omni.plugin_config.persona_ref_images=[str(source)];omni.plugin_config.persona_base_prompt='合成固定AI角色'
        before=len(received);e=event('给我三张不同场景的自拍');result,state,report=await call(e,3,['早上','下午','夜景'],selfie=True)
        selfies=received[before:]
        check('selfie_batch_preserves_fixed_persona_reference',len(selfies)==3 and all(r['refs']==[source.read_bytes()] for r in selfies))
        check('selfie_batch_success_is_recognized',state['delivered_images']==3 and e.get_extra('qq_image_task_state')=={})
        await release(e)
        before=len(received);failure_label='FAIL-ITEM';e=event('生成四张，其中第三张模拟失败')
        result,state,report=await call(e,4,['第一张','第二张','FAIL-ITEM','第四张'])
        check('partial_failure_keeps_three_delivered',state['delivered_images']==3 and [i['status'] for i in report['items']]==['sent','sent','failed','sent'])
        check('partial_result_reports_failed_index','"index": 3, "status": "failed"' in ''.join(getattr(p,'text','') for p in result.content))
        check('partial_failure_does_not_retry_whole_batch',len(received)-before==4)
        probe.image_failure_policy.check(e,1)
        check('remaining_one_image_can_be_requested',True)
        failure_label=None
        before_retry=len(received);retry,state,retry_report=await call(e,1,['第三张补试'])
        check('explicit_missing_item_retry_uses_one_request',len(received)-before_retry==1 and state['attempted_images']==5 and state['delivered_images']==4)
        await release(e)
        before=len(received)
        for key in ('deny_batch','deny_quota'):
            e=event('生成四张');e.set_extra(key,True);await call(e,4,[]);await release(e)
        check('native_permissions_and_quota_still_block_http',len(received)==before)
        before=len(received);failure_label='FATAL';failure_status=400;e=event('四张独立图片中第一张模拟不可重试拒绝')
        result,state,report=await call(e,4,['FATAL','允许的第二张','尚未启动的第三张','尚未启动的第四张'])
        check('fatal_error_stops_queued_image_http',len(received)-before==2 and [i['status'] for i in report['items']]==['failed','sent','not_started','not_started'])
        check('fatal_batch_preserves_inflight_success',state['delivered_images']==1 and '部分图片已发送' in ''.join(getattr(c,'text','') for c in result.content))
        await release(e);failure_label=None;failure_status=503
        before=len(received);e=event('四张图取消测试')
        job=asyncio.create_task(call(e,4,['取消1','取消2','取消3','取消4']))
        for _ in range(100):
            if len(received)-before>=2:break
            await asyncio.sleep(.005)
        job.cancel();await asyncio.gather(job,return_exceptions=True);await asyncio.sleep(.15)
        check('cancelled_batch_does_not_start_queued_images',len(received)-before==2)
        check('cancelled_batch_context_is_cleared',local._BATCH.get() is None)
        await release(e)
        e=event('取消后再画一张');before=len(received);result,state,report=await call(e,1,[])
        check('cancelled_batch_releases_concurrency_slots',len(received)-before==1 and state['delivered_images']==1)
        await release(e)
    finally:
        # Restore the archive wrapper first, then its underlying batch adapter.
        kept=[]
        for owner,name,wrapped,original in runtime.archive.patches:
            if owner is cls:
                if getattr(owner,name) is wrapped:setattr(owner,name,original)
            else:kept.append((owner,name,wrapped,original))
        runtime.archive.patches=kept
        adapter.close();timeout_adapter.close();logger.restore();probe.model_activity=old_activity;probe.context.get_registered_star=registered_get
        check('sir_timeout_adapter_restored',SirGraceFixture._run_agent_with_grace is sir_wait_original)
        SirGraceFixture.__module__=old_sir_module;sys.modules.pop(sir_module.__name__,None)
        await server.cleanup()
    return {'passed':all(checks.values()),'checks':checks,'mock_image_http_requests':len(received),'peak_concurrency':peak,'external_model_calls':0,'real_image_generations':0,'qq_messages_sent':0}
