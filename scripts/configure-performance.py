"""Back up database/settings, then reduce chat context and automatic recall latency."""
import copy
import json
import subprocess
from deployment_api import DeploymentAPI,ROOT,write_report

api=DeploymentAPI()
backup=ROOT/'secrets/enhancement-backup/performance-before-20261023.db'
if not backup.exists():
    code='''import sqlite3
src=sqlite3.connect("file:/AstrBot/data/data_v4.db?mode=ro",uri=True)
dst=sqlite3.connect("/AstrBot/data/temp/performance-before-20261023.db")
src.backup(dst)
dst.close()
src.close()
'''
    proc=subprocess.run(['wsl','-d','Ubuntu','--exec','docker','exec','-i','qq-ai-bot-astrbot-1','python','-'],input=code,capture_output=True,text=True)
    if proc.returncode:raise RuntimeError('Database backup failed')
    target='/mnt/e/AI/ai/qq-ai-bot/secrets/enhancement-backup/performance-before-20261023.db'
    copied=subprocess.run(['wsl','-d','Ubuntu','--exec','docker','cp','qq-ai-bot-astrbot-1:/AstrBot/data/temp/performance-before-20261023.db',target],capture_output=True,text=True)
    if copied.returncode or not backup.exists():raise RuntimeError('Database backup export failed')

profile=api.call('/api/v1/config-profiles/default')['data']['config']
api.backup('profile-before-performance.json',profile)
profile['provider_ltm_settings']['group_message_max_cnt']=40
api.call('/api/v1/config-profiles/default',profile,method='PUT',timeout=120)

provider_id='litellm-lan/siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017'
providers=api.call('/api/config/provider/template')['data']['providers']
provider=next(p for p in providers if p['id']==provider_id)
api.backup('deepseek-before-performance.json',provider)
provider=copy.deepcopy(provider)
provider.setdefault('custom_extra_body',{})['enable_thinking']=False
api.call('/api/config/provider/update',{'id':provider_id,'config':provider})

memory_name='astrbot_plugin_livingmemory'
memory=api.call('/api/v1/plugins/'+memory_name+'/config')['data']['config']
api.backup('memory-before-performance.json',memory)
memory['recall_engine']['top_k']=0
api.call('/api/v1/plugins/'+memory_name+'/config',{'config':memory},method='PUT',timeout=120)

name='astrbot_plugin_qq_persona_models'
config=api.call('/api/v1/plugins/'+name+'/config')['data']['config']
api.backup('router-before-performance.json',config)
config['performance']={'enabled':True,'history_turns':12,'history_image_turns':2}
api.call('/api/v1/plugins/'+name+'/config',{'config':config},method='PUT',timeout=120)

live_profile=api.call('/api/v1/config-profiles/default')['data']['config']
live_memory=api.call('/api/v1/plugins/'+memory_name+'/config')['data']['config']
live_router=api.call('/api/v1/plugins/'+name+'/config')['data']['config']
live_provider=next(p for p in api.call('/api/config/provider/template')['data']['providers'] if p['id']==provider_id)
checks={'database_snapshot_saved':backup.exists(),
    'recent_group_messages_40':live_profile['provider_ltm_settings']['group_message_max_cnt']==40,
    'deepseek_thinking_off':live_provider['custom_extra_body'].get('enable_thinking') is False,
    'automatic_recall_off':live_memory['recall_engine']['top_k']==0,
    'recall_tool_kept':live_memory['agent_tools']['enable_recall_tool'],
    'summarization_kept':live_memory['reflection_engine']['summary_trigger_rounds']==memory['reflection_engine']['summary_trigger_rounds'],
    'request_context_limit_saved':live_router['performance']==config['performance']}
bindings=api.call('/api/plug/qq_persona_models/verify')['data']
checks['persona_models_preserved']=all(r['passed'] for r in bindings)
report={'checks':checks,'passed':all(checks.values()),'settings':config['performance'],'qq_messages_sent':0}
write_report('performance-settings-verification.json',report)
print(json.dumps(report,ensure_ascii=False))
assert report['passed']
