"""Operator-only recovery of named QQ messages into their existing native scope.

No model calls, agent pipeline execution, sends, or automatic history scraping.
Only metadata is returned. Original timestamps/TTL are retained.
"""
import asyncio
import math
import time


async def native_event(platform, message, group):
    from aiocqhttp import Event
    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
    if not isinstance(message.get('message'), list):raise ValueError('原消息不是支持的消息段格式')
    converted = await platform._convert_handle_message_event(Event.from_payload(message), get_reply=False)
    return AiocqhttpMessageEvent(converted.message_str, converted, platform.meta(), group, platform.bot)


async def restore_group_messages(plugin, payload):
    group = str(payload.get('group_id', ''))
    ids = payload.get('message_ids')
    if group not in plugin.router.settings.get('allowed_groups', []):raise ValueError('群不在允许范围')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 5 or any(type(mid) is not int for mid in ids) or len(set(ids)) != len(ids):
        raise ValueError('需要1到5个互不重复的整数消息ID')
    runtime = plugin.attachments
    state = runtime.status()
    if state['active_requests'] or state['pending_messages'] or state['switching'] or plugin.model_activity.active:
        raise RuntimeError('当前仍有消息或模型任务，请空闲后恢复')
    if not runtime.enabled():raise ValueError('附件上下文未启用')
    platform = next((p for p in plugin.context.platform_manager.get_insts() if p.meta().id == 'qq-snowluma'), None)
    if platform is None:raise RuntimeError('QQ平台未就绪')
    policy = plugin.context.get_registered_star('astrbot_plugin_user_policy').star_cls
    login = await asyncio.wait_for(platform.bot.call_action('get_login_info'), timeout=8)
    self_id = int(login['user_id'])
    prepared = []
    now = time.time()
    lookback = min(float(runtime.settings.get('media_ttl_seconds', 86400)), float(runtime.settings.get('message_ttl_seconds', 604800)))
    # Read and authorize every requested source before writing any repaired rows.
    for mid in ids:
        original = await asyncio.wait_for(platform.bot.call_action('get_msg', message_id=mid, self_id=self_id), timeout=8)
        if str(original.get('group_id')) != group:raise ValueError('原消息不属于指定群')
        timestamp = float(original.get('time', 0))
        if not math.isfinite(timestamp) or timestamp <= 0 or timestamp > now + 60 or now - timestamp > lookback:
            raise ValueError('原消息时间无效或已超过当前保存期')
        if int(original.get('message_id', 0)) != mid:raise ValueError('返回的原消息ID不匹配')
        raw = {**original, 'self_id': self_id, 'post_type': 'message', 'message_type': 'group', 'sub_type': original.get('sub_type', 'normal')}
        event = await native_event(platform, raw, group)
        decision = policy._decision_for_event(event)
        event.set_extra('user_policy_decision', decision)
        event.set_extra('user_policy_effective_persona_id', decision.persona_id)
        event.plugins_name = None
        owner = plugin.attachment_identity(event)
        permission = policy.matcher.check_plugin_access(decision, 'astrbot_plugin_qq_persona_models')
        if not owner or not decision.persona_id or not permission.allowed:
            raise ValueError('原消息的群、成员、人格或插件策略不允许恢复')
        prepared.append((timestamp, event, owner))
    archive = runtime.archive
    results = []
    for timestamp, event, owner in sorted(prepared, key=lambda row: (row[0], int(row[1].message_obj.message_id))):
        existing = await asyncio.to_thread(archive.store.messages, archive.store.snapshot(owner['scope']), message_id=str(event.message_obj.message_id))
        if existing:
            assets = existing[0]['attachments']
            results.append({'message_id': str(event.message_obj.message_id), 'already_present': True,
                            'attachments': len(assets),
                            'ready_images': sum(row['type'] == 'image' and row['state'] == 'ready' for row in assets),
                            'unavailable': sum(row['state'] != 'ready' for row in assets)})
            continue
        generated = str(event.get_sender_id()) == str(self_id)
        parts = archive.descriptors(event, generated=generated)
        record = await asyncio.to_thread(archive.store.record, owner['scope'], event.unified_msg_origin,
            str(event.message_obj.message_id), str(event.get_sender_id()), event.get_sender_name(),
            event.get_message_str(), parts, 'assistant' if generated else 'user',
            expected_epoch=archive.store.epoch(owner['scope']), received_at=timestamp)
        for asset_id in record['ids']:
            await archive.materialize(record, asset_id)
        rows = [archive.store.source(record['scope'], record['epoch'], aid) for aid in record['ids']]
        results.append({'message_id': str(event.message_obj.message_id), 'original_time_preserved': all(row['created'] == timestamp for row in rows),
                        'attachments': len(rows), 'ready_images': sum(row['kind'] == 'image' and row['state'] == 'ready' for row in rows),
                        'unavailable': sum(row['state'] != 'ready' for row in rows)})
    return {'messages': results, 'model_calls': 0, 'qq_messages_sent': 0,
            'conversation_history_changed': False, 'source': 'qq_original_messages',
            'passed': all(not row.get('unavailable', 0) for row in results)}
