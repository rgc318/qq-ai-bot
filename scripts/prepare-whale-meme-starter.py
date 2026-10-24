"""Prepare a small, attributed subset of the maintainer's public fish pack."""
import concurrent.futures
import hashlib
import json
import sys
from pathlib import PurePosixPath
import urllib.parse
import urllib.request
import zipfile
from deployment_api import ROOT, write_report

general='--general' in sys.argv
repo='anka-afk/astrbot-meme-pack-official-01' if general else 'anka-afk/blue-fat-fish-meme-pack'
ref='main' if general else 'v1.0.0'
pack_id='qq-general-starter' if general else 'qq-whale-starter'
def get(url):
    request=urllib.request.Request(url,headers={'User-Agent':'qq-bot-personal-deployment'})
    with urllib.request.urlopen(request,timeout=35) as r:
        blob=r.read(4*1024*1024+1)
        if len(blob)>4*1024*1024:raise ValueError('Asset exceeds bounded starter-pack download size')
        return blob
tree=json.loads(get('https://api.github.com/repos/'+repo+'/git/trees/'+ref+'?recursive=1'))['tree']
manifest=json.loads(get('https://raw.githubusercontent.com/'+repo+'/'+ref+'/manifest.json'))
chosen={}
for f in sorted(tree,key=lambda x:x.get('size',10**12)):
    path=PurePosixPath(f['path'])
    if f['type']=='blob' and len(path.parts)==3 and path.parts[0]=='memes' and path.suffix.lower() in ['.gif','.png','.jpg','.webp'] and 0<f.get('size',0)<=3000000:
        chosen.setdefault(path.parts[1],f)
if len(chosen)<5:raise RuntimeError('Insufficient small categorized official assets')
def download(f):
    blob=get('https://raw.githubusercontent.com/'+repo+'/'+ref+'/'+urllib.parse.quote(f['path']))
    return f['path'],blob
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    assets=list(pool.map(download,chosen.values()))
output=ROOT/('downloads/'+pack_id+'.zip')
output.parent.mkdir(exist_ok=True)
starter={'schema_version':1,'id':pack_id,'name':'通用精选表情' if general else '大肥鱼精选表情','version':'1.0.0-local','description':'从维护者资源按分类选取的小型本地包；保留原始图片，不包含完整上游包。','author':manifest.get('author'),'homepage':'https://github.com/'+repo,'license':manifest.get('license'),'categories':{c:manifest['categories'][c] for c in chosen},'upstream_source':{'repo':repo,'ref':ref}}
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
    z.writestr('manifest.json',json.dumps(starter,ensure_ascii=False))
    for path,blob in assets:z.writestr(path,blob)
report={'pack_id':starter['id'],'source':repo,'ref':ref,'categories':len(chosen),'images':len(assets),'archive_bytes':output.stat().st_size,'archive':str(output),'assets':[{'path':path,'bytes':len(blob),'sha256':hashlib.sha256(blob).hexdigest()} for path,blob in assets]}
write_report(('general' if general else 'whale')+'-meme-starter-provenance.json',report)
print(json.dumps({k:v for k,v in report.items() if k!='assets'},ensure_ascii=False))
