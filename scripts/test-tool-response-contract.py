"""Pure prompt-contract regressions: no models, network, or message sends."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

path=Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models/tool_response_contract.py'
spec=importlib.util.spec_from_file_location('tool_contract',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
NATIVE='When using tools: never return an empty response; keep the conversation style consistent.'


class ToolResponseContractTests(unittest.TestCase):
    def request(self,names=('generate_image',),system='persona'):
        return SimpleNamespace(system_prompt=system,func_tool=SimpleNamespace(tools=[SimpleNamespace(name=name) for name in names]),contexts=[{'role':'user','content':'画图后还需要回答一个问题'}])

    def test_restores_deleted_native_rules_after_persona(self):
        req=self.request();result=module.restore_tool_response_contract(req,NATIVE)
        self.assertTrue(result['native_restored'])
        self.assertIn('# QQ Tool Response Rules\n'+NATIVE,req.system_prompt)

    def test_keeps_existing_native_rule_once(self):
        req=self.request(system='persona\n'+NATIVE)
        self.assertFalse(module.restore_tool_response_contract(req,NATIVE)['native_restored'])
        self.assertEqual(req.system_prompt.count(NATIVE),1)

    def test_repeat_attachment_is_idempotent(self):
        req=self.request();module.restore_tool_response_contract(req,NATIVE);first=req.system_prompt
        module.restore_tool_response_contract(req,NATIVE)
        self.assertEqual(req.system_prompt,first)

    def test_tool_less_meme_reply_does_not_gain_tool_rules(self):
        req=self.request(names=());module.restore_tool_response_contract(req,NATIVE)
        self.assertEqual(req.system_prompt,'persona')

    def test_non_image_tools_only_receive_native_rule(self):
        req=self.request(names=('web_search_anysearch',));result=module.restore_tool_response_contract(req,NATIVE)
        self.assertTrue(result['native_restored']);self.assertFalse(result['image_rule_added'])

    def test_request_history_and_tool_availability_are_preserved(self):
        req=self.request();history=req.contexts;tools=req.func_tool
        module.restore_tool_response_contract(req,NATIVE)
        self.assertIs(req.contexts,history);self.assertIs(req.func_tool,tools)
        self.assertFalse(hasattr(req,'tool_choice'))

    def test_completion_is_conditional_and_preserves_remaining_tasks(self):
        req=self.request();module.restore_tool_response_contract(req,NATIVE)
        for rule in ['数量大于0','失败','发送未确认','剩余要求','不要套固定话术','不要重复调用','输出格式']:
            self.assertIn(rule,req.system_prompt)


if __name__=='__main__':unittest.main(verbosity=2)
