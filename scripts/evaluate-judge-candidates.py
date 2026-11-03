"""Compare LiteLLM judges on synthetic group conversations, never real history.

No tools, images, QQ sends, provider edits or plugin reloads. Report only model
IDs, timings and synthetic verdicts. Results are a small diagnostic sample.
"""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import statistics
import time

from deployment_api import DeploymentAPI, ROOT, write_report

tree = ast.parse((ROOT / 'extensions/astrbot_plugin_qq_persona_models/reply_routing.py').read_text(encoding='utf-8'))
PROMPT = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'JUDGE_SYSTEM_PROMPT' for t in n.targets))


def activity(request, reply, id='ai-1', age=120):
    return {'id': id, 'age_seconds': age, 'status': 'sent', 'request': request,
            'reply': reply, 'requested_by': 'A'}


def row(sender, text, role='user'):
    return {'role': role, 'sender': sender, 'text': text}


def case(name, text, recent, anchor=None, *, recipient='bot', routes=('addressed', 'followup'), image=None, silence=False):
    return {'name': name, 'expected': {'recipient': recipient, 'routes': list(routes), 'silence': silence},
        'payload': {'bot_aliases': ['大肥鱼', '龙娘', 'ai助手'], 'recent_addressing_evidence': False,
            'dialogue_continuity': {'established': False, 'unclassified_turns': 0, 'other_speaker_count': 0},
            'last_ai_activity': anchor, 'recent_image_activity': image, 'recent_messages': recent,
            'latest_message': {'sender': 'B', 'name': '测试成员乙', 'text': text}}}


CASES = [
    case('split_image_translation', '翻译一下这个图片',
         [row('B', 'ai助手，帮我看下菜单'), row('bot', '把图片发来，我帮你翻译。', 'assistant'), row('B', '[图片，消息ID fixture-image]')],
         activity('帮我看菜单', '把图片发来，我帮你翻译。')),
    case('human_food_exchange', '给我也整一份',
         [row('C', '小张，我下楼买饭，帮你带鸡腿饭？'), row('D', '给我带一份，多放辣。')],
         activity('写读书会海报', '读书会海报文案已写好。', age=600), recipient='human', routes=('ambient',)),
    case('cross_member_followup', '给我也整一份，日期改成周日',
         [row('A', 'ai助手，帮我写一份周六读书会海报文案'), row('bot', '周六读书会海报文案如下……', 'assistant')],
         activity('写周六读书会海报文案', '周六读书会海报文案如下……'), routes=('followup',)),
    case('name_without_task', 'wake up',
         [row('B', '龙娘大人'), row('B', '怎么没理我')], None, routes=('addressed',)),
    case('turn_to_human', '你是谁，你是哪个班的',
         [row('B', '小张，我现在问你，不是在问机器人')],
         activity('你是谁', '我是群里的 AI 助手。'), recipient='human', routes=('ambient',)),
    case('explicit_silence', '大肥鱼，这次别回我，我只是记个笔记',
         [row('B', '测试发言')], None, routes=('ambient',), silence=True),
    case('human_edit_not_ai_task', '小张再短点吧',
         [row('C', '小张，你的自我介绍太长了'), row('D', '那段是我写的，我再改')],
         activity('写 Python CSV 示例', '这是 Python 读取 CSV 的示例。'), recipient='human', routes=('ambient',)),
    case('meme_human_exchange', '对，发个开心的表情包',
         [row('C', '小张，你收藏的开心表情给我看看'), row('D', '我发的黄色小狗吗')],
         activity('你好', '你好，有什么想聊的？'), recipient='human', routes=('ambient',)),
    case('independent_meme_request', '发个开心的表情包', [row('C', '今天的事情办完了。')], None, routes=('addressed',)),
    case('pending_picture_reminder', '图呢',
         [row('A', '把角色换成侧面姿势'), row('bot', '我来修改，保留原来的衣服。', 'assistant'), row('B', '你好'), row('bot', '你好呀。', 'assistant')],
         activity('你好', '你好呀。', id='greeting'), routes=('followup',),
         image={'id': 'image-1', 'status': 'not_called', 'age_seconds': 300, 'request': '把角色换成侧面姿势', 'reply': '我来修改，保留原来的衣服。', 'requested_by': 'B'}),
]


