import json
from deployment_api import DeploymentAPI,write_report
api=DeploymentAPI()
api.call("/api/v1/plugins/reload",{"plugin_id":"astrbot_plugin_qq_persona_models"})
binding=api.call("/api/plug/qq_persona_models/verify")
assert all(row["passed"] for row in binding["data"])
for event_name,rows in binding["handler_order"].items():
    names=[row["handler"] for row in rows]
    mine=next(i for i,handler in enumerate(names) if handler.endswith("main_bind_incoming" if event_name=="AdapterMessageEvent" else "main_bind_before_normal_request"))
    theirs=next(i for i,handler in enumerate(names) if handler.endswith("main_apply_message_policy" if event_name=="AdapterMessageEvent" else "main_resolve_auto_persona"))
    assert mine>theirs,(event_name,rows)
    if event_name=="AdapterMessageEvent":
        semantic=next(i for i,handler in enumerate(names) if handler.endswith("main_route_contextual_request"))
        proactive=next(i for i,handler in enumerate(names) if "self_initiated_reply" in handler and handler.endswith("_on_message"))
        assert semantic<proactive
bootstrap=api.call("/api/plug/astrbot_plugin_user_policy/bootstrap")["data"]
group=next(row for row in bootstrap["groups"] if row["group_id"]=="qq-snowluma:347440128")
assert group["persona_id"]=="大肥鱼" and group["memory_isolation"]
personas=api.call("/api/persona/list")["data"]
persona_summary=[{"persona_id":row["persona_id"],"tools":row.get("tools"),"prompt_length":len(row["system_prompt"])} for row in personas if row["persona_id"] in ("大肥鱼","ChatGPT龙娘")]
assert len(persona_summary)==2
result={"binding":binding,"group_policy":{"group":group["group_id"],"persona":group["persona_id"],"memory_isolation":group["memory_isolation"]},"personas":persona_summary,"messages_sent_to_qq":0}
write_report("persona-integration-verification.json",result)
print(json.dumps(result,ensure_ascii=False))
