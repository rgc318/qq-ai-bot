"""Enable local old-dialogue retrieval; keep performance and memory settings."""
import json
import time
from deployment_api import DeploymentAPI,write_report
api=DeploymentAPI()
name='astrbot_plugin_qq_persona_models'
config=api.call('/api/v1/plugins/'+name+'/config')['data']['config']
api.backup('router-before-history-recall-20261023.json',config)
config['history_recall']={'enabled':True,'catalog_chars':500}
api.call('/api/v1/plugins/'+name+'/config',{'config':config},method='PUT',timeout=120)
status=api.call('/api/plug/qq_persona_models/chat_history/status')
for _ in range(20):
    if not status['data']['initializing']:break
    time.sleep(0.2)
    status=api.call('/api/plug/qq_persona_models/chat_history/status')
checks=api.call('/api/plug/qq_persona_models/verify')['data']
report={'settings':config['history_recall'],'status':status['data'],'bindings_preserved':all(x['passed'] for x in checks),'qq_messages_sent':0}
write_report('history-recall-deployment.json',report)
print(json.dumps(report,ensure_ascii=False))
assert report['bindings_preserved'] and report['status']['enabled']
