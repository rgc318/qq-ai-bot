"""Evidence boundaries, footer privacy and validation without AstrBot/network."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('evidence',root/'extensions/astrbot_plugin_qq_persona_models/task_evidence.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Event:
    def __init__(self):
        self.extra={'qq_attachment_snapshot':{'scope':'G|P','epoch':1,'catalog':[{'id':'one','type':'image','state':'ready'},{'id':'two','type':'image','state':'ready'}]},'qq_initial_image_ids':['one']}
        self.message_obj=NS(message_id='m1')
    def get_extra(self,k):return self.extra.get(k)
    def set_extra(self,k,v):self.extra[k]=v


class Tests(unittest.TestCase):
    def fixture(self):
        event=Event();req=NS(system_prompt='persona',func_tool=NS(names=lambda:['view_context_images']),image_urls=[])
        self.assertTrue(m.attach_evidence(event,req,{}))
        return event,req
    def declared(self,**kw):return {'status':'answered','image_ids':[],'document_ids':[],'actions':[],**kw}
    def test_directory_is_not_visual_evidence(self):
        e,r=self.fixture();self.assertIn('catalog_only_image_ids',r.system_prompt)
        self.assertEqual(m.validate_state(e,self.declared(image_ids=['two'])),'image_pixels_not_provided')
    def test_initial_pixels_and_later_tool_pixels(self):
        e,_=self.fixture();self.assertEqual(m.validate_state(e,self.declared(image_ids=['one'])),'')
        e.extra[m.KEY]['viewed'].add('two');self.assertEqual(m.validate_state(e,self.declared(image_ids=['one','two'])),'')
    def test_legacy_partial_read_counter_is_not_evidence(self):
        e,_=self.fixture();e.extra['qq_context_images_viewed']=['two']
        self.assertEqual(m.validate_state(e,self.declared(image_ids=['two'])),'image_pixels_not_provided')
    def test_cross_scope_unknown_id_denied(self):
        e,_=self.fixture();self.assertEqual(m.validate_state(e,self.declared(image_ids=['othergroup'])),'image_pixels_not_provided')
    def test_document_excerpt_must_exist(self):
        e,_=self.fixture();self.assertEqual(m.validate_state(e,self.declared(document_ids=['file'])),'document_not_read')
        e.extra[m.KEY]['documents'].add('file');self.assertEqual(m.validate_state(e,self.declared(document_ids=['file'])),'')
    def test_tool_return_is_not_image_delivery(self):
        e,_=self.fixture();m.observe_result(e,'generate_image',NS(isError=False))
        self.assertEqual(m.validate_state(e,self.declared(status='completed',actions=['generate_image'])),'image_delivery_not_confirmed')
        e.extra['qq_generated_attachment_sends']=1
        self.assertEqual(m.validate_state(e,self.declared(status='completed',actions=['generate_image'])),'')
    def test_partial_batch_is_not_whole_batch_completed(self):
        e,_=self.fixture();m.observe_result(e,'generate_image',NS(isError=False));e.extra['qq_generated_attachment_sends']=1
        e.extra['qq_image_batch_report']={'items':[{'status':'sent'},{'status':'failed'}]}
        self.assertEqual(m.validate_state(e,self.declared(status='completed',actions=['generate_image'])),'image_delivery_not_confirmed')
    def test_blocked_failure_can_be_reported_without_retry(self):
        e,_=self.fixture();m.observe_result(e,'generate_image',NS(isError=True))
        self.assertEqual(m.validate_state(e,self.declared(status='blocked',actions=['generate_image'])),'')
    def test_no_unregistered_background_work(self):
        e,_=self.fixture();self.assertEqual(m.validate_state(e,self.declared(status='working')),'background_task_not_registered')
    def test_normal_reply_has_no_required_declaration(self):
        e,_=self.fixture();self.assertEqual(m.split_state('晚上好'),('晚上好',None,''));self.assertEqual(m.validate_state(e,None),'')
    def test_footer_stripped_and_rich_media_preserved(self):
        class Plain:
            def __init__(self,text):self.text=text
        image=NS(type='image');text='看到了'+m.OPEN+json.dumps(self.declared(image_ids=['one']))+m.CLOSE
        r=NS(completion_text=text,result_chain=NS(chain=[Plain(text),image]))
        declared,code=m.clean_response(r)
        self.assertEqual(r.completion_text,'看到了');self.assertEqual(r.result_chain.chain[0].text,'看到了')
        self.assertIs(r.result_chain.chain[1],image);self.assertEqual(declared['image_ids'],['one']);self.assertEqual(code,'')
    def test_truncated_or_duplicate_footer_never_leaks(self):
        for text in ['正文'+m.OPEN+'{bad', '正文'+m.OPEN+'{}'+m.CLOSE+m.OPEN+'{}'+m.CLOSE]:
            clean,_,code=m.split_state(text);self.assertEqual(clean,'正文');self.assertEqual(code,'invalid_task_state')
    def test_disabled_and_streaming_are_untouched(self):
        e=Event();r=NS(system_prompt='persona',func_tool=NS(names=lambda:['view_context_images']),streaming=True)
        self.assertFalse(m.attach_evidence(e,r,{}));self.assertEqual(r.system_prompt,'persona')
        r.streaming=False;self.assertFalse(m.attach_evidence(e,r,{'enabled':False}));self.assertIsNone(e.get_extra(m.KEY))
    def test_attach_is_idempotent_and_request_local(self):
        e,r=self.fixture();first=r.system_prompt;m.attach_evidence(e,r,{})
        self.assertEqual(first,r.system_prompt);fresh=Event();self.assertIsNone(fresh.get_extra(m.KEY))
    def test_pixel_alias_keeps_distinct_source_ids(self):
        e=Event();e.extra['qq_image_pixel_aliases']={'two':'one'}
        self.assertEqual(m.provided_images(e,NS(image_urls=[])),{'one','two'})


if __name__=='__main__':unittest.main(verbosity=2)
