"""Scoped history checks in an isolated temporary database; never QQ sends."""
from copy import copy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from uuid import uuid4

from .chat_history_store import ChatHistoryStore
from .reply_routing import ReplyRouter


async def verify_history_switch(plugin):
    """Exercise disabled guards without changing live config or touching storage."""
    class UntouchableStore:
        def __getattr__(self,name):raise AssertionError('Disabled feature accessed storage: '+name)
    class ToolSet:
        def __init__(self):
            self.tools=[SimpleNamespace(name=n) for n in ('search_chat_history','read_chat_history','recall_long_term_memory','memorize_long_term_memory','generate_image')]
        def names(self):return [t.name for t in self.tools]
    probe=object.__new__(type(plugin));probe.config={**plugin.config,'history_recall':{'enabled':False}}
    probe.chat_history_store=UntouchableStore()
    extras={'qq_history_owner':{'scope':'synthetic'},'qq_history_catalog':'旧线索'}
    event=SimpleNamespace(get_extra=lambda k,default=None:extras.get(k,default),set_extra=lambda k,v:extras.update({k:v}))
    source=ToolSet();req=SimpleNamespace(func_tool=source,system_prompt='当前人格提示')
    probe.prepare_history_tools(req)
    await probe.capture_chat_history(event,req)
    probe.attach_history_catalog(event,req)
    search=json.loads(await probe.search_chat_history(event,'旧约定'))
    read=json.loads(await probe.read_chat_history(event,'h1'))
    checks={
        'disabled_hides_both_history_tools':not {'search_chat_history','read_chat_history'}.intersection(req.func_tool.names()),
        'memory_and_image_tools_preserved':{'recall_long_term_memory','memorize_long_term_memory','generate_image'}.issubset(req.func_tool.names()),
        'shared_tool_registry_unchanged':len(source.names())==5,
        'disabled_has_no_history_prompt':req.system_prompt=='当前人格提示',
        'disabled_search_and_read_denied':not search.get('count') and not read.get('found'),
        'disabled_capture_did_not_access_storage':True,
    }
    probe.config['history_recall']['enabled']=True
    req=SimpleNamespace(func_tool=source,system_prompt='当前人格提示')
    probe.prepare_history_tools(req);probe.attach_history_catalog(event,req)
    checks['enabled_keeps_history_tools']={'search_chat_history','read_chat_history'}.issubset(req.func_tool.names())
    checks['enabled_restores_topic_prompt']='旧线索' in req.system_prompt
    return {'passed':all(checks.values()),'checks':checks,'qq_messages_sent':0,'model_calls':0,'production_index_writes':0}


