"""Use the live deployed judge on synthetic group conversations; never send QQ messages."""
import concurrent.futures
import argparse
import json
import time
from deployment_api import DeploymentAPI,write_report

api=DeploymentAPI()
ad=[{"role":"user","sender":"A","text":"ai助手，帮我写一份读书会活动文案。"},{"role":"assistant","text":"周六读书会招募：带一本你喜欢的书，一起分享阅读心得。","request":"帮 A 写读书会活动文案"}]
code=[{"role":"user","sender":"A","text":"帮我用 Python 读取 CSV 文件。"},{"role":"assistant","text":"第一步导入 csv 模块；第二步用 csv.DictReader 读取文件并逐行处理。","request":"用 Python 读取 CSV"}]
draw=[{"role":"user","sender":"A","text":"帮我画一只红色小猫。"},{"role":"assistant","text":"[AI已发送一张红色小猫的生成图片]","request":"画一只红色小猫"}]
cases=[
    {"id":"cross_member_copy","history":ad,"message":"给我也整一份","expected":"fast"},
    {"id":"shorten","history":ad,"message":"再短一点，控制在50字","expected":"fast"},
    {"id":"new_member_topic","history":ad,"message":"我也要一份，主题改成摄影社招新","expected":"fast"},
    {"id":"explain_step","history":code,"message":"第二步展开讲一下","expected":"fast"},
    {"id":"why_code","history":code,"message":"为什么这里要用DictReader？","expected":"fast"},
    {"id":"revise_image","history":draw,"message":"换成蓝色，背景保持不变","expected":"fast"},
    {"id":"another_image","history":draw,"message":"我也要一张，换成小狗","expected":"fast"},
    {"id":"pending_task","history":[{"role":"assistant","pending":True,"text":"","request":"A 刚刚请机器人写一份活动文案，正在生成"}],"message":"给我也整一份，写社团招新","expected":"fast"},
    {"id":"active_group_chatter","history":ad+[{"role":"user","sender":"C","text":"今晚玩什么游戏？"},{"role":"user","sender":"D","text":"我一会儿上线。"}],"message":"刚才机器人的读书会文案也给我写一份，换成周日","expected":"fast"},
    {"id":"name_not_prefix","history":[],"message":"能介绍一下DeepSeek吗，小鲸鱼","expected":"fast"},
    {"id":"no_context","history":[],"message":"给我也整一份","expected":"ambient"},
    {"id":"expired_context","history":[{**ad[-1],"age_seconds":1801}],"message":"给我也整一份","expected":"ambient"},
    {"id":"late_cross_member_followup","history":[{**ad[-1],"age_seconds":900}],"message":"刚才你写的读书会活动文案，也给我整一份，改成周日","expected":"fast"},
    {"id":"late_code_followup","history":[{**code[-1],"age_seconds":1440}],"message":"之前你给的CSV读取示例，DictReader那一步再详细解释一下","expected":"fast"},
    {"id":"late_food_ambiguity","history":[{**ad[-1],"age_seconds":900},{"role":"user","sender":"C","text":"楼下盒饭不错，我准备给D带一份。"},{"role":"user","sender":"D","text":"帮我带鸡腿饭吧。"}],"message":"给我也整一份","expected":"ambient"},
    {"id":"thanks","history":ad,"message":"谢谢！","expected":"ambient"},
    {"id":"reaction","history":ad,"message":"哈哈哈","expected":"ambient"},
    {"id":"unrelated_food","history":ad+[{"role":"user","sender":"C","text":"楼下盒饭今天不错，我准备给D带一份。"},{"role":"user","sender":"D","text":"帮我带个鸡腿饭吧。"}],"message":"给我也整一份","expected":"ambient"},
    {"id":"other_person","history":ad,"message":"小王，给我也整一份","targets_other":True,"expected":"ambient"},
    {"id":"human_conversation","history":code+[{"role":"user","sender":"C","text":"小张，你刚才在群里发的自我介绍太长了。"},{"role":"user","sender":"D","text":"是啊，那段是我写的，确实啰嗦。"}],"message":"小张再短点吧","expected":"ambient"},
    {"id":"reported_speech","history":ad,"message":"他刚才说了句“给我也整一份”就跑了，笑死","expected":"ambient"},
    {"id":"explicit_optout","history":ad,"message":"不用给我也做一份了，这次别回我","expected":"ambient"},
    {"id":"talking_about_ai","history":ad,"message":"我觉得GPT和DeepSeek各有优点，这是我的看法","expected":"ambient"},
    {"id":"stop_topic","history":ad,"message":"这段先不改了，我们聊点别的，机器人不用插话","expected":"ambient"},
    {"id":"continue_code","history":code,"message":"继续，给我一个完整示例","expected":"fast"},
    {"id":"happy_meme_without_anchor","history":[],"message":"发个开心的表情包","expected":"fast"},
    {"id":"happy_meme_after_image","history":[{"role":"user","sender":"A","text":"发个表情包"},{"role":"assistant","text":"表情包已经做好了：躺在一堆饭上，尾巴都垂下去，态度很明确：摆了。","request":"发个表情包","age_seconds":660}],"message":"发个开心的表情包","expected":"fast"},
    {"id":"meme_reported_speech","history":[],"message":"小王说让我发个开心的表情包，笑死了","expected":"ambient"},
    {"id":"meme_human_exchange","history":[{"role":"user","sender":"C","text":"小张，你收藏的开心表情包给我看看"},{"role":"user","sender":"D","text":"我发的那个黄色小狗吗？"}],"message":"对，发个开心的表情包","expected":"ambient"},
]

def run(case):
    start=time.monotonic()
    try:
        result=api.call("/api/plug/qq_persona_models/reply_conditions/test",{k:v for k,v in case.items() if k not in ("id","expected")},timeout=40)["data"]
        passed=result["route"]==case["expected"]
        if case["expected"]=="fast":
            passed=passed and result["normal_pipeline_eligible"] and result["selfreply_sees_direct_call"]
        return {"id":case["id"],"expected":case["expected"],"passed":bool(passed),"seconds":round(time.monotonic()-start,2),**result}
    except Exception as exc:
        return {"id":case["id"],"passed":False,"error":api.sanitize(str(exc))[:500]}

parser=argparse.ArgumentParser()
parser.add_argument('--case', action='append', default=[])
parser.add_argument('--report', default='reply-scenario-verification.json')
args=parser.parse_args()
if args.case:
    unknown=set(args.case)-{case['id'] for case in cases}
    if unknown:
        parser.error('Unknown cases: '+', '.join(sorted(unknown)))
    cases=[case for case in cases if case['id'] in args.case]
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for future in concurrent.futures.as_completed([pool.submit(run,case) for case in cases]):
        result=future.result()
        results.append(result)
        write_report(args.report,{"checked":len(results),"passed":sum(x["passed"] for x in results),"qq_messages_sent":0,"results":results})
        print(json.dumps(result,ensure_ascii=False),flush=True)
if not all(x["passed"] for x in results):
    raise SystemExit(1)
