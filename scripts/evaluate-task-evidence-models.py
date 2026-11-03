"""Two synthetic decision-only probes; no tools execute and no QQ is sent."""
import importlib.util
import json
import time
from deployment_api import DeploymentAPI,ROOT,write_report

spec=importlib.util.spec_from_file_location('task_evidence',ROOT/'extensions/astrbot_plugin_qq_persona_models/task_evidence.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
api=DeploymentAPI()
probes=json.loads((ROOT/'logs/task-evidence-probes.local.json').read_text(encoding='utf-8'))
tools=[{'type':'function','function':{'name':'view_context_images','description':'按本轮目录ID读取历史图片，返回实际像素供当前视觉模型理解；已经提供预览时无需重复读取。','parameters':{'type':'object','properties':{'attachment_ids':{'type':'array','items':{'type':'string'}}},'required':['attachment_ids']}}}]
rows=[]
baseline=json.loads(json.dumps(probes['preview']))
baseline['messages'][0]['content']=baseline['messages'][0]['content'].split('\n[本轮资料可见状态，仅作执行证据]',1)[0]
for name,probe in [('preview_without_guard',baseline),*probes.items()]:
    start=time.perf_counter()
    response=api.model('/chat/completions',{'model':'siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017','messages':probe['messages'],'tools':tools,'tool_choice':'auto','enable_thinking':False,'max_tokens':400},timeout=60)
    message=response['choices'][0]['message'];text,state,error=m.split_state(message.get('content') or '')
    calls=message.get('tool_calls') or [];selected=[]
    for call in calls:
        if call['function']['name']=='view_context_images':selected+=json.loads(call['function']['arguments']).get('attachment_ids',[])
    if name=='preview_without_guard':passed=not calls and '红' in text
    elif name=='preview':passed=not calls and '红' in text and state is not None and state.get('image_ids')==probe['image_ids'] and not error
    else:passed=bool(selected) and set(selected)==set(probe['image_ids'])
    rows.append({'case':name,'passed':passed,'seconds':round(time.perf_counter()-start,3),'initial_images':probe['initial_images'],
                 'declared_state':state is not None,'selected_tools':[c['function']['name'] for c in calls],
                 'input_tokens':response.get('usage',{}).get('prompt_tokens'),'output_tokens':response.get('usage',{}).get('completion_tokens')})
    print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
report={'passed':all(r['passed'] for r in rows),'rows':rows,'model_calls':len(rows),'tools_executed':0,'image_generations':0,'qq_messages_sent':0,'real_history_replayed':False,'limits':'One sample per synthetic case including a preview baseline; not a causal speedup estimate, production reliability or latency percentiles.'}
write_report('task-evidence-models.json',report)
assert report['passed']
