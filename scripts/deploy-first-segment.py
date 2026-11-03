"""Deploy 1.13.0 -> 1.14.0 immediate first segment, retaining native later intervals."""
from datetime import datetime
import hashlib
import json
import subprocess
import time
from copy import deepcopy
import argparse

from deployment_api import DeploymentAPI, ROOT, write_report

NAME = 'astrbot_plugin_qq_persona_models'
CONTAINER = 'qq-ai-bot-astrbot-1'
LIVE = '/AstrBot/data/plugins/' + NAME
FILES = ('main.py','metadata.yaml','context_runtime.py','model_logging.py','_conf_schema.json','reply_delivery.py')
CONFIG_FILE = '/AstrBot/data/config/' + NAME + '_config.json'
SOURCES = {n: ROOT / 'extensions' / NAME / n for n in FILES}
parser=argparse.ArgumentParser();parser.add_argument('--baseline',choices=('1.13.0','1.14.0'),default='1.13.0');args=parser.parse_args()
api = DeploymentAPI()
CONFIG = '/api/v1/plugins/' + NAME + '/config'


def docker(*args):
    return subprocess.run(['wsl', '-d', 'Ubuntu', '--exec', 'docker', *args],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=True, timeout=120).stdout


def py(code):return docker('exec', CONTAINER, 'python', '-c', code)


def plugin():return next(p for p in api.call('/api/v1/plugins')['data'] if p['name'] == NAME)


def backend():return api.call('/api/plug/qq_persona_models/context_backend/status')['data']


def idle():
    stable = 0
    for _ in range(30):
        active = api.call('/api/plug/qq_persona_models/model_activity/status')['data']['active']
        state = backend()
        proactive = api.call('/api/plug/astrbot_plugin_self_initiated_reply/status')
        proactive = proactive.get('data', proactive)
        busy = active or state['active_requests'] or state['pending_messages'] or state['switching'] or any(proactive.get('tasks', {}).get(k, 0) for k in ('delay', 'running_check')) or proactive.get('gate', {}).get('running')
        stable = 0 if busy else stable + 1
        if stable >= 2:return
        time.sleep(2)
    raise RuntimeError('Existing work still active; no reload performed')


def hashes():
    return json.loads(py('from pathlib import Path;import json,hashlib;r=Path(' + repr(LIVE) + ');'
        'print(json.dumps({n:hashlib.sha256((r/n).read_bytes()).hexdigest() if (r/n).is_file() else None for n in ' + repr(FILES) + '}))'))


assert plugin()['activated'] and plugin()['version'] == args.baseline, 'Review changed baseline'
config_before = api.call(CONFIG)['data']['config']
expected_config = deepcopy(config_before)
expected_config['reply_delivery']={**config_before.get('reply_delivery',{}),'first_segment_immediate':True}
bindings_before = api.call('/api/plug/qq_persona_models/verify')['data']
policy_before = api.call('/api/plug/astrbot_plugin_user_policy/bootstrap')['data']
policy_keys = ('revision', 'groups', 'private_users', 'schedules')
policy_before = {k: policy_before.get(k) for k in policy_keys}
original = hashes();previous_backend = backend()['backend'];recent_before=backend()['recent_input']
profile_before=api.call('/api/v1/config-profiles/default')['data']['config']
expected = {n: hashlib.sha256(SOURCES[n].read_bytes()).hexdigest() for n in FILES}
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup = '/AstrBot/data/temp/first-segment-' + stamp
report = {'version': '1.14.0', 'backup': backup, 'checks': {}, 'model_calls': 0, 'qq_messages_sent': 0}
changed = False
idle()
py('from pathlib import Path;import shutil;b=Path(' + repr(backup) + ');b.mkdir();(b/"next").mkdir();r=Path(' + repr(LIVE) + ');'
   '[(b/n).parent.mkdir(parents=True,exist_ok=True) for n in ' + repr(FILES) + '];'
   '[(b/"next"/n).parent.mkdir(parents=True,exist_ok=True) for n in ' + repr(FILES) + '];'
   '[shutil.copy2(r/n,b/n) for n in ' + repr(FILES) + ' if (r/n).is_file()];'
   'shutil.copy2(' + repr(CONFIG_FILE) + ',b/"previous-config.json")')
