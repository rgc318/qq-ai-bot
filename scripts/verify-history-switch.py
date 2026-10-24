"""Verify a real config off/on cycle, restoring the user's original setting."""
from copy import deepcopy
import json
import time
from deployment_api import DeploymentAPI,write_report

api=DeploymentAPI()
path='/api/v1/plugins/astrbot_plugin_qq_persona_models/config'
status_path='/api/plug/qq_persona_models/chat_history/status'
original=api.call(path)['data']['config']
api.backup('router-before-history-switch-20261024.json',original)
before=api.call(status_path)['data']
off=deepcopy(original)
off.setdefault('history_recall',{})['enabled']=False
checks={}
try:
    api.call(path,{'config':off},method='PUT',timeout=120)
    disabled=api.call(status_path)['data']
    checks['saved_off_stops_store_and_bootstrap']=not disabled['enabled'] and not disabled['initializing'] and not disabled['counts']
    guards=api.call('/api/plug/qq_persona_models/chat_history/verify',{'scenario':'switch'})['data']
    checks['disabled_request_guards_pass']=guards['passed']
finally:
    api.call(path,{'config':original},method='PUT',timeout=120)
after=api.call(status_path)['data']
for _ in range(25):
    if not after['initializing']:break
    time.sleep(0.2)
    after=api.call(status_path)['data']
restored=api.call(path)['data']['config']
checks['original_switch_setting_restored']=restored['history_recall']==original['history_recall']
checks['original_other_settings_preserved']={k:v for k,v in restored.items() if k!='history_recall'}=={k:v for k,v in original.items() if k!='history_recall'}
if before['enabled']:
    checks['reenabled_ready']=after['enabled'] and not after['initializing'] and 'error_type' not in after['bootstrap']
    checks['saved_records_preserved']=after['counts']['documents']>=before['counts']['documents']
report={'passed':all(checks.values()),'checks':checks,'final_enabled':after['enabled'],'before_counts':before['counts'],'after_counts':after['counts'],'qq_messages_sent':0,'model_calls':0}
write_report('history-switch-lifecycle.json',report)
print(json.dumps(report,ensure_ascii=False))
assert report['passed']
