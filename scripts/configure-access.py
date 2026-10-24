"""Update only QQ access settings in the stopped AstrBot instance."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from access_policy import derive_access_settings


deployment = json.loads(Path("/deployment-config/deployment.local.json").read_text(encoding="utf-8-sig"))
access = deployment["access"]
if not str(access.get("owner_qq", "")).strip():
    raise SystemExit("Set an administrator QQ ID before enabling QQ access")
policy = derive_access_settings(access)
config_path = Path("/AstrBot/data/cmd_config.json")
config = json.loads(config_path.read_text(encoding="utf-8-sig"))
old_settings = {"admins_id": config.get("admins_id", []), "platform_settings": {
    key: config.get("platform_settings", {}).get(key)
    for key in policy["platform_settings"]
}}
if old_settings != policy:
    backup_dir = config_path.parent / "deployment-backups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    shutil.copy2(config_path, backup_dir / f"cmd_config.before-access.{timestamp}.json")
    config["admins_id"] = policy["admins_id"]
    config.setdefault("platform_settings", {}).update(policy["platform_settings"])
    temporary = config_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(config_path)
print(json.dumps({"configured": True, "admins_id": policy["admins_id"], "whitelist": policy["platform_settings"]["id_whitelist"]}))
