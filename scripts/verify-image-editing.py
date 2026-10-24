"""One low-quality synthetic edit through the deployed plugin; sends no QQ messages."""
import base64
import json
import time
from deployment_api import DeploymentAPI, ROOT, write_report

api = DeploymentAPI()
reference = ROOT / "logs/vision-test.png"
if not reference.is_file():
    raise RuntimeError("Missing existing synthetic vision-test.png; no user images will be used.")
start = time.monotonic()
report = {"plugin": "astrbot_plugin_omnidraw", "model": "gpt-image-2.5", "synthetic_reference": True, "messages_sent_to_qq": 0}
try:
    response = api.call("/api/plug/astrbot_plugin_omnidraw/generate_image_for_plugin", {
        "prompt": "Edit the provided reference image. Change only the red square into a green square. Keep the blue circle in the same position and keep the plain white background. No text.",
        "count": 1, "size": "1024x1024", "extra_params": "--quality low",
        "refs": ["data:image/png;base64," + base64.b64encode(reference.read_bytes()).decode()],
    }, timeout=260)
    images = response.get("images", [])
    report.update(success=bool(response.get("success") and images), image_count=len(images))
    if not report["success"]:
        report["message"] = api.sanitize(str(response.get("message", "")))[:800]
        report["errors"] = api.sanitize(json.dumps(response.get("errors", []), ensure_ascii=False))[:800]
    # Never print returned data URLs, image URLs, or upstream payloads.
    if images:
        report["image_item_type"] = type(images[0]).__name__
        item = images[0]
        if isinstance(item, dict):
            report["image_field_names"] = list(item)
            data_url = next((v for v in item.values() if isinstance(v, str) and v.startswith("data:image/")), "")
        else:
            data_url = item if isinstance(item, str) and item.startswith("data:image/") else ""
        if data_url:
            target = ROOT / "logs/image-editing-test.png"
            target.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
            report["output_file"] = str(target)
except Exception as exc:
    report.update(success=False, error=api.sanitize(str(exc))[:1000])
report["seconds"] = round(time.monotonic() - start, 2)
write_report("image-editing-verification.json", report)
print(json.dumps(report, ensure_ascii=False))
