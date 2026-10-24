"""Run inside AstrBot after explicit consent; emit metadata, never history.

Read the approved incident sample in place. Optional auto-selection modes only
inspect decisions: no image, QQ-send, history-write or other tool executor exists.
"""
import copy
import json
import os
import re
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from astrbot.core.astr_main_agent_resources import TOOL_CALL_PROMPT


settings=json.load(sys.stdin)
case=json.loads(Path('/AstrBot/data/temp/sol-continuation-private.json').read_text())
upstream_key=next(line.split('=',1)[1].strip() for line in Path('/AstrBot/data/temp/cliproxy-diagnostic-key.env').read_text(encoding='utf-8-sig').splitlines() if line.startswith('CLIPROXY_API_KEY='))
proxy_key=os.environ.get('QQ_BOT_API_KEY','')
assert proxy_key and upstream_key, 'Diagnostic credentials missing'
system=settings['persona']+'\n当前是在检查已经成功交付的工具结果，禁止再次生成、修改或发送图片，禁止执行工具、联网或发送消息。本轮只允许文字回复；没有额外操作。\n'
tools=settings['tools']
chat={'messages':[{'role':'system','content':system}]+case['history'],'tools':tools,
      'tool_choice':'none','max_tokens':512,'reasoning_effort':'low'}
response_tools=[{'type':'function',**tool['function']} for tool in tools]
responses={'instructions':system,'input':case['responses_input'],'tools':response_tools,
           'tool_choice':'none','max_output_tokens':512,'reasoning':{'effort':'low'},'store':False}
jobs=[('sol_direct_chat','http://192.168.31.229:8317/v1/chat/completions',upstream_key,{'model':'gpt-6.1-sol',**chat}),
      ('sol_litellm_chat','http://192.168.31.229:4000/v1/chat/completions',proxy_key,{'model':'cliproxyapi/gpt-6.1-sol',**chat,'allowed_openai_params':['reasoning_effort']}),
      ('sol_direct_responses','http://192.168.31.229:8317/v1/responses',upstream_key,{'model':'gpt-6.1-sol',**responses})]
