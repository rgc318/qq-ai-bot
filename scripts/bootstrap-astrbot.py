"""Apply this deployment's configuration inside the official AstrBot image while stopped."""

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

from astrbot.core.config.default import DEFAULT_CONFIG
from astrbot.core.utils.auth_password import hash_dashboard_password, verify_dashboard_password
from access_policy import derive_access_settings


data_dir = Path("/AstrBot/data")
data_dir.mkdir(parents=True, exist_ok=True)
config_path = data_dir / "cmd_config.json"
marker_path = data_dir / ".qq-ai-bot-initialized"
first_initialization = not marker_path.exists()
deployment = json.loads(Path("/deployment-config/deployment.local.json").read_text(encoding="utf-8-sig"))
credentials = json.loads(Path("/deployment-secrets/credentials.local.json").read_text(encoding="utf-8"))
config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else copy.deepcopy(DEFAULT_CONFIG)
if first_initialization:
    # The official image can seed a sample configuration into a fresh volume.
    # Keep a backup below, and start this dedicated deployment from its defaults.
    config = copy.deepcopy(DEFAULT_CONFIG)

source_id = "litellm-lan"
provider_id = "litellm-default-chat"
api_key = os.environ.get("QQ_BOT_API_KEY", "").strip()
if not api_key:
    raise SystemExit("QQ_BOT_API_KEY is not configured")
source = {
    "id": source_id,
    "provider": "openai",
    "type": "openai_chat_completion",
    "provider_type": "chat_completion",
    "enable": True,
    # The dashboard model-list path instantiates a provider without expanding env vars.
    "key": [api_key],
    "api_base": deployment["model_api"]["base_url"],
    "timeout": 120,
    "proxy": "",
    "custom_headers": {},
}
provider = {
    "id": provider_id,
    "provider_source_id": source_id,
    "type": "openai_chat_completion",
    "provider_type": "chat_completion",
    "enable": True,
    "model": deployment["model_api"]["model_id"],
    "modalities": ["text"],
}
config["provider_sources"] = [x for x in config.get("provider_sources", []) if x.get("id") != source_id] + [source]
config["provider"] = [x for x in config.get("provider", []) if x.get("id") != provider_id] + [provider]
runner = copy.deepcopy(DEFAULT_CONFIG["agent_runner"])
runner["config"]["model"].update({"provider_id": provider_id, "request_max_retries": 2})
runner["config"]["misc"]["max_steps"] = 16
config["agent_runner"] = runner
platform_id = "qq-snowluma"
platform = {
    "id": platform_id,
    "type": "aiocqhttp",
    "enable": True,
    "ws_reverse_host": "0.0.0.0",
    "ws_reverse_port": 6199,
    "ws_reverse_token": credentials["onebot_token"],
}
config["platform"] = [x for x in config.get("platform", []) if x.get("id") != platform_id] + [platform]

# Until the owner is known, block all real QQ users instead of opening the bot.
access = deployment["access"]
policy = derive_access_settings(access, platform_id)
owner = str(access.get("owner_qq", "")).strip()
allowed_ids = policy["platform_settings"]["id_whitelist"]
config["admins_id"] = policy["admins_id"]
settings = config.setdefault("platform_settings", {})
settings.update(policy["platform_settings"])
settings.update({
    "unique_session": True,
    "ignore_bot_self_message": True,
})
provider_settings = config.setdefault("provider_settings", {})
provider_settings.update({"computer_use_runtime": "none", "web_search": False})
provider_settings.setdefault("proactive_capability", {})["add_cron_tools"] = False
config["timezone"] = "Asia/Shanghai"
config["wake_prefix"] = ["/"]
config["disable_metrics"] = True

dashboard = config.setdefault("dashboard", {})
if first_initialization or not dashboard.get("password") or (
    not dashboard.get("pbkdf2_password")
    and verify_dashboard_password(dashboard.get("password", ""), credentials["astrbot_password"])
):
    dashboard.update({
        "username": credentials["astrbot_username"],
        "password": hashlib.md5(credentials["astrbot_password"].encode()).hexdigest(),
        "pbkdf2_password": hash_dashboard_password(credentials["astrbot_password"]),
        "password_storage_upgraded": True,
        "password_change_required": False,
    })
dashboard.update({"host": "0.0.0.0", "port": 6185})

if config_path.exists():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = data_dir / "deployment-backups"
    backup_dir.mkdir(exist_ok=True)
    shutil.copy2(config_path, backup_dir / f"cmd_config.{timestamp}.json")
temporary = config_path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(config_path)
marker_path.write_text("initialized\n", encoding="utf-8")
print(json.dumps({"configured": True, "provider_id": provider_id, "model": provider["model"], "owner_configured": bool(owner), "qq_access": "configured_allowlist" if owner or access.get("allowed_groups") or access.get("allowed_private_users") else "blocked_pending_owner"}))
