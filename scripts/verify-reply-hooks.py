import json
from deployment_api import DeploymentAPI,write_report
api=DeploymentAPI()
result=api.call("/api/plug/qq_persona_models/reply_conditions/verify_hooks",timeout=45)
write_report("reply-hooks-verification.json",result)
print(json.dumps(result,ensure_ascii=False))
assert result["data"]["passed"]
