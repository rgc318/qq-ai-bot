"""Request-local evidence and one bounded correction, never a separate judge.

The model declares dependencies; code validates access/delivery, not semantics.
Missing declarations are observable, not evidence that an ordinary reply failed.
"""
from copy import copy
from functools import wraps
import json
import re
import time

OPEN = '[[QQ_TASK_STATE]]'
CLOSE = '[[/QQ_TASK_STATE]]'
KEY = 'qq_task_evidence'
IMAGES = {'generate_image', 'generate_selfie'}
READERS = {'view_context_images', 'read_context_document', 'read_group_message', 'browse_group_history'}
FOOTER = re.compile(re.escape(OPEN) + r'(.*?)' + re.escape(CLOSE), re.S)


def split_state(text):
    """Remove private metadata even when malformed; never parse chat input."""
    text = text or ''
    matches = list(FOOTER.finditer(text))
    present = OPEN in text
    clean = FOOTER.sub('', text)
    # A truncated footer must not escape to QQ, nor become a normal answer.
    if OPEN in clean:clean = clean.split(OPEN, 1)[0]
    if not present:return clean.strip(), None, ''
    if len(matches) != 1:return clean.strip(), None, 'invalid_task_state'
    raw = matches[0].group(1)
    try:
        if len(raw) > 4096:raise ValueError()
        state = json.loads(raw)
        if not isinstance(state, dict):raise ValueError()
        if state.get('status') not in ('answered', 'completed', 'blocked', 'needs_input', 'working'):raise ValueError()
        for key in ('image_ids', 'document_ids', 'actions'):
            ids = state.get(key, [])
            if not isinstance(ids, list) or len(ids) > 16 or any(not isinstance(i, str) or len(i) > 160 for i in ids):raise ValueError()
        return clean.strip(), state, ''
    except (ValueError, TypeError):return clean.strip(), None, 'invalid_task_state'


def known_images(event):
    mapping = event.get_extra('qq_ca_source_map') or {}
    snapshot = event.get_extra('qq_attachment_snapshot') or {}
    if event.get_extra('qq_context_backend') == 'contextaware':return set(mapping)
    return {r['id'] for r in snapshot.get('catalog', []) if r.get('type') == 'image'}


def provided_images(event, request):
    mapping = event.get_extra('qq_ca_source_map') or {}
    reverse = {v:k for k,v in mapping.items()}
    snapshot = event.get_extra('qq_attachment_snapshot') or {}
    current = set(event.get_extra('qq_attachment_current_ids') or []) if getattr(request, 'image_urls', None) else set()
    current &= {r['id'] for r in snapshot.get('catalog', []) if r.get('type') == 'image' and r.get('state') == 'ready'}
    provided=set(event.get_extra('qq_initial_image_ids') or []) | {reverse.get(i, i) for i in current}
    return provided | {alias for alias,source in (event.get_extra('qq_image_pixel_aliases') or {}).items() if source in provided}


def attach_evidence(event, request, settings):
    """Only enabled native non-stream requests receive the private contract."""
    if not settings.get('enabled', True) or not event.get_extra('qq_attachment_snapshot'):return False
    if getattr(request, 'streaming', False):return False
    state = event.get_extra(KEY)
    if state is not None:return True
    tools = set(request.func_tool.names()) if getattr(request, 'func_tool', None) else set()
    if not tools.intersection(READERS | IMAGES):return False
    provided = provided_images(event, request)
    state = {'provided':provided, 'viewed':set(), 'documents':set(), 'tools':{},
             'repairs':0, 'checks':0, 'last_code':'', 'declared':False,
             'message':str(event.message_obj.message_id), 'scope':event.get_extra('qq_reply_scope'),
             'snapshot':dict(event.get_extra('qq_attachment_snapshot')), 'started':time.monotonic()}
    event.set_extra(KEY, state)
    directory = {'provided_image_ids':sorted(provided),
                 'catalog_only_image_ids':sorted(known_images(event) - provided),
                 'meaning':'provided 表示本轮已提供视觉输入，不表示保证理解正确；catalog_only 仅有索引，需按需读取。'}
    request.system_prompt = (request.system_prompt or '') + '\n[本轮资料可见状态，仅作执行证据]\n' + json.dumps(directory, ensure_ascii=False, separators=(',', ':'))
    request.system_prompt += ('\n[任务状态协议]\n普通闲聊不用附加状态。最终回答依赖图片/文件内容，或承诺执行工具任务时，'
        '在给用户的正文末尾附一个内部标记：' + OPEN + '{"status":"answered","image_ids":[],"document_ids":[],"actions":[]}' + CLOSE + '。'
        '标记由程序移除，不是用户文案。image_ids 填本次回答实际依赖的可见图片ID；document_ids 填实际读取的文件ID；'
        'actions 填本轮实际执行的工具名，不把计划当执行。status 可为 answered（已回答）、completed（已执行交付）、'
        'blocked（失败或不可用）、needs_input（资料歧义需要澄清）、working（确有已确认后台任务）。'
        'blocked/needs_input 不声称看过缺失资料，依赖列表只填实际已获得的内容。'
        '缺少像素时先用读图工具，不要仅凭来源文字编造。仅工具调用时无需标记；不能以 working 代替工具执行。\n')
    return True


