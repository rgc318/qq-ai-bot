"""Local deployment API helpers. Never print credentials or authentication responses."""
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

class DeploymentAPI:
    def __init__(self):
        self.inventory = read_json(ROOT / "config/deployment.local.json")
        credentials = read_json(ROOT / "secrets/credentials.local.json")
        self.api_key = next(line.split("=", 1)[1].strip() for line in (ROOT / "secrets/model-api.env").read_text(encoding="utf-8-sig").splitlines() if line.startswith("QQ_BOT_API_KEY="))
        self.base = "http://127.0.0.1:6185"
        self.model_base = self.inventory["model_api"]["base_url"].rstrip("/")
        self.token = None
        self.redactions = [self.api_key] + [v for v in credentials.values() if isinstance(v, str) and len(v) >= 8]
        login = self.call("/api/auth/login", {"username": credentials["astrbot_username"], "password": credentials["astrbot_password"]})
        self.token = login["data"]["token"]
        self.redactions.append(self.token)

    def sanitize(self, text):
        for secret in self.redactions:
            text = text.replace(secret, "[REDACTED]")
        return text

    def request(self, url, payload=None, method=None, headers=None, timeout=90):
        headers = {"Content-Type": "application/json", **(headers or {})}
        request = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None, headers=headers, method=method or ("POST" if payload is not None else "GET"))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read(1500).decode(errors="replace")
            raise RuntimeError(self.sanitize(f"HTTP {exc.code}: {detail}")) from None

    def call(self, path, payload=None, method=None, timeout=90):
        result = self.request(self.base + path, payload, method, {"Authorization": "Bearer " + self.token} if self.token else {}, timeout)
        if isinstance(result, dict) and result.get("status") == "error":
            raise RuntimeError(self.sanitize(str(result.get("message"))))
        return result

    def model(self, path, payload=None, timeout=120):
        return self.request(self.model_base + path, payload, headers={"Authorization": "Bearer " + self.api_key}, timeout=timeout)

    def backup(self, name, data):
        target = ROOT / "secrets/enhancement-backup"
        target.mkdir(exist_ok=True)
        file = target / name
        if not file.exists():
            file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def write_report(name, data):
    (ROOT / "logs" / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
