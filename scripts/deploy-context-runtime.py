"""Deploy the locked context runtime with idle gates and reversible directory swaps.

Uses existing authenticated local APIs; no model calls, QQ sends or real replay.
No history/config migration. Backups stay in the same AstrBot data volume.
"""
from datetime import datetime
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time

from deployment_api import DeploymentAPI,write_report

ROOT=Path(__file__).resolve().parents[1]
NAME='astrbot_plugin_qq_persona_models'
CONTAINER='qq-ai-bot-astrbot-1'
LIVE='/AstrBot/data/plugins/'+NAME
DATA='/AstrBot/data/plugin_data/'+NAME
SOURCE=DATA+'/contextaware-source'
VERSION='1.11.1'
api=DeploymentAPI()
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline',choices=('1.8.1','1.9.0','1.10.0','1.11.0','1.11.1'),default='1.11.0',help='Explicitly reviewed live version')
args=parser.parse_args()
CONFIG='/api/v1/plugins/'+NAME+'/config'
before_config=api.call(CONFIG)['data']['config']
assert before_config['reply_conditions']['allowed_groups']==['347440128'],'Scope expansion is forbidden'
assert before_config.get('multimodal_context',{}).get('enabled'),'Existing shared archive must be enabled'
OMNI_CONFIG='/api/v1/plugins/astrbot_plugin_omnidraw/config'
before_omni=api.call(OMNI_CONFIG)['data']['config']
next_omni=deepcopy(before_omni);next_omni.setdefault('optimizer_config',{})['max_batch_count']=4
assert before_omni.get('optimizer_config',{}).get('max_batch_count') in (1,4),'Review unexpected batch baseline'


def docker(*args):
    return subprocess.run(['wsl','-d','Ubuntu','--exec','docker',*args],capture_output=True,
        text=True,encoding='utf-8',errors='replace',check=True,timeout=120).stdout


def py(code):return docker('exec',CONTAINER,'python','-c',code)


def plugin():return next(p for p in api.call('/api/v1/plugins')['data'] if p['name']==NAME)


def idle():
    stable=0
    for i in range(90):
        active=api.call('/api/plug/qq_persona_models/model_activity/status')['data']['active']
        proactive=api.call('/api/plug/astrbot_plugin_self_initiated_reply/status')
        proactive=proactive.get('data',proactive)
        queued=any(proactive.get('tasks',{}).get(k,0) for k in ('delay','running_check')) or bool(proactive.get('gate',{}).get('running'))
        owned=False
        if plugin()['version'] in ('1.9.0','1.10.0','1.11.0','1.11.1'):
            runtime=backend();owned=runtime['active_requests'] or runtime['pending_messages'] or runtime['switching']
        stable=0 if active or queued or owned else stable+1
        if stable>=3:return
        if active and i%8==0:print('Waiting for current model/tool work; no reload yet',flush=True)
        time.sleep(2)
    raise RuntimeError('Requests remain active; deployment stopped at idle gate')


def backend():return api.call('/api/plug/qq_persona_models/context_backend/status')['data']


def switch(mode):
    state=api.call('/api/plug/qq_persona_models/context_backend/switch',{'mode':mode},timeout=120)['data']
    assert state['backend']==mode and not state['failed']
    return state


def live_hashes():
    return json.loads(py('import json,hashlib;from pathlib import Path;r=Path('+repr(LIVE)+');print(json.dumps({str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in r.rglob("*") if p.is_file() and "__pycache__" not in p.parts}))'))


old=plugin()
assert old['activated'] and old['version']==args.baseline,'Review a changed production baseline before deployment'
original=live_hashes()
stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
backup='/AstrBot/data/temp/context-runtime-backup-'+stamp
report={'version':VERSION,'backup':backup,'checks':{},'model_calls':0,'image_generations':0,'qq_messages_sent':0}
api.backup('context-runtime-config-before-'+stamp+'.json',before_config)
api.backup('multi-image-omnidraw-before-'+stamp+'.json',before_omni)
native_hashes=json.loads((ROOT/'downloads/omnidraw-native-source/test-source-hashes.json').read_text(encoding='utf-8'))
current_hashes=json.loads(py('import json,hashlib;from pathlib import Path;r=Path("/AstrBot/data/plugins/astrbot_plugin_omnidraw");names='+repr(list(native_hashes))+';print(json.dumps({n:hashlib.sha256((r/n).read_bytes()).hexdigest() for n in names}))'))
assert current_hashes==native_hashes,'OmniDraw source changed since native wire tests'
report['checks']['omnidraw_source_matches_native_test']=True
lock=json.loads((ROOT/'integrations/contextaware/source-lock.json').read_text(encoding='utf-8'))
source=ROOT/'downloads/contextaware-f026c56'
for name,entry in lock['files'].items():
    assert Path(name).name==name
    assert hashlib.sha256((source/name).read_bytes()).hexdigest()==entry['sha256'],name

