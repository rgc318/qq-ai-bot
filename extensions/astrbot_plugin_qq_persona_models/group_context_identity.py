"""Validate native User Policy group aliases without changing its scope key."""


def matches_group_identity(event, identity):
    if identity.is_private or str(identity.user_id) != str(event.get_sender_id()):
        return False
    group = str(event.get_group_id())
    umo = str(event.unified_msg_origin)
    instance, separator, target = umo.partition(':GroupMessage:')
    if not separator or not instance or not group or target != group:
        return False
    # PolicyMatcher legitimately selects any one of these exact rule keys.
    # Do not use suffix matching: a foreign instance/group must remain denied.
    if str(identity.group_id) not in (group, instance + ':' + group, umo):
        return False
    platform = str(getattr(identity, 'platform', '') or '')
    if platform and platform not in (str(event.get_platform_name()), instance):
        return False
    return True
