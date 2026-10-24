"""Summarize recent deployment errors without returning ordinary chat logs."""
import collections
import json
import re
import subprocess
from deployment_api import DeploymentAPI, write_report

api = DeploymentAPI()
report = {}
for container in ["qq-ai-bot-astrbot-1", "qq-ai-bot-snowluma-1"]:
    proc = subprocess.run(["wsl", "-d", "Ubuntu", "--exec", "docker", "logs", "--since", "90m", container], capture_output=True, encoding="utf-8", errors="replace")
    lines = (proc.stdout + proc.stderr).splitlines()
    summaries = []
    counts = collections.Counter()
    for line in lines:
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        if not re.search(r"\b(?:ERROR|CRITICAL)\b|(?:Error|Exception):", line):
            continue
        line = api.sanitize(line)
        line = re.sub(r"data:image/[^\s\"']+", "[IMAGE_DATA]", line)
        line = re.sub(r"https?://[^\s\"'<>]+", "[URL]", line)
        line = re.sub(r"sk-[A-Za-z0-9_-]+", "[API_KEY]", line)
        line = re.sub(r"(?i)(?:bearer\s+)[A-Za-z0-9._-]+", "Bearer [REDACTED]", line)
        category = next((name for name in ["invalid_json", "tool", "image", "provider", "timeout", "permission", "websocket"] if name in line.lower()), "other")
        counts[category] += 1
        summaries.append(line[:600])
    report[container] = {"error_line_categories": dict(counts), "last_error_lines": summaries[-16:]}
write_report("runtime-error-audit.json", report)
print(json.dumps(report, ensure_ascii=False))