changed=False
omni_changed=False
try:
    with TemporaryDirectory(dir=ROOT/'downloads',prefix='context-runtime-stage-') as temp:
        stage=Path(temp);target=stage/'next'
        shutil.copytree(ROOT/'extensions'/NAME,target,ignore=shutil.ignore_patterns('__pycache__','_ca_runtime'))
        shutil.copytree(ROOT/'integrations/contextaware',target/'_ca_runtime',ignore=shutil.ignore_patterns('__pycache__'))
        expected={str(p.relative_to(target)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
        (stage/'source').mkdir()
        for name in lock['files']:shutil.copy2(source/name,stage/'source'/name)
        idle()
        py('from pathlib import Path;p=Path('+repr(backup)+');assert p.parent==Path("/AstrBot/data/temp");p.mkdir()')
        wsl_stage='/mnt/e/AI/ai/qq-ai-bot/downloads/'+stage.name
        docker('cp',wsl_stage+'/next',CONTAINER+':'+backup+'/next')
        docker('cp',wsl_stage+'/source',CONTAINER+':'+backup+'/source')
    docker('exec',CONTAINER,'python','-m','compileall','-q',backup+'/next',backup+'/source')
    idle()
    py('from pathlib import Path;import shutil;b=Path('+repr(backup)+');state=Path('+repr(DATA)+')/"context_backend.json";'
       'shutil.copy2(state,b/"previous-mode.json") if state.exists() else None')
    changed=True
    # All moves stay inside the exact named data/plugin or backup directories.
    py('from pathlib import Path;import shutil;live=Path('+repr(LIVE)+');b=Path('+repr(backup)+');src=Path('+repr(SOURCE)+');state=src.parent/"context_backend.json";'
       'assert live.parent==Path("/AstrBot/data/plugins") and b.parent==Path("/AstrBot/data/temp");'
       'src.rename(b/"previous-source") if src.exists() else None;'
       '(b/"source").rename(src);live.rename(b/"previous-plugin");(b/"next").rename(live)')
    if before_omni!=next_omni:
        omni_changed=True
        api.call(OMNI_CONFIG,{'config':next_omni},method='PUT',timeout=120)
    api.call('/api/v1/plugins/reload',{'plugin_id':NAME},timeout=120)
    current=plugin()
    report['checks']['version']=current['activated'] and current['version']==VERSION
    report['checks']['source_hashes_match']=live_hashes()==expected
    report['checks']['configuration_unchanged']=api.call(CONFIG)['data']['config']==before_config
    report['checks']['omnidraw_only_batch_limit_changed']=api.call(OMNI_CONFIG)['data']['config']==next_omni
    batch_status=api.call('/api/plug/qq_persona_models/image_batch/status')['data']
    report['checks']['batch_ready']=batch_status=={'ready':True,'max_images_per_request':4,'max_image_attempts':5,'concurrency':2,'timeouts_ready':True,'image_tool_timeout_seconds':600}
    state=backend()
    report['checks']['candidate_ready']=any(c['value']=='contextaware' and c['available'] for c in state['choices'])
    report['checks']['page_registered']=any('上下文后端' in str(p) for p in current.get('pages',[]))
    report['checks']['page_namespace_api']=api.call('/api/plug/'+NAME+'/context_backend/status')['data']['backend']==state['backend']
    assert all(report['checks'].values()),'Runtime initialization verification failed'
    for mode in ('attachments_only','image_reference_only','image_notice_only','recent_upload_only','image_followup_only','model_logging_only','group_permissions_only','image_task_only','image_batch_only'):
        result=api.call('/api/plug/qq_persona_models/verify_memory_meme',{mode:True},timeout=120)['data']
        assert result.get('model_calls',0)==0 and result.get('qq_messages_sent',0)==0,'Unexpected diagnostic side effects'
        report['checks'][mode]=result['passed'];report[mode+'_count']=len(result.get('checks',{}))
        print(mode,result['passed'],len(result.get('checks',{})),flush=True)
    report['checks']['persona_bindings']=all(r['passed'] for r in api.call('/api/plug/qq_persona_models/verify')['data'])
    tools=api.call('/api/v1/tools')['data']
    report['checks']['history_tool_enabled']=any(t['name']=='browse_group_history' and t.get('active') for t in tools)
    before_stats=api.call('/api/plug/qq_persona_models/attachments/status')['data']
    idle();switch('contextaware');switch('builtin');switch('contextaware')
    after_stats=api.call('/api/plug/qq_persona_models/attachments/status')['data']
    report['checks']['switch_preserves_archive']=before_stats==after_stats
    report['checks']['test_group_scope_unchanged']=api.call(CONFIG)['data']['config']==before_config
    report['backend']=backend()
    report['passed']=all(report['checks'].values())
    assert report['passed'],'Deployment verification failed'
except BaseException as exc:
    report['passed']=False;report['error_type']=type(exc).__name__
    if changed:
        idle()
        py('from pathlib import Path;import shutil;live=Path('+repr(LIVE)+');b=Path('+repr(backup)+');src=Path('+repr(SOURCE)+');state=src.parent/"context_backend.json";'
           'assert live.parent==Path("/AstrBot/data/plugins") and b.parent==Path("/AstrBot/data/temp");'
           'live.rename(b/"failed-plugin") if (b/"previous-plugin").exists() and live.exists() else None;'
           '(b/"previous-plugin").rename(live) if (b/"previous-plugin").exists() else None;'
           'src.rename(b/"failed-source") if src.exists() and not (b/"source").exists() else None;'
           '(b/"previous-source").rename(src) if (b/"previous-source").exists() else None;'
           'shutil.copy2(b/"previous-mode.json",state) if (b/"previous-mode.json").exists() else state.unlink(missing_ok=True)')
        api.call('/api/v1/plugins/reload',{'plugin_id':NAME},timeout=120)
        if omni_changed:api.call(OMNI_CONFIG,{'config':before_omni},method='PUT',timeout=120)
        report['rolled_back']=live_hashes()==original and plugin()['version']==old['version']
        report['configuration_unchanged_after_rollback']=api.call(CONFIG)['data']['config']==before_config
        report['omnidraw_restored_after_rollback']=api.call(OMNI_CONFIG)['data']['config']==before_omni
    write_report('context-runtime-deployment.json',report)
    raise
write_report('context-runtime-deployment.json',report)
print(json.dumps(report,ensure_ascii=False,indent=2))
