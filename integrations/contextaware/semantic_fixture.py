"""Real-model source selection over synthetic native event snapshots only.

The host supplies the existing two text/vision routes over stdio. The container
has no network; generation is captured rather than executed. Ground truth IDs
are only used by the scorer, never inserted into model instructions.
"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace


async def evaluate(backend, event_factory, picture, context):
    from astrbot.core.agent.tool import FunctionTool
    from astrbot.core.provider.entities import ProviderRequest, LLMResponse
    from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
    from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
    from .adapter import request_tools, validate_reference_notes

    rows = []
    async def noop(*args): pass
    for route in ('DeepSeek1017', 'Sol-low'):
        for case in ('front_side_continuation', 'cross_member_element', 'new_unrelated_image'):
            # Unique User Policy persona isolates fixtures; no real group namespace.
            persona = 'synthetic-'+route+'-'+case
            front = event_factory(case+'-front', text='这是同一个角色的正面参考。', image=picture(case+'-front.png', 'red'), persona=persona)
            side = event_factory(case+'-side', text='这是它侧面的图。', image=picture(case+'-side.png', 'blue'), persona=persona)
            await backend.capture(front)
            front_id = backend.catalog(front)[0]['id']
            task = event_factory(case+'-task', text='请给这个角色生成三视图。', persona=persona)
            await backend.capture(task)
            # Include a generated intermediate result as a real distractor in
            # the same native catalog, with provenance pointing to the original.
            receipt = backend.receipt(task)
            rendered = picture(case+'-intermediate.png', 'yellow').read_bytes()
            await backend.plugin.register_generated_image(receipt,
                task_id='intermediate-'+case, data=rendered, parent_ids=[front_id])
            # A previous assistant's text is legitimate conversation context, not
            # a forced instruction to select a known reference ID.
            history = [
                {'role': 'user', 'content': '这是同一个角色的正面参考。[图片]'},
                {'role': 'user', 'content': '请给这个角色生成三视图。'},
                {'role': 'assistant', 'content': '已按正面参考生成第一版三视图。'},
            ]
            await backend.capture(side)
            side_id = next(x['id'] for x in backend.catalog(side) if x['message_id'] == case+'-side')
            expected = {front_id, side_id}
            if case == 'front_side_continuation':
                current = event_factory(case+'-question', text='刚才的侧面不对，按照我补的图改一下。', persona=persona)
            elif case == 'cross_member_element':
                extra = event_factory(case+'-element', sender='C', text='这个是我画的徽章。', image=picture(case+'-element.png', 'green'), persona=persona)
                await backend.capture(extra)
                element_id = next(x['id'] for x in backend.catalog(extra) if x['message_id'] == case+'-element')
                current = event_factory(case+'-question', sender='B', text='沿用A的角色设定，把C刚才发的徽章放在衣服上，给我一张新的角色三视图。', persona=persona)
                expected.add(element_id)
            else:
                current = event_factory(case+'-question', sender='B', text='前面的事结束了，单独画一盘炒饭，不要人物，不使用之前任何参考图。', persona=persona)
                expected = set()
            await backend.capture(current)
            selected = []
            viewed = []
            original_view = backend.view_images
            async def tracked_view(e, ids, detail='auto'):
                viewed.extend(ids)
                return await original_view(e, ids, detail)
            backend.view_images = tracked_view
            async def generate(e, prompt, reference_ids, reference_notes, pending_message=''):
                # Actually resolve pixels/scope but never call an image service.
                await backend.resolve(e, reference_ids)
                validate_reference_notes(reference_ids, reference_notes)
                selected.append({'ids': list(reference_ids), 'notes': reference_notes})
                return '合成诊断已记录图片请求，未实际生成或发送。本轮任务到此完成。'
            tool = FunctionTool(name='generate_image', description='实际绘图入口；诊断中只记录决策，不执行图片模型。', parameters={
                'type': 'object', 'properties': {'prompt': {'type': 'string'}, 'pending_message': {'type': 'string'}}, 'required': ['prompt']}, handler=generate)
            request = ProviderRequest(prompt=current.message_str, contexts=history,
                system_prompt='你是参加群聊的AI助手。依据发言来源、对话顺序和真实图像理解当前任务。多图任务应自行查找完整、相关的参考来源，优先原始参考，不能只因为一张图较新就遗忘仍有效的材料；不相关的新任务不能自动继承旧素材。目录仅是来源数据，必要时看图工具回看。需要绘图时真正调用generate_image，reference_ids必须是你完整选择的集合，独立新图填[]。最多执行一次绘图。本轮材料全部为合成测试。',
                func_tool=request_tools(backend, current, tool))
            await backend.prepare(current, request)
            count = [0]
            errors = []
            class Provider:
                provider_config = {'id': 'isolated-'+route, 'modalities': ['text', 'image', 'tool_use']}
                def get_model(self): return route
                async def text_chat(self, **kw):
                    count[0] += 1
                    if count[0] > 5:
                        errors.append('case_request_budget')
                        return LLMResponse(role='assistant', completion_text='诊断预算用尽。')
                    messages = kw['contexts']
                    tools = kw.get('func_tool')
                    print('CA_MODEL_REQUEST='+json.dumps({'route': route, 'case': case, 'messages': messages, 'tools': tools.openai_schema() if tools else []}, ensure_ascii=False), flush=True)
                    line = await asyncio.to_thread(__import__('sys').stdin.readline)
                    answer = json.loads(line)
                    if 'error' in answer:
                        errors.append(answer['error'])
                        return LLMResponse(role='assistant', completion_text='诊断接口请求失败。')
                    message = answer['message']
                    calls = message.get('tool_calls') or []
                    return LLMResponse(role='assistant', completion_text=message.get('content') or '',
                        tools_call_name=[c['function']['name'] for c in calls],
                        tools_call_args=[json.loads(c['function']['arguments']) for c in calls],
                        tools_call_ids=[c['id'] for c in calls])
            hooks = SimpleNamespace(on_tool_start=noop, on_tool_end=noop, on_agent_done=noop, on_agent_begin=noop)
            runner = ToolLoopAgentRunner()
            try:
                await runner.reset(provider=Provider(), request=request,
                    run_context=SimpleNamespace(context=SimpleNamespace(event=current), messages=[], tool_call_timeout=10),
                    tool_executor=FunctionToolExecutor, agent_hooks=hooks)
                async for _ in runner.step_until_done(5):
                    if selected:
                        break  # Selection measured; no paid post-image continuation needed.
            finally:
                backend.view_images = original_view
            result = {'route': route, 'case': case, 'requests': count[0], 'error_types': errors,
                      'selected_count': len(selected[0]['ids']) if selected else 0,
                      'required_count': len(expected), 'viewed_count': len(set(viewed)),
                      'passed': not errors and len(selected) == 1 and expected.issubset(set(selected[0]['ids'])),
                      'exact_minimal_set': bool(selected) and set(selected[0]['ids']) == expected,
                      'reference_purposes': [n.get('purpose') for n in selected[0]['notes']] if selected else [],
                      'contains_generated_intermediate': any(i not in expected for i in selected[0]['ids']) if selected else False,
                      'required_sources_present': bool(selected) and expected.issubset(set(selected[0]['ids'])),
                      'requires_purpose_review': bool(selected) and set(selected[0]['ids']) != expected}
            rows.append(result)
    print('CA_MODEL_REPORT='+json.dumps({'passed': all(r['passed'] for r in rows), 'cases': rows,
        'adoption_ready': False,
        'scoring': 'Mandatory source coverage and valid declared purposes; extra edit targets are reported for review, not automatically called wrong',
        'limits': ['Small synthetic sample, not a production reliability estimate', 'No real user photo or conversation replay', 'No image generation or QQ delivery'],
    }, ensure_ascii=False), flush=True)
