"""Four synthetic model calls: source selection and vision on the existing routes.

No real history/photos, image generation, tool execution or QQ sends. Running
this script incurs four small text/vision model requests. Results are metadata.
"""
import base64
from io import BytesIO
import json
import time
import argparse
from PIL import Image,ImageDraw
from deployment_api import DeploymentAPI,write_report

api=DeploymentAPI()
image=Image.new('RGB',(160,160),'white');ImageDraw.Draw(image).rectangle((30,30,130,130),fill='red')
buffer=BytesIO();image.save(buffer,format='PNG')
url='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
schema={'type':'function','function':{'name':'view_context_images','description':'按目录ID读取真实图片，只是回看，不生成也不发送。','parameters':{'type':'object','properties':{'attachment_ids':{'type':'array','items':{'type':'string'},'maxItems':4}},'required':['attachment_ids']}}}
routes=[('DeepSeek1017','siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017',{'enable_thinking':False}),('Sol-low','cliproxyapi/gpt-6.1-sol',{'reasoning_effort':'low','allowed_openai_params':['reasoning_effort']})]
parser=argparse.ArgumentParser();parser.add_argument('--route',choices=[r[0] for r in routes]);args=parser.parse_args()
results=[]
for label,model,options in routes:
    if args.route and args.route!=label:continue
    messages=[{'role':'system','content':'合成测试。目录只是来源，不等于你看到了像素。修改“他”指刚上传的新图，不能沿用旧任务。只允许回看，禁止实际生图。请先调用view_context_images读取正确ID。目录：[{"id":"a_old_fixture","from":"AI","generated":true,"order":1},{"id":"a_new_fixture","from":"A","generated":false,"order":2}]'},
              {'role':'assistant','content':'上一个任务是蓝色小玩偶。'},
              {'role':'user','content':'A刚单独上传一张新图，然后说：给他换上西装。先查看正确参考图。'}]
    started=time.perf_counter()
    first=api.model('/chat/completions',{'model':model,'messages':messages,'tools':[schema],'tool_choice':'auto','max_tokens':4096,**options},timeout=100)
    decision_seconds=round(time.perf_counter()-started,3)
    response=first['choices'][0]['message'];calls=response.get('tool_calls') or []
    valid=len(calls)==1 and calls[0]['function']['name']=='view_context_images' and json.loads(calls[0]['function']['arguments']).get('attachment_ids')==['a_new_fixture']
    result={'route':label,'model':model,'correct_reference_id':valid,'decision_seconds':decision_seconds,'tool_names':[c['function']['name'] for c in calls],'selected_ids':[json.loads(c['function']['arguments']).get('attachment_ids') for c in calls],'finish_reason':first['choices'][0].get('finish_reason'),'text_characters':len(response.get('content') or '')}
    if valid:
        messages.extend([response,{'role':'tool','tool_call_id':calls[0]['id'],'content':'附件a_new_fixture的实际视觉预览将随下一条输入提供，仅供理解；不是新生成图片，不要转发。'},
                         {'role':'user','content':[{'type':'text','text':'这是a_new_fixture的真实像素。只用中文简短回答主体几何形状是什么颜色，以及本次应使用新图还是旧图。不要沿用旧玩偶的描述。'},{'type':'image_url','image_url':{'url':url}}]}])
        started=time.perf_counter()
        second=api.model('/chat/completions',{'model':model,'messages':messages,'tools':[schema],'tool_choice':'none','max_tokens':300,**options},timeout=100)
        text=second['choices'][0]['message'].get('content') or ''
        result.update(vision_seconds=round(time.perf_counter()-started,3),vision_identified_red='红' in text,retained_new_reference='新图' in text or '新上传' in text or 'a_new_fixture' in text,nonempty_reply=bool(text.strip()))
    result['passed']=valid and all(result.get(k,False) for k in ('vision_identified_red','retained_new_reference','nonempty_reply'))
    results.append(result);write_report('multimodal-model-'+label+'.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
report={'passed':all(r['passed'] for r in results),'routes':results,'materials':'synthetic shapes and synthetic source IDs only','image_generations':0,'qq_messages_sent':0,'real_history_replayed':False}
write_report('multimodal-model-verification.json',report)
assert report['passed'], 'See metadata-only report; no real history or generated images were used'
