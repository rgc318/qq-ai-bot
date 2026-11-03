"""Replace only qq-reply-judge-fast; retain personas, groups and 8s deadlines.

Uses synthetic classifier diagnostics only, never QQ sends, main replies,
image generation or real conversation replay. Restore the provider on failure.
"""
from copy import deepcopy
from datetime import datetime
import json
import time

from deployment_api import DeploymentAPI, write_report

api = DeploymentAPI()
PROVIDER = 'qq-reply-judge-fast'
MODEL = 'siliconflow/deepseek-ai/DeepSeek-V4.1-Flash'
LOCAL = '/api/v1/plugins/astrbot_plugin_qq_persona_models/config'
AMBIENT = '/api/v1/plugins/astrbot_plugin_self_initiated_reply/config'


def providers():
    return api.call('/api/config/provider/template')['data']['providers']


def idle():
    stable = 0
    for _ in range(30):
        active = api.call('/api/plug/qq_persona_models/model_activity/status')['data']['active']
        state = api.call('/api/plug/qq_persona_models/context_backend/status')['data']
        proactive = api.call('/api/plug/astrbot_plugin_self_initiated_reply/status')
        proactive = proactive.get('data', proactive)
        busy = active or state['active_requests'] or state['pending_messages'] or state['switching'] or any(proactive.get('tasks', {}).get(k, 0) for k in ('delay', 'running_check')) or proactive.get('gate', {}).get('running')
        stable = 0 if busy else stable + 1
        if stable >= 2:return
        time.sleep(2)
    raise RuntimeError('Current work still active; provider unchanged')


catalog = {m['id'] for m in api.model('/models')['data']}
assert MODEL in catalog
all_before = providers()
original = deepcopy(next(p for p in all_before if p['id'] == PROVIDER))
local_before = api.call(LOCAL)['data']['config']
ambient_before = api.call(AMBIENT)['data']['config']
bindings_before = api.call('/api/plug/qq_persona_models/verify')['data']
assert local_before['reply_conditions']['judge_provider_id'] == PROVIDER
assert ambient_before['judge_provider_id'] == PROVIDER
assert local_before['reply_conditions']['judge_timeout_seconds'] == 8 and ambient_before['decision_timeout_sec'] == 8
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
api.backup('qwen-judge-before-deepseek-' + stamp + '.json', original)
next_provider = deepcopy(original)
next_provider.update(model=MODEL, enable=True)
next_provider['custom_extra_body'] = {**next_provider.get('custom_extra_body', {}),
    'enable_thinking': False, 'max_tokens': 240, 'temperature': 0.1,
    'response_format': {'type': 'json_object'}}
report = {'provider': PROVIDER, 'model': MODEL, 'checks': {}, 'cases': [],
          'qq_messages_sent': 0, 'main_model_calls': 0, 'image_generations': 0}
changed = False
try:
    idle()
    assert next(p for p in providers() if p['id'] == PROVIDER) == original, 'Provider changed while waiting'
    changed = True
    api.call('/api/config/provider/update', {'id': PROVIDER, 'config': next_provider})
    history = [{'role': 'user', 'sender': 'A', 'text': '请帮我写一份周六读书会海报文案'},
               {'role': 'assistant', 'sender': 'A', 'request': '写周六读书会海报文案', 'text': '周六读书会海报文案已完成。'}]
    fixtures = [
        ('cross_member_followup', {'sender': 'B', 'message': '给我也整一份，日期改成周日', 'history': history}, True),
        ('human_exchange_stays_silent', {'sender': 'B', 'message': '给我也整一份', 'history': history + [
            {'role': 'user', 'sender': 'C', 'text': '小张，我下楼买饭，给你带鸡腿饭？'},
            {'role': 'user', 'sender': 'D', 'text': '给我带一份，多放辣。'}]}, False),
        ('image_translation_request', {'sender': 'B', 'message': '翻译一下这个图片', 'history': [
            {'role': 'user', 'sender': 'B', 'text': 'ai助手，帮我看下菜单'},
            {'role': 'assistant', 'sender': 'B', 'request': '帮我看菜单', 'text': '把图片发来，我帮你翻译。'},
            {'role': 'user', 'sender': 'B', 'text': '[合成图片占位，无图片数据]'}]}, True),
    ]
    for name, payload, expected in fixtures:
        verdict = api.call('/api/plug/qq_persona_models/reply_conditions/test', payload, timeout=20)['data']
        passed = verdict['normal_pipeline_eligible'] == expected and verdict.get('judge_seconds', 0) > 0 and verdict.get('qq_messages_sent') == 0
        report['cases'].append({'name': name, 'passed': passed, 'route': verdict['route'],
            'reason': verdict['reason'], 'seconds': verdict['judge_seconds']})
        print(json.dumps(report['cases'][-1], ensure_ascii=False), flush=True)
        assert passed, 'Native classifier diagnostic failed'
    actual = next(p for p in providers() if p['id'] == PROVIDER)
    report['checks']['provider_changed_to_tested_deepseek'] = actual['model'] == MODEL and actual['custom_extra_body'] == next_provider['custom_extra_body']
    report['checks']['both_judge_references_unchanged'] = api.call(LOCAL)['data']['config'] == local_before and api.call(AMBIENT)['data']['config'] == ambient_before
    after = providers()
    report['checks']['other_providers_unchanged'] = {p['id']: p for p in all_before if p['id'] != PROVIDER} == {p['id']: p for p in after if p['id'] != PROVIDER}
    bindings_after = api.call('/api/plug/qq_persona_models/verify')['data']
    report['checks']['persona_models_unchanged'] = bindings_after == bindings_before and all(r['passed'] for r in bindings_after)
    report['checks']['all_native_cases_passed'] = all(c['passed'] for c in report['cases'])
    recent = api.call('/api/plug/qq_persona_models/model_activity/status')['data']['recent']
    report['checks']['native_calls_used_new_model'] = any(r.get('provider') == PROVIDER and r.get('model') == MODEL and r.get('event') == 'success' for r in recent)
    report['judge_timeout_seconds'] = 8
    report['synthetic_judge_calls'] = len(report['cases'])
    report['passed'] = all(report['checks'].values())
    assert report['passed']
except BaseException as exc:
    report['passed'] = False;report['error_type'] = type(exc).__name__
    if changed:
        idle()
        api.call('/api/config/provider/update', {'id': PROVIDER, 'config': original})
        report['rolled_back'] = next(p for p in providers() if p['id'] == PROVIDER) == original
    write_report('judge-deepseek-replacement.json', report)
    raise
write_report('judge-deepseek-replacement.json', report)
print(json.dumps(report, ensure_ascii=False, indent=2))
