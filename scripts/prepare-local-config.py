"""Prepare local deployment credentials. Existing credentials are preserved."""

import json
from pathlib import Path
import secrets


root = Path(__file__).resolve().parent.parent
secret_dir = root / "secrets"
secret_dir.mkdir(exist_ok=True)
credential_path = secret_dir / "credentials.local.json"
if credential_path.exists():
    credentials = json.loads(credential_path.read_text(encoding="utf-8"))
else:
    credentials = {
        "astrbot_username": "astrbot",
        "astrbot_password": "Ab!" + secrets.token_urlsafe(24),
        "snowluma_password": "Sl!" + secrets.token_urlsafe(24),
        "novnc_password": secrets.token_hex(4),
        "onebot_token": secrets.token_urlsafe(32),
    }
    with credential_path.open("x", encoding="utf-8") as stream:
        json.dump(credentials, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

snow_env_path = secret_dir / "snowluma.env"
if not snow_env_path.exists():
    snow_env_path.write_text(
        "SNOWLUMA_WEBUI_BOOTSTRAP_PASSWORD=" + credentials["snowluma_password"] + "\n"
        "VNC_PASSWD=" + credentials["novnc_password"] + "\n",
        encoding="utf-8",
    )

onebot_path = secret_dir / "onebot.json"
if not onebot_path.exists():
    onebot = {
        "networks": {
            "httpServers": [],
            "httpClients": [],
            "wsServers": [],
            "wsClients": [{
                "name": "astrbot",
                "enabled": True,
                "url": "ws://astrbot:6199/ws",
                "role": "Universal",
                "accessToken": credentials["onebot_token"],
                "messageFormat": "array",
                "reportSelfMessage": False,
                "reconnectIntervalMs": 3000,
            }],
        },
        "statusCommand": {"enabled": False, "swallow": False, "cooldownSeconds": 5, "trigger": "#sl"},
        "historySync": {"enabled": False},
        "notifications": {"channelIds": []},
    }
    onebot_path.write_text(json.dumps(onebot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

inventory_path = root / "config" / "deployment.local.json"
inventory = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
inventory["deployment"].update({"platform": "wsl2-ubuntu", "topology": "docker_compose"})
inventory["snowluma"].update({"reference_version": "v2.1.1", "directory": "docker-volume:qq-ai-bot_snowluma-data"})
inventory["astrbot"].update({"working_directory": "docker-volume:qq-ai-bot_astrbot-data"})
inventory["onebot"].update({"astrbot_bind_host": "0.0.0.0", "snowluma_connect_url": "ws://astrbot:6199/ws", "token_configured": True})
inventory["model_api"].update({"provider_type": "OpenAI Compatible", "base_url": "http://192.168.31.229:4000/v1"})
if not inventory["model_api"].get("model_id"):
    inventory["model_api"]["model_id"] = "siliconflow/deepseek-ai/DeepSeek-V4.1-Flash"
inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Local credentials, OneBot configuration and deployment inventory prepared; no secrets printed.")
