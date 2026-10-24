"""Read-only deployment audit. Reports exclude secrets and chat contents."""
import json
from datetime import datetime, timezone
from deployment_api import DeploymentAPI, write_report

api = DeploymentAPI()

def rows(data):
    return data if isinstance(data, list) else data.get("list", [])

def take(data, keys):
    return {k: data.get(k) for k in keys if k in data}

report = {"checked_at": datetime.now(timezone.utc).isoformat()}
profile = api.call("/api/v1/config-profiles/default")["data"]["config"]
report["profile"] = take(profile, ["admins_id", "wake_prefix", "enable", "reply_prefix", "record_telemetry"])
report["platform"] = take(profile.get("platform_settings", {}), ["unique_session", "id_whitelist", "enable_id_white_list", "ignore_at_all", "rate_limit", "segmented_reply", "segmented_reply_config"])
ps = profile.get("provider_settings", {})
report["provider_settings"] = take(ps, ["enable", "default_provider_id", "default_personality", "web_search", "websearch_provider", "web_search_link", "display_reasoning_text", "group_name_display", "identifier", "computer_use_runtime", "computer_use_require_admin", "proactive_capability", "streaming_response", "show_tool_use_status", "show_tool_call_result"])
report["group_context_enabled"] = profile.get("provider_ltm_settings", {}).get("group_icl_enable")
report["voice"] = {k: take(profile.get(k, {}), ["enable", "provider_id"]) for k in ["provider_stt_settings", "provider_tts_settings"]}
report["agent"] = take(profile.get("agent_runner", {}).get("config", {}), ["model", "compression", "max_steps", "max_tool_calls", "computer_use", "tools", "runtime"])
report["other_feature_keys"] = [k for k in profile if any(s in k for s in ["tts", "stt", "computer", "sandbox", "tool", "cron"])]
report["personas"] = [{**take(p, ["persona_id", "tools", "skills"]), "prompt_chars": len(p.get("system_prompt", ""))} for p in rows(api.call("/api/persona/list")["data"])]
report["providers"] = [take(p, ["id", "model", "type", "enable", "modalities", "max_context_tokens", "custom_extra_body"]) for p in api.call("/api/config/provider/template")["data"].get("providers", [])]
report["plugins"] = [take(p, ["name", "display_name", "version", "activated", "status", "failed", "error"]) for p in rows(api.call("/api/v1/plugins")["data"])]
report["tools"] = [take(t, ["name", "active", "origin", "builtin_config_statuses", "permission", "permission_configured"]) for t in rows(api.call("/api/v1/tools")["data"])]
report["proactive"] = take(api.call("/api/v1/plugins/astrbot_plugin_self_initiated_reply/config")["data"]["config"], ["enabled", "whitelist_sessions", "allow_private", "judge_provider_id", "message_delay_sec", "min_silence_sec", "cooldown_sec", "max_daily_replies_per_session", "enabled_patrol_trigger", "abandon_stale_on_new_message", "skip_after_direct_call", "proactive_inherit_tools", "vision_judge_enabled", "vision_main_enabled", "vision_provider_id", "max_reply_chars", "decision_history_min_messages", "log_reply_content"])
report["semantic"] = api.call("/api/plug/qq_persona_models/reply_conditions/status")["data"]
bootstrap = api.call("/api/plug/astrbot_plugin_user_policy/bootstrap")["data"]
report["groups"] = [take(g, ["group_id", "persona_mode", "persona_id", "provider_id", "memory_isolation", "livingmemory_isolation", "plugin_access", "member_access", "policy_admins"]) for g in bootstrap.get("groups", [])]
c = api.call("/api/v1/plugins/astrbot_plugin_omnidraw/config")["data"]["config"]
report["image"] = {"providers": [take(p, ["id", "model", "api_type", "base_url", "timeout"]) for p in c.get("providers", [])], "routing": c.get("router_config"), "quota": c.get("usage_config"), "cache": c.get("cache_config"), "show_request_model": c.get("show_request_model"), "show_generation_time": c.get("show_generation_time"), "optimizer": take(c.get("optimizer_config", {}), ["enable_optimizer", "max_batch_count"]), "reference_counts": [{"id": p.get("id"), "count": len(p.get("persona_ref_image", []))} for p in c.get("persona_config", {}).get("profiles", [])]}
report["binding_verification"] = api.call("/api/plug/qq_persona_models/verify")
report["messages_sent_to_qq"] = 0
safe = json.loads(api.sanitize(json.dumps(report, ensure_ascii=False)))
write_report("configuration-audit-current.json", safe)
print(json.dumps(safe, ensure_ascii=False))
