"""Authenticated synthetic checks against live plugin components; never QQ sends."""
import importlib
import time
from types import SimpleNamespace
from uuid import uuid4


async def verify_image_pending_notice(plugin):
    """Run native before-tool hooks with captured sends; no tool execution or QQ messages."""
    from astrbot.core.astr_agent_hooks import MAIN_AGENT_HOOKS
    group=next(iter(plugin.router.settings['allowed_groups']))
    def event(group_id=group,private=False,fail=False):
        extra={'qq_diagnostic':True}
        captured=[]
        async def send(result):
            if fail:raise RuntimeError('Synthetic send failure')
            captured.append(result)
        ev=SimpleNamespace(plugins_name=None,is_stopped=lambda:False,is_private_chat=lambda:private,get_group_id=lambda:group_id,get_sender_id=lambda:'diagnostic-user',get_self_id=lambda:'diagnostic-bot',get_extra=lambda k,default=None:extra.get(k,default),set_extra=lambda k,v:extra.__setitem__(k,v),send=send,plain_result=lambda text:text)
        return ev,captured
    async def start(ev,name,args=None):
        await MAIN_AGENT_HOOKS.on_tool_start(SimpleNamespace(context=SimpleNamespace(event=ev)),SimpleNamespace(name=name),args or {})
    first,sent=event()
    first_args={'prompt':'把米饭换成蛋炒饭','pending_message':'白米饭升级蛋炒饭？这碗交给我，给它添点香气！'}
    await start(first,'generate_image',first_args)
    sent.append('[generation would start here]')
    second_args={'pending_message':'第二句不应重复发'}
    await start(first,'generate_selfie',second_args)
    checks={'notice_before_generation':len(sent)==2 and sent[0]!='[generation would start here]',
        'model_dialogue_sent_verbatim':sent[0]=='白米饭升级蛋炒饭？这碗交给我，给它添点香气！',
        'notice_parameter_removed_before_backend':first_args=={'prompt':'把米饭换成蛋炒饭'} and not second_args,
        'one_notice_per_request':len(sent)==2,
        'event_not_stopped':not first.is_stopped()}
    selfie,ss=event()
    await start(selfie,'generate_selfie',{'pending_message':'厨师帽先戴好，这回给你拍个精神点的。'})
    checks['selfie_notice']=ss==['厨师帽先戴好，这回给你拍个精神点的。']
    for label,ev in [('other_group',event('not-allowed')),('private',event(private=True))]:
        args={'pending_message':'不应发送'}
        await start(ev[0],'generate_image',args)
        checks[label+'_silent']=not ev[1]
        checks[label+'_parameter_removed']=not args
    other,os=event()
    await start(other,'recall_long_term_memory')
    checks['other_tools_silent']=not os
    internal,ins=event()
    legacy_args={'return_result':True,'refs':'/untrusted/model/path.png','pending_message':'我来照着参考图改一下。'}
    await start(internal,'generate_image',legacy_args)
    checks['legacy_chat_flags_normalized_before_notice']=len(ins)==1 and not legacy_args
    broken,_=event(fail=True)
    await start(broken,'generate_image',{'pending_message':'让我来画。'})
    checks['notice_failure_does_not_abort']=not broken.is_stopped()
    missing,ms=event()
    await start(missing,'generate_image')
    checks['missing_model_line_does_not_use_template']=not ms and not missing.is_stopped()
    invalid,vs=event()
    await start(invalid,'generate_image',{'pending_message':['invalid']})
    checks['invalid_model_line_does_not_abort_or_send']=not vs and not invalid.is_stopped()
    return {'checks':checks,'passed':all(checks.values()),'example_notice':sent[0],'qq_messages_sent':0,'image_generations':0}


