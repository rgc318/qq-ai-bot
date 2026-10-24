import concurrent.futures
import json
from deployment_api import DeploymentAPI, ROOT, write_report

api=DeploymentAPI()
results={}
def check(name,path,payload=None,timeout=120):
    try:
        raw=api.call(path,payload,timeout=timeout)
        if name=="plugin_image_generation":
            return name,{"success":raw.get("success"),"message":raw.get("message"),"image_count":len(raw.get("images",[]))}
        return name,raw
    except Exception as exc:
        return name,{"ok":False,"error":api.sanitize(str(exc))[:900]}
jobs=[
    ("persona_bindings","/api/plug/qq_persona_models/verify"),
    ("fish_provider","/api/config/provider/check_one?id=litellm-lan%2Fsiliconflow%2Fdeepseek-ai%2FDeepSeek-V4.1-Flash-1017"),
    ("dragon_provider","/api/config/provider/check_one?id=qq-dragon-sol-low"),
    ("plugin_image_generation","/api/plug/astrbot_plugin_omnidraw/generate_image_for_plugin",{"prompt":"A minimalist blue whale and a small silver dragon reading together, white background, friendly flat illustration, no text.","count":1,"size":"1024x1024","extra_params":"--quality low"},300),
]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for future in concurrent.futures.as_completed([pool.submit(check,*job) for job in jobs]):
        name,value=future.result()
        results[name]=value
        write_report("enhancement-verification.json",results)
        print(json.dumps({"name":name,"result":value},ensure_ascii=False),flush=True)
plugins=api.call("/api/v1/plugins")["data"]
results["plugins"]=[{k:x.get(k) for k in ("name","version","activated")} for x in plugins if not x.get("reserved")]
profile=api.call("/api/v1/config-profiles/default")["data"]["config"]
results["profile"]={"default_persona":profile["provider_settings"].get("default_personality"),"default_provider":profile["agent_runner"]["config"]["model"].get("provider_id"),"wake_prefix":profile["wake_prefix"],"shared_group_context":not profile["platform_settings"].get("unique_session"),"whitelist":profile["platform_settings"].get("id_whitelist"),"search":profile["provider_settings"].get("websearch_provider")}
selfreply=api.call("/api/v1/plugins/astrbot_plugin_self_initiated_reply/config")["data"]["config"]
results["proactive"]={k:selfreply.get(k) for k in ("enabled","whitelist_sessions","message_delay_sec","min_silence_sec","cooldown_sec","max_daily_replies_per_session","vision_main_enabled","proactive_inherit_tools")}
write_report("enhancement-verification.json",results)
print(json.dumps({"plugins":results["plugins"],"profile":results["profile"],"proactive":results["proactive"]},ensure_ascii=False),flush=True)
