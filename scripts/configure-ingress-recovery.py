"""Apply the incident-specific ambient prompt correction, preserving other settings."""
import json
from deployment_api import DeploymentAPI,write_report
api=DeploymentAPI()
name='astrbot_plugin_self_initiated_reply'
config=api.call('/api/v1/plugins/'+name+'/config')['data']['config']
api.backup('ambient-before-ingress-recovery.json',config)
note='\n补充：独立的具体能力请求（例如“发个开心的表情包”）不是纯附和；本群约定独立、肯定的表情发送指令默认由机器人受理，不要求昵称或既往AI任务。如果前文机器人刚发表情或图片，要求换一种情绪的表情可以是同一任务的延续。没有明确指向其他群友的证据时，不要凭空判定“发给别人”。有群友正在互相索要表情、转述或拒绝回应时仍保持安静。'
if note not in config['decision_prompt_template']:
    config['decision_prompt_template']+=note
api.call('/api/v1/plugins/'+name+'/config',{'config':config},method='PUT',timeout=120)
live=api.call('/api/plug/astrbot_plugin_self_initiated_reply/config')
report={'prompt_correction_present':note in live['decision_prompt_template'],'message_delay_sec':live['message_delay_sec'],'min_silence_sec':live['min_silence_sec'],'cooldown_sec':live['cooldown_sec'],'qq_messages_sent':0}
assert report['prompt_correction_present']
write_report('ingress-recovery-settings.json',report)
print(json.dumps(report,ensure_ascii=False))
