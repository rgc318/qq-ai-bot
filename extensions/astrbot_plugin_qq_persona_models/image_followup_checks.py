"""Image-thread continuity and conservative failure fallback, no network."""
import asyncio
import base64
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from .reply_routing import ReplyRouter
from .image_followup import latest_image_turn,result_state,tool_started,decode_history_refs,select_previous_reference,restored_paths,capture_turn,prune_cache


async def verify_image_followup(plugin=None):
    checks={};seen=[];now=1000.
    settings={'allowed_groups':['G'],'followup_window_seconds':1800,'image_followup_window_seconds':7200,'judge_timeout_seconds':.02,'aliases':['龙娘']}
    async def judge(payload):
        seen.append(payload)
        return {'recipient':'bot','silence_requested':False,'route':'followup','anchor_id':'image-fixture','confidence':.99}
    def router():
        r=ReplyRouter(dict(settings),judge,clock=lambda:now)
        r.context('G').scope='policy|dragon'
        r.context('G').image_turn={'id':'image-fixture','requested_by':'A','request':'把这张柴犬图转成人形','reply':'我来改','status':'not_called','time':900.,'paths':['private-path'],'reference_count':1,'image_activity':True}
        r.note_ai('G','我醒着呢',request='hello',sender='A')
        return r
    r=router();verdict=await r.decide('G','A','图呢')
    checks['semantic_followup_uses_image_not_greeting']=verdict['reference']['id']=='image-fixture' and seen[-1]['last_ai_activity']['request']=='hello'
    checks['judge_gets_execution_facts_without_paths']=seen[-1]['recent_image_activity']['status']=='not_called' and 'paths' not in seen[-1]['recent_image_activity']
    async def timeout(_):raise asyncio.TimeoutError()
    r=router();r.judge=timeout;verdict=await r.decide('G','A','你说好的那个呢')
    checks['timeout_goes_to_main_context_review']=verdict['route']=='fast' and verdict['reason']=='context_review_judge_unavailable' and verdict['recipient']=='context_review'
    checks['backoff_can_review_without_second_judge']=(await r.decide('G','A','还有呢',explicit=True))['route']=='direct'
    now+=3;verdict=await r.decide('G','A','前面的还没好吗')
    checks['backoff_retains_same_image_facts']=verdict['reason']=='context_review_judge_backoff' and verdict['reference']['status']=='not_called'
    r=router();r.judge=timeout
    checks['no_timeout_fallback_for_other_member']=(await r.decide('G','B','图呢'))['route']=='ambient'
    r=router();r.judge=timeout
    checks['no_hijack_of_other_person']=(await r.decide('G','A','图呢',targets_other=True))['route']=='ambient'
    r=router();r.judge=timeout;r.context('G').messages.append({'role':'user','sender':'A','targets_other':True,'text':'小张给我看看','time':now})
    checks['handoff_prevents_failure_fallback']=(await r.decide('G','A','图呢'))['route']=='ambient'
    async def human(_):return {'recipient':'human','route':'ambient','confidence':.99}
    r=router();r.judge=human
    checks['explicit_negative_not_overridden']=(await r.decide('G','A','小张的图呢'))['route']=='ambient'
    r=router();r.judge=timeout;r.settings['image_context_enabled']=False
    checks['feature_off_stops_fallback']=(await r.decide('G','A','图呢'))['route']=='ambient'
    r=router();r.judge=timeout;r.settings['image_followup_fallback']=False
    checks['fallback_switch_works']=(await r.decide('G','A','图呢'))['route']=='ambient'
    r=router();r.context('G').image_turn['time']=now-7201;r.judge=timeout
    checks['expired_image_not_resumed']=(await r.decide('G','A','图呢'))['route']=='ambient'
    from .context_recovery import read_persona_conversation
    calls=[]
    async def unsafe_default(_):calls.append(True);return 'wrong-scope'
    isolation=SimpleNamespace(_scope=lambda _:('member:B','member'),bindings={'bindings':{}})
    context=SimpleNamespace(conversation_manager=SimpleNamespace(get_curr_conversation_id=unsafe_default),get_registered_star=lambda _:SimpleNamespace(star_cls=SimpleNamespace(memory_isolation=isolation)))
    scoped_event=SimpleNamespace(unified_msg_origin='bot:GroupMessage:G',get_extra=lambda _:SimpleNamespace(memory_isolation=True))
    checks['missing_isolated_binding_never_reads_default']=await read_persona_conversation(context,scoped_event,'dragon') is None and not calls
    r=router();r.context('G').image_turn['status']='running'
    saved=r.snapshot(wall_time=10000);restored=ReplyRouter(dict(settings),judge,clock=lambda:5000.)
    restored.restore(saved,wall_time=10003)
    checks['reload_keeps_scope_and_marks_interruption']=restored.context('G').image_turn['status']=='interrupted' and restored.context('G').scope=='policy|dragon'
    extras={};event=SimpleNamespace(get_extra=lambda k:extras.get(k),set_extra=lambda k,v:extras.update({k:v}),get_message_str=lambda:'画图',get_sender_id=lambda:'A',message_obj=SimpleNamespace(message_id='new-image'))
    probe=SimpleNamespace(router=router(),scoped_group=lambda _: 'G')
    tool=SimpleNamespace(name='generate_image');tool_started(probe,event,tool)
    try:tool_started(probe,event,tool);blocked=False
    except RuntimeError:blocked=True
    checks['running_task_not_started_twice']=blocked and extras['qq_current_image_turn']['status']=='running'
    def result(text):return SimpleNamespace(content=[SimpleNamespace(text=text)],isError=False)
    checks['delivery_success_is_observed']=result_state(result('系统提示：已成功下发 1 张图。'))=='sent'
    checks['zero_delivery_not_success']=result_state(result('系统提示：已成功下发 0 张图。'))=='result_unconfirmed'
    checks['failure_not_marked_running']=result_state(result('系统提示：画图失败 (HTTP 400)。'))=='failed'
    from PIL import Image
    raw=BytesIO();Image.new('RGB',(2,2),'blue').save(raw,format='PNG')
    data='data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode()
    history=[{'role':'user','content':[{'type':'text','text':'把这个转成人形 <system_reminder>User ID: 123, Nickname: 甲</system_reminder>'},{'type':'image_url','image_url':{'url':data}}]},{'role':'assistant','content':'我来改'}]
    with TemporaryDirectory() as directory:
        turn=latest_image_turn(history,20,now,Path(directory))
        checks['original_pixels_recovered_from_history']=turn['status']=='not_called' and Path(turn['paths'][0]).read_bytes()==raw.getvalue()
        checks['owner_and_request_recovered']=turn['requested_by']=='123' and turn['request']=='把这个转成人形'
        checks['arbitrary_history_paths_rejected']=not decode_history_refs(['/etc/passwd','file:///etc/passwd','data:image/png;base64,eA=='],Path(directory))
    from .image_tool_compat import prepare_chat_image_tools
    definition=SimpleNamespace(name='generate_image',parameters={'type':'object','properties':{'prompt':{'type':'string'}},'required':['prompt']},description='draw')
    request=SimpleNamespace(func_tool=SimpleNamespace(tools=[definition]))
    prepare_chat_image_tools(request,contextual_reference=True)
    checks['reference_choice_only_in_request_copy']='use_previous_reference' in request.func_tool.tools[0].parameters['required'] and 'use_previous_reference' not in definition.parameters['properties']
    with TemporaryDirectory(dir='/AstrBot/data',prefix='followup-unit-') as directory:
        root=Path(directory);image=root/'source.png';image.write_bytes(raw.getvalue())
        r=router();turn=r.context('G').image_turn;turn['paths']=[str(image)];turn['reference_count']=1
        extras={'qq_available_image_turn':turn};event=SimpleNamespace(get_extra=lambda k:extras.get(k),set_extra=lambda k,v:extras.update({k:v}),message_obj=SimpleNamespace(message=[]))
        probe=SimpleNamespace(router=r,scoped_group=lambda _:'G')
        args={'use_previous_reference':True};select_previous_reference(probe,event,args)
        checks['model_selected_reference_restored_and_flag_removed']=not args and len(event.message_obj.message)==1 and extras['qq_current_image_turn'] is turn
        event.message_obj.message=[];select_previous_reference(probe,event,{'use_previous_reference':False})
        checks['new_image_can_decline_old_reference']=not event.message_obj.message
        try:select_previous_reference(probe,event,{});blocked=False
        except ValueError:blocked=True
        checks['missing_reference_choice_never_silently_generates']=blocked
        extras['qq_available_image_turn']={**turn}
        try:select_previous_reference(probe,event,{'use_previous_reference':True});blocked=False
        except ValueError:blocked=True
        checks['other_scope_reference_rejected']=blocked
        turn['reference_count']=2
        checks['partial_reference_never_used']=not restored_paths(turn)
        from astrbot.api.message_components import Image as ComponentImage
        component=ComponentImage(file=str(image),path=str(image))
        extras={};event=SimpleNamespace(get_extra=lambda k:extras.get(k),set_extra=lambda k,v:extras.update({k:v}),get_messages=lambda:[component],get_message_str=lambda:'改图',get_sender_id=lambda:'A',message_obj=SimpleNamespace(message_id='fixture'))
        probe.cache_path=root/'reply_context.json'
        await capture_turn(probe,event,SimpleNamespace())
        image.unlink()
        checks['reference_survives_original_temp_cleanup']=Path(r.context('G').image_turn['paths'][0]).read_bytes()==raw.getvalue()
        import os,time
        old=root/('a'*64+'.png');old.write_bytes(raw.getvalue());os.utime(old,(time.time()-200000,time.time()-200000))
        other=root/'user-file.png';other.write_bytes(raw.getvalue());os.utime(other,(time.time()-200000,time.time()-200000))
        prune_cache(root,7200)
        checks['cache_cleanup_only_removes_owned_expired_files']=not old.exists() and other.exists()
    if plugin is not None:
        from astrbot.core.agent.tool import FunctionTool
        from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
        from .image_tool_compat import IMAGE_GUARD_ERROR
        calls=[];sends=[]
        async def original_handler(event,prompt):
            calls.append(prompt)
            return 'fixture: no real image generation'
        definition=FunctionTool(name='generate_image',description='fixture',parameters={'type':'object','properties':{'prompt':{'type':'string'}},'required':['prompt']},handler=original_handler)
        request=SimpleNamespace(func_tool=SimpleNamespace(tools=[definition]))
        prepare_chat_image_tools(request,contextual_reference=True,model_notice=True)
        guarded=request.func_tool.tools[0]
        probe=object.__new__(type(plugin));probe.context=plugin.context
        probe.config={'image_pending_notice':{'enabled':True,'model_generated':True}}
        probe.router=router()
        turn=probe.router.context('G').image_turn;turn['status']='sent'
        extras={'qq_diagnostic':True,'qq_available_image_turn':turn,'qq_current_image_turn':turn}
        async def no_send(*args):sends.append(True)
        event=SimpleNamespace(get_extra=lambda k,default=None:extras.get(k,default),set_extra=lambda k,v:extras.update({k:v}),get_group_id=lambda:'G',get_sender_id=lambda:'A',get_self_id=lambda:'bot',is_stopped=lambda:False,is_private_chat=lambda:False,send=no_send,message_obj=SimpleNamespace(message_id='native-guard-fixture',message=[]))
        context=SimpleNamespace(context=SimpleNamespace(event=event),tool_call_timeout=5)
        args={'prompt':'fixture','pending_message':'不应发送的对白'}
        await probe.normalize_image_arguments(event,guarded,args)
        await probe.announce_image_generation(event,guarded,args)
        output=[r async for r in FunctionToolExecutor.execute(guarded,context,**args)]
        checks['executor_blocks_missing_choice_without_image_call']=not calls and any('本次未调用图片模型' in c.text for r in output if r for c in r.content)
        checks['blocked_call_skips_notice_and_model_fallback']=not sends and not extras.get('qq_notice_model_calls') and not extras.get('qq_image_pending_notice_attempted')
        checks['blocked_call_does_not_increment_execution_count']=not extras.get('qq_image_tools_started')
        checks['blocked_call_preserves_previous_task_state']=turn['status']=='sent'
        extras['qq_diagnostic']=False
        await probe.track_image_tool_result(event,guarded,args,output[0])
        checks['blocked_result_preserves_previous_success_state']=turn['status']=='sent'
        extras['qq_diagnostic']=True
        checks['original_registered_handler_unchanged']=definition.handler is original_handler and IMAGE_GUARD_ERROR not in definition.parameters['properties']
        args={'prompt':'valid new image','use_previous_reference':False}
        await probe.normalize_image_arguments(event,guarded,args)
        output=[r async for r in FunctionToolExecutor.execute(guarded,context,**args)]
        checks['executor_allows_explicit_new_image_choice']=calls==['valid new image'] and extras.get('qq_image_tools_started')==1 and not args.get(IMAGE_GUARD_ERROR)
        # Exercise the native runner, not only direct executor calls. In the
        # real incident the tool reaching the hook still had its raw handler.
        from astrbot.core.agent.tool import ToolSet
        from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
        from astrbot.core.provider.entites import ProviderRequest,LLMResponse
        raw_tool=FunctionTool(name='generate_image',description='fixture',parameters={'type':'object','properties':{'prompt':{'type':'string'}},'required':['prompt']},handler=original_handler)
        request=ProviderRequest(func_tool=ToolSet(tools=[raw_tool]))
        runner=ToolLoopAgentRunner()
        async def start(context,tool,args):
            await probe.normalize_image_arguments(context.context.event,tool,args)
            await probe.announce_image_generation(context.context.event,tool,args)
        async def end(context,tool,args,result):
            extras['qq_diagnostic']=False
            try:await probe.track_image_tool_result(context.context.event,tool,args,result)
            finally:extras['qq_diagnostic']=True
        context.messages=[]
        await runner.reset(provider=SimpleNamespace(provider_config={'id':'fixture'}),request=request,run_context=context,tool_executor=FunctionToolExecutor,agent_hooks=SimpleNamespace(on_tool_start=start,on_tool_end=end))
        before_calls=len(calls)
        response=LLMResponse(role='assistant',tools_call_name=['generate_image'],tools_call_args=[{'prompt':'must be blocked'}],tools_call_ids=['fixture-missing-choice'])
        results=[r async for r in runner._handle_function_tools(request,response)]
        checks['native_runner_blocks_unwrapped_handler']=len(calls)==before_calls and any('本次未调用图片模型' in str(block.content) for r in results for block in r.tool_call_result_blocks or [])
        checks['native_original_args_preserve_previous_task_state']=turn['status']=='sent'
        checks['native_runner_installs_execution_guard']=getattr(raw_tool.handler,'_qq_image_guarded',False)
        probe.image_execution_guard.restore()
        checks['runtime_guard_is_reversible']=raw_tool.handler is original_handler
    return {'passed':all(checks.values()),'checks':checks,'model_calls':0,'image_generations':0,'qq_messages_sent':0}