async def verify_chat_image_references(plugin):
    from copy import copy,deepcopy
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from PIL import Image as PILImage
    from astrbot.api.message_components import Image
    from astrbot.core.astr_agent_hooks import MAIN_AGENT_HOOKS
    from .image_tool_compat import prepare_chat_image_tools
    omni=plugin.context.get_registered_star('astrbot_plugin_omnidraw').star_cls
    checks={}
    full=plugin.context.get_llm_tool_manager().get_full_tool_set()
    original={t.name:deepcopy(t.parameters) for t in full.tools if t.name in ('generate_image','generate_selfie')}
    req=SimpleNamespace(func_tool=full)
    prepare_chat_image_tools(req,model_notice=True)
    checks['chat_schemas_hide_internal_fields']=all(not {'return_result','refs'}.intersection(t.parameters.get('properties',{})) for t in req.func_tool.tools if t.name in original)
    checks['global_schemas_unchanged']=all(t.parameters==original[t.name] for t in full.tools if t.name in original)
    checks['model_notice_required_only_on_image_copies']=all('pending_message' in t.parameters.get('properties',{}) and 'pending_message' in t.parameters.get('required',[]) for t in req.func_tool.tools if t.name in original)
    group=next(iter(plugin.router.settings['allowed_groups']))
    with TemporaryDirectory(prefix='qq-image-reference-check-',dir='/AstrBot/data/temp') as temporary:
        paths=[str(Path(temporary)/name) for name in ('rabbit.png','wolf.png')]
        for color,path in zip(('red','blue'),paths):PILImage.new('RGB',(16,16),color).save(path)
        extra={}
        notices=[]
        async def capture(result):notices.append(result)
        event=SimpleNamespace(plugins_name=None,is_stopped=lambda:False,is_private_chat=lambda:False,get_group_id=lambda:group,get_sender_id=lambda:'diagnostic-user',get_self_id=lambda:'diagnostic-bot',get_extra=lambda k,default=None:extra.get(k,default),set_extra=lambda k,v:extra.__setitem__(k,v),send=capture,plain_result=lambda text:text,message_obj=SimpleNamespace(message=[Image.fromFileSystem(p) for p in paths]))
        args={'prompt':'保留漫画构图，用两张参考图分别替换兔子和恶魔狼','aspect_ratio':'3:4','count':1,'return_result':True,'refs':'\n'.join(paths),'pending_message':'两张参考图收到了，我来把角色换进去。'}
        tool=req.func_tool.get_tool('generate_image')
        await MAIN_AGENT_HOOKS.on_tool_start(SimpleNamespace(context=SimpleNamespace(event=event)),tool,args)
        checks['legacy_model_flags_removed_before_execution']='return_result' not in args and 'refs' not in args
        checks['model_notice_not_forwarded_to_image_backend']='pending_message' not in args
        checks['pending_notice_still_sent']=len(notices)==1
        # Use an instance copy and a stub generator/sender. No global patches,
        # quota changes, backend calls or actual QQ sends occur in this probe.
        clone=copy(omni)
        clone._permission_denied_message=lambda ev:''
        clone._reserve_image_quota=lambda ev,count:('',0)
        clone._complete_image_quota=lambda *a:None
        clone._release_image_quota=lambda *a:None
        observed={}
        async def generation(ev,prompt,count,**kwargs):
            raw=clone._get_event_images(ev)
            safe=await clone._process_and_save_images(raw)
            observed.update(raw=raw,safe=safe)
            return {'results':[safe[0]]}
        async def sender(ev,results):
            observed['sent_images']=len(results)
            return len(results)
        async def forbidden(*a,**kw):raise AssertionError('Chat must not use the plugin-only result API')
        clone._run_text2img_generation=generation
        clone._send_generated_images=sender
        clone.generate_images_for_plugin=forbidden
        result=await clone.tool_generate_image(event,**args)
        checks['both_message_references_selected']=observed.get('raw')==paths
        checks['both_temp_references_validated']=observed.get('safe')==paths
        checks['normal_auto_send_path_used']=observed.get('sent_images')==1 and '成功下发 1 张图' in result
        try:
            omni._validated_plugin_image_refs(paths)
            checks['plugin_api_path_restriction_preserved']=False
        except ValueError:
            checks['plugin_api_path_restriction_preserved']=True
    return {'checks':checks,'passed':all(checks.values()),'references':2,'backend':'stub_not_called','image_generations':0,'qq_messages_sent':0}


