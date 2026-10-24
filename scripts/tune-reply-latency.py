"""Adjust only the long follow-up window and ordinary-chat debounce."""
import json
from deployment_api import DeploymentAPI,write_report
api=DeploymentAPI()
router_name='astrbot_plugin_qq_persona_models'
ambient_name='astrbot_plugin_self_initiated_reply'
r=api.call('/api/v1/plugins/'+router_name+'/config')['data']['config']
s=api.call('/api/v1/plugins/'+ambient_name+'/config')['data']['config']
api.backup('router-before-latency-tuning.json',r)
api.backup('ambient-before-latency-tuning.json',s)
r['reply_conditions']['followup_window_seconds']=1800
s.update(message_delay_sec=5,min_silence_sec=5)
api.call('/api/v1/plugins/'+router_name+'/config',{'config':r},method='PUT',timeout=120)
api.call('/api/v1/plugins/'+ambient_name+'/config',{'config':s},method='PUT',timeout=120)
live_router=api.call('/api/plug/qq_persona_models/reply_conditions/status')['data']['settings']
live_ambient=api.call('/api/plug/astrbot_plugin_self_initiated_reply/config')
result={'followup_window_seconds':live_router['followup_window_seconds'],'message_delay_sec':live_ambient['message_delay_sec'],'min_silence_sec':live_ambient['min_silence_sec'],'cooldown_sec':live_ambient['cooldown_sec'],'qq_messages_sent':0}
assert result['followup_window_seconds']==1800 and result['message_delay_sec']==result['min_silence_sec']==5
write_report('reply-latency-settings.json',result)
print(json.dumps(result,ensure_ascii=False))
