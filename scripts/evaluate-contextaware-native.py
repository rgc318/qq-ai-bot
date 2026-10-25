"""Native Core/ContextAware seam tests, run only in a network-disabled container.

Uses synthetic pixels/events and fake model/generator/sender. The upstream source
is integrity-locked. No credentials, live data volumes or OneBot connection.
"""
import ast
import asyncio
import base64
from copy import deepcopy
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import statistics
import sys
from tempfile import TemporaryDirectory
import time
from types import ModuleType, SimpleNamespace

ROOT = Path('/workspace')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, '/AstrBot')
from integrations.contextaware.adapter import CandidateBackend, DeliveredImage, OmniDrawBridge, request_tools


def load_candidate(root):
    lock = json.loads((ROOT/'integrations/contextaware/source-lock.json').read_text())
    for name, entry in lock['files'].items():
        raw = (root/name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry['sha256'], name+' source changed'
    package = ModuleType('qq_ca_candidate')
    package.__path__ = [str(root)]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(package.__name__+'.main', root/'main.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def native_omni_api(path):
    """Compile the installed public method unchanged; substitute only boundaries.

    The real method's permission, quota, cancellation and usage code executes.
    Data storage/generation are in-memory test doubles, not claimed as an
    integration test of OmniDraw's full pipeline or its provider SDK.
    """
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and
               any(getattr(m, 'name', '') == 'generate_images_for_plugin' for m in n.body))
    names = {'generate_images_for_plugin', '_validated_plugin_image_refs',
             '_as_plugin_image_refs', '_plugin_generation_mode'}
    selected = [n for n in cls.body if getattr(n, 'name', '') in names]
    new_class = ast.ClassDef(name='NativeOmni', bases=[], keywords=[], body=selected, decorator_list=[])
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), new_class], type_ignores=[])
    namespace = {'asyncio': asyncio, 'json': json, 're': __import__('re'),
                 'MAX_REFERENCE_IMAGES_PER_REQUEST': 14}
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    omni = namespace['NativeOmni']()
    omni.calls = []
    omni.permission = ''
    omni.quota = ''
    omni.reserved = omni.released = omni.finalized = 0
    omni._refresh_from_native_config_if_changed = lambda: None
    omni._normalize_count = int
    omni._permission_denied_message = lambda event: omni.permission
    def reserve(event, count):
        if omni.quota:
            return omni.quota, 0
        omni.reserved += count
        return '', count
    omni._reserve_image_quota = reserve
    omni._release_image_quota = lambda e, n: setattr(omni, 'released', omni.released+n)
    omni._finalize_image_quota = lambda e, n, actual: setattr(omni, 'finalized', omni.finalized+actual)
    omni._record_generated_images = lambda e, n: None
    omni._plugin_generation_response = lambda x: (x, x.get('images', []))
    return omni


