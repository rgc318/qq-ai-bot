"""Synthetic dialogue decisions plus real persona responses; never QQ sends."""
import json
import time
from types import SimpleNamespace
from uuid import uuid4
from .reply_routing import ReplyRouter


async def verify_dialogue_cases(plugin,call_model=False,only=None):
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage,MessageMember,Group
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.api.message_components import Plain
    from astrbot.api.provider import ProviderRequest
    class NoSendEvent(AstrMessageEvent):
        async def send(self,*args,**kwargs):raise AssertionError('No sends in dialogue checks')
    group=next(iter(plugin.router.settings['allowed_groups']))
    policy=plugin.context.get_registered_star('astrbot_plugin_user_policy').star_cls
    before=json.dumps(policy.store.config,sort_keys=True,ensure_ascii=False)
    cases=[
        {'name':'call_without_task','history':[('1511659008','甲','ChatGPT大人'),('1511659008','甲','在吗')],'text':'wake up','reply':True,'generate':True},
        {'name':'multi_member_planning','history':[('test-A','甲','龙娘，请帮我们安排周日的活动'),('test-A','甲','我14点以后才有空'),('test-B','乙','我15点之前必须离开'),('test-C','丙','我想去图书馆')],'text':'请结合甲乙丙三个人的条件，明确给出可用时间范围和地点。','reply':True,'generate':True},
        {'name':'human_wakeup_not_bot','history':[('test-X','路人','ChatGPT这个名字挺流行'),('test-A','甲','小张，明早我叫你起床'),('test-B','小张','我现在还在睡，甲你叫我吧')],'text':'小张，wake up','reply':False},
        {'name':'answer_ai_question','history':[],'text':'好的','reply':True,'question':'按周日14点到15点安排图书馆活动，可以吗？'},
        {'name':'explicit_no_reply','history':[('test-A','甲','我们在和龙娘说话')],'text':'龙娘，这条不用回复，我只是记一下。','reply':False},
    ]
    results=[];checks={};model_calls=0
    if only is not None:
        if not isinstance(only,list) or not only or not set(only).issubset({c['name'] for c in cases}):raise ValueError('Unknown dialogue cases')
        cases=[case for case in cases if case['name'] in only]
    for case in cases:
        async def fake_judge(payload):return {'route':'addressed' if case['reply'] else 'ambient','recipient':'bot' if case['reply'] else 'human','silence_requested':case['name']=='explicit_no_reply','confidence':0.99}
        probe=object.__new__(type(plugin));probe.context=plugin.context;probe.config=plugin.config
        probe.router=ReplyRouter(dict(plugin.router.settings),plugin.judge_reply if call_model else fake_judge)
        probe.chat_history_store=None
        msg=AstrBotMessage();msg.type=MessageType.GROUP_MESSAGE;msg.self_id='2354912009';msg.session_id=group
        msg.group=Group(group_id=group);msg.sender=MessageMember(user_id='1511659008',nickname='对话验收')
        msg.message_id='dialogue-diagnostic-'+uuid4().hex;msg.message_str=case['text'];msg.message=[Plain(text=case['text'])];msg.raw_message={'sender':{'role':'member'}}
        event=NoSendEvent(case['text'],msg,PlatformMetadata(name='aiocqhttp',description='isolated dialogue check',id='qq-snowluma'),group)
        event.set_extra('qq_diagnostic',True)
        decision=policy._get_or_create_decision(event)
        event.set_extra('user_policy_effective_persona_id',decision.persona_id)
        ctx=probe.router.context(group);ctx.scope=policy.memory_isolation._scope(decision)[0]+'|'+decision.persona_id;ctx.hydration_attempted=True
        for i,(sender,name,text) in enumerate(case['history']):
            ctx.messages.append({'role':'user','sender':sender,'name':name,'text':text,'message_id':'fixture-'+str(i),'time':probe.router.clock()-10+i})
        if case.get('question'):probe.router.note_ai(group,case['question'],sender='1511659008')
        await probe.route_contextual_request(event)
        allowed=bool(event.is_at_or_wake_command)
        checks[case['name']]=allowed==case['reply']
        verdict=event.get_extra('qq_semantic_decision') or {}
        entry={'name':case['name'],'allowed':allowed,'passed':checks[case['name']],'route':verdict.get('route'),'reason':verdict.get('reason'),'judge_seconds':verdict.get('judge_seconds',0)}
        if call_model and verdict.get('judged'):model_calls+=1
        if allowed and case.get('generate'):
            persona=await plugin.context.persona_manager.get_persona(decision.persona_id)
            req=ProviderRequest(prompt=case['text'],contexts=[],system_prompt=persona.system_prompt,func_tool=None)
            req.conversation=SimpleNamespace(cid='synthetic-dialogue-only',persona_id=decision.persona_id)
            await probe.attach_reference_and_track_request(event,req)
            rows=event.get_extra('qq_dialogue_snapshot')['rows']
            checks[case['name']+'_snapshot_attached']=bool(event.get_extra('qq_dialogue_context_attached'))
            if case['name']=='multi_member_planning':checks['all_three_speakers_preserved']={'test-A','test-B','test-C'}.issubset({r['speaker_id'] for r in rows})
            if call_model:
                provider=plugin.context.get_provider_by_id(plugin.config['bindings'][decision.persona_id])
                started=time.monotonic()
                response=await provider.text_chat(prompt=req.prompt,system_prompt=req.system_prompt,contexts=req.contexts,func_tool=None)
                model_calls+=1;text=response.completion_text or ''
                checks[case['name']+'_main_response']=bool(text.strip()) if case['name']=='call_without_task' else all(word in text for word in ('14','15','图书馆'))
                entry.update(persona=decision.persona_id,model=provider.get_model(),response=text,snapshot_rows=len(rows),main_model_seconds=round(time.monotonic()-started,3))
            # A stale ingress snapshot must not cross either persona or group
            # policy namespace boundaries before final request construction.
            for label,bad_scope in [('persona',ctx.scope.rsplit('|',1)[0]+'|other-persona'),('namespace','other-group|'+decision.persona_id)]:
                event.set_extra('qq_dialogue_context_attached',False)
                event.set_extra('qq_dialogue_snapshot',{'scope':bad_scope,'rows':rows})
                isolated_req=ProviderRequest(prompt=case['text'],contexts=[],system_prompt=persona.system_prompt,func_tool=None)
                await probe.attach_reference_and_track_request(event,isolated_req)
                checks[case['name']+'_'+label+'_isolation']=not event.get_extra('qq_dialogue_context_attached')
        results.append(entry)
    checks['real_group_policy_unchanged']=before==json.dumps(policy.store.config,sort_keys=True,ensure_ascii=False)
    return {'passed':all(checks.values()),'checks':checks,'cases':results,'model_calls':model_calls,'qq_messages_sent':0,'production_conversation_writes':0}
