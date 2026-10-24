"""Prefer persona dialogue in the tool call, supplement only when missing."""
import json
from deployment_api import DeploymentAPI,write_report
api=DeploymentAPI()
name='astrbot_plugin_qq_persona_models'
config=api.call('/api/v1/plugins/'+name+'/config')['data']['config']
api.backup('router-before-model-image-notice.json',config)
config.setdefault('image_pending_notice',{}).update(enabled=True,model_generated=True,fallback_timeout_seconds=10)
api.call('/api/v1/plugins/'+name+'/config',{'config':config},method='PUT',timeout=120)
live=api.call('/api/v1/plugins/'+name+'/config')['data']['config']['image_pending_notice']
assert live==config['image_pending_notice']
check=api.call('/api/plug/qq_persona_models/verify_memory_meme',{'image_notice_only':True},timeout=45)['data']
write_report('image-pending-notice-verification.json',{'settings':live,**check})
print(json.dumps({'settings':live,**check},ensure_ascii=False))
assert check['passed']
