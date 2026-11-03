"""Actual model probes using only isolated exported synthetic native payloads."""
import json
import importlib.util
import time
from deployment_api import DeploymentAPI, ROOT, write_report

api=DeploymentAPI()
probes=json.loads((ROOT/'logs/context-architecture-probes.local.json').read_text(encoding='utf-8'))
tool={'type':'function','function':{'name':'view_context_images','description':'仅在本轮没有相应图片像素或需要更高清细节时，读取目录中的原图片。已提供清晰预览无需重复读取。',
      'parameters':{'type':'object','properties':{'attachment_ids':{'type':'array','items':{'type':'string'},'maxItems':4}},'required':['attachment_ids']}}}
model='siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017'
spec=importlib.util.spec_from_file_location('image_task',ROOT/'extensions/astrbot_plugin_qq_persona_models/image_task_contract.py')
contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)
generation={'type':'function','function':{'name':'generate_image','description':'实际生成或修改图片。参数中的参考图ID必须来自当前目录，独立新图不使用历史参考。',
 'parameters':{'type':'object','properties':{'prompt':{'type':'string'},'pending_message':{'type':'string'},'image_task':contract.task_schema(),
 'reference_ids':{'type':'array','items':{'type':'string'},'maxItems':4},'reference_notes':contract.notes_schema()},
 'required':['prompt','pending_message','image_task','reference_ids','reference_notes']}}}
rows=[]
for name,probe in probes.items():
    started=time.perf_counter()
    editing='expected_reference_ids' in probe
    response=api.model('/chat/completions',{'model':model,'messages':probe['messages'],'tools':[tool,generation] if editing else [tool],'tool_choice':'auto','enable_thinking':False,'max_tokens':800 if editing else 250},timeout=60)
    message=response['choices'][0]['message'];answer=message.get('content') or '';calls=message.get('tool_calls') or []
    row={'case':name,'seconds':round(time.perf_counter()-started,3),'initial_images':probe['initial_images'],'model_calls':1,
         'actual_colors_correct':all(value in answer for value in probe['expected']),'unnecessary_tool_calls':[c['function']['name'] for c in calls],
         'output_chars':len(answer),'input_tokens':response.get('usage',{}).get('prompt_tokens'),'output_tokens':response.get('usage',{}).get('completion_tokens')}
    if editing:
        selected=next((c for c in calls if c['function']['name']=='generate_image'),None)
        args=json.loads(selected['function']['arguments']) if selected else {}
        valid=False
        try:
            contract.validate_task(args,probe['current_text'],{});valid=True
        except ValueError:pass
        row.update(reference_set_correct=set(args.get('reference_ids',[]))==set(probe['expected_reference_ids']),task_schema_valid=valid,
                   operation=(args.get('image_task') or {}).get('operation'))
        row['passed']=bool(selected) and row['reference_set_correct'] and valid
        row.pop('actual_colors_correct');row['selected_tools']=row.pop('unnecessary_tool_calls')
    else:row['passed']=row['actual_colors_correct'] and not calls
    rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
report={'passed':all(r['passed'] for r in rows),'model':model,'rows':rows,'model_calls':len(rows),'qq_messages_sent':0,'image_generations':0,'tools_executed':0,
        'real_history_replayed':False,'limits':'Synthetic native multimodal answers and generation decisions only; selected tools never executed. Not production p95.'}
write_report('unified-context-models.json',report)
assert report['passed'],'Synthetic native multimodal behavior check failed'
