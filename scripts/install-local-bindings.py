import io
import json
import urllib.request
import zipfile
import argparse
from deployment_api import DeploymentAPI, ROOT

parser=argparse.ArgumentParser(description='Package a complete local plugin; fresh installation only.')
parser.add_argument('--package-only',action='store_true',help='Write an ignored ZIP without accessing AstrBot')
options=parser.parse_args()
folder=ROOT/"extensions/astrbot_plugin_qq_persona_models"
buffer=io.BytesIO()
with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
    for source,prefix in ((folder,'astrbot_plugin_qq_persona_models/'),(ROOT/'integrations/contextaware','astrbot_plugin_qq_persona_models/_ca_runtime/')):
        for file in source.rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts:
                archive.write(file,prefix+file.relative_to(source).as_posix())
if options.package_only:
    target=ROOT/'downloads/astrbot_plugin_qq_persona_models.zip'
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(buffer.getvalue())
    print('Complete plugin ZIP packaged; no API calls')
    raise SystemExit(0)
api=DeploymentAPI()
if any(p['name']=='astrbot_plugin_qq_persona_models' for p in api.call('/api/v1/plugins')['data']):
    raise SystemExit('Existing instance: use deploy-context-runtime.py with the explicitly reviewed baseline and idle gates.')
boundary="QQPersonaBindingDeploymentBoundary"
body=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"astrbot_plugin_qq_persona_models.zip\"\r\nContent-Type: application/zip\r\n\r\n").encode()+buffer.getvalue()+f"\r\n--{boundary}--\r\n".encode()
request=urllib.request.Request(api.base+"/api/v1/plugins/install/upload",data=body,headers={"Authorization":"Bearer "+api.token,"Content-Type":"multipart/form-data; boundary="+boundary},method="POST")
with urllib.request.urlopen(request,timeout=120) as response:
    result=json.load(response)
print(json.dumps({"status":result.get("status"),"message":result.get("message")},ensure_ascii=False))
if result.get("status")!="ok":
    raise SystemExit(1)
