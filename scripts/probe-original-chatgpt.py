"""Probe the original LiteLLM Chat Completions route without external tool effects."""
import copy
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from deployment_api import DeploymentAPI, write_report


api = DeploymentAPI()
MODEL = "cliproxyapi/gpt-6.1-sol"
REPORT_NAME = "original-chatgpt-low-tools.json" if "--low-tools" in sys.argv else "original-chatgpt-probe.json"
report = {"model": MODEL, "endpoint": "/chat/completions", "qq_messages_sent": 0,
          "images_generated": 0, "tests": {}}
tool = {"type": "function", "function": {
    "name": "deployment_echo", "description": "Echo a word in an isolated protocol test.",
    "parameters": {"type": "object", "properties": {"word": {"type": "string"}},
                   "required": ["word"], "additionalProperties": False}}}


def request(label, payload):
    started = time.monotonic()
    row = {"seconds": None, "ok": False}
    result = None
    try:
        result = api.model("/chat/completions", payload, timeout=100)
        choice = result["choices"][0]
        message = choice["message"]
        row.update(ok=bool(message.get("content") or message.get("tool_calls")),
                   text=str(message.get("content") or "")[:350],
                   tools=[x.get("function", {}).get("name") for x in message.get("tool_calls", [])],
                   finish_reason=choice.get("finish_reason"), usage=result.get("usage"))
    except Exception as exc:
        row["error"] = api.sanitize(str(exc))[:1400]
    row["seconds"] = round(time.monotonic() - started, 3)
    return label, row, result


base = {"model": MODEL, "max_tokens": 512}
jobs = [
    ("original_text", {**base, "messages": [{"role": "user", "content": "Reply with exactly OK."}]}),
    ("original_tool_start", {**base,
        "messages": [{"role": "user", "content": "Call deployment_echo with word OK. After the tool result, reply with exactly OK."}],
        "tools": [tool], "tool_choice": {"type": "function", "function": {"name": "deployment_echo"}}}),
    ("low_passthrough_text", {**base, "reasoning_effort": "low", "allowed_openai_params": ["reasoning_effort"],
        "messages": [{"role": "user", "content": "Reply with exactly OK."}]}),
]
if "--low-tools" in sys.argv:
    # LiteLLM's old capability table rejects this new model's reasoning field
    # unless explicitly allowed. Keep the override local to this provider.
    base.update(reasoning_effort="low", allowed_openai_params=["reasoning_effort"])
    jobs = [("low_tool_start", {**jobs[1][1], **base})]
results = {}
with ThreadPoolExecutor(max_workers=3) as pool:
    for label, row, response in pool.map(lambda job: request(*job), jobs):
        report["tests"][label] = row
        results[label] = response
        write_report(REPORT_NAME, report)
        print(json.dumps({"test": label, **row}, ensure_ascii=False), flush=True)

tool_label = "low_tool_start" if "--low-tools" in sys.argv else "original_tool_start"
first = results.get(tool_label)
if first:
    message = first["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if calls:
        messages = copy.deepcopy(next(payload["messages"] for label, payload in jobs if label == tool_label))
        messages.append({k: message[k] for k in ("role", "content", "tool_calls") if k in message})
        for call in calls:
            assert call["function"]["name"] == "deployment_echo", "Unexpected tool; no action performed"
            args = json.loads(call["function"]["arguments"])
            assert args == {"word": "OK"}, "Unexpected arguments; no action performed"
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"echo": "OK"})})
        label, row, _ = request(tool_label.replace("start", "resume"), {**base, "messages": messages, "tools": [tool], "tool_choice": "none"})
        report["tests"][label] = row
        report["tool_round_trip_passed"] = row["ok"] and row.get("text", "").strip() == "OK"
        print(json.dumps({"test": label, **row}, ensure_ascii=False), flush=True)
write_report(REPORT_NAME, report)
