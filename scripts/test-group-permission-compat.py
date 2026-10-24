"""Saved group-admin rights, scope boundaries and reversible installation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

path=Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models/group_permission_compat.py'
spec=importlib.util.spec_from_file_location('group_compat',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class PermissionTests(unittest.TestCase):
    def setUp(self):
        class Policy:
            store=SimpleNamespace(config={'groups':{'qq-snowluma:347440128':{'policy_admins':['1511659008'],'persona_id':'大肥鱼'}}})
            def _group_rule_for_event(self,event):
                for key in event.aliases:
                    rule=self.store.config['groups'].get(key,{})
                    if isinstance(rule,dict):return rule
                return {}
            def _group_policy_id_for_event(self,event):
                return next((k for k in event.aliases if k in self.store.config['groups']),event.get_group_id())
            def _can_use_query_command(self,event,decision):return event.is_admin() or decision.allow_persona_switch
            def _event_user_id(self,event):return event.get_sender_id()
        self.Policy=Policy;self.policy=Policy()
        self.original_rule=Policy._group_rule_for_event;self.original_query=Policy._can_use_query_command
        self.context=SimpleNamespace(get_registered_star=lambda name:SimpleNamespace(star_cls=self.policy))
        self.adapter=module.GroupPermissionAdapter(lambda:['347440128'])
        self.adapter.install(self.context)
    def tearDown(self):
        self.adapter.restore()
        self.assertIs(self.Policy._group_rule_for_event,self.original_rule)
        self.assertIs(self.Policy._can_use_query_command,self.original_query)
    def event(self,user='1511659008',group='347440128',instance='qq-snowluma',private=False,global_admin=False):
        return SimpleNamespace(aliases=[f'{instance}:GroupMessage:{group}',f'{instance}:{group}',group],get_group_id=lambda:group,get_sender_id=lambda:user,is_private_chat=lambda:private,is_admin=lambda:global_admin)
    def decision(self,allow=False,blocked=False):return SimpleNamespace(allow_persona_switch=allow,is_blocked=blocked)
    def test_missing_first_alias_no_longer_hides_saved_rule(self):
        ev=self.event()
        self.assertEqual(self.original_rule(self.policy,ev),{})
        self.assertEqual(self.policy._group_rule_for_event(ev)['persona_id'],'大肥鱼')
    def test_group_admin_can_query_without_personal_switch_permission(self):
        self.assertFalse(self.original_query(self.policy,self.event(),self.decision()))
        self.assertTrue(self.policy._can_use_query_command(self.event(),self.decision()))
    def test_unlisted_member_not_promoted(self):
        self.assertFalse(self.policy._can_use_query_command(self.event(user='other'),self.decision()))
    def test_other_group_and_instance_do_not_inherit_admin(self):
        for ev in (self.event(group='other'),self.event(instance='other-bot')):
            self.assertFalse(self.policy._can_use_query_command(ev,self.decision()))
    def test_blocked_group_admin_not_newly_authorized(self):
        self.assertFalse(self.policy._can_use_query_command(self.event(),self.decision(blocked=True)))
    def test_private_conversation_keeps_native_permissions(self):
        self.assertFalse(self.policy._can_use_query_command(self.event(private=True),self.decision()))
        self.assertTrue(self.policy._can_use_query_command(self.event(private=True),self.decision(allow=True)))
    def test_native_global_admin_permission_unchanged(self):
        self.assertTrue(self.policy._can_use_query_command(self.event(global_admin=True),self.decision()))
    def test_reinstall_does_not_nest_wrappers(self):
        before=self.Policy._can_use_query_command
        self.assertTrue(self.adapter.install(self.context))
        self.assertIs(self.Policy._can_use_query_command,before)

if __name__=='__main__':unittest.main(verbosity=2)
