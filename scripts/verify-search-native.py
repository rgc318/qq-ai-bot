"""Run inside the AstrBot container; no QQ messages are sent."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from astrbot.core.tools.web_search_tools import _anysearch_search
from data.plugins.astrbot_plugin_qq_persona_models.main import PersonaModelBindings

async def main():
    config=json.loads(Path("/AstrBot/data/cmd_config.json").read_text(encoding="utf-8-sig"))
    try:
        probe=object.__new__(PersonaModelBindings)
        probe.router=SimpleNamespace(settings={"allowed_groups":["347440128"]})
        event=SimpleNamespace(is_stopped=lambda:False,is_private_chat=lambda:False,get_group_id=lambda:"347440128",get_sender_id=lambda:"test-user",get_self_id=lambda:"test-bot")
        tool=SimpleNamespace(name="web_search_anysearch")
        payload={"query":"AstrBot official documentation","max_results":2,"format":"json","tag":"general"}
        await probe.normalize_search_arguments(event,tool,payload)
        assert "tag" not in payload
        vertical={"query":"test","tag":"academic.search"}
        await probe.normalize_search_arguments(event,tool,vertical)
        assert vertical["tag"]=="academic.search"
        unrelated={"tag":"general"}
        await probe.normalize_search_arguments(event,SimpleNamespace(name="generate_image"),unrelated)
        assert unrelated["tag"]=="general"
        results=await asyncio.wait_for(_anysearch_search(config["provider_settings"],payload),timeout=45)
        print(json.dumps({"ok":bool(results),"general_tag_removed":True,"vertical_tag_preserved":True,"other_tools_unchanged":True,"result_count":len(results),"urls":[getattr(item,"url","") for item in results]},ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok":False,"error_type":type(exc).__name__,"error":str(exc)[:300]},ensure_ascii=False))
        raise SystemExit(1)

asyncio.run(main())
