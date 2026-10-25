"""Deploy only the three-file 1.8.1 permission-wrapper hotfix; no model calls.

Does not deploy ContextAware, change configuration, send QQ or replay requests.
Every failed command aborts. Backup and rollback preserve the existing data.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time

from deployment_api import DeploymentAPI,write_report

ROOT=Path(__file__).resolve().parents[1]
NAME='astrbot_plugin_qq_persona_models'
CONTAINER='qq-ai-bot-astrbot-1'
LIVE='/AstrBot/data/plugins/'+NAME
FILES=('image_tool_compat.py','main.py','metadata.yaml')
api=DeploymentAPI()
config_path='/api/v1/plugins/'+NAME+'/config'
before_config=api.call(config_path)['data']['config']
assert before_config['reply_conditions']['allowed_groups']==['347440128'],'Do not expand scope'


def docker(*args):
    return subprocess.run(['wsl','-d','Ubuntu','--exec','docker',*args],capture_output=True,
        text=True,encoding='utf-8',errors='replace',check=True,timeout=60).stdout


def idle():
    stable=0
    for i in range(90):
        active=api.call('/api/plug/qq_persona_models/model_activity/status')['data']['active']
        stable=0 if active else stable+1
        if stable>=3:return
        if active and i%8==0:print('Waiting for active model/tool requests to finish; production unchanged',flush=True)
        time.sleep(2)
    raise RuntimeError('Active model requests remain; no reload performed')


def version():
    return next(p for p in api.call('/api/v1/plugins')['data'] if p['name']==NAME)


def hashes():
    code='import json,hashlib;from pathlib import Path;root=Path('+repr(LIVE)+');names='+repr(FILES)+';print(json.dumps({n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in names}))'
    return json.loads(docker('exec',CONTAINER,'python','-c',code))


expected={n:hashlib.sha256((ROOT/'extensions'/NAME/n).read_bytes()).hexdigest() for n in FILES}
old_version=version()
if old_version['version']=='1.8.1':
    assert hashes()==expected,'Different hotfix already installed; inspect before replacing'
    print('Version 1.8.1 source already matches; no mutation')
    raise SystemExit(0)
assert old_version['version']=='1.8.0' and old_version['activated'],'Unexpected baseline'
idle()
stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
backup='/AstrBot/data/temp/image-guard-backup-'+stamp
stage=backup+'/next'
original=hashes()
api.backup('image-guard-config-before-'+stamp+'.json',before_config)
docker('exec',CONTAINER,'python','-c',
    'from pathlib import Path;import shutil;root=Path('+repr(backup)+');root.mkdir();(root/"next").mkdir();'+
    '[shutil.copy2(Path('+repr(LIVE)+')/n,root/n) for n in '+repr(FILES)+']')
for name in FILES:
    docker('cp','/mnt/e/AI/ai/qq-ai-bot/extensions/'+NAME+'/'+name,CONTAINER+':'+stage+'/'+name)
docker('exec',CONTAINER,'python','-m','compileall','-q',stage)
report={'version':'1.8.1','checks':{},'backup':backup,'model_calls':0,'image_generations':0,'qq_messages_sent':0}
changed=False
try:
    idle()
    changed=True
    docker('exec',CONTAINER,'python','-c','from pathlib import Path;import shutil;'+
        '[shutil.copy2(Path('+repr(stage)+')/n,Path('+repr(LIVE)+')/n) for n in '+repr(FILES)+']')
    idle()
    api.call('/api/v1/plugins/reload',{'plugin_id':NAME},timeout=120)
    current=version()
    report['checks']['version']=current['activated'] and current['version']=='1.8.1'
    report['checks']['source_hashes_match']=hashes()==expected
    report['checks']['configuration_unchanged']=api.call(config_path)['data']['config']==before_config
    for mode in ('attachments_only','image_reference_only','image_notice_only','recent_upload_only','image_followup_only'):
        result=api.call('/api/plug/qq_persona_models/verify_memory_meme',{mode:True},timeout=120)['data']
        assert result.get('model_calls',0)==0 and result.get('qq_messages_sent',0)==0,'Unexpected diagnostic side effects'
        report['checks'][mode]=result['passed']
        report[mode+'_count']=len(result.get('checks',{}))
        print(mode,result['passed'],len(result.get('checks',{})),flush=True)
    report['checks']['persona_bindings']=all(r['passed'] for r in api.call('/api/plug/qq_persona_models/verify')['data'])
    report['passed']=all(report['checks'].values())
    assert report['passed'],'Hotfix verification failed'
except BaseException as exc:
    report['passed']=False;report['error_type']=type(exc).__name__
    if changed:
        idle()
        docker('exec',CONTAINER,'python','-c','from pathlib import Path;import shutil;'+
            '[shutil.copy2(Path('+repr(backup)+')/n,Path('+repr(LIVE)+')/n) for n in '+repr(FILES)+']')
        api.call('/api/v1/plugins/reload',{'plugin_id':NAME},timeout=120)
        report['rolled_back']=hashes()==original and version()['version']==old_version['version']
    write_report('image-guard-hotfix-deployment.json',report)
    raise
write_report('image-guard-hotfix-deployment.json',report)
print(json.dumps(report,ensure_ascii=False,indent=2))
