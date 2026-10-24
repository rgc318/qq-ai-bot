"""Import the prepared small attributed packs and bind existing personas."""
import json
import urllib.request
import uuid
from deployment_api import DeploymentAPI, ROOT, write_report

api=DeploymentAPI()
prefix='/api/plug/meme_manager'
existing={p['id'] for p in api.call(prefix+'/packs')['packs'] if p.get('image_count',0)>0}
results=[]
for name in ['qq-general-starter','qq-whale-starter']:
    if name not in existing:
        archive=ROOT/('downloads/'+name+'.zip')
        boundary='qqmemes'+uuid.uuid4().hex
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="set_as_default"\r\n\r\nfalse\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{archive.name}"\r\nContent-Type: application/zip\r\n\r\n').encode()+archive.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
        req=urllib.request.Request(api.base+prefix+'/packs/import',data=body,headers={'Authorization':'Bearer '+api.token,'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=90) as response:r=json.load(response)
        except urllib.error.HTTPError as e:
            raise RuntimeError(api.sanitize(e.read(1200).decode(errors='replace'))) from None
        row={k:r.get(k) for k in ['message','pack_id','image_count','name']}
    else:row={'pack_id':name,'already_installed':True}
    results.append(row)
    write_report('meme-packs-install.json',results)
    print(json.dumps(row,ensure_ascii=False),flush=True)
rules=[{'id':'qq-whale','scope':'persona','target':'大肥鱼','pack_id':'qq-whale-starter'},
       {'id':'qq-dragon','scope':'persona','target':'ChatGPT龙娘','pack_id':'qq-general-starter'},
       {'id':'default','scope':'default','pack_id':'qq-general-starter'}]
api.backup('meme-rules-before-persona-binding.json',api.call(prefix+'/settings/rules'))
api.call(prefix+'/settings/rules',{'rules':rules})
summary={'packs':[{k:p.get(k) for k in ['id','name','image_count','category_count']} for p in api.call(prefix+'/packs')['packs']], 'rules':rules,'native_allowed_groups':['347440128']}
write_report('meme-packs-configuration.json',summary)
print(json.dumps(summary,ensure_ascii=False))
