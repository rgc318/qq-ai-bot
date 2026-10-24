"""Select the tested original LiteLLM ChatGPT route for Dragon only."""
import copy
import json
from datetime import datetime

from deployment_api import DeploymentAPI, ROOT, write_report


api = DeploymentAPI()
provider_id = "litellm-lan/cliproxyapi/gpt-6.1-sol"
plugin_path = "/api/v1/plugins/astrbot_plugin_qq_persona_models/config"
for name in ("original-chatgpt-probe.json", "original-chatgpt-low-tools.json"):
    result = json.loads((ROOT / "logs" / name).read_text(encoding="utf-8"))
    assert result.get("tool_round_trip_passed"), f"Must pass protocol test first: {name}"
activity = api.call("/api/plug/qq_persona_models/model_activity/status")
data = activity.get("data", activity)
assert not data.get("active"), "Wait for current model calls before changing providers"
providers = api.call("/api/config/provider/template")["data"]["providers"]
original = next(row for row in providers if row["id"] == provider_id)
old_config = api.call(plugin_path)["data"]["config"]
personas_before = api.call("/api/persona/list")["data"]
policy_before = api.call("/api/plug/astrbot_plugin_user_policy/bootstrap")["data"]
policy_keys = ("revision", "groups", "private_users", "schedules")
policy_before = {key: policy_before.get(key) for key in policy_keys}
profile = api.call("/api/v1/config-profiles/default")["data"]["config"]
source = next(row for row in profile["provider_sources"] if row["id"] == original["provider_source_id"])
assert source["type"] == "openai_chat_completion", "Original source must use Chat Completions"
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
api.backup(f"original-chatgpt-provider-{stamp}.json", original)
api.backup(f"original-chatgpt-bindings-{stamp}.json", old_config)
provider = copy.deepcopy(original)
provider.update(enable=True, type="openai_chat_completion", modalities=["text", "image", "tool_use"])
provider["custom_extra_body"] = {**provider.get("custom_extra_body", {}),
    "max_tokens": 4096, "reasoning_effort": "low", "allowed_openai_params": ["reasoning_effort"]}
config = copy.deepcopy(old_config)
config["bindings"]["ChatGPT龙娘"] = provider_id
try:
    api.call("/api/config/provider/update", {"id": provider_id, "config": provider})
    api.call(plugin_path, {"config": config}, method="PUT", timeout=120)
    verified = api.call("/api/plug/qq_persona_models/verify")["data"]
    assert all(row["passed"] for row in verified), "Runtime provider binding failed"
    dragon = next(row for row in verified if row["persona"] == "ChatGPT龙娘")
    assert dragon["selected_provider"] == provider_id and dragon["type"] == "openai_chat_completion"
    assert api.call("/api/persona/list")["data"] == personas_before, "Persona definitions changed"
    policy_after = api.call("/api/plug/astrbot_plugin_user_policy/bootstrap")["data"]
    assert {key: policy_after.get(key) for key in policy_keys} == policy_before, "Group policy changed"
except Exception:
    api.call(plugin_path, {"config": old_config}, method="PUT", timeout=120)
    api.call("/api/config/provider/update", {"id": provider_id, "config": original})
    raise
report = {"provider_id": provider_id, "model": provider["model"], "protocol": provider["type"],
          "extra_body": provider["custom_extra_body"], "bindings": verified,
          "personas_preserved": True, "group_policy_preserved": True,
          "old_responses_provider_retained": True, "qq_messages_sent": 0, "images_generated": 0}
write_report("original-chatgpt-configuration.json", report)
print(json.dumps(report, ensure_ascii=False))
