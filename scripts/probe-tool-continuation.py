"""Compare raw tool continuations. Tools are simulated; no images or QQ sends."""
import copy
import base64
import json
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit
import zlib

from deployment_api import DeploymentAPI, write_report


api=DeploymentAPI()
SOL='cliproxyapi/gpt-6.1-sol'
FISH='siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017'
function={'name':'deployment_task','description':'整理并交付一份文字清单，完成后返回交付状态。本次由诊断程序模拟，不执行外部动作。',
    'parameters':{'type':'object','properties':{'label':{'type':'string'}},'required':['label'],'additionalProperties':False}}
system='你是助手，使用提供的文字工具满足用户要求。本次没有图片、联网或消息发送操作。'
user='请调用 deployment_task，把测试用文字清单整理好交付给我。'
messages=[{'role':'system','content':system},{'role':'user','content':user}]
result_text='系统提示：已成功整理并交付 1 份文字清单。'
REPORT_NAME='tool-continuation-probe.json'
if '--user-visible' in sys.argv:
    function['name']='send_message_to_user'
    function['description']='模拟向当前用户交付一条文字消息，返回交付状态。不执行真实发送、不生成图片。'
    user='请调用 send_message_to_user，把“测试用文字清单已整理好”这句话交付给我。'
    messages=[{'role':'system','content':system},{'role':'user','content':user}]
    result_text='系统提示：已成功向当前用户发送 1 条文字消息。'
    REPORT_NAME='tool-continuation-visible-probe.json'
if '--vision' in sys.argv:
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    pixels=b''.join(b'\0'+bytes((255,0,0))*64 for _ in range(64))
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',64,64,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')
    system='本次仅识别输入图片，用文字工具登记颜色；禁止生成或修改图片，不进行联网或真实发送。'
    user='请识别这张图片的主要颜色，调用 deployment_task 登记，然后告诉我完成状态。'
    messages=[{'role':'system','content':system},{'role':'user','content':[{'type':'text','text':user},
        {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode()}}]}]
    result_text='系统提示：已成功登记颜色为红色，共 1 项。'
    REPORT_NAME='tool-continuation-vision-probe.json'
report={'qq_messages_sent':0,'image_generations':0,'tests':{}}


def request(name,path,payload):
    started=time.monotonic();row={'endpoint':path,'model':payload['model']};body=None
    try:
        req=urllib.request.Request(api.model_base+path,data=json.dumps(payload,ensure_ascii=False).encode(),
            headers={'Content-Type':'application/json','Authorization':'Bearer '+api.api_key})
        with urllib.request.urlopen(req,timeout=65) as response:
            body=json.loads(response.read())
            row['http_status']=response.status
            headers={}
            for key in ('x-request-id','x-litellm-call-id','x-litellm-model-id','x-litellm-model-api-base','x-litellm-version'):
                value=response.headers.get(key)
                if value:
                    if key.endswith('api-base'):
                        parts=urlsplit(value);value=f'{parts.scheme}://{parts.hostname}' + (f':{parts.port}' if parts.port else '') + parts.path
                    headers[key]=api.sanitize(value)
            row['headers']=headers
        row['top_level_keys']=list(body)
        if 'choices' in body:
            choice=body['choices'][0];message=choice['message']
            row.update(text=message.get('content'),finish_reason=choice.get('finish_reason'),message_keys=list(message),
                tool_calls=[x.get('function',{}).get('name') for x in message.get('tool_calls') or []],usage=body.get('usage'))
        else:
            row.update(status=body.get('status'),output_types=[x.get('type') for x in body.get('output',[])],
                text=''.join(c.get('text','') for x in body.get('output',[]) for c in x.get('content',[]) if c.get('type')=='output_text'),
                tool_calls=[x.get('name') for x in body.get('output',[]) if x.get('type')=='function_call'],usage=body.get('usage'))
        row['usable_output']=bool(row.get('text') or row.get('tool_calls'))
    except urllib.error.HTTPError as exc:
        row.update(error=api.sanitize(exc.read(1800).decode(errors='replace')),http_status=exc.code)
    except Exception as exc:row['error']=api.sanitize(str(exc))[:800]
    row['seconds']=round(time.monotonic()-started,3)
    return name,row,body


initial={
    'sol_chat':('/chat/completions',{'model':SOL,'messages':messages,'max_tokens':1024,'reasoning_effort':'low','allowed_openai_params':['reasoning_effort'],
        'tools':[{'type':'function','function':function}],'tool_choice':{'type':'function','function':{'name':function['name']}}}),
    'deepseek_chat':('/chat/completions',{'model':FISH,'messages':messages,'max_tokens':1024,'enable_thinking':False,
        'tools':[{'type':'function','function':function}],'tool_choice':{'type':'function','function':{'name':function['name']}}}),
    'sol_responses':('/responses',{'model':SOL,'instructions':system,'input':[messages[1]],'max_output_tokens':1024,'reasoning':{'effort':'low'},
        'tools':[{'type':'function',**function}],'tool_choice':{'type':'function','name':function['name']},'store':False})}
if '--vision' in sys.argv:
    initial['sol_responses'][1]['input']=[{'role':'user','content':[{'type':'input_text','text':user},
        {'type':'input_image','image_url':messages[1]['content'][1]['image_url']['url']}]}]
bodies={}
with ThreadPoolExecutor(max_workers=3) as pool:
    futures=[pool.submit(request,name+'_start',path,payload) for name,(path,payload) in initial.items()]
    for future in as_completed(futures):
        name,row,body=future.result();report['tests'][name]=row;bodies[name.removesuffix('_start')]=body
        print(json.dumps({'test':name,**{k:v for k,v in row.items() if k!='usage'}},ensure_ascii=False),flush=True)
        write_report(REPORT_NAME,report)

jobs=[]
for name,(path,base) in initial.items():
    body=bodies.get(name)
    if not body:continue
    payload=copy.deepcopy(base)
    if path=='/chat/completions':
        message=body['choices'][0]['message'];calls=message.get('tool_calls') or []
        if not calls:continue
        for call in calls:
            assert call['function']['name']==function['name'], 'Unexpected tool; nothing executed'
        payload['messages'].append({k:message[k] for k in ('role','content','tool_calls') if k in message})
        payload['messages'].extend({'role':'tool','tool_call_id':call['id'],'content':result_text} for call in calls)
        payload['tool_choice']='auto'
        jobs.append((name+'_resume_auto',path,payload))
        if name=='sol_chat':
            without=copy.deepcopy(payload);without['tool_choice']='none'
            jobs.append((name+'_resume_none',path,without))
    else:
        calls=[x for x in body.get('output',[]) if x.get('type')=='function_call']
        if not calls:continue
        assert all(call['name']==function['name'] for call in calls), 'Unexpected tool; nothing executed'
        payload['input'].extend(copy.deepcopy(body['output']))
        payload['input'].extend({'type':'function_call_output','call_id':call['call_id'],'output':result_text} for call in calls)
        payload['tool_choice']='auto'
        jobs.append((name+'_resume_auto',path,payload))
with ThreadPoolExecutor(max_workers=3) as pool:
    futures=[pool.submit(request,*job) for job in jobs]
    for future in as_completed(futures):
        name,row,_=future.result();report['tests'][name]=row
        print(json.dumps({'test':name,**{k:v for k,v in row.items() if k!='usage'}},ensure_ascii=False),flush=True)
        write_report(REPORT_NAME,report)
