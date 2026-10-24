"""Verify vision and the live Dragon image-tool preparation without generating images."""
import base64
import json
import struct
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed

from deployment_api import DeploymentAPI, write_report


api = DeploymentAPI()


def vision():
    def chunk(kind, content):
        return struct.pack("!I", len(content)) + kind + content + struct.pack("!I", zlib.crc32(kind + content) & 0xffffffff)
    pixels = b"".join(b"\0" + bytes((255, 0, 0)) * 64 for _ in range(64))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", 64, 64, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    started = time.monotonic()
    response = api.model("/chat/completions", {
        "model": "cliproxyapi/gpt-6.1-sol", "reasoning_effort": "low", "allowed_openai_params": ["reasoning_effort"], "max_tokens": 128,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "What color fills this image? Reply with one English color word."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]})
    text = response["choices"][0]["message"].get("content") or ""
    return {"passed": "red" in text.lower(), "text": text[:200], "seconds": round(time.monotonic() - started, 3)}


def native_image_tools():
    return api.call("/api/plug/qq_persona_models/verify_memory_meme", {
        "image_notice_model_only": True, "early_close": True,
        "message": "这是一个全新的画图请求，不使用以前的图：请画一只戴厨师帽、正在做蛋炒饭的小龙娘。请实际调用画图工具。"}, timeout=180)["data"]


report = {"qq_messages_sent": 0, "images_generated": 0}
with ThreadPoolExecutor(max_workers=2) as pool:
    jobs = {pool.submit(fn): name for name, fn in (("vision", vision), ("native_image_tools", native_image_tools))}
    for future in as_completed(jobs):
        name = jobs[future]
        try:
            row = future.result()
        except Exception as exc:
            row = {"passed": False, "error": api.sanitize(str(exc))[:1500]}
        report[name] = row
        write_report("original-chatgpt-native-verification.json", report)
        summary = {key: row[key] for key in ("passed", "text", "seconds", "model", "image_tool_calls", "captured_notices", "native_tool_executions", "cross_task_close_clean", "error") if key in row}
        print(json.dumps({"test": name, **summary}, ensure_ascii=False), flush=True)
assert all(report[key]["passed"] for key in ("vision", "native_image_tools")), "See verification report"
