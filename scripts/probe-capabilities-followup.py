from deployment_api import DeploymentAPI, ROOT, write_report
import base64
import json
import concurrent.futures
import time

api = DeploymentAPI()
data_url = "data:image/png;base64,"+base64.b64encode((ROOT/"logs/vision-test.png").read_bytes()).decode()
jobs = [
    ("sol_responses_vision","/responses",{"model":"cliproxyapi/gpt-6.1-sol","reasoning":{"effort":"low"},"input":[{"role":"user","content":[{"type":"input_text","text":"Describe the colors and shapes in the image from left to right."},{"type":"input_image","image_url":data_url}]}],"max_output_tokens":512}),
    ("image_generation_no_response_format","/images/generations",{"model":"gpt-image-2.5","prompt":"A simple flat blue whale icon on a plain white background, friendly, no text.","n":1,"size":"1024x1024","quality":"low"}),
]
def run(job):
    name,path,payload=job
    start=time.monotonic()
    try:
        result=api.model(path,payload,timeout=300)
        out={"name":name,"ok":True,"seconds":round(time.monotonic()-start,2)}
        if "output" in result:
            out.update(text=" ".join(c.get("text","") for x in result["output"] for c in x.get("content",[]) if c.get("type")=="output_text"),reasoning=result.get("reasoning"))
        else:
            out["image_count"]=len(result.get("data",[]))
            for item in result.get("data",[]):
                if item.get("b64_json"):
                    blob=base64.b64decode(item["b64_json"])
                    target=ROOT/"logs/image-generation-test.png"
                    target.write_bytes(blob)
                    out.update(image_bytes=len(blob),image_file=str(target))
                elif item.get("url"):
                    out["image_url_returned"]=True
        return out
    except Exception as exc:
        return {"name":name,"ok":False,"error":api.sanitize(str(exc))[:1400]}
results={}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for future in concurrent.futures.as_completed([pool.submit(run,j) for j in jobs]):
        value=future.result()
        results[value["name"]]=value
        write_report("capability-followup.json",results)
        print(json.dumps(value,ensure_ascii=False),flush=True)
