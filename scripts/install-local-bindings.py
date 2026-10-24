import io
import json
import urllib.request
import zipfile
from deployment_api import DeploymentAPI, ROOT

api=DeploymentAPI()
folder=ROOT/"extensions/astrbot_plugin_qq_persona_models"
buffer=io.BytesIO()
with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
    for file in folder.iterdir():
        if file.is_file():
            archive.write(file,"astrbot_plugin_qq_persona_models/"+file.name)
boundary="QQPersonaBindingDeploymentBoundary"
body=(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"astrbot_plugin_qq_persona_models.zip\"\r\nContent-Type: application/zip\r\n\r\n").encode()+buffer.getvalue()+f"\r\n--{boundary}--\r\n".encode()
request=urllib.request.Request(api.base+"/api/v1/plugins/install/upload",data=body,headers={"Authorization":"Bearer "+api.token,"Content-Type":"multipart/form-data; boundary="+boundary},method="POST")
with urllib.request.urlopen(request,timeout=120) as response:
    result=json.load(response)
print(json.dumps({"status":result.get("status"),"message":result.get("message")},ensure_ascii=False))
if result.get("status")!="ok":
    raise SystemExit(1)
