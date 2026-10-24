"""Verify new components plus the unchanged persona model selection."""
import json
from deployment_api import DeploymentAPI,write_report
api=DeploymentAPI()
result=api.call('/api/plug/qq_persona_models/verify_memory_meme',{},timeout=120)
binding=api.call('/api/plug/qq_persona_models/verify')
result['model_bindings_passed']=all(row['passed'] for row in binding['data'])
write_report('memory-memes-verification.json',result)
print(json.dumps(result,ensure_ascii=False))
assert result['data']['passed'] and result['model_bindings_passed']
