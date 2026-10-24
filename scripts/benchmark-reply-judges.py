"""Compare judge latency/decisions on synthetic conversations; no QQ messages."""
import concurrent.futures
import ast
import json
import sys
import time
from deployment_api import DeploymentAPI, ROOT, write_report

tree=ast.parse((ROOT/'extensions/astrbot_plugin_qq_persona_models/reply_routing.py').read_text(encoding='utf-8'))
prompt=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='JUDGE_SYSTEM_PROMPT' for t in node.targets))
api=DeploymentAPI()
models=['siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017','siliconflow/Qwen/Qwen3-30B-A3B-Instruct-2507','siliconflow/Qwen/Qwen3.5-9B']
cases=[
    ('followup','现在用生图模型把之前让你画的菜生成出来',[], 'followup'),
    ('human_exchange','给我也整一份',[{'role':'user','sender':'C','text':'楼下盒饭不错，我准备给D带一份。'},{'role':'user','sender':'D','text':'给我带鸡腿饭。'}], 'ambient'),
    ('cross_member','给我也整一份，改成周日',[], 'followup'),
]
def run(model):
    rows=[]
    for name,text,recent,expected in cases:
        payload={'bot_aliases':['大肥鱼','ai助手'],'last_ai_activity':{'id':'ai-1','status':'sent','age_seconds':600,'request':'画一桌菜和读书会海报','reply':'可以，我来画。','requested_by':'A'},'recent_messages':recent,'latest_message':{'sender':'B','text':text}}
        start=time.monotonic()
        try:
            response=api.model('/chat/completions',{'model':model,'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],'temperature':0.1,'max_tokens':240,'enable_thinking':False,'response_format':{'type':'json_object'}},timeout=25)
            verdict=json.loads(response['choices'][0]['message']['content'])
            rows.append({'case':name,'seconds':round(time.monotonic()-start,2),'passed':verdict.get('route')==expected,'verdict':verdict,'usage':response.get('usage')})
        except Exception as exc:
            rows.append({'case':name,'seconds':round(time.monotonic()-start,2),'passed':False,'error':api.sanitize(str(exc))[:240]})
    result={'model':model,'rows':rows}
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results=list(pool.map(run,models))
write_report('reply-judge-community-benchmark.json',{'results':results,'qq_messages_sent':0})