fish={'model':'siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017',**copy.deepcopy(chat),'enable_thinking':False}
fish.pop('reasoning_effort')
jobs.append(('deepseek_same_persona','http://192.168.31.229:4000/v1/chat/completions',proxy_key,fish))
if settings.get('compare_native_tool_contract'):
    native=json.loads(Path('/AstrBot/data/temp/native-tool-prompt-private.json').read_text())
    native_chat={'messages':[{'role':'system','content':native['system_prompt']}]+case['history'],
        'tools':native['tools'],'tool_choice':'auto','max_tokens':512,'reasoning_effort':'low'}
    direct={'model':'gpt-6.1-sol',**native_chat}
    proxy={'model':'cliproxyapi/gpt-6.1-sol',**copy.deepcopy(native_chat),'allowed_openai_params':['reasoning_effort']}
    control=copy.deepcopy(direct);control['tool_choice']='none'
    restored=copy.deepcopy(direct);restored['messages'][0]['content']+='\n# Tool Response Rules\n'+TOOL_CALL_PROMPT+'\n'
    restored_proxy=copy.deepcopy(proxy);restored_proxy['messages'][0]['content']+='\n# Tool Response Rules\n'+TOOL_CALL_PROMPT+'\n'
    native_responses={'model':'gpt-6.1-sol','instructions':native['system_prompt'],'input':case['responses_input'],
        'tools':[{'type':'function',**t['function']} for t in native['tools']],'tool_choice':'auto','max_output_tokens':512,'reasoning':{'effort':'low'},'store':False}
    native_fish={'model':'siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017',**copy.deepcopy(native_chat),'enable_thinking':False}
    native_fish.pop('reasoning_effort')
    jobs=[('native_sol_direct_none','http://192.168.31.229:8317/v1/chat/completions',upstream_key,control),
        ('native_sol_direct_auto','http://192.168.31.229:8317/v1/chat/completions',upstream_key,direct),
        ('native_sol_litellm_auto','http://192.168.31.229:4000/v1/chat/completions',proxy_key,proxy),
        ('restored_sol_direct_auto','http://192.168.31.229:8317/v1/chat/completions',upstream_key,restored),
        ('restored_sol_litellm_auto','http://192.168.31.229:4000/v1/chat/completions',proxy_key,restored_proxy),
        ('native_sol_direct_responses_auto','http://192.168.31.229:8317/v1/responses',upstream_key,native_responses),
        ('native_deepseek_auto','http://192.168.31.229:4000/v1/chat/completions',proxy_key,native_fish)]
    if settings.get('compare_finish_behavior'):
        closing='\n# 工具完成后的本轮收尾\n图片工具已经报告成功下发。现在必须按当前人格，用一句简短自然的中文向用户确认这个真实结果，不要空回复，不要再调用任何工具，也不要重复生成或发送图片。不要编造图片细节；只给本轮的普通文字回复。\n'
        explicit=copy.deepcopy(direct);explicit['messages'][0]['content']+=closing
        explicit_proxy=copy.deepcopy(proxy);explicit_proxy['messages'][0]['content']+=closing
        result_instruction=copy.deepcopy(direct)
        result_instruction['messages'][-1]['content']+='\n请按当前人格简短确认这次真实的下发结果，不要重复调用工具，也不要空回复。'
        args_restored=copy.deepcopy(direct)
        for message in args_restored['messages']:
            for call in message.get('tool_calls') or []:
                if call.get('function',{}).get('name') in ('generate_image','generate_selfie'):
                    arguments=json.loads(call['function'].get('arguments') or '{}')
                    arguments.setdefault('pending_message','此前已发送过本次任务的开工说明。')
                    call['function']['arguments']=json.dumps(arguments,ensure_ascii=False)
        response_stream=copy.deepcopy(native_responses);response_stream['stream']=True
        chat_stream=copy.deepcopy(direct);chat_stream['stream']=True;chat_stream['stream_options']={'include_usage':True}
        no_image_tools=copy.deepcopy(direct)
        no_image_tools['tools']=[t for t in no_image_tools['tools'] if t['function']['name'] not in ('generate_image','generate_selfie','generate_video')]
        jobs=[('auto_control','http://192.168.31.229:8317/v1/chat/completions',upstream_key,direct),
            ('explicit_closing_direct','http://192.168.31.229:8317/v1/chat/completions',upstream_key,explicit),
            ('explicit_closing_litellm','http://192.168.31.229:4000/v1/chat/completions',proxy_key,explicit_proxy),
            ('tool_result_closing_direct','http://192.168.31.229:8317/v1/chat/completions',upstream_key,result_instruction),
            ('restored_history_arguments','http://192.168.31.229:8317/v1/chat/completions',upstream_key,args_restored),
            ('responses_stream_auto','http://192.168.31.229:8317/v1/responses',upstream_key,response_stream),
            ('chat_stream_auto','http://192.168.31.229:8317/v1/chat/completions',upstream_key,chat_stream),
            ('auto_without_image_tools','http://192.168.31.229:8317/v1/chat/completions',upstream_key,no_image_tools)]
    if settings.get('verify_deployed_fix'):
        before=json.loads(Path('/AstrBot/data/temp/native-tool-prompt-before-fix.json').read_text())
        baseline=copy.deepcopy(direct);baseline['messages'][0]['content']=before['system_prompt'];baseline['tools']=before['tools']
        failed=copy.deepcopy(direct);failed['messages'][-1]['content']='系统提示：画图失败（本项为诊断替身状态，未执行新操作）。'
        remaining=copy.deepcopy(direct)
        for message in reversed(remaining['messages']):
            if message.get('role')=='user':
                if isinstance(message.get('content'),list):
                    message['content'].append({'type':'text','text':'图片发完后，还请调用 search_chat_history 查找群里此前约定的活动时间，再告诉我。必须先查工具，不要猜测。'})
                else:message['content']+='\n图片发完后，还请调用 search_chat_history 查找群里此前约定的活动时间，再告诉我。必须先查工具，不要猜测。'
                break
        jobs=[('before_fix_control','http://192.168.31.229:8317/v1/chat/completions',upstream_key,baseline),
            ('fixed_sol_direct_chat_auto','http://192.168.31.229:8317/v1/chat/completions',upstream_key,direct),
            ('fixed_sol_litellm_chat_auto','http://192.168.31.229:4000/v1/chat/completions',proxy_key,proxy),
            ('fixed_sol_direct_responses_auto','http://192.168.31.229:8317/v1/responses',upstream_key,native_responses),
            ('fixed_failure_counterexample','http://192.168.31.229:8317/v1/chat/completions',upstream_key,failed),
            ('fixed_remaining_task_counterexample','http://192.168.31.229:8317/v1/chat/completions',upstream_key,remaining)]
        conversation_id=settings.get('conversation_id') or case.get('conversation_id')
        if conversation_id:
            with_header=copy.deepcopy(proxy)
            with_header['_diagnostic_headers']={'x-astrbot-conversation-id':conversation_id}
            jobs.append(('fixed_production_conversation_header','http://192.168.31.229:4000/v1/chat/completions',proxy_key,with_header))


