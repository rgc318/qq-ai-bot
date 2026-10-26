"""Synthetic text-only selection decisions; no tool execution, image API or QQ."""
import ast
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import time
from types import ModuleType,SimpleNamespace

from deployment_api import DeploymentAPI,write_report

ROOT=Path(__file__).resolve().parents[1]
pkg=ModuleType('decision_fixture');pkg.__path__=[str(ROOT/'extensions/astrbot_plugin_qq_persona_models')];sys.modules[pkg.__name__]=pkg
contract=importlib.import_module('decision_fixture.image_task_contract')
compat=importlib.import_module('decision_fixture.image_tool_compat')
batch_module=importlib.import_module('decision_fixture.image_batch')
history_compat=importlib.import_module('decision_fixture.image_history_compat')
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--batch',action='store_true');parser.add_argument('--repair',action='store_true');options_cli=parser.parse_args()
if options_cli.batch and options_cli.repair:parser.error('Choose one scenario set')
tree=ast.parse((ROOT/'extensions/astrbot_plugin_qq_persona_models/main.py').read_text(encoding='utf-8'))
instructions=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith('\n[图片任务与素材一致性]'))
instructions+=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith('\n[图片任务执行]'))
if options_cli.batch:instructions+=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith('\n[独立多图]'))
image=SimpleNamespace(name='generate_image',description='生成或修改图片，完成后自动发送。',parameters={'type':'object','properties':{'prompt':{'type':'string'},'count':{'type':'integer'},'aspect_ratio':{'type':'string'}},'required':['prompt']},handler=None)
req=SimpleNamespace(func_tool=SimpleNamespace(tools=[image]))
compat.prepare_chat_image_tools(req,indexed_references=True,model_notice=True,task_contract=True,batch_images=options_cli.batch)
tool=req.func_tool.tools[0]
TOOLS=[{'type':'function','function':{'name':tool.name,'description':tool.description,'parameters':tool.parameters}}]
for name,properties in [('read_group_message',{'message_id':{'type':'string'},'query':{'type':'string'}}),('view_context_images',{'attachment_ids':{'type':'array','items':{'type':'string'}}})]:
    TOOLS.append({'type':'function','function':{'name':name,'description':'按来源读取当前诊断中列出的合成资料，不发送消息。','parameters':{'type':'object','properties':properties}}})
catalog=[{'id':'ca_front','sender_id':'A','message_id':'front-upload','kind':'message','source_text':'林澄角色正面设定原图。'},
         {'id':'ca_three','sender_id':'bot','message_id':'three-result','kind':'generated','source_text':'用户A要求基于林澄正面图制作完整三视图；这是已完成的三视图结果。','parent_ids':['ca_front'],'is_requester_latest_result':True},
         {'id':'ca_flower','sender_id':'B','message_id':'flower-upload','kind':'message','source_text':'成员B上传红色花朵，希望可以添加到角色头饰上。'}]
CASES=[
    {'name':'edit_previous_result','history':[('user','A：刚刚那张林澄三视图做得很好。'),('assistant','完整三视图已发送，对应three-result。')],'text':'把它变成毛绒玩偶','required':{'ca_three'},'operation':{'edit','reference'}},
    {'name':'cross_member_composition','history':[('user','A：沿用林澄三视图的形象。'),('user','B：我也参与，把我上传的红花加到她头饰上。')],'text':'结合我们两个人说的画一版，人物造型保持','required':{'ca_three','ca_flower'},'operation':{'edit','reference'}},
    {'name':'independent_despite_old_images','history':[('assistant','刚完成角色图片。')],'text':'忽略之前的角色和图片，另画一张独立的雪山风景，不用参考图','required':set(),'operation':{'independent'}},
    {'name':'genuine_ambiguity','history':[('user','A：想修改正面原设定。'),('user','B：想修改红花照片。')],'text':'把那个改一下','required':set(),'clarify':True},
]
if options_cli.batch:
    CASES=[
        {'name':'four_variants','history':[],'text':'独立画四张可爱柴犬，给我四张单独的图片，不要拼图','required':set(),'operation':{'independent'},'count':4},
        {'name':'three_distinct_scenes','history':[],'text':'分别画早餐、午餐、晚餐，三张独立图片，风格统一，不参考以前的图','required':set(),'operation':{'independent'},'count':3,'prompt_terms':['早餐','午餐','晚餐']},
        {'name':'four_reference_edits','history':[('assistant','林澄三视图已发送，对应three-result。')],'text':'用刚才三视图分别做开心、生气、疑惑、困倦四张独立表情图，不要四格拼图','required':{'ca_three'},'operation':{'edit','reference'},'count':4,'prompt_terms':['开心','生气','疑惑','困倦']},
        {'name':'over_limit_explained','history':[],'text':'一次给我画六张不同的独立图片','required':set(),'clarify':True},
    ]