async def verify_performance_request(context,probe,call_model=False):
    from pathlib import Path
    from tempfile import TemporaryDirectory
    import gzip,json
    with TemporaryDirectory(prefix='qq-context-archive-check-',dir='/AstrBot/data/temp') as folder:
        extra={'qq_diagnostic':True}
        group=next(iter(probe.router.settings['allowed_groups']))
        event=SimpleNamespace(unified_msg_origin='qq-snowluma:GroupMessage:'+group,get_group_id=lambda:group,get_message_str=lambda:'今天晚上吃什么',get_extra=lambda k,default=None:extra.get(k,default),set_extra=lambda k,v:extra.__setitem__(k,v))
        source=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,ARCHIVE_TEST'}}]}]
        request=SimpleNamespace(contexts=source,system_prompt='',conversation=SimpleNamespace(cid='diagnostic-archive'))
        probe.cache_path=Path(folder)/'reply_context.json'
        probe.prepare_performance_context(event,request)
        files=list((Path(folder)/'history_archive').glob('*.json.gz'))
        checks={'archive_roundtrip':len(files)==1 and json.loads(gzip.decompress(files[0].read_bytes()))['history']==source,'request_image_omitted':request.contexts!=source}
        blocker=Path(folder)/'not-a-directory'
        blocker.write_text('synthetic',encoding='utf-8')
        probe.cache_path=blocker/'reply_context.json'
        failure_request=SimpleNamespace(contexts=source,system_prompt='',conversation=SimpleNamespace(cid='diagnostic-failure'))
        probe.prepare_performance_context(event,failure_request)
        checks['archive_failure_preserves_original']=failure_request.contexts is source and event.get_extra('qq_performance').get('archive_failed') is True
        del probe.cache_path
    result=await verify_native_meme_request(context,probe,call_model,'今天晚上吃什么',True)
    result['archive_checks']=checks
    if 'passed' in result:result['passed']=result['passed'] and all(checks.values())
    return result