def run(name,url,key,payload):
    start=time.monotonic();row={'test':name}
    try:
        payload=dict(payload);extra_headers=payload.pop('_diagnostic_headers',{})
        request=urllib.request.Request(url,data=json.dumps(payload,ensure_ascii=False).encode(),
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json',**extra_headers})
        with urllib.request.urlopen(request,timeout=75) as response:
            row['status']=response.status
            row['call_id']=response.headers.get('x-litellm-call-id')
            if payload.get('stream'):
                text='';events={};completed_chars=None;output_tokens=None
                for line in response:
                    line=line.decode('utf-8',errors='replace').strip()
                    if not line.startswith('data:'):continue
                    value=line[5:].strip()
                    if value=='[DONE]':continue
                    item=json.loads(value);kind=item.get('type','chat_chunk');events[kind]=events.get(kind,0)+1
                    if kind=='response.output_text.delta':text+=item.get('delta') or ''
                    for choice in item.get('choices',[]):
                        text+=choice.get('delta',{}).get('content') or ''
                        if choice.get('finish_reason'):row['finish_reason']=choice['finish_reason']
                    if item.get('usage'):output_tokens=item['usage'].get('completion_tokens')
                    if kind=='response.completed':
                        final=item.get('response',{});output_tokens=final.get('usage',{}).get('output_tokens')
                        completed_chars=sum(len(c.get('text','')) for m in final.get('output',[]) for c in m.get('content',[]) if c.get('type')=='output_text')
                row.update(stream=True,text_chars=len(text),usable_text=bool(text.strip()),events=events,completed_text_chars=completed_chars,output_tokens=output_tokens)
                row['seconds']=round(time.monotonic()-start,3)
                return row
            result=json.load(response)
        if 'choices' in result:
            choice=result['choices'][0];message=choice['message']
            text=message.get('content') or ''
            row.update(finish_reason=choice.get('finish_reason'),message_keys=list(message),
                tool_calls=[c.get('function',{}).get('name') for c in message.get('tool_calls') or []],image_output_present=bool(message.get('images')))
        else:
            text=''.join(c.get('text','') for item in result.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
            row.update(response_status=result.get('status'),output_types=[i.get('type') for i in result.get('output',[])],tool_calls=[i.get('name') for i in result.get('output',[]) if i.get('type')=='function_call'])
        usage=result.get('usage',{})
        row.update(text_chars=len(text),usable_text=bool(text.strip()),
            response_id=result.get('id'),
            negative_failure_feedback=bool(re.search(r'失败|未成功|没成功|没能|没完成|未完成',text)),
            output_tokens=usage.get('completion_tokens',usage.get('output_tokens')),
            input_tokens=usage.get('prompt_tokens',usage.get('input_tokens')))
    except urllib.error.HTTPError as exc:
        # Error bodies may contain rejected images/history: do not export them.
        row.update(error='HTTPError',status=exc.code)
        error=exc.read(25000).decode(errors='replace').lower()
        row['error_markers']=[name for name in ('unsupportedparams','tool_choice','invalid_image','image_url','badrequest','message','name','function','parameter','tool') if name in error]
    except Exception as exc:row['error']=type(exc).__name__
    row['seconds']=round(time.monotonic()-start,3)
    return row


report={'case':'approved stored incident history with prepared system prompt; decision-only; not exact captured wire payload',
        'tool_execution_enabled':False,'history_messages':len(case['history']),'qq_messages_sent':0,'image_generations_requested':0,'tests':[]}
with ThreadPoolExecutor(max_workers=3) as pool:
    futures=[pool.submit(run,*job) for job in jobs]
    for future in as_completed(futures):
        row=future.result();report['tests'].append(row)
        Path('/AstrBot/data/temp/continuation-metadata.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(row,ensure_ascii=False),flush=True)
