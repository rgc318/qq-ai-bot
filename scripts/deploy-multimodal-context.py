"""Deploy the tested local plugin; only the existing test group gains media indexing.

Run with access to the existing local AstrBot API and WSL Docker. No QQ sends,
model calls, image generation or real-history replays are part of this script.
"""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time
from deployment_api import DeploymentAPI,write_report

ROOT=Path(__file__).resolve().parents[1]
NAME='astrbot_plugin_qq_persona_models'
VERSION='1.8.1'
CONTAINER='qq-ai-bot-astrbot-1'
api=DeploymentAPI()
path='/api/v1/plugins/'+NAME+'/config'
old=api.call(path)['data']['config']
assert old['reply_conditions']['allowed_groups']==['347440128'], 'Do not expand the deployment scope'
stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
backup='/AstrBot/data/temp/qq-media-backup-'+stamp
candidate='/AstrBot/data/temp/qq-media-stage-'+stamp
live='/AstrBot/data/plugins/'+NAME

def docker(*args):
    subprocess.run(['wsl','-d','Ubuntu','--exec','docker',*args],check=True,capture_output=True,text=True,timeout=60)

def idle():
    for _ in range(15):
        active=api.call('/api/plug/qq_persona_models/model_activity/status')['data']['active']
        if not active:return
        time.sleep(2)
    raise RuntimeError('Active model requests remain; no subsequent reload is authorized by this check')

def version():
    item=next(x for x in api.call('/api/v1/plugins')['data'] if x['name']==NAME)
    assert item['activated'] and item['version']==VERSION, 'Do not call new diagnostics on an older plugin'

idle()
api.backup('multimodal-config-before-'+stamp+'.json',old)
docker('exec',CONTAINER,'python','-c',f'import shutil;shutil.copytree({live!r},{backup!r})')
changed=False
report={'backup_stamp':stamp,'qq_messages_sent':0,'image_generations':0,'model_calls':0,'checks':{}}
try:
    docker('cp','/mnt/e/AI/ai/qq-ai-bot/extensions/'+NAME,CONTAINER+':'+candidate)
    docker('exec',CONTAINER,'python','-m','compileall','-q',candidate)
    docker('exec',CONTAINER,'python','-c',f'import shutil;shutil.copytree({candidate!r},{live!r},dirs_exist_ok=True)')
    changed=True
    api.call('/api/v1/plugins/reload',{'plugin_id':NAME},timeout=120)
    version()
    # Config saving also reloads; independently gate that operation.
    idle()
    config=deepcopy(old)
    config['multimodal_context']={'enabled':True,'auto_attach':True,'auto_attach_seconds':180,'on_demand_read':True,'documents':True,'media_ttl_seconds':86400,'message_ttl_seconds':604800,'messages_per_scope':5000,'catalog_chars':1800,'scope_bytes':134217728,'total_bytes':536870912}
    api.call(path,{'config':config},method='PUT',timeout=120)
    version()
    current=api.call(path)['data']['config']
    report['checks']['other_settings_preserved']={k:v for k,v in current.items() if k!='multimodal_context'}=={k:v for k,v in old.items() if k!='multimodal_context'}
    report['checks']['test_group_only']=current['reply_conditions']['allowed_groups']==['347440128']
    for mode in ('attachments_only','recent_upload_only','image_followup_only','image_reference_only','image_notice_only','group_permissions_only','model_logging_only'):
        version()
        result=api.call('/api/plug/qq_persona_models/verify_memory_meme',{mode:True},timeout=120)['data']
        assert 'checks' in result and 'passed' in result, 'Unexpected diagnostic response'
        if mode=='attachments_only':assert 'native_runner_requests_real_visual_content' in result['checks']
        report[mode]=result
        report['checks'][mode]=result['passed']
        print(mode,result['passed'],len(result['checks']),flush=True)
    hooks=api.call('/api/plug/qq_persona_models/reply_conditions/verify_hooks')['data']
    report['checks']['reply_hooks']=hooks['passed']
    bindings=api.call('/api/plug/qq_persona_models/verify')
    report['checks']['persona_bindings']=all(x['passed'] for x in bindings['data'])
    tools=api.call('/api/v1/tools')['data']
    report['checks']['attachment_tools_registered']={'read_group_message','view_context_images','read_context_document'}.issubset({t['name'] for t in tools if t.get('active')})
    report['status']=api.call('/api/plug/qq_persona_models/attachments/status')['data']
    report['passed']=all(report['checks'].values())
    write_report('multimodal-deployment-verification.json',report)
    assert report['passed'], 'Deployment verification failed'
    print(json.dumps({'passed':True,'version':VERSION,'checks':report['checks'],'measurements':report['attachments_only']['measurements']},ensure_ascii=False))
except Exception as exc:
    report['passed']=False;report['error_type']=type(exc).__name__
    if changed:
        idle()
        # Restore inside the container; no deletion of histories or media.
        docker('exec',CONTAINER,'python','-c',f'import shutil;shutil.copytree({backup!r},{live!r},dirs_exist_ok=True)')
        api.call(path,{'config':old},method='PUT',timeout=120)
        report['rolled_back']=True
    write_report('multimodal-deployment-verification.json',report)
    raise
