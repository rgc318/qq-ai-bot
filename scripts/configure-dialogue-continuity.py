"""Enable bounded same-speaker continuity without changing models or group rules."""
import copy
import json
from datetime import datetime

from deployment_api import DeploymentAPI, write_report


api=DeploymentAPI()
name='astrbot_plugin_qq_persona_models'
activity=api.call('/api/plug/qq_persona_models/model_activity/status')['data']
assert not activity['active'], 'Wait for active calls before reloading the plugin'
before=api.call('/api/v1/plugins/'+name+'/config')['data']['config']
api.backup('dialogue-continuity-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json',before)
config=copy.deepcopy(before)
config['reply_conditions'].update(dialogue_continuity_enabled=True,dialogue_continuity_window_seconds=600)
api.call('/api/v1/plugins/'+name+'/config',{'config':config},method='PUT',timeout=120)
plugin=next(row for row in api.call('/api/v1/plugins')['data'] if row['name']==name)
assert plugin['activated'] and plugin['version']=='1.7.0', 'New plugin must be loaded'
bindings=api.call('/api/plug/qq_persona_models/verify')['data']
assert all(row['passed'] for row in bindings)
after=api.call('/api/v1/plugins/'+name+'/config')['data']['config']
assert after['bindings']==before['bindings'], 'Model bindings must stay unchanged'
assert {k:v for k,v in after.items() if k!='reply_conditions'}=={k:v for k,v in before.items() if k!='reply_conditions'}
checks=api.call('/api/plug/qq_persona_models/reply_conditions/verify_hooks')['data']
assert checks['passed'], checks
report={'version':plugin['version'],'settings':{k:after['reply_conditions'][k] for k in ('dialogue_continuity_enabled','dialogue_continuity_window_seconds')},
    'bindings':bindings,'native_checks':checks,'qq_messages_sent':0,'model_calls':0}
write_report('dialogue-continuity-configuration.json',report)
print(json.dumps(report,ensure_ascii=False))
