"""Verify native construction and response decoration with existing history; never send QQ."""
import argparse
import json
from deployment_api import DeploymentAPI,write_report

parser=argparse.ArgumentParser()
parser.add_argument('--inspect-only',action='store_true')
args=parser.parse_args()
api=DeploymentAPI()
result=api.call('/api/plug/qq_persona_models/verify_memory_meme',{'native_request_only':True,'call_model':not args.inspect_only},timeout=120)
write_report('meme-native-flow-verification.json',result)
print(json.dumps(result,ensure_ascii=False))
if not args.inspect_only:
    assert result['data']['passed']
