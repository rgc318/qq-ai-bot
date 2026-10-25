"""Run scoped runtime tests with no production data or network in the container."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
BASE=['wsl','-d','Ubuntu','--exec','docker']


def docker(*args,timeout=120):
    return subprocess.run(BASE+list(args),capture_output=True,text=True,encoding='utf-8',errors='replace',check=True,timeout=timeout)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--same-volume',action='store_true');parser.add_argument('--models',action='store_true');args=parser.parse_args()
    info=json.loads(docker('inspect','qq-ai-bot-astrbot-1').stdout)[0]
    name='qq-context-runtime-'+uuid4().hex[:10]
    cmd=['run','--rm','--name',name,'--network','none','--read-only','--memory','1g','--cap-drop','ALL','--security-opt','no-new-privileges','--tmpfs','/tmp:rw,size=128m','-e','PYTHONDONTWRITEBYTECODE=1','-e','TZ=Asia/Shanghai']
    if args.same_volume:
        volume=next(v['Name'] for v in info['Mounts'] if v['Destination']=='/AstrBot/data' and v['Type']=='volume')
        subpath='temp/'+name
        docker('exec','qq-ai-bot-astrbot-1','python','-c','from pathlib import Path;p=Path('+repr('/AstrBot/data/'+subpath)+');assert p.parent==Path("/AstrBot/data/temp");p.mkdir()')
        cmd+=['--mount','type=volume,source='+volume+',destination=/AstrBot/data,volume-subpath='+subpath]
    else:cmd+=['--tmpfs','/AstrBot/data:rw,size=256m']
    for src,dst in [('extensions','/workspace/extensions'),('integrations','/workspace/integrations'),('downloads/contextaware-f026c56','/candidate'),('scripts/verify-context-runtime-native.py','/workspace/verify.py')]:
        cmd+=['--mount','type=bind,src=/mnt/e/AI/ai/qq-ai-bot/'+src+',dst='+dst+',readonly']
    cmd+=['--entrypoint','python',info['Image'],'/workspace/verify.py']
    try:result=docker(*cmd)
    except subprocess.CalledProcessError as exc:
        print(exc.stdout[-16000:]);print(exc.stderr[-5000:]);raise SystemExit(exc.returncode)
    except (subprocess.TimeoutExpired,KeyboardInterrupt):
        docker('rm','-f',name);raise
    report=json.loads(next(l.split('=',1)[1] for l in result.stdout.splitlines() if l.startswith('RUNTIME_REPORT=')))
    probes=report.pop('model_probes',{})
    report['storage']='isolated_subdirectory_on_production_volume' if args.same_volume else 'tmpfs'
    report['runtime_image']=info['Image']
    path=ROOT/'logs'/('context-runtime-'+('volume' if args.same_volume else 'isolated')+'.json')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    assert report['passed']
    if args.models:
        from deployment_api import DeploymentAPI
        api=DeploymentAPI();rows=[]
        routes=[('DeepSeek1017','siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017',{'enable_thinking':False}),('Sol-low','cliproxyapi/gpt-6.1-sol',{'reasoning_effort':'low','allowed_openai_params':['reasoning_effort']})]
        for label,model,options in routes:
            for mode,messages in probes.items():
                start=time.perf_counter()
                response=api.model('/chat/completions',{'model':model,'messages':messages,'max_tokens':512,**options},timeout=100)
                message=response['choices'][0]['message'];text=message.get('content') or ''
                row={'route':label,'backend':mode,'seconds':round(time.perf_counter()-start,3),'input_chars':len(json.dumps(messages,ensure_ascii=False)),
                     'input_tokens':response.get('usage',{}).get('prompt_tokens'),'output_chars':len(text),
                     'facts_correct':('12' in text or '十二' in text) and ('A厅' in text or 'A 厅' in text),
                     'unexpected_tool_calls':len(message.get('tool_calls') or [])}
                rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        model_report={'passed':all(r['facts_correct'] and not r['unexpected_tool_calls'] for r in rows),'rows':rows,'model_calls':len(rows),'synthetic_only':True,'real_history_replayed':False,'image_generations':0,'qq_messages_sent':0,'limits':'One prepared synthetic request per route/backend; not a production mean or p95'}
        (ROOT/'logs/context-runtime-model-probe.json').write_text(json.dumps(model_report,ensure_ascii=False,indent=2),encoding='utf-8')
        assert model_report['passed'],'Synthetic text/latency probe failed'


if __name__=='__main__':main()
