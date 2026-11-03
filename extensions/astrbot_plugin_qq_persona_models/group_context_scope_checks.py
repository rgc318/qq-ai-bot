"""Read-only native policy checks; no history reads, writes, model or QQ calls."""


def verify_group_context_scopes(plugin):
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember, Group
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.api.message_components import Plain
    policy = plugin.context.get_registered_star('astrbot_plugin_user_policy').star_cls
    checks = {}
    for group in plugin.router.settings.get('allowed_groups', []):
        raw = AstrBotMessage()
        raw.type = MessageType.GROUP_MESSAGE;raw.self_id = 'scope-fixture-bot'
        raw.session_id = str(group);raw.group = Group(group_id=str(group), group_name='scope fixture')
        raw.message_id = 'scope-diagnostic';raw.sender = MessageMember(user_id='scope-fixture-user', nickname='scope fixture')
        raw.message_str = 'scope fixture';raw.message = [Plain(text=raw.message_str)];raw.raw_message = {}
        class Event(AstrMessageEvent):
            async def send(self, *args, **kwargs):raise AssertionError('No sends in scope diagnostics')
        event = Event(raw.message_str, raw, PlatformMetadata(name='aiocqhttp', description='fixture', id='qq-snowluma'), str(group))
        decision = policy._decision_for_event(event)
        event.set_extra('user_policy_decision', decision)
        event.set_extra('user_policy_effective_persona_id', decision.persona_id)
        owner = plugin.attachment_identity(event)
        history = plugin.chat_history_identity(event)
        configured = decision.policy_configured and decision.memory_isolation and not decision.is_blocked
        checks[str(group) + '_native_policy_scope_matches'] = bool(owner) == bool(configured)
        checks[str(group) + '_history_scope_matches'] = bool(history) == bool(configured)
        if configured:
            namespace, _ = policy.memory_isolation._scope(decision)
            from .chat_history_store import scope_id
            checks[str(group) + '_existing_native_namespace_preserved'] = owner['scope'] == scope_id(namespace, decision.persona_id)
    return {'passed': bool(checks) and all(checks.values()), 'checks': checks,
            'model_calls': 0, 'qq_messages_sent': 0, 'history_writes': 0}
