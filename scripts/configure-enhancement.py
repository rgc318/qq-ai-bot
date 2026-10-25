"""Apply researched persona, model and tool settings through native authenticated APIs."""
import copy
import json
from deployment_api import DeploymentAPI, ROOT, write_report

api = DeploymentAPI()
fish_id = "litellm-lan/siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017"
dragon_id = "qq-dragon-sol-low"
steps=[]
def done(label):
    steps.append(label)
    write_report("enhancement-configuration.json",{"steps":steps})
    print(label,flush=True)

profile=api.call("/api/v1/config-profiles/default")["data"]["config"]
api.backup("profile-before-enhancement.json",profile)
source=copy.deepcopy(next(x for x in profile["provider_sources"] if x["id"]=="litellm-lan"))
source.update(id="litellm-responses",type="openai_responses",key=[api.api_key])
api.call("/api/v1/provider-sources/by-id",{"source_id":"litellm-responses","config":source},method="PUT")

providers=api.call("/api/config/provider/template")["data"]["providers"]
fish=copy.deepcopy(next(x for x in providers if x["id"]==fish_id))
fish.update(type="openai_chat_completion",enable=True,modalities=["text","image","tool_use"],custom_extra_body={"max_tokens":4096})
api.call("/api/config/provider/update",{"id":fish_id,"config":fish})
dragon={"id":dragon_id,"model":"cliproxyapi/gpt-6.1-sol","provider_source_id":"litellm-responses","type":"openai_responses","provider_type":"chat_completion","enable":True,"modalities":["text","image","tool_use"],"custom_extra_body":{"reasoning_effort":"low","max_output_tokens":4096}}
if any(x["id"]==dragon_id for x in providers):
    api.call("/api/config/provider/update",{"id":dragon_id,"config":dragon})
else:
    api.call("/api/v1/provider-sources/providers",{"source_id":"litellm-responses","config":dragon})
# An image generator should be exposed as an image tool, not a selectable chat brain.
for item in providers:
    if item.get("id")=="litellm-lan/cliproxyapi/gpt-6.1-sol" or (item.get("model")=="gpt-image-2.5" and item.get("enable",True)):
        item=copy.deepcopy(item)
        item["enable"]=False
        api.call("/api/config/provider/update",{"id":item["id"],"config":item})
done("Configured DeepSeek 1017 and a dedicated Responses / low provider for Sol.")

existing={x["persona_id"] for x in api.call("/api/persona/list")["data"]}
for persona in ("大肥鱼","ChatGPT龙娘"):
    payload={"persona_id":persona,"system_prompt":(ROOT/"personas"/(persona+".md")).read_text(encoding="utf-8"),"tools":["generate_image","web_search_anysearch"],"skills":[],"begin_dialogs":[]}
    api.call("/api/persona/"+("update" if persona in existing else "create"),payload)
done("Created both personas with explicit image-generation and web-search tool access.")

# Fetch the latest profile to preserve newly-created provider records.
profile=api.call("/api/v1/config-profiles/default")["data"]["config"]
profile["provider_settings"].update(default_provider_id=fish_id,default_personality="大肥鱼",identifier=True,group_name_display=True,web_search=True,websearch_provider="anysearch",websearch_anysearch_key=[],web_search_link=True,display_reasoning_text=False)
profile["agent_runner"]["config"]["model"]["provider_id"]=fish_id
profile["platform_settings"].update(unique_session=False,empty_mention_waiting=False)
profile["provider_ltm_settings"]["group_icl_enable"]=True
profile["provider_ltm_settings"].setdefault("active_reply",{})["enable"]=False
profile["wake_prefix"]=["/","大肥鱼","肥鱼","龙娘","ai助手","AI助手"]
api.call("/api/v1/config-profiles/default",profile,method="PUT",timeout=120)
done("Configured shared group context, explicit nickname waking, and native AnySearch.")

