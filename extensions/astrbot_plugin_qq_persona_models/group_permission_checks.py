"""Native permission and command checks; no sends or real group mutations."""
from copy import copy
import json
from uuid import uuid4


async def verify_group_permissions(plugin):
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage,MessageMember,Group
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.message.components import Plain
    class NoSendEvent(AstrMessageEvent):
        async def send(self,*args,**kwargs):raise AssertionError('No QQ sends in permission check')
    group=next(iter(plugin.router.settings['allowed_groups']))
    policy=plugin.context.get_registered_star('astrbot_plugin_user_policy').star_cls
    before=json.dumps(policy.store.config,ensure_ascii=False,sort_keys=True)
    def event(text='/群当前人格',user='1511659008',group_id=group,instance='qq-snowluma'):
        msg=AstrBotMessage();msg.type=MessageType.GROUP_MESSAGE
        msg.self_id='2354912009';msg.session_id=group_id;msg.group=Group(group_id=group_id)
        msg.sender=MessageMember(user_id=user,nickname='权限诊断')
        msg.message_id='permission-diagnostic-'+uuid4().hex
        msg.message_str=text;msg.message=[Plain(text=text)]
        msg.raw_message={'sender':{'role':'member'}}
        ev=NoSendEvent(text,msg,PlatformMetadata(name='aiocqhttp',description='isolated permission check',id=instance),group_id)
        ev.set_extra('qq_diagnostic',True)
        return ev
    current=event()
    decision=policy._get_or_create_decision(current)
    rule=policy._group_rule_for_event(current)
    baseline=plugin.group_permission_adapter.originals['_can_use_query_command'](policy,current,decision)
    query=[r.get_plain_text() async for r in policy.current_group_persona_command(current)]
    probe=copy(policy);attempts=[]
    async def capture_set(group_id,persona_id,mode):attempts.append((group_id,persona_id,mode))
    probe._set_group_persona=capture_set
    result=[r.get_plain_text() async for r in probe.switch_group_persona_command(event('/群切换人格 ChatGPT龙娘'))]
    checks={
        'saved_group_admin_found':'1511659008' in rule.get('policy_admins',[]),
        'native_query_bug_reproduced':not baseline,
        'group_admin_query_allowed':policy._can_use_query_command(current,decision),
        'native_query_command_returns_persona':any('当前群默认人格：' in text for text in query),
        'group_admin_manage_allowed':await policy._can_manage_group(current),
        'switch_command_reaches_exact_group_rule':attempts==[('qq-snowluma:'+group,'ChatGPT龙娘','fixed')],
        'switch_command_reports_success':any('已切换为' in text for text in result),
        'group_admin_is_not_global_admin':not current.is_admin(),
    }
    for label,ev in [('ordinary_member',event(user='permission-unlisted-member')),('other_group',event(group_id='unallowed-group')),('other_instance',event(instance='other-bot'))]:
        d=policy._get_or_create_decision(ev)
        checks[label+'_cannot_manage']=not await policy._can_manage_group(ev)
        checks[label+'_query_not_newly_granted']=policy._can_use_query_command(ev,d)==plugin.group_permission_adapter.originals['_can_use_query_command'](policy,ev,d)
    checks['real_policy_unchanged']=before==json.dumps(policy.store.config,ensure_ascii=False,sort_keys=True)
    return {'checks':checks,'passed':all(checks.values()),'query_result':query,'switch_result':result,'real_group_changes':0,'qq_messages_sent':0,'model_calls':0}
