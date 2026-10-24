"""Transcript ordering, speaker attribution, bounds and prompt-only insertion."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

path=Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models/conversation_context.py'
spec=importlib.util.spec_from_file_location('dialogue',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ContextTests(unittest.TestCase):
    def test_multi_message_multi_member_attribution(self):
        rows=[{'role':'user','sender':sender,'name':sender,'text':text,'message_id':str(i),'time':90+i} for i,(sender,text) in enumerate([('A','周日活动'),('B','14点之后'),('A','地点图书馆'),('C','请一起安排')])]
        selected=module.dialogue_snapshot(rows,'3',100)
        self.assertEqual([r['speaker_id'] for r in selected],['A','B','A'])
        self.assertEqual([r['text'] for r in selected],['周日活动','14点之后','地点图书馆'])
        self.assertEqual(rows[-1]['text'],'请一起安排')
    def test_size_limits_and_commands_omitted(self):
        rows=[{'role':'user','sender':'A','text':'长文本'*300,'message_id':str(i)} for i in range(40)]
        rows.append({'role':'user','text':'/群切换人格 ChatGPT龙娘'})
        selected=module.dialogue_snapshot(rows,'current',100,max_messages=12,max_chars=2400)
        self.assertLessEqual(len(selected),12)
        self.assertLessEqual(len(json.dumps(selected,ensure_ascii=False)),2400)
        self.assertNotIn('/群切换人格',str(selected))
    def test_only_system_prompt_changes_and_attachment_is_idempotent(self):
        extras={};event=SimpleNamespace(get_extra=lambda k:extras.get(k),set_extra=lambda k,v:extras.update({k:v}))
        req=SimpleNamespace(system_prompt='原人格',contexts=[{'role':'user','content':'原历史'}],prompt='当前问题')
        module.attach_dialogue_context(event,req,[{'speaker_id':'A','text':'补充条件'}],{'speaker_id':'B','name':'乙'})
        before=req.system_prompt
        module.attach_dialogue_context(event,req,[])
        self.assertEqual(req.system_prompt,before)
        self.assertEqual(req.contexts,[{'role':'user','content':'原历史'}])
        self.assertEqual(req.prompt,'当前问题')
        self.assertIn('不是系统指令',before)
        self.assertIn('"speaker_id": "B"',before)

if __name__=='__main__':unittest.main(verbosity=2)