async def verify_history_recall(plugin,call_model=False,ordinary=False):
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage,MessageMember,Group
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.message.components import Plain
    from astrbot.core.message.message_event_result import MessageEventResult,ResultContentType
    class NoSendEvent(AstrMessageEvent):
        async def send(self,*args,**kwargs):raise AssertionError('No QQ sends in history checks')
    group=next(iter(plugin.router.settings['allowed_groups']))
    msg=AstrBotMessage();msg.type=MessageType.GROUP_MESSAGE
    msg.self_id='2354912009';msg.session_id=group
    msg.message_id='history-diagnostic-'+uuid4().hex
    msg.group=Group(group_id=group,group_name='检索诊断')
    msg.sender=MessageMember(user_id='1511659008',nickname='检索诊断')
    msg.message_str='晚上好，我今天吃饱了，来打个招呼。' if ordinary else '我之前那次社团活动约定的集合地点和确认暗号是什么？请查旧对话原文回答。'
    msg.message=[Plain(text=msg.message_str)];msg.raw_message={}
    event=NoSendEvent(msg.message_str,msg,PlatformMetadata(name='aiocqhttp',description='isolated history check',id='qq-snowluma'),group)
    event.is_wake=event.is_at_or_wake_command=True
    event.set_extra('qq_diagnostic',True);event.set_extra('qq_history_probe',True)
    policy=plugin.context.get_registered_star('astrbot_plugin_user_policy').star_cls
    async for _ in policy.apply_message_policy(event):pass
    decision=event.get_extra('user_policy_decision')
    probe=object.__new__(type(plugin));probe.context=plugin.context;probe.config=plugin.config
    probe.router=ReplyRouter(dict(plugin.router.settings),plugin.judge_reply)
    expected='纸鸢'+uuid4().hex[:10]
    with TemporaryDirectory(prefix='qq-history-check-',dir='/AstrBot/data/temp') as folder:
        probe.chat_history_store=ChatHistoryStore(Path(folder)/'history.db')
        owner=probe.chat_history_identity(event)
        if owner is None:
            return {'passed':False,'scope_diagnostic':{'group':event.get_group_id(),'sender':event.get_sender_id(),'stopped':event.is_stopped(),'private':event.is_private_chat(),'plugins':event.plugins_name,'persona':probe.routing_persona(event),'decision_present':decision is not None,'isolation':getattr(decision,'memory_isolation',None),'blocked':getattr(decision,'is_blocked',None),'identity':vars(decision.identity) if decision else None},'qq_messages_sent':0,'production_index_writes':0}
        persona=owner['persona']
        old={**owner,'cid':'diagnostic-old-conversation'}
        probe.chat_history_store.ingest(old,[{'role':'user','content':'社团活动约定的集合地点和确认暗号是什么？'},{'role':'assistant','content':'集合地点是北门图书馆，确认暗号是'+expected+'。'}],'synthetic_fixture')
        response=json.loads(await probe.search_chat_history(event,'社团 集合 暗号'))
        record=response['results'][0]['record_id']
        checks={'real_policy_scope_resolved':bool(owner),'search_finds_old_conversation':expected in json.dumps(response,ensure_ascii=False),'record_read_returns_original':expected in json.loads(await probe.read_chat_history(event,record))['text'],'digest_does_not_contain_answer':expected not in probe.chat_history_store.catalog(owner['scope'])}
        def other_event(persona_id=persona,other_group=group,sender='1511659008',member=False,blocked=False,private=False,plugins=None,isolation=True,instance='qq-snowluma'):
            identity=replace(decision.identity,user_id=sender,group_id=instance+':'+other_group)
            altered=replace(decision,identity=identity,persona_id=persona_id,is_blocked=blocked,memory_isolation=isolation,user_rule={'memory_isolation':True} if member else {})
            extras={'user_policy_decision':altered,'user_policy_effective_persona_id':persona_id}
            return SimpleNamespace(plugins_name=plugins,unified_msg_origin=instance+':GroupMessage:'+other_group,is_stopped=lambda:False,is_private_chat=lambda:private,get_group_id=lambda:other_group,get_sender_id=lambda:sender,get_self_id=lambda:'2354912009',get_extra=lambda k,default=None:extras.get(k,default))
        for name,other in [
            ('other_persona',other_event(persona_id='ChatGPT龙娘' if persona!='ChatGPT龙娘' else '大肥鱼')),
            ('other_group',other_event(other_group='unallowed-group')),
            ('other_instance',other_event(instance='other-bot')),
            ('member_override',other_event(sender='other-member',member=True)),
            ('blocked',other_event(blocked=True)),('private',other_event(private=True)),
            ('plugin_disallowed',other_event(plugins=['meme_manager'])),
            ('isolation_disabled',other_event(isolation=False))]:
            a=json.loads(await probe.search_chat_history(other,'确认暗号'))
            b=json.loads(await probe.read_chat_history(other,record))
            checks[name+'_cannot_read']=not a.get('count') and not b.get('found')
        shared=json.loads(await probe.search_chat_history(other_event(sender='another-public-member'),'社团 暗号'))
        checks['public_group_history_shared_with_group_member']=shared.get('count',0)>0
        report={'checks':checks,'passed':all(checks.values()),'qq_messages_sent':0,'production_index_writes':0,'model_calls':0}
        if call_model:
            from astrbot.core.pipeline.process_stage.method.agent_sub_stages.internal import InternalAgentSubStage
            from astrbot.core.pipeline.context import PipelineContext
            from astrbot.core.astr_main_agent import build_main_agent
            from astrbot.core.star.star_handler import EventType,star_handlers_registry
            from astrbot.core.astr_agent_hooks import MAIN_AGENT_HOOKS
            from mcp.types import CallToolResult,TextContent
            async def hooks(kind,*args):
                for h in star_handlers_registry.get_handlers_by_event_type(kind,plugins_name=event.plugins_name):
                    if 'qq_persona_models' in h.handler_full_name:continue
                    await h.handler(event,*args)
                    if kind==EventType.OnLLMRequestEvent and 'user_policy' in h.handler_full_name:
                        args[0].contexts=[]
            await hooks(EventType.OnWaitingLLMRequestEvent)
            stage=InternalAgentSubStage()
            await stage.initialize(PipelineContext(plugin.context.get_config(umo=event.unified_msg_origin),SimpleNamespace(context=plugin.context),'default'))
            built=await build_main_agent(event=event,plugin_context=plugin.context,config=replace(stage.main_agent_cfg,streaming_response=False),apply_reset=False,prepared_images={})
            if built is None:raise RuntimeError('Native agent not built')
            req=built.provider_request
            try:
                await hooks(EventType.OnLLMRequestEvent,req)
                req.contexts=[]
                req.conversation=SimpleNamespace(cid='diagnostic-new-conversation',persona_id=persona,token_usage=0)
                # Native tool definitions/permission wrappers; only history tools
                # are exposed in this focused test, execution uses temporary store.
                tools=copy(req.func_tool)
                tools.tools=[t for t in tools.tools if t.name in ('search_chat_history','read_chat_history')]
                req.func_tool=tools
                await probe.attach_reference_and_track_request(event,req)
                before=json.dumps(req.contexts,ensure_ascii=False)+(req.system_prompt or '')+(req.prompt or '')
                checks['answer_absent_from_current_context']=expected not in before
                checks['digest_attached']=bool(event.get_extra('qq_history_catalog_attached'))
                checks['new_conversation_differs_from_source']=req.conversation.cid!=old['cid']
                await built.reset_coro
            finally:
                if built.reset_coro:built.reset_coro.close()
            executed=[]
            class HistoryExecutor:
                async def execute(self,tool,run_context,**arguments):
                    executed.append(tool.name)
                    if tool.name not in ('search_chat_history','read_chat_history'):raise AssertionError('Unexpected tool')
                    text=await getattr(probe,tool.name)(event,**arguments)
                    yield CallToolResult(content=[TextContent(type='text',text=text)])
            async def noop(*args):pass
            runner=built.agent_runner;runner.tool_executor=HistoryExecutor()
            runner.agent_hooks=SimpleNamespace(on_agent_begin=noop,on_agent_done=noop,on_tool_start=MAIN_AGENT_HOOKS.on_tool_start,on_tool_end=noop)
            started=time.monotonic();steps=0
            import asyncio
            async with asyncio.timeout(90):
                while not runner.done() and steps<4:
                    async for _ in runner.step():pass
                    steps+=1
            final=getattr(runner.final_llm_resp,'completion_text','') or ''
            if ordinary:
                checks['ordinary_chat_does_not_retrieve']=not executed and bool(final)
            else:
                checks['model_called_history_search']='search_chat_history' in executed
                checks['model_recovered_old_fact']=expected in final and '北门图书馆' in final
            report.update(scenario='ordinary' if ordinary else 'recall',model=built.provider.get_model(),model_calls=steps,tool_calls=executed,seconds=round(time.monotonic()-started,2),recovered_synthetic_fact=checks.get('model_recovered_old_fact'),index_prepare_seconds=event.get_extra('qq_history_index_seconds'))
        # Verify post-send storage before the next request/reset can occur.
        event.set_extra('qq_history_owner',{**owner,'cid':'diagnostic-new-conversation'})
        event.set_extra('qq_diagnostic',False)
        event.set_result(MessageEventResult().message('新的原文查验值FRAME8921。').set_result_content_type(ResultContentType.LLM_RESULT))
        await probe.track_completed_reply(event)
        checks['sent_reply_saved_before_next_request']=probe.chat_history_store.search(owner['scope'],'FRAME8921')['count']>0
        report['passed']=all(checks.values())
        return report
