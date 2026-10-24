"""Exercise the installed AstrBot whitelist stage without sending any messages."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from astrbot.core.pipeline.whitelist_check.stage import WhitelistCheckStage
from astrbot.core.platform.message_type import MessageType


class LocalEvent:
    def __init__(self, message_type, session_id, group_id="", role="member"):
        self.unified_msg_origin = f"qq-snowluma:{message_type.value}:{session_id}"
        self.message_type = message_type
        self.group_id = group_id
        self.role = role
        self.stopped = False

    def get_platform_name(self):
        return "aiocqhttp"

    def get_message_type(self):
        return self.message_type

    def get_group_id(self):
        return self.group_id

    def stop_event(self):
        self.stopped = True


async def main():
    config = json.loads(Path("/AstrBot/data/cmd_config.json").read_text(encoding="utf-8-sig"))
    assert config["admins_id"] == ["2354912009"]
    assert set(config["platform_settings"]["id_whitelist"]) == {
        "qq-snowluma:FriendMessage:2354912009", "347440128"
    }
    stage = WhitelistCheckStage()
    await stage.initialize(SimpleNamespace(astrbot_config=config))
    stage.wl_log = False
    cases = [
        ("owner_private", LocalEvent(MessageType.FRIEND_MESSAGE, "2354912009", role="admin"), True),
        ("explicit_private_session", LocalEvent(MessageType.FRIEND_MESSAGE, "2354912009"), True),
        ("allowed_group_member", LocalEvent(MessageType.GROUP_MESSAGE, "347440128_10001", "347440128"), True),
        ("other_private_user", LocalEvent(MessageType.FRIEND_MESSAGE, "10001"), False),
        ("private_user_matching_group_number", LocalEvent(MessageType.FRIEND_MESSAGE, "347440128"), False),
        ("group_matching_owner_number", LocalEvent(MessageType.GROUP_MESSAGE, "2354912009_10001", "2354912009"), False),
        ("owner_in_other_group", LocalEvent(MessageType.GROUP_MESSAGE, "10002_2354912009", "10002", role="admin"), False),
    ]
    for name, event, expected_allowed in cases:
        await stage.process(event)
        assert (not event.stopped) == expected_allowed, name
    print(json.dumps({"ok": True, "checked_cases": len(cases), "admins_id": config["admins_id"], "whitelist": config["platform_settings"]["id_whitelist"]}))


if __name__ == "__main__":
    asyncio.run(main())
