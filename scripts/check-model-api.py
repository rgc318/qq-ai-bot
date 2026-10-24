"""Check this deployment's model API without printing the API key."""

import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://192.168.31.229:4000/v1")
    parser.add_argument("--model", default="siliconflow/deepseek-ai/DeepSeek-V4.1-Flash")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    api_key = os.environ.get("QQ_BOT_API_KEY", "")
    if args.env_file:
        for line in args.env_file.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("QQ_BOT_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
    if not api_key:
        raise SystemExit("QQ_BOT_API_KEY is not configured")

    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": "Reply with exactly OK."}],
        "max_tokens": 512,
        "stream": False,
    }
    req = urllib.request.Request(
        args.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            result = json.load(response)
        message = result["choices"][0]["message"].get("content")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("The model returned no assistant text")
        print(json.dumps({
            "ok": True,
            "model": args.model,
            "reply": message[:100],
            "elapsed_seconds": round(time.monotonic() - start, 2),
            "usage": result.get("usage"),
        }, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        # Do not print server error bodies or request headers; they may contain credentials.
        print(json.dumps({"ok": False, "http_status": exc.code, "model": args.model}))
        raise SystemExit(1)
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "model": args.model}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