def valid_verdict(verdict, fixture):
    expected = fixture['expected']
    if not isinstance(verdict, dict):return False
    # Production checks silence before route. An addressed message that
    # explicitly asks for silence must also count as a successful no-reply.
    if expected['silence']:
        return verdict.get('silence_requested') is True
    if verdict.get('route') not in expected['routes']:return False
    if verdict.get('recipient') != expected['recipient']:return False
    if verdict.get('silence_requested') is not expected['silence']:return False
    if not expected['silence'] and expected['recipient'] == 'bot':
        confidence = verdict.get('confidence')
        if type(confidence) not in (int, float) or not 0.88 <= confidence <= 1:return False
    if verdict.get('route') == 'followup':
        anchors = [fixture['payload'].get(k) for k in ('last_ai_activity', 'recent_image_activity')]
        if verdict.get('anchor_id') not in {a['id'] for a in anchors if a}:return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', nargs='+', required=True)
    parser.add_argument('--screen', action='store_true')
    parser.add_argument('--report', default='judge-candidate-comparison.json')
    args = parser.parse_args()
    if not args.report.endswith('.json') or '/' in args.report or '\\' in args.report:raise ValueError('Report must be a local JSON basename')
    api = DeploymentAPI()
    catalog = {r['id'] for r in api.model('/models')['data']}
    assert all(model in catalog for model in args.models), 'Only compare listed model IDs'
    fixtures = CASES[:3] if args.screen else CASES
    def run(model):
        results = []
        options = {'max_tokens': 240, 'temperature': 0.1, 'response_format': {'type': 'json_object'}}
        # SiliconFlow's documented toggle. The existing Instruct baseline has
        # no thinking switch, so retain its actual production request options.
        if 'DeepSeek' in model or '/GLM-' in model:options['enable_thinking'] = False
        for fixture in fixtures:
            started = time.perf_counter()
            result = {'case': fixture['name']}
            try:
                response = api.model('/chat/completions', {'model': model, 'stream': False,
                    'messages': [{'role': 'system', 'content': PROMPT},
                                 {'role': 'user', 'content': json.dumps(fixture['payload'], ensure_ascii=False)}], **options}, timeout=12)
                elapsed = time.perf_counter() - started
                choice = response['choices'][0];message = choice['message'];content = message.get('content') or ''
                verdict = json.loads(content)
                correct = valid_verdict(verdict, fixture)
                result.update(seconds=round(elapsed, 3), correct=correct, within_8_seconds=elapsed < 8,
                    json_valid=True, finish_reason=choice.get('finish_reason'), verdict=verdict,
                    unexpected_tool_calls=len(message.get('tool_calls') or []),
                    reasoning_chars=len(message.get('reasoning_content') or ''),
                    input_tokens=response.get('usage', {}).get('prompt_tokens'),
                    output_tokens=response.get('usage', {}).get('completion_tokens'))
            except Exception as exc:
                elapsed = time.perf_counter() - started
                result.update(seconds=round(elapsed, 3), correct=False,
                    within_8_seconds=elapsed < 8, json_valid=False, error_type=type(exc).__name__,
                    error=api.sanitize(str(exc))[:350])
            results.append(result)
        durations = [r['seconds'] for r in results]
        report = {'model': model, 'options': options, 'samples': len(results),
                  'correct': sum(r['correct'] for r in results),
                  'timely_correct': sum(r['correct'] and r['within_8_seconds'] for r in results),
                  'over_8_seconds': sum(not r['within_8_seconds'] for r in results),
                  'errors': sum('error_type' in r for r in results),
                  'median_seconds': round(statistics.median(durations), 3),
                  'max_seconds': max(durations), 'results': results}
        print(json.dumps({k: v for k, v in report.items() if k not in ('results', 'options')}, ensure_ascii=False), flush=True)
        return report
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(run, args.models))
    write_report(args.report, {'synthetic_only': True, 'production_changed': False, 'qq_messages_sent': 0,
        'image_generations': 0, 'model_calls': sum(r['samples'] for r in reports), 'results': reports,
        'limits': 'Small time-local sample; median/max are not production p95. Routes may share an upstream backend.'})


if __name__ == '__main__':main()