def observe_result(event, name, result):
    state = event.get_extra(KEY)
    if not state:return
    error = bool(getattr(result, 'isError', False))
    state['tools'][name] = 'failed' if error else 'returned' if result is not None else 'unconfirmed'


def validate_state(event, declared):
    state = event.get_extra(KEY)
    if not state or declared is None:return ''
    visible = state['provided'] | state['viewed']
    if set(declared.get('image_ids', [])) - visible:return 'image_pixels_not_provided'
    if set(declared.get('document_ids', [])) - state['documents']:return 'document_not_read'
    actions = set(declared.get('actions', []))
    accepted = {'returned', 'failed', 'unconfirmed'} if declared['status'] == 'blocked' else {'returned'}
    if any(state['tools'].get(name) not in accepted for name in actions):return 'action_not_confirmed'
    if declared['status'] == 'completed' and not actions:return 'completion_action_missing'
    if declared['status'] == 'working':return 'background_task_not_registered'
    if declared['status'] == 'completed' and actions & IMAGES:
        report = event.get_extra('qq_image_batch_report') or {}
        if report:
            if not report.get('items') or any(i.get('status') != 'sent' for i in report['items']):return 'image_delivery_not_confirmed'
        elif not int(event.get_extra('qq_generated_attachment_sends') or 0):return 'image_delivery_not_confirmed'
    return ''


def clean_response(response):
    """Preserve rich media, remove the internal footer from all Plain text."""
    chain = getattr(response, 'result_chain', None)
    plain = [p for p in getattr(chain, 'chain', []) if type(p).__name__ == 'Plain'] if chain else []
    original = getattr(response, 'completion_text', '') or ''.join(p.text for p in plain)
    text, declared, code = split_state(original)
    response.completion_text = text
    if OPEN in original and plain:
        plain[0].text = text
        for part in plain[1:]:part.text = ''
    return declared, code