async def verify_native_meme_request(context,probe,call_model=False,message_text='发个开心的表情包',direct=False,image_notice=False):
    """Use native construction, existing history and ordered hooks; never run tools/send/save history."""
    from dataclasses import replace
    from .meme_intent import wants_existing_meme
    total_started=time.monotonic()
    stock_request=wants_existing_meme(message_text)
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember, Group
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.message.components import Plain
    from astrbot.core.pipeline.process_stage.method.agent_sub_stages.internal import InternalAgentSubStage
    from astrbot.core.pipeline.context import PipelineContext
    from astrbot.core.astr_main_agent import build_main_agent
    from astrbot.core.star.star_handler import EventType,star_handlers_registry
    class NoSendEvent(AstrMessageEvent):
        async def send(self,*a,**kw):raise RuntimeError('Diagnostics cannot send QQ messages')
        async def send_streaming(self,*a,**kw):raise RuntimeError('Diagnostics cannot send QQ messages')
    group=next(iter(probe.router.settings['allowed_groups']))
    msg=AstrBotMessage()
    msg.type=MessageType.GROUP_MESSAGE
    msg.self_id='2354912009'
    msg.session_id=group
    msg.message_id='native-diagnostic-'+uuid4().hex
    msg.group=Group(group_id=group,group_name='测试群')
    msg.sender=MessageMember(user_id='1511659008',nickname='部署验证')
    msg.message_str=message_text
    msg.message=[Plain(text=msg.message_str)]
    msg.raw_message={}
    event=NoSendEvent(msg.message_str,msg,PlatformMetadata(name='aiocqhttp',description='isolated diagnostic',id='qq-snowluma'),group)
    event.is_wake=True
    event.is_at_or_wake_command=direct
    policy=context.get_registered_star('astrbot_plugin_user_policy').star_cls
    async for _ in policy.apply_message_policy(event):pass
    had_anchor=bool(probe.router.context(group).last_ai)
    await probe.route_contextual_request(event)
    if not event.is_at_or_wake_command:
        raise RuntimeError('Native synthetic request did not wake the normal pipeline')
    stages=[]
    async def hooks(kind,*args):
        for h in star_handlers_registry.get_handlers_by_event_type(kind,plugins_name=event.plugins_name):
            # Reflection writes synthetic replies into persistent memory. It is
            # irrelevant to verifying image rendering and must not run here.
            if kind==EventType.OnLLMResponseEvent and 'livingmemory' in h.handler_full_name:
                continue
            handler=h.handler
            if 'qq_persona_models' in h.handler_full_name:
                handler=getattr(probe,h.handler_name)
            hook_started=time.monotonic()
            await handler(event,*args)
            if args and hasattr(args[0],'system_prompt'):
                req=args[0]
                stages.append({'handler':h.handler_full_name,'seconds':round(time.monotonic()-hook_started,3),'meme_prompt':'<!-- meme_manager_prompt:start -->' in (req.system_prompt or ''),'stock_policy':'本次现成表情请求' in (req.system_prompt or ''),'tool_names':req.func_tool.names() if req.func_tool else [],'history_messages':len(req.contexts or [])})
            if event.is_stopped():raise RuntimeError('Diagnostic event stopped by '+h.handler_full_name)
    await hooks(EventType.OnWaitingLLMRequestEvent)
    stage=InternalAgentSubStage()
    await stage.initialize(PipelineContext(context.get_config(umo=event.unified_msg_origin),SimpleNamespace(context=context),'default'))
    result=await build_main_agent(event=event,plugin_context=context,config=replace(stage.main_agent_cfg,streaming_response=False),apply_reset=False,prepared_images={})
    if result is None:raise RuntimeError('Native builder did not create a request')
    req=result.provider_request
    try:
        await hooks(EventType.OnLLMRequestEvent,req)
        await result.reset_coro
    finally:
        # close is harmless after await and prevents a warning if a hook failed.
        if result.reset_coro:result.reset_coro.close()
    runner=result.agent_runner
    report={'stages':stages,'live_anchor_present':had_anchor,'old_anchor_injected':bool(event.get_extra('qq_semantic_reference_attached')),'history_messages':len(req.contexts or []),'history_tool_calls':sum(bool(x.get('tool_calls')) for x in req.contexts or []),'model':result.provider.get_model(),'final_meme_prompt':'<!-- meme_manager_prompt:start -->' in (req.system_prompt or ''),'final_stock_policy':'本次现成表情请求' in (req.system_prompt or ''),'generation_tools_absent':not {'generate_image','generate_selfie','generate_video'}.intersection(req.func_tool.names() if req.func_tool else []),'qq_messages_sent':0}
    report['performance']=event.get_extra('qq_performance')
    report['history_user_turns']=sum(x.get('role')=='user' for x in req.contexts or [])
    report['history_serialized_chars']=len(__import__('json').dumps(req.contexts or [],ensure_ascii=False))
    if call_model:
        start=time.monotonic()
        responses=[response async for response in runner._iter_llm_responses()]
        response=responses[-1]
        if image_notice:
            from copy import deepcopy
            from astrbot.core.astr_agent_hooks import MAIN_AGENT_HOOKS
            from mcp.types import CallToolResult,TextContent
            captured=[]
            event.set_extra('qq_diagnostic',True)
            event.set_extra('qq_notice_model_fallback_allowed',True)
            if image_notice=='force_fallback':
                for arguments in response.tools_call_args:arguments.pop('pending_message',None)
            async def capture(result):captured.append(result.get_plain_text())
            event.send=capture
            calls=[]
            for name,args in zip(response.tools_call_name,response.tools_call_args):
                if name not in ('generate_image','generate_selfie'):continue
                calls.append({'tool':name,'model_notice':args.get('pending_message')})
            executions=[]
            class DryExecutor:
                async def execute(self,tool,run_context,**arguments):
                    executions.append({'tool':tool.name,'notice_sent_before_execution':bool(captured),'helper_fields_removed':not {'pending_message','return_result','refs'}.intersection(arguments)})
                    yield CallToolResult(content=[TextContent(type='text',text='诊断：没有执行生图或发送图片。')])
            async def end_noop(*args):pass
            # Use the real runner's argument filtering and before-tool hooks,
            # replacing only execution and after-tool persistence side effects.
            runner.tool_executor=DryExecutor()
            runner.agent_hooks=SimpleNamespace(on_tool_start=MAIN_AGENT_HOOKS.on_tool_start,on_tool_end=end_noop)
            async for _ in runner._handle_function_tools(req,response):pass
            report.update(primary_model_calls=1,notice_model_calls=event.get_extra('qq_notice_model_calls') or 0,notice_source=event.get_extra('qq_image_notice_source'),seconds=round(time.monotonic()-start,2),image_tool_calls=calls,captured_notices=captured,image_generations=0,native_tool_executions=executions,schema_has_notice=all('pending_message' in req.func_tool.get_tool(c['tool']).parameters.get('properties',{}) for c in calls),raw_response_has_notice='pending_message' in str(response.raw_completion),system_notice_present='图片任务开工对白' in req.system_prompt,execution_rule_present='[图片任务执行]' in req.system_prompt,response_text=response.completion_text or '')
            report['passed']=bool(calls) and len(captured)==1 and bool(executions) and all(e['helper_fields_removed'] and e['notice_sent_before_execution'] for e in executions)
            return report
        memes=context.get_registered_star('meme_manager').star_cls
        prepared=await memes.compat_prepare_message(event,response.completion_text or '')
        report.update(seconds=round(time.monotonic()-start,2),tool_calls=getattr(response,'tools_call_name',[]) or [],prepared_images=len(prepared['images']))
        usage=getattr(response,'usage',None)
        report['usage']={k:getattr(usage,k,None) for k in ('input_other','input_cached','output')}
        # Continue through the same response and decoration hooks as a normal
        # non-streaming agent reply, but stop before RespondStage/after_sent.
        from astrbot.core.message.message_event_result import MessageEventResult,ResultContentType
        from astrbot.core.message.components import Image
        await hooks(EventType.OnLLMResponseEvent,response)
        outgoing=MessageEventResult().set_result_content_type(ResultContentType.LLM_RESULT)
        if response.result_chain:
            outgoing.chain=list(response.result_chain.chain)
        else:
            outgoing.message(response.completion_text or '')
        event.set_result(outgoing)
        await hooks(EventType.OnDecoratingResultEvent)
        report['decorated_images']=sum(isinstance(x,Image) for x in outgoing.chain)
        report['pending_images']=len(event.get_extra('meme_manager_pending_images') or [])
        report['outgoing_tags_removed']=all('&&' not in getattr(x,'text','') for x in outgoing.chain)
        if stock_request:
            report['passed']=report['final_meme_prompt'] and report['final_stock_policy'] and report['generation_tools_absent'] and not report['tool_calls'] and report['prepared_images']==1 and report['decorated_images']+report['pending_images']==1 and report['outgoing_tags_removed']
        else:
            report['passed']=report['final_meme_prompt'] and not report['tool_calls'] and report['history_user_turns']<=int(probe.config.get('performance',{}).get('history_turns',12))
        report['pipeline_seconds']=round(time.monotonic()-total_started,2)
    return report


