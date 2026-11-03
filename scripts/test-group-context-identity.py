"""Exact group aliases retain native scope; cross-user/group/platform stay denied."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

path = Path(__file__).resolve().parents[1] / 'extensions/astrbot_plugin_qq_persona_models/group_context_identity.py'
spec = importlib.util.spec_from_file_location('group_context_identity', path)
module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class IdentityTests(unittest.TestCase):
    def fixture(self, group_id='G', user_id='U', platform='aiocqhttp', private=False, umo='qq:GroupMessage:G'):
        event = SimpleNamespace(unified_msg_origin=umo, get_group_id=lambda:'G', get_sender_id=lambda:'U', get_platform_name=lambda:'aiocqhttp')
        identity = SimpleNamespace(group_id=group_id, user_id=user_id, platform=platform, is_private=private)
        return event, identity

    def test_three_native_aliases(self):
        for alias in ('G', 'qq:G', 'qq:GroupMessage:G'):
            with self.subTest(alias=alias):self.assertTrue(module.matches_group_identity(*self.fixture(group_id=alias)))

    def test_foreign_scope_rejected(self):
        for alias in ('Other', 'qq:Other', 'foreign:G', 'foreign:GroupMessage:G', 'user_G', 'prefixG'):
            with self.subTest(alias=alias):self.assertFalse(module.matches_group_identity(*self.fixture(group_id=alias)))

    def test_foreign_sender_private_or_platform_rejected(self):
        for kwargs in ({'user_id':'other'}, {'private':True}, {'platform':'wechat'}):
            with self.subTest(kwargs=kwargs):self.assertFalse(module.matches_group_identity(*self.fixture(**kwargs)))

    def test_mismatched_event_origin_rejected(self):
        for umo in ('qq:GroupMessage:Other', 'qq:FriendMessage:G', ':GroupMessage:G', 'G'):
            with self.subTest(umo=umo):self.assertFalse(module.matches_group_identity(*self.fixture(umo=umo)))


if __name__ == '__main__':unittest.main(verbosity=2)