class TaskEvidenceGuard:
    def __init__(self, plugin):self.plugin = plugin;self.patch = None

    def attach(self, event, request):
        settings = self.plugin.config.get('task_completion', {})
        # QQ currently uses non-stream generation. Streaming cannot retract text.
        if self.plugin.context.get_config(umo=event.unified_msg_origin).get('provider_settings', {}).get('streaming_response', False):return False
        return attach_evidence(event, request, settings)

    def emit(self, event, code, **extra):
        from .model_logging import event_trace
        logger = getattr(self.plugin, 'model_activity', None)
        if logger:logger.emit('task_evidence_check', **event_trace(event), validation_code=code, **extra)

    def install(self):
        if self.patch:return
        from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
        owner = ToolLoopAgentRunner;original = owner._iter_llm_responses_with_fallback
        @wraps(original)
        async def wrapped(runner, *args, **kwargs):
            event = getattr(getattr(getattr(runner, 'run_context', None), 'context', None), 'event', None)
            state = event.get_extra(KEY) if event else None
            if not state or getattr(runner, 'streaming', True):
                iterator = original(runner, *args, **kwargs)
                try:
                    async for response in iterator:yield response
                finally:await iterator.aclose()
                return
            while True:
                iterator = original(runner, *args, **kwargs)
                response = None
                try:
                    async for candidate in iterator:
                        if getattr(candidate, 'is_chunk', False):yield candidate
                        else:response = candidate;break
                finally:await iterator.aclose()
                if response is None:return
                if getattr(response, 'role', '') == 'err':yield response;return
                if getattr(response, 'tools_call_name', None):
                    clean_response(response);yield response;return
                declared, code = clean_response(response)
                if state['repairs'] and declared is None:code = code or 'missing_correction_state'
                state['checks'] += 1;state['declared'] = declared is not None
                state['task_status'] = declared.get('status') if declared else 'unreported'
                code = code or validate_state(event, declared)
                rich = any(type(part).__name__ != 'Plain' for part in getattr(getattr(response,'result_chain',None),'chain',[]) or [])
                if not response.completion_text.strip() and not rich:code = code or 'empty_user_reply'
                state['last_code'] = code
                self.emit(event, code or ('ok' if declared else 'not_declared'), repair_attempts=state['repairs'],
                          task_status=declared.get('status') if declared else 'unknown',
                          provided_source_count=len(state['provided']), viewed_source_count=len(state['viewed']))
                if not code:yield response;return
                maximum = getattr(runner, '_step_budget_max', None)
                budget = maximum is None or getattr(runner, '_step_budget_used', 0) < maximum
                safe = (event.get_extra(KEY) is state and str(event.message_obj.message_id) == state['message']
                        and event.get_extra('qq_reply_scope') == state['scope'] and not runner._is_stop_requested())
                runtime = getattr(self.plugin, 'attachments', None)
                snapshot = state['snapshot']
                if runtime and snapshot.get('scope'):
                    safe = safe and runtime.store.epoch(snapshot['scope']) == snapshot['epoch']
                if not safe:
                    runner.request_stop()
                    self.emit(event,'correction_aborted',repair_attempts=state['repairs'],outcome='context_changed_or_cancelled')
                    return
                if state['repairs'] or not budget:
                    # Do not pass an objectively contradicted completion to QQ.
                    response.result_chain = None
                    response.completion_text = '这次的资料读取或执行结果尚未确认，任务没有完整完成。请稍后再试，或说明需要继续处理哪一项。'
                    self.emit(event, 'correction_exhausted', repair_attempts=state['repairs'], outcome='incomplete')
                    event.set_extra('qq_task_incomplete', True)
                    state['task_status'] = 'incomplete'
                    yield response;return
                state['repairs'] = 1
                # Bill the discarded call, but keep occupancy tied to the
                # next actual request rather than summing two input windows.
                if getattr(response,'usage',None) is not None:runner.stats.token_usage += response.usage
                if maximum is not None:runner._step_budget_used += 1
                # Successful image deliveries are never repeated during correction.
                if int(event.get_extra('qq_generated_attachment_sends') or 0):
                    tools = getattr(runner.req, 'func_tool', None)
                    if tools:
                        restricted = copy(tools);restricted.tools = [t for t in tools.tools if t.name not in IMAGES]
                        runner.req.func_tool = restricted
                from astrbot.core.agent.message import Message, TextPart
                facts = {'failure':code, 'provided_image_ids':sorted(state['provided'] | state['viewed']),
                         'read_document_ids':sorted(state['documents']), 'tools':dict(state['tools']),
                         'delivered_images':int(event.get_extra('qq_generated_attachment_sends') or 0)}
                feedback = ('[本地任务证据核对，仅一次纠正]\n' + json.dumps(facts, ensure_ascii=False, separators=(',', ':')) +
                    '\n上一条未发送。沿用原用户任务与权限，缺少资料可按现有工具读取；失败则如实说明或澄清。'
                    '已发送的图片不能再生成。不要声称后台仍在运行。最终仍按任务状态协议回答。')
                runner.run_context.messages.append(Message(role='user', content=[TextPart(text=feedback).mark_as_temp()]))
                self.emit(event, 'correction_started', repair_attempts=1, outcome='same_agent_retry')
        owner._iter_llm_responses_with_fallback = wrapped;self.patch = (owner, original, wrapped)

    def restore(self):
        if self.patch:
            owner, original, wrapped = self.patch
            if owner._iter_llm_responses_with_fallback is wrapped:owner._iter_llm_responses_with_fallback = original
            self.patch = None
