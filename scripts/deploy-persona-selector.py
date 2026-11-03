"""Upgrade 1.11.4 to native persona/model selectors without model or QQ calls.

Back up changed files and raw config in the existing volume. Wait for idle,
reload only this plugin, verify binding equivalence and restore on failure.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from deployment_api import DeploymentAPI, ROOT, write_report

NAME = 'astrbot_plugin_qq_persona_models'
CONTAINER = 'qq-ai-bot-astrbot-1'
LIVE = '/AstrBot/data/plugins/' + NAME
CONFIG_FILE = '/AstrBot/data/config/' + NAME + '_config.json'
CONFIG_API = '/api/v1/plugins/' + NAME + '/config'
FILES = ('persona_bindings.py', '_conf_schema.json', 'main.py', 'metadata.yaml',
         'attachment_context.py', 'dialogue_checks.py', 'image_quote_checks.py')
sys.path.insert(0, str(ROOT / 'extensions' / NAME))
from persona_bindings import binding_map, binding_rows


def docker(*args):
    return subprocess.run(['wsl', '-d', 'Ubuntu', '--exec', 'docker', *args],
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', check=True, timeout=120).stdout


def py(code):
    return docker('exec', CONTAINER, 'python', '-c', code)


api = DeploymentAPI()


def plugin():
    return next(p for p in api.call('/api/v1/plugins')['data'] if p['name'] == NAME)


def idle():
    stable = 0
    for i in range(30):
        active = api.call('/api/plug/qq_persona_models/model_activity/status')['data']['active']
        backend = api.call('/api/plug/qq_persona_models/context_backend/status')['data']
        proactive = api.call('/api/plug/astrbot_plugin_self_initiated_reply/status')
        proactive = proactive.get('data', proactive)
        queued = any(proactive.get('tasks', {}).get(k, 0) for k in ('delay', 'running_check')) or bool(proactive.get('gate', {}).get('running'))
        busy = active or queued or backend['active_requests'] or backend['pending_messages'] or backend['switching']
        stable = 0 if busy else stable + 1
        if stable >= 2:
            return
        if busy and i % 10 == 0:
            print('Waiting for current model/tool work before reload', flush=True)
        time.sleep(2)
    raise RuntimeError('Requests remain active; no reload performed')


def hashes():
    return json.loads(py('from pathlib import Path;import json,hashlib;r=Path(' + repr(LIVE) + ');'
        'print(json.dumps({n:hashlib.sha256((r/n).read_bytes()).hexdigest() if (r/n).is_file() else None for n in ' + repr(FILES) + '}))'))


old_plugin = plugin()
assert old_plugin['activated'] and old_plugin['version'] == '1.11.4', 'Review the changed baseline first'
before = api.call(CONFIG_API)['data']['config']
expected_config = {**before, 'bindings': binding_rows(before.get('bindings', {}))}
expected_bindings = binding_map(before)
assert expected_bindings, 'Review empty bindings before migration'
providers = api.call('/api/config/provider/template')['data']['providers']
assert all(any(p['id'] == pid for p in providers) for pid in expected_bindings.values()), 'A bound provider is missing'
original = hashes()
expected = {n: hashlib.sha256((ROOT / 'extensions' / NAME / n).read_bytes()).hexdigest() for n in FILES}
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup = '/AstrBot/data/temp/persona-selector-' + stamp
api.backup('persona-selector-config-before-' + stamp + '.json', before)
report = {'version': '1.11.5', 'backup': backup, 'checks': {}, 'model_calls': 0, 'qq_messages_sent': 0}
changed = False
idle()
# Refuse to overwrite edits made while waiting for existing work.
assert api.call(CONFIG_API)['data']['config'] == before, 'Config changed during idle wait'
py('from pathlib import Path;import shutil;b=Path(' + repr(backup) + ');b.mkdir();(b/"next").mkdir();'
   'r=Path(' + repr(LIVE) + ');'
   '[shutil.copy2(r/n,b/n) for n in ' + repr(FILES) + ' if (r/n).is_file()];'
   'shutil.copy2(' + repr(CONFIG_FILE) + ',b/"previous-config.json")')
for name in FILES:
    docker('cp', '/mnt/e/AI/ai/qq-ai-bot/extensions/' + NAME + '/' + name, CONTAINER + ':' + backup + '/next/' + name)
docker('exec', CONTAINER, 'python', '-m', 'compileall', '-q', backup + '/next')
try:
    idle()
    assert api.call(CONFIG_API)['data']['config'] == before, 'Config changed before file update'
    changed = True
    py('from pathlib import Path;import shutil;b=Path(' + repr(backup) + ');r=Path(' + repr(LIVE) + ');'
       '[shutil.copy2(b/"next"/n,r/n) for n in ' + repr(FILES) + ']')
    api.call('/api/v1/plugins/reload', {'plugin_id': NAME}, timeout=120)
    data = api.call(CONFIG_API)['data']
    after = data['config']
    schema = data['metadata'][NAME]['items']['bindings']
    report['checks']['version'] = plugin()['version'] == '1.11.5' and plugin()['activated']
    report['checks']['source_hashes_match'] = hashes() == expected
    report['checks']['only_binding_structure_changed'] = after == expected_config
    report['checks']['same_persona_model_pairs'] = binding_map(after) == expected_bindings
    report['checks']['native_selectors'] = schema['type'] == 'template_list' and schema['templates']['binding']['items']['provider_id']['_special'] == 'select_provider' and schema['templates']['binding']['items']['persona_id']['_special'] == 'select_persona'
    verification = api.call('/api/plug/qq_persona_models/verify')['data']
    report['checks']['runtime_routes_preserved'] = len(verification) == len(expected_bindings) and all(r['passed'] for r in verification)
    # Exercise the real save/reload path with exactly the migrated values.
    idle()
    assert api.call(CONFIG_API)['data']['config'] == expected_config, 'Config changed before round-trip test'
    api.call(CONFIG_API, {'config': expected_config}, method='PUT', timeout=120)
    report['checks']['native_save_round_trip'] = api.call(CONFIG_API)['data']['config'] == expected_config
    verification = api.call('/api/plug/qq_persona_models/verify')['data']
    report['checks']['saved_routes_preserved'] = len(verification) == len(expected_bindings) and all(r['passed'] for r in verification)
    backend = api.call('/api/plug/qq_persona_models/context_backend/status')['data']
    report['checks']['context_backend_ready'] = not backend['failed']
    report['binding_count'] = len(expected_bindings)
    report['passed'] = all(report['checks'].values())
    assert report['passed'], 'Selector deployment verification failed'
except BaseException as exc:
    report['passed'] = False
    report['error_type'] = type(exc).__name__
    if changed:
        idle()
        py('from pathlib import Path;import shutil;b=Path(' + repr(backup) + ');r=Path(' + repr(LIVE) + ');'
           '[shutil.copy2(b/n,r/n) if (b/n).is_file() else (r/n).unlink(missing_ok=True) for n in ' + repr(FILES) + '];'
           'shutil.copy2(b/"previous-config.json",' + repr(CONFIG_FILE) + ')')
        api.call('/api/v1/plugins/reload', {'plugin_id': NAME}, timeout=120)
        report['rolled_back'] = hashes() == original and api.call(CONFIG_API)['data']['config'] == before
    write_report('persona-selector-deployment.json', report)
    raise
write_report('persona-selector-deployment.json', report)
print(json.dumps(report, ensure_ascii=False, indent=2))