for name in FILES:
    source=SOURCES[name].relative_to(ROOT).as_posix()
    docker('cp', '/mnt/e/AI/ai/qq-ai-bot/' + source, CONTAINER + ':' + backup + '/next/' + name)
docker('exec', CONTAINER, 'python', '-m', 'compileall', '-q', backup + '/next')
try:
    idle()
    assert api.call(CONFIG)['data']['config'] == config_before, 'Config changed while waiting'
    changed = True
    py('from pathlib import Path;import shutil;b=Path(' + repr(backup) + ');r=Path(' + repr(LIVE) + ');'
       '[shutil.copy2(b/"next"/n,r/n) for n in ' + repr(FILES) + '];'
       'p=Path(' + repr(CONFIG_FILE) + ');p.write_text(' + repr(json.dumps(expected_config,ensure_ascii=False,indent=2)) + ',encoding="utf-8")')
    api.call('/api/v1/plugins/' + NAME + '/reload', {}, timeout=120)
    state = backend()
    report['checks']['version_and_backend'] = plugin()['version'] == '1.14.0' and plugin()['activated'] and state['backend'] == previous_backend and not state['failed'] and not state['startup_pending']
    report['checks']['source_hashes_match'] = hashes() == expected
    report['checks']['only_first_segment_option_enabled'] = api.call(CONFIG)['data']['config'] == expected_config
    report['checks']['task_guard_installed'] = state['task_completion']['installed'] and state['task_completion']['enabled'] == expected_config['task_completion']['enabled'] and state['task_completion']['max_corrections'] == 1
    report['checks']['first_segment_adapter_ready'] = state['reply_delivery']['installed'] and state['reply_delivery']['first_segment_immediate'] and state['reply_delivery']['subsequent_interval']=='native'
    report['checks']['native_config_and_models_preserved'] = api.call('/api/v1/config-profiles/default')['data']['config'] == profile_before
    report['checks']['recent_input_unchanged'] = state['recent_input'] == recent_before
    policy_after = api.call('/api/plug/astrbot_plugin_user_policy/bootstrap')['data']
    report['checks']['native_policies_unchanged'] = {k: policy_after.get(k) for k in policy_keys} == policy_before
    report['checks']['persona_models_unchanged'] = api.call('/api/plug/qq_persona_models/verify')['data'] == bindings_before
    scopes = api.call('/api/plug/qq_persona_models/verify_memory_meme', {'group_context_scope_only': True}, timeout=30)['data']
    report['checks']['live_native_group_scopes'] = scopes['passed'] and scopes['model_calls'] == 0 and scopes['qq_messages_sent'] == 0 and scopes['history_writes'] == 0
    report['scope_checks'] = scopes['checks']
    report['passed'] = all(report['checks'].values())
    assert report['passed'], 'Post-deployment scope verification failed'
except BaseException as exc:
    report['passed'] = False;report['error_type'] = type(exc).__name__
    if changed:
        idle()
        py('from pathlib import Path;import shutil;b=Path(' + repr(backup) + ');r=Path(' + repr(LIVE) + ');'
           '[shutil.copy2(b/n,r/n) if (b/n).is_file() else (r/n).unlink(missing_ok=True) for n in ' + repr(FILES) + '];'
           'shutil.copy2(b/"previous-config.json",' + repr(CONFIG_FILE) + ')')
        api.call('/api/v1/plugins/' + NAME + '/reload', {}, timeout=120)
        report['rolled_back'] = hashes() == original and api.call(CONFIG)['data']['config'] == config_before
    write_report('first-segment-deployment.json', report)
    raise
write_report('first-segment-deployment.json', report)
print(json.dumps(report, ensure_ascii=False, indent=2))
