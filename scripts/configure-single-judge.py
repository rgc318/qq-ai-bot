"""Configure one bounded lightweight classification; preserve persona models."""
import copy
import json
from deployment_api import DeploymentAPI,write_report
api=DeploymentAPI()
provider=next(p for p in api.call('/api/config/provider/template')['data']['providers'] if p['id']=='qq-reply-judge-fast')
api.backup('judge-before-single-judge-20261023.json',provider)
provider=copy.deepcopy(provider)
provider['model']='siliconflow/Qwen/Qwen3-30B-A3B-Instruct-2507'
provider['custom_extra_body']={'max_tokens':180,'temperature':0.1,'response_format':{'type':'json_object'}}
api.call('/api/config/provider/update',{'id':provider['id'],'config':provider})
name='astrbot_plugin_qq_persona_models'
config=api.call('/api/v1/plugins/'+name+'/config')['data']['config']
api.backup('router-before-single-judge-20261023.json',config)
config['reply_conditions'].update(judge_timeout_seconds=8,judge_failure_backoff_seconds=15,single_judge=True,judge_recent_messages=12,judge_recent_chars=3600)
api.call('/api/v1/plugins/'+name+'/config',{'config':config},method='PUT',timeout=120)
name='astrbot_plugin_self_initiated_reply'
ambient=api.call('/api/v1/plugins/'+name+'/config')['data']['config']
api.backup('selfreply-before-single-judge-20261023.json',ambient)
ambient['judge_provider_id']='qq-reply-judge-fast'
ambient['decision_timeout_sec']=8
api.call('/api/v1/plugins/'+name+'/config',{'config':ambient},method='PUT',timeout=120)
bindings=api.call('/api/plug/qq_persona_models/verify')['data']
report={'judge_provider':provider['id'],'judge_model':provider['model'],'settings':config['reply_conditions'],'ambient_timeout':ambient['decision_timeout_sec'],'persona_bindings':bindings,'qq_messages_sent':0}
write_report('single-judge-settings.json',report)
print(json.dumps(report,ensure_ascii=False))
assert all(row['passed'] for row in bindings)
