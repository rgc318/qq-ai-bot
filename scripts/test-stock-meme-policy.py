"""Regressions for transient stock-meme request filtering; no network."""
from pathlib import Path
import importlib.util
from types import SimpleNamespace
import unittest
path=Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models/meme_intent.py'
spec=importlib.util.spec_from_file_location('stock_policy_under_test',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
apply_existing_meme_policy=module.apply_existing_meme_policy

class StockPolicyTests(unittest.TestCase):
    def test_old_tool_calls_filtered_without_mutating_saved_history_or_global_tools(self):
        history=[{'role':'user','content':'画只小猫'},
            {'role':'assistant','content':None,'tool_calls':[{'id':'old','function':{'name':'generate_image'}}]},
            {'role':'tool','tool_call_id':'old','content':'工具成功'},
            {'role':'assistant','content':'小猫画好了'},
            {'role':'user','content':'好开心'}]
        tools=object()
        req=SimpleNamespace(prompt='发个开心的表情包',system_prompt='',contexts=history,func_tool=tools)
        self.assertTrue(apply_existing_meme_policy(req,req.prompt))
        self.assertIsNone(req.func_tool)
        self.assertEqual([r['content'] for r in req.contexts],['画只小猫','小猫画好了','好开心'])
        self.assertEqual(len(history),5)
        self.assertTrue(history[1]['tool_calls'])
        self.assertIsNotNone(tools)

    def test_actual_creation_keeps_generation_tools_and_history(self):
        for text in ['画一个小猫在打篮球的图片','帮我生成一张新的表情包','帮我做一张表情包']:
            history=[{'role':'assistant','tool_calls':[{'id':'one'}]}]
            tools=object()
            req=SimpleNamespace(prompt=text,system_prompt='',contexts=history,func_tool=tools)
            self.assertFalse(apply_existing_meme_policy(req,text))
            self.assertIs(req.func_tool,tools)
            self.assertIs(req.contexts,history)
            self.assertEqual(req.prompt,text)

    def test_assistant_text_survives_when_old_tool_fields_are_removed(self):
        history=[{'role':'assistant','content':'已经搜到了答案','tool_calls':[{'id':'old'}]}]
        req=SimpleNamespace(prompt='发个开心的表情包',system_prompt='',contexts=history,func_tool=None)
        apply_existing_meme_policy(req,req.prompt)
        self.assertEqual(req.contexts,[{'role':'assistant','content':'已经搜到了答案'}])
        self.assertIn('tool_calls',history[0])

if __name__=='__main__':unittest.main(verbosity=2)
