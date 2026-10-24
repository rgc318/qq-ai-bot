"""One edit using the failed GIF reference; no QQ sends, no automatic retry."""
import base64
import json
import time
from deployment_api import DeploymentAPI,ROOT,write_report
api=DeploymentAPI()
source=ROOT/'logs/incident-reference-20261023-2228.gif'
assert source.is_file()
report={'reference_format':'GIF','reference_bytes':source.stat().st_size,'model':'gpt-image-2.5','qq_messages_sent':0,'attempts':1}
start=time.monotonic()
try:
    result=api.call('/api/plug/astrbot_plugin_omnidraw/generate_image_for_plugin',{
        'prompt':'根据参考表情包画一张可爱的卡通肖像：保留狗头顶着蓝色大桶水的构图与淡定表情，白色简洁背景，清晰插画，无文字。',
        'count':1,'size':'1024x1024','extra_params':'--quality low',
        'refs':['data:image/gif;base64,'+base64.b64encode(source.read_bytes()).decode()]},timeout=260)
    images=result.get('images',[])
    report.update(success=bool(result.get('success') and images),image_count=len(images))
    if not report['success']:
        report['message']=api.sanitize(str(result.get('message','')))[:800]
        report['errors']=api.sanitize(json.dumps(result.get('errors',[]),ensure_ascii=False))[:800]
    if images:
        item=images[0]
        values=item.values() if isinstance(item,dict) else [item]
        data=next((v for v in values if isinstance(v,str) and v.startswith('data:image/')),'')
        if data:
            target=ROOT/'logs/gif-image-editing-verification.png'
            target.write_bytes(base64.b64decode(data.split(',',1)[1]))
            report['output_file']=str(target)
except Exception as exc:
    report.update(success=False,error=api.sanitize(str(exc))[:1000])
report['seconds']=round(time.monotonic()-start,2)
write_report('gif-image-editing-verification.json',report)
print(json.dumps(report,ensure_ascii=False),flush=True)
assert report['success']
