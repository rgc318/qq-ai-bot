"""Verify history/media limits preserve source data and complete tool rounds."""
from pathlib import Path
import importlib.util
import unittest
from copy import deepcopy
path=Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models/performance_context.py'
spec=importlib.util.spec_from_file_location('performance_context_under_test',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ContextTests(unittest.TestCase):
    def test_round_limit_preserves_tool_call_pairs(self):
        history=[]
        for n in range(20):
            history.extend([{'role':'user','content':str(n)},{'role':'assistant','tool_calls':[{'id':str(n)}]},{'role':'tool','tool_call_id':str(n),'content':'ok'},{'role':'assistant','content':'done'}])
        result,stats=module.plan_history(history,'今天晚上吃什么',{'history_turns':12})
        self.assertEqual(sum(r['role']=='user' for r in result),12)
        self.assertEqual(result[0]['content'],'8')
        self.assertEqual(len(result),48)
        self.assertEqual(len(history),80)
        self.assertEqual(stats['dropped_messages'],32)

    def test_plain_chat_omits_old_images_without_mutating_source(self):
        history=[{'role':'user','content':[{'type':'text','text':'看这个'},{'type':'image_url','image_url':{'url':'data:image/png;base64,IMAGE'}}]}]
        before=deepcopy(history)
        result,stats=module.plan_history(history,'今晚吃什么',{})
        self.assertEqual(stats['removed_history_images'],1)
        self.assertEqual(history,before)
        self.assertEqual(result[0]['content'][0],history[0]['content'][0])

    def test_referenced_images_only_keep_recent_image_turns(self):
        history=[]
        for n in range(4):history.extend([{'role':'user','content':[{'type':'image_url','image_url':{'url':str(n)}}]},{'role':'assistant','content':'ok'}])
        _,stats=module.plan_history(history,'把刚才那张改成蓝色',{'history_image_turns':2})
        self.assertEqual(stats['kept_history_images'],2)
        self.assertEqual(stats['removed_history_images'],2)

    def test_short_text_history_unchanged(self):
        history=[{'role':'user','content':'你好'},{'role':'assistant','content':'你好呀'}]
        result,stats=module.plan_history(history,'你好吗',{})
        self.assertEqual(result,history)
        self.assertFalse(stats['changed'])

if __name__=='__main__':unittest.main(verbosity=2)