async def main():
    from PIL import Image as PILImage
    from astrbot.api.message_components import Image, Plain, At
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember, Group
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.provider.entities import ProviderRequest, LLMResponse
    from astrbot.core.agent.tool import FunctionTool
    from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
    from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
    from extensions.astrbot_plugin_qq_persona_models.main import PersonaModelBindings

    ca = load_candidate(Path('/candidate'))
    checks = {}
    def check(name, value):
        checks[name] = bool(value)
        if not value:
            raise AssertionError(name)

    class Event(AstrMessageEvent):
        async def send(self, *args, **kwargs):
            raise AssertionError('Real platform sends forbidden')

    def event(mid, sender='A', text='', image=None, persona='whale', member=False, blocked=False):
        raw = AstrBotMessage()
        raw.type = MessageType.GROUP_MESSAGE
        raw.self_id = 'bot'
        raw.session_id = 'G'
        raw.group = Group(group_id='G', group_name='fixture')
        raw.message_id = mid
        raw.sender = MessageMember(user_id=sender, nickname=sender)
        raw.message_str = text
        raw.message = [Plain(text=text)]
        if image:
            raw.message.append(Image.fromFileSystem(str(image)))
        raw.raw_message = {}
        e = Event(text, raw, PlatformMetadata(name='aiocqhttp', description='isolated', id='fixture'), 'G')
        e.is_at_or_wake_command = bool(text)
        e.plugins_name = ['astrbot_plugin_qq_persona_models']
        e.set_extra('user_policy_effective_persona_id', persona)
        e.set_extra('user_policy_decision', SimpleNamespace(
            is_blocked=blocked, memory_isolation=True, member=member,
            identity=SimpleNamespace(is_private=False, group_id='fixture:G', user_id=sender),
        ))
        return e

    # Call the CURRENT identity method, rather than bypassing it with a fake scope.
    policy = SimpleNamespace(star_cls=SimpleNamespace(memory_isolation=SimpleNamespace(
        _scope=lambda decision: (
            ('fixture:G:'+decision.identity.user_id, 'member') if decision.member
            else ('fixture:G', 'group')
        )
    )))
    model = SimpleNamespace(provider_config={'id': 'synthetic', 'modalities': ['text', 'image', 'tool_use']})
    lookups = []
    def get_config(**kwargs):
        lookups.append(kwargs.get('umo'))
        return {'wake_prefix': []}
    context = SimpleNamespace(get_config=get_config, get_using_provider=lambda **kw: model,
                              get_registered_star=lambda name: policy if name == 'astrbot_plugin_user_policy' else None)
    probe = object.__new__(PersonaModelBindings)
    probe.context = context
    probe.router = SimpleNamespace(settings={'allowed_groups': ['G']})
    probe.routing_persona = lambda e: e.get_extra('user_policy_effective_persona_id')

    with TemporaryDirectory(dir='/AstrBot/data', prefix='ca-isolated-') as tmp:
        root = Path(tmp)
        def picture(name, color):
            path = root/name
            PILImage.new('RGB', (40, 30), color).save(path)
            return path
        front = picture('front.png', 'red')
        side = picture('side.png', 'blue')
        other = picture('third-member.png', 'green')
        output = picture('output.png', 'yellow').read_bytes()
        cfg = {'image_cache_dir': str(root/'ca-cache'), 'image_recall': True,
               'image_recall_auto': False, 'image_recall_max_per_request': 4,
               'image_caption': False, 'history_compress_strategy': 'off',
               'private_topic': {'enabled': False}, 'video_input': {'enabled': False},
               'llm_image_compress': {'enable': False}, 'show_sender_id': True,
               'image_recall_ttl': 86400, 'dialogue_window': 12, 'warn_builtin_ltm': False}
        backend = CandidateBackend(ca, context, cfg, probe.attachment_identity)
        try:
            if '--models' in sys.argv:
                from integrations.contextaware.semantic_fixture import evaluate
                await evaluate(backend, event, picture, context)
                return
            a = event('front', image=front)
            await backend.capture(a)
            front_id = backend.catalog(a)[0]['id']
            front_bytes = front.read_bytes()
            front.unlink()
            q = event('q', text='请生成三视图')
            await backend.capture(q)
            omni = native_omni_api(Path('/omnidraw.py'))
            async def generate(e, prompt, count, **kwargs):
                omni.calls.append({'event': e, 'refs': kwargs['refs'], 'prompt': prompt})
                return {'success': True, 'images': [{'data': output}]}
            omni._run_text2img_generation = generate
            omni._run_selfie_generation = generate
            deliveries = []
            async def send(e, image):
                deliveries.append((e.unified_msg_origin, image['data']))
                return DeliveredImage(image['data'], 'sent-fixture-'+str(len(deliveries)))
            class FixtureBridge(OmniDrawBridge):
                async def execute(self, e, **kw):
                    refs = kw.get('reference_ids')
                    if isinstance(refs, list) and 'reference_notes' not in kw:
                        kw['reference_notes'] = [{'image_id': i, 'purpose': '合成机械测试用途'} for i in refs]
                    return await super().execute(e, **kw)
            bridge = FixtureBridge(backend, omni, send)
            first = await bridge.execute(q, task_id='first', prompt='三视图', reference_ids=[front_id])
            check('successful_result_registered_after_send', len(first['registered_ids']) == 1 and len(deliveries) == 1)
            b = event('side', text='这是它侧面的图', image=side)
            await backend.capture(b)
            side_id = next(r['id'] for r in backend.catalog(b) if r['message_id'] == 'side')
            check('original_platform_route_unchanged', b.unified_msg_origin == 'fixture:GroupMessage:G')
            check('config_lookup_uses_real_platform_route', bool(lookups) and all(x == b.unified_msg_origin for x in lookups))
            check('front_and_side_both_available', {front_id, side_id}.issubset({r['id'] for r in backend.catalog(b)}))
            viewed = await backend.view_images(b, [front_id, side_id])
            check('both_original_pixels_available_after_event_cleanup', sum(p.type == 'image' for p in viewed.content) == 2)
            result = await bridge.execute(b, task_id='second', prompt='综合原正面与新侧面', reference_ids=[front_id, side_id])
            refs = omni.calls[-1]['refs']
            check('omni_public_api_receives_all_selected_original_bytes', [base64.b64decode(r.split(',', 1)[1]) for r in refs] == [front_bytes, side.read_bytes()])
            generated = backend.plugin._image_index.get(backend.scoped(b).unified_msg_origin, result['registered_ids'][0])
            check('registered_result_keeps_exact_parents', generated.entry.parent_ids == (front_id, side_id))
            check('quota_path_not_bypassed', omni.reserved == 2 and omni.finalized == 2)
            duplicate = await bridge.execute(b, task_id='second', prompt='综合原正面与新侧面', reference_ids=[front_id, side_id])
            check('duplicate_task_does_not_regenerate_or_resend', duplicate == result and len(omni.calls) == 2 and len(deliveries) == 2)
            strict_bridge = OmniDrawBridge(backend, omni, send)
            before_calls = len(omni.calls)
            for label, notes in [('omitted-purpose', None), ('wrong-purpose', [{'image_id': side_id, 'purpose': 'fixture'}])]:
                try:
                    await strict_bridge.execute(b, task_id=label, prompt='synthetic', reference_ids=[front_id], reference_notes=notes)
                    denied = False
                except ValueError:
                    denied = True
                check(label+'_rejected_before_generation', denied and len(omni.calls) == before_calls)
            check('declared_reference_purposes_reach_image_prompt', '参考图用途' in omni.calls[-1]['prompt'])

            c = event('c-image', sender='C', image=other)
            await backend.capture(c)
            ask = event('b-asks', sender='B', text='把C之前图片的元素也加进去')
            await backend.capture(ask)
            check('public_same_group_member_can_see_shared_materials', len(backend.catalog(ask)) >= 3)
            for name, e in [('persona', event('dragon', persona='dragon')),
                            ('member', event('private-member', sender='B', member=True))]:
                await backend.capture(e)
                try:
                    await backend.resolve(e, [front_id])
                    denied = False
                except ValueError:
                    denied = True
                check(name+'_namespace_isolation', not backend.catalog(e) and denied)
            denied_event = event('blocked', blocked=True)
            try:
                await backend.capture(denied_event)
                denied = False
            except ValueError:
                denied = True
            check('blocked_policy_cannot_capture', denied)
            old_calls = len(omni.calls)
            for label, ids in [('missing', None), ('foreign', ['ca_wrong']), ('duplicate', [front_id, front_id])]:
                try:
                    await bridge.execute(ask, task_id=label, prompt='edit', reference_ids=ids)
                    denied = False
                except ValueError:
                    denied = True
                check(label+'_references_fail_before_generation', denied and len(omni.calls) == old_calls)
            # An explicitly fresh image must not inherit even current references.
            await bridge.execute(ask, task_id='fresh', prompt='独立新图', reference_ids=[])
            check('explicit_empty_reference_set_is_new_generation', omni.calls[-1]['refs'] == [])
            before = len(backend.plugin._image_index.resources)
            omni.permission = 'not allowed'
            denied = await bridge.execute(ask, task_id='denied', prompt='x', reference_ids=[])
            omni.permission = ''
            check('omni_permission_denial_preserved', not denied['success'] and len(backend.plugin._image_index.resources) == before)
            omni.quota = 'daily quota'
            denied = await bridge.execute(ask, task_id='quota', prompt='x', reference_ids=[])
            omni.quota = ''
            check('omni_quota_denial_preserved', not denied['success'] and len(backend.plugin._image_index.resources) == before)
            async def fail_send(*args):
                raise RuntimeError('synthetic send failure')
            failing = FixtureBridge(backend, omni, fail_send)
            try:
                await failing.execute(ask, task_id='send-failure', prompt='x', reference_ids=[])
            except RuntimeError:
                pass
            check('failed_send_is_never_registered', len(backend.plugin._image_index.resources) == before)

            # Facts renderer must not preserve authoritative inference/instruction.
            req = ProviderRequest(prompt=ask.message_str)
            req.func_tool = request_tools(backend, ask, FunctionTool(name='generate_image', description='synthetic generation',
                parameters={'type': 'object', 'properties': {'prompt': {'type': 'string'}}, 'required': ['prompt']}, handler=lambda: None))
            await backend.prepare(ask, req)
            wire_text = json.dumps(await req.assemble_context(), ensure_ascii=False)
            check('fact_scene_has_source_message_and_speaker', all(x in wire_text for x in ['b-asks', 'c-image', 'sender_id']))
            check('fact_scene_has_no_rule_target_or_instruction', '<instruction>' not in wire_text and '<talking_to>' not in wire_text)
            check('catalog_advertised_with_native_view_tool', front_id in wire_text and 'context_aware_view_images' in wire_text)

            # Native AgentRunner + real tool executor: view then explicit multiref
            # handoff. This is a mechanical test, NOT autonomous model selection.
            native = event('native', sender='B', text='综合这两张参考图')
            await backend.capture(native)
            requests = []
            native_result = []
            async def image_tool(e, prompt, reference_ids, reference_notes):
                native_result.append(await bridge.execute(e, task_id='native', prompt=prompt, reference_ids=reference_ids, reference_notes=reference_notes))
                return 'synthetic image sent'
            tool = FunctionTool(name='generate_image', description='synthetic', parameters={
                'type': 'object', 'properties': {'prompt': {'type': 'string'}}, 'required': ['prompt']}, handler=image_tool)
            from astrbot.core.provider.func_tool_manager import _PermissionGuardedTool
            permission_checks = []
            async def allow_tool(name, context):
                permission_checks.append(name)
                return None
            wrapped = _PermissionGuardedTool(tool, SimpleNamespace(_check_tool_permission=allow_tool))
            native_req = ProviderRequest(prompt=native.message_str, func_tool=request_tools(backend, native, wrapped))
            await backend.prepare(native, native_req)
            class FakeProvider:
                provider_config = {'id': 'synthetic-native', 'modalities': ['text', 'image', 'tool_use']}
                def get_model(self): return 'synthetic-native'
                async def text_chat(self, **kw):
                    tools = kw.get('func_tool')
                    requests.append({'messages': deepcopy(kw['contexts']), 'schema': tools.get_func_desc_openai_style() if tools else []})
                    if len(requests) == 1:
                        return LLMResponse(role='assistant', tools_call_name=['context_aware_view_images'], tools_call_args=[{'image_ids': [front_id, side_id]}], tools_call_ids=['ca-fixture-view'])
                    if len(requests) == 2:
                        return LLMResponse(role='assistant', tools_call_name=['generate_image'], tools_call_args=[{'prompt': 'synthetic', 'reference_ids': [front_id, side_id], 'reference_notes': [{'image_id': front_id, 'purpose': '正面设定'}, {'image_id': side_id, 'purpose': '侧面设定'}]}], tools_call_ids=['ca-fixture-edit'])
                    return LLMResponse(role='assistant', completion_text='完成合成测试。')
            async def noop(*args): pass
            hooks = SimpleNamespace(on_tool_start=noop, on_tool_end=noop, on_agent_done=noop, on_agent_begin=noop)
            runner = ToolLoopAgentRunner()
            await runner.reset(provider=FakeProvider(), request=native_req,
                               run_context=SimpleNamespace(context=SimpleNamespace(event=native), messages=[], tool_call_timeout=10),
                               tool_executor=FunctionToolExecutor, agent_hooks=hooks)
            async for _ in runner.step_until_done(5): pass
            check('native_runner_executes_view_and_generation_tools', len(requests) == 3 and bool(native_result))
            schema = next(s['function'] for s in requests[0]['schema'] if s['function']['name'] == 'generate_image')
            check('serialized_provider_schema_requires_explicit_references', 'reference_ids' in schema['parameters']['required'] and schema['parameters']['properties']['reference_ids']['items']['type'] == 'string')
            pixels = [part for row in requests[1]['messages'] if isinstance(row.get('content'), list) for part in row['content'] if part.get('type') == 'image_url']
            check('native_runner_delivers_multiple_real_images_to_model', len(pixels) == 2)
            check('native_tool_handoff_preserves_selected_bytes', native_result[0]['reference_sha256'] == [hashlib.sha256(front_bytes).hexdigest(), hashlib.sha256(side.read_bytes()).hexdigest()])
            check('native_permission_guard_still_executes_after_schema_clone', permission_checks == ['generate_image'])
            async def deny_tool(name, context): return 'synthetic permission denied'
            denied_tool = _PermissionGuardedTool(tool, SimpleNamespace(_check_tool_permission=deny_tool))
            before_native = len(native_result)
            denied_result = await denied_tool.call(SimpleNamespace(context=SimpleNamespace(event=native)), prompt='x', reference_ids=[], reference_notes=[])
            check('native_permission_guard_denies_without_image_execution', denied_result == 'synthetic permission denied' and len(native_result) == before_native)

            old_receipt = backend.receipt(ask)
            await backend.clear(ask)
            stale = await backend.plugin.register_generated_image(old_receipt, task_id='late', data=output)
            check('reset_rejects_late_generated_results', stale is None)
            check('reset_clears_current_scope_only', not backend.catalog(ask))
            # Scope translation must reject an event from a different instance.
            cloned_backend = CandidateBackend(ca, context, cfg, probe.attachment_identity)
            try:
                try:
                    cloned_backend.catalog(ask)
                    denied = False
                except ValueError:
                    denied = True
                check('backend_generation_cannot_reuse_old_event_view', denied)
            finally:
                await cloned_backend.close()

            # Disk restoration reuses the CURRENT attachment database/epoch and
            # no second selector. A different candidate instance has an empty
            # native cache before explicit restore, demonstrating a real restart.
            from extensions.astrbot_plugin_qq_persona_models.attachment_store import AttachmentStore
            from integrations.contextaware.archive_restore import ArchiveRestorer
            store = AttachmentStore(root/'persistent-archive')
            restart_event = event('restart-fixture', text='继续之前的任务')
            owner = probe.attachment_identity(restart_event)
            scope = owner['scope']
            def retain(mid, data, *, generated=False, parents=(), request_seq=None):
                source = {'generated': generated}
                if request_seq is not None: source['request_seq'] = request_seq
                r = store.record(scope, restart_event.unified_msg_origin, mid, 'bot' if generated else 'A', 'A', '',
                    [{'type': 'image', 'ordinal': 0, 'source': source}], 'generated' if generated else 'user', parents)
                store.retain(scope, r['epoch'], r['ids'][0], data, 'image/png', 'png')
                return r
            persisted = retain('real-original-id', front_bytes)
            persisted_generated = retain('real-generated-id', output, generated=True, parents=persisted['ids'], request_seq=persisted['seq'])
            restoration = CandidateBackend(ca, context, {**cfg, 'image_cache_dir': str(root/'restart-cache')}, probe.attachment_identity)
            try:
                restorer = ArchiveRestorer(restoration, store)
                cold_started = time.perf_counter()
                loaded = await restorer.hydrate(restart_event)
                cold_ms = (time.perf_counter()-cold_started)*1000
                await restoration.capture(restart_event)
                catalog = restoration.catalog(restart_event)
                originals = {r['message_id']: r for r in catalog}
                check('restart_restores_both_original_and_generated_sources', set(originals) == {'real-original-id', 'real-generated-id'})
                refs = await restoration.resolve(restart_event, [originals['real-original-id']['id']])
                check('restart_restores_exact_original_pixels', refs[0]['data'] == front_bytes)
                generated_row = originals['real-generated-id']
                check('restart_preserves_generated_lineage', generated_row['kind'] == 'generated' and generated_row['parent_ids'] == [originals['real-original-id']['id']])
                check('restart_recovers_original_requester_without_guessing', generated_row['sender_id'] == 'A')
                again = event('restart-next', text='你好')
                loaded_again = await restorer.hydrate(again)
                check('repeated_restore_does_not_duplicate_active_images', loaded_again['imported'] == 0 and len(loaded_again['mapping']) == 2)
                forbidden = event('restart-foreign', persona='dragon')
                blocked_restore = await restorer.hydrate(forbidden)
                check('disk_restore_preserves_persona_scope', blocked_restore['imported'] == 0)
                store.invalidate(scope)
                after_clear = event('restart-after-reset')
                cleared = await restorer.hydrate(after_clear)
                check('disk_restore_respects_persisted_reset_epoch', cleared['imported'] == 0 and not restoration.catalog(after_clear))
                stale = retain('expired-source', side.read_bytes())
                with store.db() as db:
                    db.execute('UPDATE assets SET expires=0 WHERE id=?', (stale['ids'][0],))
                no_expired = await restorer.hydrate(event('restart-expired'))
                check('disk_restore_does_not_resurrect_expired_sources', no_expired['imported'] == 0)
            finally:
                await restoration.close()
            samples = []
            for i in range(40):
                e = event('timing-'+str(i), text='你好，测试文字准备')
                rq = ProviderRequest(prompt=e.message_str)
                started = time.perf_counter()
                await backend.capture(e)
                await backend.prepare(e, rq)
                samples.append((time.perf_counter()-started)*1000)
            p95 = sorted(samples)[37]
            check('text_preparation_p95_below_200ms_in_isolation', p95 < 200)
            check('captions_and_summary_off', not backend.plugin._image_caption_enabled and backend.plugin._topic is None and backend.plugin._cfg('history_compress_strategy') == 'off')
            report = {'passed': all(checks.values()), 'checks': checks,
                      'measurements': {'samples': len(samples), 'text_preparation_ms_p50': round(statistics.median(samples), 3), 'text_preparation_ms_p95': round(p95, 3), 'cold_restore_two_images_ms': round(cold_ms, 3)},
                      'scope': 'isolated_three_seams_only',
                      'limits': ['Scripted fake model; autonomous choice is a separate --models test', 'No full OmniDraw provider SDK execution', 'Cold restore tested; live capture/persistence ownership not yet wired', 'Backend switch not yet connected to production hooks'],
                      'model_api_calls': 0, 'image_generations': 0, 'qq_messages_sent': 0, 'production_writes': 0}
            print('CA_EVALUATION_REPORT='+json.dumps(report, ensure_ascii=False), flush=True)
        finally:
            await backend.close()


if __name__ == '__main__':
    asyncio.run(main())