async def verify_memory_meme(context, bind_persona):
    memory=context.get_registered_star('astrbot_plugin_livingmemory').star_cls
    memes=context.get_registered_star('meme_manager').star_cls
    ready,message=await memory._ensure_plugin_ready()
    if not ready:
        raise RuntimeError('LivingMemory not ready: '+message)
    engine=memory.initializer.memory_engine
    namespace='deployment-check-'+uuid4().hex
    session_a,session_b=namespace+':A',namespace+':B'
    scope=importlib.import_module(memory.__class__.__module__.rsplit('.',1)[0]+'.core.memory_scope')
    report={'checks':{},'qq_messages_sent':0,'test_memories_removed':False}
    checks=report['checks']
    def event(group,persona='大肥鱼'):
        extras={'user_policy_effective_persona_id':persona}
        async def no_send(*args,**kwargs):
            raise RuntimeError('Synthetic check must not send messages')
        return SimpleNamespace(unified_msg_origin='qq-snowluma:GroupMessage:'+group,session_id=group,get_group_id=lambda:group,get_sender_id=lambda:'deployment-check-user',get_sender_name=lambda:'部署验收虚拟用户',get_platform_name=lambda:'aiocqhttp',get_extra=lambda k,default=None:extras.get(k,default),set_extra=lambda k,v:extras.__setitem__(k,v),send=no_send)
    checks['memory_allows_test_group']=scope.is_event_memory_allowed(memory.config_manager,event('347440128'))
    checks['memory_denies_other_group']=not scope.is_event_memory_allowed(memory.config_manager,event('999999999'))
    ids=[]
    try:
        for session,persona,fact in [(session_a,'大肥鱼','乌龙茶'),(session_a,'ChatGPT龙娘','茉莉花茶'),(session_b,'大肥鱼','咖啡')]:
            mid=await engine.add_memory(content=f'{namespace}：部署验收虚拟用户偏好{fact}。',session_id=session,persona_id=persona,importance=0.6,metadata={'memory_type':'PREFERENCE','topics':[namespace],'key_facts':[f'部署验收虚拟用户偏好{fact}']},atoms=[])
            ids.append(mid)
        wanted=await engine.search_memories(query=namespace+' 虚拟用户偏好的饮品',k=5,session_id=session_a,persona_id='大肥鱼')
        wanted_ids={r.doc_id for r in wanted}
        checks['memory_write_and_recall']=ids[0] in wanted_ids
        checks['memory_persona_isolation']=ids[1] not in wanted_ids
        checks['memory_group_isolation']=ids[2] not in wanted_ids
        dragon=await engine.search_memories(query=namespace+' 虚拟用户偏好的饮品',k=5,session_id=session_a,persona_id='ChatGPT龙娘')
        checks['dragon_has_separate_memory']=ids[1] in {r.doc_id for r in dragon} and ids[0] not in {r.doc_id for r in dragon}
    finally:
        if ids:
            removed=await engine.batch_delete_memories(ids)
            report['test_memories_removed']=removed==len(ids)
        else:
            report['test_memories_removed']=True
    checks['memory_test_cleanup']=report['test_memories_removed']
    packs={}
    for persona in ['大肥鱼','ChatGPT龙娘']:
        ev=event('347440128',persona)
        bind_persona(ev)
        checks[persona+'_effective_persona_propagated']=ev.get_extra('meme_manager_resolved_persona_id')==persona
        pc=memes._resolve_runtime_pack_context(event=ev)
        mapping=pc.get('category_mapping') or {}
        categories=[c for c in mapping if memes._get_category_meme_files(ev,c)]
        if not categories:
            raise RuntimeError('No usable meme categories for '+persona)
        tag=categories[0]
        prepared=await memes.compat_prepare_message(ev,'收到，验收文本。\n&&'+tag+'&&\n&&'+categories[-1]+'&&')
        chain=prepared['cleaned_chain']
        text=''.join(getattr(x,'text','') for x in chain.chain)
        checks[persona+'_meme_markup_removed']='&&' not in text
        checks[persona+'_meme_image_prepared']=len(prepared['images'])==1
        checks[persona+'_meme_one_image_limit']=len(prepared['images'])<=1
        packs[persona]={'pack_ids':pc.get('pack_ids'),'usable_categories':len(categories)}
    report['packs']=packs
    checks['persona_pack_switching']=packs['大肥鱼']['pack_ids']!=packs['ChatGPT龙娘']['pack_ids']
    names={tool.name for tool in context.get_llm_tool_manager().func_list}
    checks['recall_tool_registered']='recall_long_term_memory' in names
    checks['memorize_tool_registered']='memorize_long_term_memory' in names
    report['passed']=all(checks.values())
    return report