# Establish a fixed default; the binding helper follows all later persona switches.
prefix="/api/plug/astrbot_plugin_user_policy"
bootstrap=api.call(prefix+"/bootstrap")["data"]
group_id="qq-snowluma:347440128"
rule={"description":"测试群：大肥鱼默认，龙娘可切换","persona_mode":"fixed","persona_id":"大肥鱼","provider_id":"","auto_persona":{"persona_ids":[],"scenario":"","persona_settings":{}},"memory_isolation":True,"livingmemory_isolation":True,"plugin_access":{"mode":"all","plugins":[]},"member_access":{"mode":"all","users":[]},"policy_admins":[],"users":{}}
api.call(prefix+"/groups/save",{"revision":bootstrap["revision"],"group_id":group_id,"rule":rule})
done("Bound the allowed group to the default whale persona with persona history isolation.")

omni_result=api.call("/api/v1/plugins/astrbot_plugin_omnidraw/config")["data"]
omni=copy.deepcopy(omni_result["config"])
api.backup("omnidraw-before-enhancement.json",omni)
omni.update(providers=[{"__template_key":"image_provider","id":"litellm-image25","api_type":"openai_image","base_url":api.model_base,"api_keys":api.api_key,"model":"gpt-image-2.5","available_models":["gpt-image-2.5"],"timeout":240}],video_providers=[])
omni["router_config"].update(chain_text2img="litellm-image25",chain_selfie="litellm-image25")
omni["optimizer_config"].update(enable_optimizer=False,max_batch_count=4)
omni["usage_config"].update(enable_daily_limit=True,daily_image_limit=10,enable_checkin=False)
omni["cache_config"].update(enable_size_limit_cleanup=True,max_cache_size_mb=512)
omni["persona_config"].update(active_persona_id="whale",profiles=[{"__template_key":"persona","id":"whale","persona_name":"大肥鱼","persona_base_prompt":"蓝色长发、鲸鱼尾巴、蓝白女仆裙的成年鲸鱼娘，友善可爱，日系插画。","persona_ref_image":[]},{"__template_key":"persona","id":"dragon","persona_name":"ChatGPT龙娘","persona_base_prompt":"成年白银龙娘，银白长发、浅紫眼眸、双龙角、小龙翼与银色鳞尾，优雅白银服装，日系插画。","persona_ref_image":[]}])
api.call("/api/plug/astrbot_plugin_omnidraw/save_config",omni)
done("Configured OmniDraw to use the existing image2.5 route and both character descriptions.")

selfreply=api.call("/api/v1/plugins/astrbot_plugin_self_initiated_reply/config")["data"]["config"]
selfreply.update(enabled=True,decision_model_enabled=True,judge_provider_id=fish_id,bot_aliases=["大肥鱼","肥鱼","小鱼","ai助手","AI助手","龙娘","ChatGPT","GPT"],whitelist_sessions=["347440128"],enabled_private_sessions=False,message_delay_sec=10,min_silence_sec=10,cooldown_sec=60,max_daily_replies_per_session=100,recent_message_limit=30,decision_history_min_messages=8,decision_timeout_sec=35,generation_timeout_sec=120,enabled_message_trigger=True,enabled_patrol_trigger=False,skip_after_direct_call=True,proactive_inherit_tools=True,vision_judge_enabled=False,vision_main_enabled=True,vision_provider_id=fish_id,vision_skip_stickers=True,vision_max_images=2,vision_timeout_sec=35,quote_mode="model",log_reply_content=False,max_reply_chars=500)
# Preserve the plugin's current template and append a focused rule.
extra="\n部署补充：大肥鱼、肥鱼、龙娘、ai助手是本机器人的称呼。有人用这些称呼向你提问，或明显继续追问机器人的上一条回复时，优先判断为应接话。请区分群友之间的对话；没有新问题、只发简单附和、明确不要机器人回答时保持安静。只有用户明确请求生图才允许建议生图，不主动消耗绘图额度。"
if extra not in selfreply["decision_prompt_template"]:
    selfreply["decision_prompt_template"]+=extra
api.call("/api/v1/plugins/astrbot_plugin_self_initiated_reply/config",{"config":selfreply},method="PUT",timeout=120)
done("Enabled proactive replies only in the allowed group: 10s pause, 60s cooldown, 100/day.")
write_report("enhancement-configuration.json",{"steps":steps,"default_persona":"大肥鱼","persona_models":{"大肥鱼":fish_id,"ChatGPT龙娘":dragon_id},"shared_group_context":True,"group":"347440128"})