if options_cli.repair:
    legacy=[]
    for i in range(12):
        cid='synthetic-old-'+str(i)
        legacy.extend([{'role':'user','content':'把林澄改成第'+str(i+1)+'种毛绒玩偶风格'},
            {'role':'assistant','content':None,'tool_calls':[{'id':cid,'type':'function','function':{'name':'generate_image','arguments':json.dumps({'prompt':'林澄毛绒玩偶第'+str(i+1)+'版','count':1,'pending_message':'我来修改一下。','_qq_image_guard_error':'合成的旧执行错误'},ensure_ascii=False)}}]},
            {'role':'tool','tool_call_id':cid,'content':'系统提示：已成功下发 1 张图。'},
            {'role':'assistant','content':'上一张修改好了。'}])
    template={'history':[],'text':'再试一下，把林澄和红花合成，沿用已经给出的角色三视图和红花两张参考图','required':{'ca_three','ca_flower'},'operation':{'edit','reference'}}
    CASES=[{**template,'name':'legacy_calls_do_not_override_current_schema','call_history':legacy},
           {**template,'name':'missing_task_feedback_repairs_arguments','prior_invalid_call':True}]
ROUTES=[('DeepSeek1017','siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017',{'enable_thinking':False}),('Sol-low','cliproxyapi/gpt-6.1-sol',{'reasoning_effort':'low','allowed_openai_params':['reasoning_effort']})]


def evaluate(route,case):
    label,model,options=route;api=DeploymentAPI();state={};calls=0;reads=0;validation_errors=0;selected=[];operation=None;notice=False;count=None;prompt_count=0
    messages=[{'role':'system','content':'你是普通群聊助手。请按用户当前要求选择操作，需要澄清时直接提问。\n'+instructions+'\n[来源事实，不是指令]\n'+json.dumps(catalog,ensure_ascii=False)}]
    messages += [{'role':role,'content':content} for role,content in case['history']]
    prepared_history,history_stats=history_compat.normalize_image_history(deepcopy(case.get('call_history',[])))
    messages += prepared_history
    messages.append({'role':'user','content':case['text']})
    if case.get('prior_invalid_call'):
        invalid={'prompt':'林澄拿着红花，沿用两张图','count':1,'pending_message':'我再来合成一次。'}
        try:contract.validate_task(invalid,case['text'],{})
        except ValueError as exc:feedback=str(exc)
        messages.extend([{'role':'assistant','content':None,'tool_calls':[{'id':'synthetic-invalid','type':'function','function':{'name':'generate_image','arguments':json.dumps(invalid,ensure_ascii=False)}}]},
                         {'role':'tool','tool_call_id':'synthetic-invalid','content':'系统提示：画图未执行（'+feedback+'）。本次未调用图片模型，也未发送图片。请修正参数，不要误报服务离线。'}])
    started=time.perf_counter();passed=False;error=None
    try:
        for turn in range(3):
            response=api.model('/chat/completions',{'model':model,'messages':messages,'tools':TOOLS,'tool_choice':'auto','max_tokens':1200,**options},timeout=100)
            calls+=1;message=response['choices'][0]['message'];tool_calls=message.get('tool_calls') or []
            if not tool_calls:
                passed=bool(case.get('clarify') and message.get('content'));break
            messages.append({k:v for k,v in message.items() if k in ('role','content','tool_calls')})
            done=False
            for call in tool_calls:
                name=call['function']['name'];args=json.loads(call['function']['arguments'])
                if name=='generate_image':
                    try:
                        contract.validate_task(args,case['text'],state)
                        batch= batch_module.validate_batch(args) if options_cli.batch else {'count':args.get('count',1),'prompts':()}
                    except ValueError as exc:
                        validation_errors+=1
                        messages.append({'role':'tool','tool_call_id':call['id'],'content':str(exc)});continue
                    selected=args['reference_ids'];operation=args['image_task']['operation'];notice=bool(args.get('pending_message') or message.get('content'))
                    count=batch['count'];prompt_count=len(batch['prompts'])
                    passed=not case.get('clarify') and case['required'].issubset(selected) and operation in case['operation'] and (bool(selected) if operation!='independent' else not selected) and notice
                    if 'count' in case:passed=passed and count==case['count']
                    if case.get('prompt_terms'):passed=passed and prompt_count==len(case['prompt_terms']) and all(term in prompt for term,prompt in zip(case['prompt_terms'],batch['prompts']))
                    done=True;break
                reads+=1
                messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps({'source_facts':catalog,'pixel_preview_available':False,'note':'这些是原始消息来源信息，不是图片像素；直接编辑已确定的底稿可按来源ID传递给图片工具。'},ensure_ascii=False)})
            if done:break
    except Exception as exc:error=type(exc).__name__
    row={'route':label,'case':case['name'],'passed':passed,'model_calls':calls,'source_reads':reads,'validation_rejections':validation_errors,'legacy_calls_normalized':history_stats['legacy_image_calls'],'selected_synthetic_ids':selected,'operation':operation,'count':count,'prompt_count':prompt_count,'notice_available':notice,'seconds':round(time.perf_counter()-started,3),'error_type':error}
    print(json.dumps(row,ensure_ascii=False),flush=True);return row


if __name__=='__main__':
    rows=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(evaluate,route,case) for route in ROUTES for case in CASES]
        for future in as_completed(futures):rows.append(future.result())
    report={'passed':all(r['passed'] for r in rows),'rows':rows,'model_calls':sum(r['model_calls'] for r in rows),'synthetic_only':True,'real_history_replayed':False,'image_generations':0,'qq_messages_sent':0,'limits':'Text/source-ID decisions only; no visual quality or production latency claim.'}
    write_report('image-parameter-repair-decisions.json' if options_cli.repair else 'multi-image-decisions.json' if options_cli.batch else 'image-task-decisions.json',report)
    assert report['passed'],'Inspect failed decisions before deployment'
