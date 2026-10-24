"""Add verified embedding/summary providers and the two requested plugins."""
import copy
import json
from deployment_api import DeploymentAPI, write_report

api=DeploymentAPI()
profile=api.call('/api/v1/config-profiles/default')['data']['config']
api.backup('profile-before-memory-memes-install.json',profile)
source=copy.deepcopy(next(s for s in profile['provider_sources'] if s['id']=='litellm-lan'))
source.update(id='litellm-embedding',type='openai_embedding',key=[api.api_key])
api.call('/api/v1/provider-sources/by-id',{'source_id':source['id'],'config':source},method='PUT')
providers=api.call('/api/config/provider/template')['data']['providers']
records=[
 {'id':'qq-memory-embedding','model':'siliconflow/Qwen/Qwen3-Embedding-0.6B','embedding_model':'siliconflow/Qwen/Qwen3-Embedding-0.6B','embedding_api_base':api.model_base,'embedding_api_key':api.api_key,'provider_source_id':'litellm-embedding','type':'openai_embedding','provider_type':'embedding','enable':True,'embedding_dimensions':1024,'embedding_dimensions_mode':'never'},
 {'id':'qq-memory-summary','model':'siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017','provider_source_id':'litellm-lan','type':'openai_chat_completion','provider_type':'chat_completion','enable':True,'modalities':['text'],'custom_extra_body':{'enable_thinking':False,'max_tokens':4096}},
]
for p in records:
    if any(x['id']==p['id'] for x in providers):
        api.call('/api/config/provider/update',{'id':p['id'],'config':p})
    else:
        api.call('/api/v1/provider-sources/providers',{'source_id':p['provider_source_id'],'config':p})
    print(json.dumps({'configured_provider':p['id'],'model':p['model']},ensure_ascii=False),flush=True)
installed={x['name'] for x in api.call('/api/v1/plugins')['data']}
result=[]
for name,repo,ref in [
 ('astrbot_plugin_livingmemory','lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory','tags/2.7.1'),
 ('meme_manager','anka-afk/astrbot_plugin_meme_manager','tags/v5.2.5'),
]:
    if name in installed:
        row={'plugin':name,'already_installed':True}
    else:
        r=api.call('/api/v1/plugins/install/url',{'repository':'https://github.com/'+repo,'download_url':'https://codeload.github.com/'+repo+'/zip/refs/'+ref},timeout=360)
        row={'plugin':name,'status':r.get('status'),'message':r.get('message')}
    result.append(row)
    write_report('memory-memes-install.json',result)
    print(json.dumps(row,ensure_ascii=False),flush=True)
