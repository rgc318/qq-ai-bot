"""Measure native request preparation and one real model response; no tools/QQ sends/history writes."""
import json
from deployment_api import DeploymentAPI,write_report
api=DeploymentAPI()
result=api.call('/api/plug/qq_persona_models/verify_memory_meme',{'performance_only':True,'call_model':True},timeout=120)
write_report('performance-native-verification.json',result)
print(json.dumps(result,ensure_ascii=False))
assert result['data']['passed']
