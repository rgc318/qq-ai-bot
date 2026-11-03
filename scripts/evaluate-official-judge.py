"""Synthetic classifier conformance over the official API, from AstrBot's network."""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request


def worker():
    config=json.load(sys.stdin);rows=[]
    for fixture in config['cases']:
        payload={'model':config['model'],'messages':[{'role':'system','content':config['prompt']},{'role':'user','content':json.dumps(fixture['payload'],ensure_ascii=False)}],
            'thinking':{'type':'disabled'},'max_tokens':240,'temperature':0.1,'response_format':{'type':'json_object'},'stream':False}
        start=time.perf_counter();row={'case':fixture['name']}
        try:
            request=urllib.request.Request('https://api.deepseek.com/v1/chat/completions',data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+config['key'],'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=8) as response:data=json.load(response)
            message=data['choices'][0]['message'];row.update(seconds=round(time.perf_counter()-start,3),verdict=json.loads(message.get('content') or ''),
                reasoning_chars=len(message.get('reasoning_content') or ''),input_tokens=data.get('usage',{}).get('prompt_tokens'),output_tokens=data.get('usage',{}).get('completion_tokens'))
        except urllib.error.HTTPError as exc:row.update(seconds=round(time.perf_counter()-start,3),error_type='HTTPError',http_status=exc.code)
        except Exception as exc:row.update(seconds=round(time.perf_counter()-start,3),error_type=type(exc).__name__)
        rows.append(row);print(json.dumps({'type':'sample',**{k:v for k,v in row.items() if k!='verdict'}},ensure_ascii=False),flush=True)
    print(json.dumps({'type':'result','rows':rows},ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',action='store_true');parser.add_argument('--confidence-audit',action='store_true');parser.add_argument('--model',choices=('deepseek-flash','deepseek-v4-pro'),default='deepseek-flash');args=parser.parse_args()
    if args.worker:worker();return
    from deployment_api import ROOT,write_report
    spec=importlib.util.spec_from_file_location('judge_fixtures',ROOT/'scripts/evaluate-judge-candidates.py')
    fixture_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture_module)
    key=next(line.split('=',1)[1].strip() for line in (ROOT/'secrets/deepseek-official.env').read_text(encoding='utf-8-sig').splitlines() if line.startswith('DEEPSEEK_API_KEY='))
    fixtures_to_run=fixture_module.CASES
    if args.confidence_audit:fixtures_to_run=[next(f for f in fixture_module.CASES if f['name']=='independent_meme_request')]*3
    config={'key':key,'prompt':fixture_module.PROMPT,'cases':fixtures_to_run,'model':args.model}
    container='qq-ai-bot-astrbot-1';destination='/AstrBot/data/temp/evaluate-official-judge.py'
    subprocess.run(['wsl','-d','Ubuntu','--exec','docker','cp','/mnt/e/AI/ai/qq-ai-bot/scripts/evaluate-official-judge.py',container+':'+destination],check=True,capture_output=True)
    proc=subprocess.Popen(['wsl','-d','Ubuntu','--exec','docker','exec','-i',container,'python','-u',destination,'--worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace')
    rows=None
    try:
        proc.stdin.write(json.dumps(config,ensure_ascii=False));proc.stdin.close()
        for line in proc.stdout:
            try:item=json.loads(line)
            except ValueError:continue
            if item.get('type')=='result':rows=item['rows']
            else:print(json.dumps(item,ensure_ascii=False),flush=True)
        proc.wait(timeout=20);assert proc.returncode==0 and rows is not None,'Synthetic worker failed'
        fixtures={f['name']:f for f in fixture_module.CASES}
        for row in rows:
            row['correct']=fixture_module.valid_verdict(row.get('verdict'),fixtures[row['case']])
            row['passed']=row['correct'] and row['seconds']<8 and row.get('reasoning_chars')==0 and 'error_type' not in row
        report={'passed':all(r['passed'] for r in rows),'model':args.model,'provider':'official_direct','samples':len(rows),'correct':sum(r['correct'] for r in rows),
            'median_seconds':round(statistics.median(r['seconds'] for r in rows),3),'maximum_seconds':max(r['seconds'] for r in rows),'rows':rows,
            'synthetic_only':True,'model_calls':len(rows),'qq_messages_sent':0,'main_replies':0,'image_generations':0,'real_history_replayed':False,
            'limits':'Small synthetic classifier sample, not production p95 or a replay of the 7.25-second request.'}
        prefix='official-deepseek-pro-judge' if args.model=='deepseek-v4-pro' else 'official-deepseek-judge'
        write_report(prefix+('-confidence-audit.json' if args.confidence_audit else '-evaluation.json'),report)
        print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False,indent=2))
        assert report['passed'],'Official classifier conformance failed'
    finally:
        if proc.poll() is None:proc.terminate()
        subprocess.run(['wsl','-d','Ubuntu','--exec','docker','exec',container,'python','-c',"from pathlib import Path;Path('/AstrBot/data/temp/evaluate-official-judge.py').unlink(missing_ok=True)"],capture_output=True)


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    main()
