"""Apply the user-approved memory/meme plan, preserving existing unrelated settings."""
import copy
import json
import sys
from deployment_api import DeploymentAPI, ROOT, read_json, write_report

api=DeploymentAPI()
plan=read_json(ROOT/'config/memory-memes.plan.json')
def merge(target,patch):
    for k,v in patch.items():
        if isinstance(v,dict):
            if not isinstance(target.get(k),dict):target[k]={}
            merge(target[k],v)
        else:target[k]=copy.deepcopy(v)
    return target

results=[]
for plugin,key in [('astrbot_plugin_livingmemory','livingmemory'),('meme_manager','meme_manager')]:
    if plugin=='meme_manager' and '--memory-only' in sys.argv:
        continue
    original=api.call('/api/v1/plugins/'+plugin+'/config')['data']['config']
    api.backup(plugin+'-before-config.json',original)
    patch=copy.deepcopy(plan[key]);patch.pop('pack_policy',None)
    if plugin=='meme_manager':
        patch['community']={'github_accelerator_url':''}
    updated=merge(copy.deepcopy(original),patch)
    api.call('/api/v1/plugins/'+plugin+'/config',{'config':updated},method='PUT',timeout=120)
    results.append({'plugin':plugin,'config_saved':True})
    write_report('memory-memes-configuration.json',results)
    print(json.dumps(results[-1],ensure_ascii=False),flush=True)

# User Policy 3.5.6 normalizes its legacy meme adapter to enabled=True.
# Meme Manager 5.x uses native pack rules instead. The local binding helper
# passes the effective persona per request; leave upstream adapter code intact.
