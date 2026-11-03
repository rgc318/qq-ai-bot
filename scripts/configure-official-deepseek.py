"""Trial the tested official 1017 route for Whale only, with rollback."""
from copy import deepcopy
from datetime import datetime
import json
import sys
import time
from urllib.parse import quote

from deployment_api import DeploymentAPI,ROOT,write_report
sys.path.insert(0,str(ROOT/'extensions/astrbot_plugin_qq_persona_models'))
from persona_bindings import binding_map,binding_rows

api=DeploymentAPI();source_id='deepseek-official';provider_id=source_id+'/deepseek-flash'
local='/api/v1/plugins/astrbot_plugin_qq_persona_models/config'
comparison=json.loads((ROOT/'logs/deepseek-provider-comparison.json').read_text(encoding='utf-8'))
assert comparison['passed'] and comparison['real_history_replayed'] is False
assert all(r['reasoning_chars']==0 for r in comparison['rows'])
assert len([r for r in comparison['rows'] if r['route']=='official' and r['case']=='long_image' and r['input_tokens']>=11000])>=3
key=next(line.split('=',1)[1].strip() for line in (ROOT/'secrets/deepseek-official.env').read_text(encoding='utf-8-sig').splitlines() if line.startswith('DEEPSEEK_API_KEY='))


def idle():
    stable=0
    for _ in range(30):
        a=api.call('/api/plug/qq_persona_models/model_activity/status')['data']
        b=api.call('/api/plug/qq_persona_models/context_backend/status')['data']
        s=api.call('/api/plug/astrbot_plugin_self_initiated_reply/status');s=s.get('data',s)
        busy=a['active'] or b['active_requests'] or b['pending_messages'] or b['switching'] or any(s.get('tasks',{}).get(k,0) for k in ('delay','running_check')) or s.get('gate',{}).get('running')
        stable=0 if busy else stable+1
        if stable>=2:return
        time.sleep(2)
    raise RuntimeError('Current work active; no configuration changed')


def providers():return api.call('/api/config/provider/template')['data']['providers']


idle()
before=api.call(local)['data']['config'];original_bindings=binding_map(before)
old_provider=original_bindings['大肥鱼'];all_before=providers()
original=deepcopy(next(p for p in all_before if p['id']==old_provider))
assert original['model']=='siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017'
profile=api.call('/api/v1/config-profiles/default')['data']['config']
assert all(s['id']!=source_id for s in profile['provider_sources']) and all(p['id']!=provider_id for p in all_before),'Review existing official source; not overwriting'
policy_before=api.call('/api/plug/astrbot_plugin_user_policy/bootstrap')['data'];policy_keys=('revision','groups','private_users','schedules')
policy_before={k:policy_before.get(k) for k in policy_keys}
personas_before=api.call('/api/persona/list')['data']
ambient_before=api.call('/api/v1/plugins/astrbot_plugin_self_initiated_reply/config')['data']['config']
backend_before=api.call('/api/plug/qq_persona_models/context_backend/status')['data']['backend']
stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
api.backup('official-deepseek-bindings-before-'+stamp+'.json',before)
api.backup('official-deepseek-profile-before-'+stamp+'.json',profile)
source={'id':source_id,'provider':'openai','type':'openai_chat_completion','provider_type':'chat_completion','enable':True,
        'key':[key],'api_base':'https://api.deepseek.com/v1','timeout':120,'proxy':'','custom_headers':{}}
provider=deepcopy(original);provider.update(id=provider_id,provider_source_id=source_id,model='deepseek-flash',enable=True,
    modalities=['text','image','tool_use'],custom_extra_body={'max_tokens':4096,'thinking':{'type':'disabled'}})
next_config=deepcopy(before);next_bindings=dict(original_bindings);next_bindings['大肥鱼']=provider_id
next_config['bindings']=binding_rows(next_bindings)
report={'checks':{},'previous_provider':old_provider,'selected_provider':provider_id,'source':source_id,'model':'deepseek-flash',
        'thinking':'disabled','backup_stamp':stamp,'qq_messages_sent':0,'real_history_replayed':False}
created_source=False;created_provider=False;switched=False
try:
    idle();assert api.call(local)['data']['config']==before,'Plugin config changed while waiting'
    api.call('/api/v1/provider-sources',{'config':source});created_source=True
    api.call('/api/v1/providers',{'config':provider});created_provider=True
    test=api.call('/api/v1/providers/test',{'provider_id':provider_id},timeout=90)
    # API envelopes are also 'ok' when the service reports 'unavailable'.
    # No real group context is passed to this synthetic connectivity test.
    report['native_provider_test']=(test.get('data') or {}).get('status')=='available'
    assert report['native_provider_test'],'Native official provider test failed'
    idle();assert api.call(local)['data']['config']==before,'Plugin config changed during native test'
    switched=True;api.call(local,{'config':next_config},method='PUT',timeout=120)
    actual=api.call(local)['data']['config'];verified=api.call('/api/plug/qq_persona_models/verify')['data']
    report['checks']['only_whale_binding_changed']=actual==next_config and binding_map(actual)==next_bindings
    report['checks']['runtime_binding_verified']=all(r['passed'] for r in verified) and next(r for r in verified if r['persona']=='大肥鱼')['selected_provider']==provider_id
    all_after=providers();loaded=next(p for p in all_after if p['id']==provider_id)
    report['checks']['official_non_thinking_config']=loaded['custom_extra_body']==provider['custom_extra_body'] and loaded['model']=='deepseek-flash'
    report['checks']['all_previous_providers_preserved']=all(next(p for p in all_after if p['id']==old['id'])==old for old in all_before)
    current_profile=api.call('/api/v1/config-profiles/default')['data']['config']
    report['checks']['existing_sources_preserved']=all(next(s for s in current_profile['provider_sources'] if s['id']==old['id'])==old for old in profile['provider_sources'])
    current_policy=api.call('/api/plug/astrbot_plugin_user_policy/bootstrap')['data']
    report['checks']['personas_and_group_policy_preserved']=api.call('/api/persona/list')['data']==personas_before and {k:current_policy.get(k) for k in policy_keys}==policy_before
    report['checks']['judge_and_image_settings_preserved']=actual['reply_conditions']==before['reply_conditions'] and api.call('/api/v1/plugins/astrbot_plugin_self_initiated_reply/config')['data']['config']==ambient_before
    backend=api.call('/api/plug/qq_persona_models/context_backend/status')['data']
    report['checks']['backend_and_task_guard_ready']=backend['backend']==backend_before and not backend['failed'] and backend['task_completion']['installed']
    report['passed']=all(report['checks'].values());assert report['passed'],'Post-switch verification failed'
except BaseException as exc:
    report['passed']=False;report['error_type']=type(exc).__name__
    if switched:api.call(local,{'config':before},method='PUT',timeout=120)
    if created_provider:api.call('/api/v1/providers/by-id?provider_id='+quote(provider_id,safe=''),method='DELETE')
    if created_source:api.call('/api/v1/provider-sources/by-id?source_id='+source_id,method='DELETE')
    report['rolled_back']=True;write_report('official-deepseek-configuration.json',report);raise
write_report('official-deepseek-configuration.json',report)
print(json.dumps(report,ensure_ascii=False,indent=2))
