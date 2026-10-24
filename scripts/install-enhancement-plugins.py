from deployment_api import DeploymentAPI, write_report
import json

api = DeploymentAPI()
installed = {x["name"] for x in api.call("/api/v1/plugins")["data"]}
results = []
for name, repo in (
    ("astrbot_plugin_user_policy", "https://github.com/yanyuhanyue/astrbot_plugin_user_policy"),
    ("astrbot_plugin_omnidraw", "https://github.com/diaomin66/astrbot_plugin_omnidraw"),
):
    if name in installed:
        results.append({"name":name,"already_installed":True})
    else:
        archive = "https://codeload.github.com/" + repo.removeprefix("https://github.com/") + "/zip/refs/heads/main"
        result = api.call("/api/v1/plugins/install/url", {"repository":repo, "download_url":archive}, timeout=300)
        results.append({"name":name,"status":result.get("status"),"message":result.get("message")})
    write_report("enhancement-plugin-install.json",results)
    print(api.sanitize(json.dumps(results[-1],ensure_ascii=False)),flush=True)
