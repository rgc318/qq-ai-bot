"""Deploy the reviewed 1.11.5 -> 1.11.6 lifecycle/page fix with idle gates.

Only five owned files change. Configuration, saved backend, archives, upstream
ContextAware and OmniDraw are preserved; no model calls or QQ sends.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import quote, urljoin
import urllib.request

from deployment_api import DeploymentAPI, ROOT, write_report

NAME = 'astrbot_plugin_qq_persona_models'
CONTAINER = 'qq-ai-bot-astrbot-1'
LIVE = '/AstrBot/data/plugins/' + NAME
FILES = ('main.py', 'metadata.yaml', 'context_runtime.py',
         'pages/上下文后端/app.js', 'pages/上下文后端/index.html')
api = DeploymentAPI()
CONFIG_API = '/api/v1/plugins/' + NAME + '/config'


def docker(*args):
    return subprocess.run(['wsl', '-d', 'Ubuntu', '--exec', 'docker', *args],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=True, timeout=120).stdout


def py(code):
    return docker('exec', CONTAINER, 'python', '-c', code)


def plugin():
    return next(p for p in api.call('/api/v1/plugins')['data'] if p['name'] == NAME)


def status():
    return api.call('/api/plug/qq_persona_models/context_backend/status')['data']


def idle():
    stable = 0
    for i in range(30):
        active = api.call('/api/plug/qq_persona_models/model_activity/status')['data']['active']
        state = status()
        proactive = api.call('/api/plug/astrbot_plugin_self_initiated_reply/status')
        proactive = proactive.get('data', proactive)
        queued = any(proactive.get('tasks', {}).get(k, 0) for k in ('delay', 'running_check')) or bool(proactive.get('gate', {}).get('running'))
        busy = active or queued or state['active_requests'] or state['pending_messages'] or state['switching']
        stable = 0 if busy else stable + 1
        if stable >= 2:return
        if busy and i % 10 == 0:print('Waiting for existing work before plugin reload', flush=True)
        time.sleep(2)
    raise RuntimeError('Still busy; no reload performed')


def hashes():
    return json.loads(py('from pathlib import Path;import json,hashlib;r=Path(' + repr(LIVE) + ');'
        'print(json.dumps({n:hashlib.sha256((r/n).read_bytes()).hexdigest() for n in ' + repr(FILES) + '}))'))


baseline = plugin()
assert baseline['activated'] and baseline['version'] == '1.11.5', 'Review the current plugin baseline first'
before = api.call(CONFIG_API)['data']['config']
saved = status()
original = hashes()
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup = '/AstrBot/data/temp/context-lifecycle-' + stamp
expected = {n: hashlib.sha256((ROOT / 'extensions' / NAME / n).read_bytes()).hexdigest() for n in FILES}
api.backup('context-lifecycle-config-' + stamp + '.json', before)
report = {'version': '1.11.6', 'backup': backup, 'checks': {}, 'model_calls': 0, 'qq_messages_sent': 0}
changed = False
idle()
assert api.call(CONFIG_API)['data']['config'] == before, 'Configuration changed while waiting'
py('from pathlib import Path;import shutil;b=Path(' + repr(backup) + ');b.mkdir();'
   'r=Path(' + repr(LIVE) + ');'
   '[(b/n).parent.mkdir(parents=True,exist_ok=True) for n in ' + repr(FILES) + '];'
   '[shutil.copy2(r/n,b/n) for n in ' + repr(FILES) + '];'
   '[(b/"next"/n).parent.mkdir(parents=True,exist_ok=True) for n in ' + repr(FILES) + ']')
for name in FILES:
    docker('cp', '/mnt/e/AI/ai/qq-ai-bot/extensions/' + NAME + '/' + name, CONTAINER + ':' + backup + '/next/' + name)
docker('exec', CONTAINER, 'python', '-m', 'compileall', '-q', backup + '/next')
try:
    idle()
    assert api.call(CONFIG_API)['data']['config'] == before, 'Configuration changed before deployment'
    changed = True
    py('from pathlib import Path;import shutil;b=Path(' + repr(backup) + ');r=Path(' + repr(LIVE) + ');'
       '[shutil.copy2(b/"next"/n,r/n) for n in ' + repr(FILES) + ']')
    for attempt in range(2):
        idle()
        api.call('/api/v1/plugins/' + NAME + '/reload', {}, timeout=120)
        current = plugin();state = status()
        report['checks']['reload_' + str(attempt + 1)] = current['activated'] and current['version'] == '1.11.6' and not state['failed'] and not state['startup_pending'] and state['backend'] == saved['backend']
        assert report['checks']['reload_' + str(attempt + 1)], 'Plugin did not restore selected backend'
    report['checks']['source_hashes_match'] = hashes() == expected
    report['checks']['configuration_unchanged'] = api.call(CONFIG_API)['data']['config'] == before
    routes = api.call('/api/plug/qq_persona_models/verify')['data']
    report['checks']['persona_bindings_preserved'] = bool(routes) and all(r['passed'] for r in routes)
    state = api.call('/api/plug/' + NAME + '/context_backend/status')['data']
    report['checks']['page_api_ready'] = state['backend'] == saved['backend'] and not state['startup_pending']
    entry = api.call('/api/v1/plugins/' + NAME + '/views/' + quote('上下文后端'))['data']
    # Asset tokens remain local and are never printed or saved to the report.
    with urllib.request.urlopen(api.base + entry['content_path'], timeout=15) as response:
        html = response.read().decode('utf-8')
    report['checks']['served_page_cache_version'] = './app.js?v=1.11.6' in html
    with urllib.request.urlopen(urljoin(api.base + entry['content_path'], 'app.js?v=1.11.6'), timeout=15) as response:
        script_bytes = response.read()
    report['checks']['served_page_script_matches'] = hashlib.sha256(script_bytes).hexdigest() == expected['pages/上下文后端/app.js']
    report['backend'] = state['backend']
    report['passed'] = all(report['checks'].values())
    assert report['passed'], 'Post-deployment verification failed'
except BaseException as exc:
    report['passed'] = False; report['error_type'] = type(exc).__name__
    if changed:
        idle()
        py('from pathlib import Path;import shutil;b=Path(' + repr(backup) + ');r=Path(' + repr(LIVE) + ');'
           '[shutil.copy2(b/n,r/n) for n in ' + repr(FILES) + ']')
        api.call('/api/v1/plugins/' + NAME + '/reload', {}, timeout=120)
        report['rolled_back'] = hashes() == original and api.call(CONFIG_API)['data']['config'] == before
    write_report('context-lifecycle-deployment.json', report)
    raise
write_report('context-lifecycle-deployment.json', report)
print(json.dumps(report, ensure_ascii=False, indent=2))
