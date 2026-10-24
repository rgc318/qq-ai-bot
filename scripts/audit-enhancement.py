from deployment_api import DeploymentAPI, write_report
import json

api = DeploymentAPI()
summary = {}
for name, path in {
    "profile": "/api/v1/config-profiles/default",
    "providers": "/api/config/provider/template",
    "personas": "/api/persona/list",
    "plugins": "/api/v1/plugins",
    "tools": "/api/v1/tools",
    "selfreply": "/api/v1/plugins/astrbot_plugin_self_initiated_reply/config",
}.items():
    try:
        result = api.call(path)
        api.backup(name + ".json", result)
        data = result.get("data", {})
        if name == "profile":
            summary[name] = {"keys": list(data), "config_keys": list(data.get("config", {}))}
        elif name == "providers":
            summary[name] = [{k: item.get(k) for k in ("id", "type", "model", "modalities", "custom_extra_body", "provider_source_id")} for item in data.get("providers", [])]
        elif name == "plugins":
            summary[name] = data
        elif name == "tools":
            summary[name] = {"keys": list(data)} if isinstance(data, dict) else data
        else:
            summary[name] = data
    except Exception as exc:
        summary[name] = api.sanitize(str(exc))[:500]
models = api.model("/models")
summary["target_models"] = [item["id"] for item in models.get("data", []) if any(s in item["id"].lower() for s in ("1017", "6.1-sol", "image-2.5"))]
write_report("enhancement-audit.json", summary)
print(api.sanitize(json.dumps(summary, ensure_ascii=False)))
