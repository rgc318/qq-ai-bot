"""Verify the user's exact model routes, using small synthetic inputs; no QQ sends."""
import base64
import concurrent.futures
import json
import struct
import time
import zlib
from deployment_api import DeploymentAPI, ROOT, write_report

api = DeploymentAPI()
deepseek = "siliconflow/deepseek-ai/DeepSeek-V4.1-Flash-1017"
sol = "cliproxyapi/gpt-6.1-sol"

def test_png():
    rows = []
    for y in range(96):
        row = bytearray()
        for x in range(128):
            rgb = (255, 255, 255)
            if 10 <= x < 50 and 25 <= y < 65:
                rgb = (255, 0, 0)
            if (x-94)**2+(y-45)**2 <= 20**2:
                rgb = (0, 0, 255)
            row.extend(rgb)
        rows.append(b"\0" + bytes(row))
    def chunk(name, data):
        return struct.pack("!I", len(data))+name+data+struct.pack("!I", zlib.crc32(name+data)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack("!2I5B",128,96,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(b"".join(rows)))+chunk(b"IEND",b"")

image_bytes = test_png()
(ROOT / "logs/vision-test.png").write_bytes(image_bytes)
data_url = "data:image/png;base64,"+base64.b64encode(image_bytes).decode()
tool = {"name":"deployment_echo","description":"Return the provided word for an isolated configuration test.","parameters":{"type":"object","properties":{"word":{"type":"string"}},"required":["word"],"additionalProperties":False}}

def probe(name, path, payload, timeout=150):
    start = time.monotonic()
    try:
        result = api.model(path, payload, timeout=timeout)
        summary = {"name":name,"ok":True,"endpoint":path,"model":payload.get("model"),"seconds":round(time.monotonic()-start,2)}
        if "choices" in result:
            msg = result["choices"][0]["message"]
            summary.update(text=str(msg.get("content", ""))[:700],tool_calls=[x.get("function",{}).get("name") for x in msg.get("tool_calls",[])],finish_reason=result["choices"][0].get("finish_reason"))
        elif "output" in result:
            summary.update(text=" ".join(c.get("text","") for item in result["output"] for c in item.get("content",[]) if c.get("type")=="output_text")[:700],tool_calls=[x.get("name") for x in result["output"] if x.get("type")=="function_call"],response_status=result.get("status"),reasoning=result.get("reasoning"))
        elif "data" in result:
            summary["image_count"] = len(result["data"])
            for index, item in enumerate(result["data"]):
                if item.get("b64_json"):
                    blob = base64.b64decode(item["b64_json"])
                    target = ROOT / f"logs/image-generation-test-{index}.png"
                    target.write_bytes(blob)
                    summary["image_bytes"] = len(blob)
                    summary["image_file"] = str(target)
                elif item.get("url"):
                    summary["image_url_returned"] = True
        else:
            summary["response_keys"] = list(result)
        return summary
    except Exception as exc:
        return {"name":name,"ok":False,"seconds":round(time.monotonic()-start,2),"error":api.sanitize(str(exc))[:1200]}

jobs = []
for label, model in (("deepseek",deepseek),("sol",sol)):
    base = {"model":model,"messages":[{"role":"user","content":"Reply with exactly OK."}],"max_tokens":512}
    if label == "sol":
        base["reasoning_effort"] = "low"
    jobs.append((label+"_chat","/chat/completions",base))
    vision = {**base,"messages":[{"role":"user","content":[{"type":"text","text":"Describe the colors and shapes in this image, from left to right. Be brief."},{"type":"image_url","image_url":{"url":data_url}}]}]}
    jobs.append((label+"_vision","/chat/completions",vision))
    if label == "deepseek":
        tools = {**base,"messages":[{"role":"user","content":"Call deployment_echo with word OK."}],"tools":[{"type":"function","function":tool}],"tool_choice":{"type":"function","function":{"name":"deployment_echo"}}}
        jobs.append((label+"_tools","/chat/completions",tools))

response_base = {"model":sol,"input":"Reply with exactly OK.","reasoning":{"effort":"low"},"max_output_tokens":512}
jobs.append(("sol_responses","/responses",response_base))
jobs.append(("sol_responses_tools","/responses",{**response_base,"input":"Call deployment_echo with word OK.","tools":[{"type":"function",**tool}],"tool_choice":{"type":"function","name":"deployment_echo"}}))
jobs.append(("image_generation","/images/generations",{"model":"gpt-image-2.5","prompt":"A simple flat blue whale icon on a plain white background, friendly, no text.","n":1,"size":"1024x1024","quality":"low","response_format":"b64_json"}))
results = {}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    futures = {pool.submit(probe, *job, 300 if job[0]=="image_generation" else 150):job[0] for job in jobs}
    for future in concurrent.futures.as_completed(futures):
        value = future.result()
        results[value["name"]] = value
        write_report("capability-probes.json",results)
        print(json.dumps(value,ensure_ascii=False),flush=True)