async def verify_existing_meme_request(context,request_hook,text='发个表情包'):
    from .meme_intent import wants_existing_meme
    cases={'发个表情包':True,'发个开心的表情':True,'来个表情包':True,'给我整一个表情包':True,'不要生成新的，发个现成表情包':True,'画一张新的表情包':False,'生成一张你的表情包':False,'把这张图改成表情包':False,'帮我做一张表情包':False,'表情包是什么意思':False,'/画 表情包':False,'帮我画一只猫':False}
    checks={'intent_cases':all(wants_existing_meme(t)==v for t,v in cases.items())}
    memes=context.get_registered_star('meme_manager').star_cls
    extras={'meme_manager_resolved_persona_id':'大肥鱼'}
    event=SimpleNamespace(session_id='347440128',unified_msg_origin='qq-snowluma:GroupMessage:347440128',is_stopped=lambda:False,is_private_chat=lambda:False,get_group_id=lambda:'347440128',get_sender_id=lambda:'diagnostic-user',get_self_id=lambda:'diagnostic-bot',get_message_str=lambda:text,get_extra=lambda k,default=None:extras.get(k,default),set_extra=lambda k,v:extras.__setitem__(k,v))
    persona=context.persona_manager.get_persona_v3_by_id('大肥鱼')
    req=SimpleNamespace(prompt=text,system_prompt=persona.get('prompt',persona.get('system_prompt','')),func_tool=context.get_llm_tool_manager().get_full_tool_set(),conversation=None,session_id='347440128')
    memes._apply_request_prompt(req,event=event)
    await request_hook(event,req)
    checks['stock_request_has_no_generation_tools']=not {'generate_image','generate_selfie','generate_video'}.intersection(req.func_tool.names() if req.func_tool else [])
    checks['global_generation_tools_preserved']={'generate_image','generate_selfie'}.issubset(set(context.get_llm_tool_manager().get_full_tool_set().names()))
    cfg=context.get_config(umo=event.unified_msg_origin)
    provider_id=cfg.get('agent_runner',{}).get('config',{}).get('model',{}).get('provider_id') or cfg.get('provider_settings',{}).get('default_provider_id')
    response=await context.get_provider_by_id(provider_id).text_chat(prompt=req.prompt,system_prompt=req.system_prompt,func_tool=req.func_tool)
    tool_calls=getattr(response,'tools_call_name',[]) or []
    checks['real_model_did_not_call_tools']=not tool_calls
    prepared=await memes.compat_prepare_message(event,response.completion_text or '')
    checks['real_model_selected_existing_meme']=len(prepared['images'])==1
    return {'checks':checks,'intent_case_count':len(cases),'passed':all(checks.values()),'model_tool_calls':tool_calls,'prepared_images':len(prepared['images']),'qq_messages_sent':0}
