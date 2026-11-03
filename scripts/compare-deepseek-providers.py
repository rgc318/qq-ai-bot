"""Paired synthetic probes from the AstrBot container; never execute tools.

Keys travel only over docker exec stdin, never command arguments or reports.
Official direct vs existing LiteLLM/SiliconFlow is a route comparison, not proof
that a particular intermediate service caused an outlier.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        before=urllib.parse.urlsplit(req.full_url);after=urllib.parse.urlsplit(newurl)
        if (before.scheme,before.netloc)!=(after.scheme,after.netloc):raise urllib.error.URLError('cross_origin_redirect_denied')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def http(route,path,payload=None):
    req=urllib.request.Request(route['base']+path,data=json.dumps(payload,ensure_ascii=False).encode() if payload is not None else None,
        headers={'Authorization':'Bearer '+route['key'],'Content-Type':'application/json'})
    with urllib.request.build_opener(SameOriginRedirect()).open(req,timeout=75) as response:return json.load(response)


def probe(route,case,round_number):
    payload={'model':route['model'],'messages':case['messages'],'max_tokens':240,
             'tools':case['tools'],'tool_choice':'auto' if case['kind']=='catalog' else 'none','stream':False}
    payload.update(thinking={'type':'disabled'}) if route['name']=='official' else payload.update(enable_thinking=False)
    start=time.perf_counter();row={'route':route['name'],'model_requested':route['model'],'case':case['kind'],'round':round_number}
    try:
        response=http(route,'/chat/completions',payload);row['seconds']=round(time.perf_counter()-start,3)
        message=response['choices'][0]['message'];calls=message.get('tool_calls') or [];text=message.get('content') or ''
        selected=[]
        for call in calls:
            if call['function']['name']=='view_context_images':selected+=json.loads(call['function']['arguments']).get('attachment_ids',[])
        row.update(ok=True,model_returned=response.get('model'),tool_names=[c['function']['name'] for c in calls],
            correct=(set(selected)==set(case['image_ids']) and bool(selected)) if case['kind']=='catalog' else '红' in text and not calls,
            output_chars=len(text),reasoning_chars=len(message.get('reasoning_content') or ''),
            input_tokens=response.get('usage',{}).get('prompt_tokens'),output_tokens=response.get('usage',{}).get('completion_tokens'),
            cache_hit_tokens=response.get('usage',{}).get('prompt_cache_hit_tokens'),finish_reason=response['choices'][0].get('finish_reason'))
    except urllib.error.HTTPError as exc:
        row.update(ok=False,http_status=exc.code,seconds=round(time.perf_counter()-start,3))
        # Do not emit remote error strings, which may echo request credentials.
    except Exception as exc:row.update(ok=False,error_type=type(exc).__name__,seconds=round(time.perf_counter()-start,3))
    return row


def worker():
    config=json.load(sys.stdin);routes=config['routes'];fixtures=config['fixtures'];rounds=config['rounds'];rows=[]
    try:
        data=http(routes[0],'/models')
        if not any(m.get('id')=='deepseek-flash' for m in data.get('data',[])):raise ValueError('model_not_available')
    except urllib.error.HTTPError as exc:
        print(json.dumps({'type':'blocked','http_status':exc.code,'reason':'official_model_discovery_failed'}),flush=True);return 2
    except Exception as exc:
        print(json.dumps({'type':'blocked','error_type':type(exc).__name__,'reason':'official_model_discovery_failed'}),flush=True);return 2
    tools=[{'type':'function','function':{'name':'view_context_images','description':'按来源ID读取历史图片。已提供预览时无需重复读取。',
        'parameters':{'type':'object','properties':{'attachment_ids':{'type':'array','items':{'type':'string'}}},'required':['attachment_ids']}}}]
    short=deepcopy(fixtures['preview']);short.update(kind='short_image',tools=tools)
    catalog=deepcopy(fixtures['catalog']);catalog.update(kind='catalog',tools=tools)
    long=deepcopy(short);long['kind']='long_image'
    records=[f'合成练习记录{i:03d}：第{i%7+1}小组在第{i%5+1}教室准备虚构展览，角色编号为R{i:03d}，提交了设计草稿与材料清单。此段仅用于填充测试上下文，不是真实成员经历，不修改图片样本，也不覆盖最后的问题。' for i in range(200)]
    history=[]
    for i in range(10):history.extend([{'role':'user','content':'\n'.join(records[i*20:(i+1)*20])},{'role':'assistant','content':f'已记录第{i+1}批合成练习资料。'}])
    long['messages']=long['messages'][:1]+history+long['messages'][1:]
    jobs=[(short,1),*[(long,i+1) for i in range(rounds)],(catalog,1)]
    for case,round_number in jobs:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending=[pool.submit(probe,route,case,round_number) for route in routes]
            for future in as_completed(pending):
                row=future.result();rows.append(row);print(json.dumps({'type':'sample',**row},ensure_ascii=False),flush=True)
        if any(r.get('http_status') in (401,402,403) for r in rows):break
    summary=[]
    for route in routes:
        for kind in ('short_image','long_image','catalog'):
            group=[r for r in rows if r['route']==route['name'] and r['case']==kind];times=[r['seconds'] for r in group if r.get('ok')]
            summary.append({'route':route['name'],'case':kind,'samples':len(group),'successes':len(times),'correct':sum(bool(r.get('correct')) for r in group),
                'median_seconds':round(statistics.median(times),3) if times else None,'maximum_seconds':max(times) if times else None})
    report={'type':'report','passed':all(r.get('ok') and r.get('correct') for r in rows) and len(rows)==2*len(jobs),'rows':rows,'summary':summary,
        'model_calls':len(rows),'tools_executed':0,'image_generations':0,'qq_messages_sent':0,'real_history_replayed':False,
        'location':'existing_astrbot_container','automatic_http_retries':0,
        'proxy_env_present':any(os.environ.get(k) for k in ('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy')),
        'limits':'Small synthetic paired route comparison. Official direct vs LAN LiteLLM/SiliconFlow; cannot isolate LiteLLM overhead from upstream provider. No production p95 claim.'}
    print(json.dumps(report,ensure_ascii=False),flush=True);return 0 if report['passed'] else 1


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',action='store_true');parser.add_argument('--rounds',type=int,default=3);args=parser.parse_args()
    if args.worker:return worker()
    if not 1<=args.rounds<=5:raise ValueError('rounds must be 1..5')
    from deployment_api import DeploymentAPI,ROOT,write_report
    key=next(line.split('=',1)[1].strip() for line in (ROOT/'secrets/deepseek-official.env').read_text(encoding='utf-8-sig').splitlines() if line.startswith('DEEPSEEK_API_KEY='))
    api=DeploymentAPI();fixtures=json.loads((ROOT/'logs/task-evidence-probes.local.json').read_text(encoding='utf-8'))
    # Only isolated synthetic exports are admitted, never production histories.
    assert set(fixtures)=={'preview','catalog'} and all('fixture-' in json.dumps(v) for v in fixtures.values())
    config={'routes':[{'name':'official','base':'https://api.deepseek.com/v1','key':key,'model':'deepseek-flash'},
                      {'name':'litellm_siliconflow','base':api.model_base,'key':api.api_key,'model':'siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017'}],
            'fixtures':fixtures,'rounds':args.rounds}
    container='qq-ai-bot-astrbot-1';destination='/AstrBot/data/temp/deepseek-provider-comparison.py'
    subprocess.run(['wsl','-d','Ubuntu','--exec','docker','cp','/mnt/e/AI/ai/qq-ai-bot/scripts/compare-deepseek-providers.py',container+':'+destination],check=True,capture_output=True)
    proc=subprocess.Popen(['wsl','-d','Ubuntu','--exec','docker','exec','-i',container,'python','-u',destination,'--worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace')
    report=None
    try:
        proc.stdin.write(json.dumps(config,ensure_ascii=False));proc.stdin.close()
        for line in proc.stdout:
            try:row=json.loads(line)
            except ValueError:continue
            if row.get('type')=='report':report=row
            else:print(json.dumps(row,ensure_ascii=False),flush=True)
        proc.wait(timeout=20)
        if report:
            write_report('deepseek-provider-comparison.json',report);print(json.dumps({'summary':report['summary'],'passed':report['passed']},ensure_ascii=False,indent=2))
        elif proc.returncode:print(json.dumps({'error':'benchmark_worker_failed','exit_code':proc.returncode}))
        return proc.returncode
    finally:
        if proc.poll() is None:proc.terminate()
        subprocess.run(['wsl','-d','Ubuntu','--exec','docker','exec',container,'python','-c',"from pathlib import Path;p=Path('/AstrBot/data/temp/deepseek-provider-comparison.py');p.unlink(missing_ok=True)"],capture_output=True)


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    raise SystemExit(main())
