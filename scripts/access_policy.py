"""Translate deployment QQ access settings into AstrBot's native allowlist."""

import re


def qq_id(value):
    normalized = str(value).strip()
    if not re.fullmatch(r"[1-9][0-9]*", normalized):
        raise ValueError("QQ and group IDs must be positive decimal strings")
    return normalized


def derive_access_settings(access, platform_id="qq-snowluma"):
    owner_raw = str(access.get("owner_qq", "")).strip()
    owner = qq_id(owner_raw) if owner_raw else ""
    private_users = {qq_id(value) for value in access.get("allowed_private_users", [])}
    if owner:
        private_users.add(owner)
    groups = {qq_id(value) for value in access.get("allowed_groups", [])}
    # Private users must be full session IDs. Bare numbers are matched as GROUP IDs
    # by AstrBot's WhitelistCheckStage and must not be used for private users.
    allowlist = [f"{platform_id}:FriendMessage:{user}" for user in sorted(private_users)]
    allowlist.extend(sorted(groups))
    return {
        "admins_id": [owner] if owner else [],
        "platform_settings": {
            "enable_id_white_list": True,
            "id_whitelist": allowlist or ["__deployment_pending_owner__"],
            "wl_ignore_admin_on_friend": True,
            "wl_ignore_admin_on_group": False,
            "no_permission_reply": False,
        },
    }
