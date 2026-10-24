"""Reference recovery and fail-closed editing; no QQ, network or model calls."""
import asyncio
import hashlib
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from PIL import Image

source=Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models/image_quote_compat.py'
spec=importlib.util.spec_from_file_location('quote_compat',source)
compat=importlib.util.module_from_spec(spec);spec.loader.exec_module(compat)

class QuoteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'temp_images').mkdir()
        self.image=self.root/'temp_images'/'generated.png'
        Image.new('RGB',(8,8),'blue').save(self.image)
        self.calls=[];self.key_calls=[];self.backend=[]
        test=self
        class Stage:
            async def _normalize_image_component(self,event,component):
                test.calls.append(component.url)
                if Path(component.url).is_file() or parse_qs(urlsplit(component.url).query).get('rkey')==['fresh']:
                    component.url=component.path=component.file=str(test.image);return
                raise ValueError('HTTP status code: 400')
        class Reply:
            def __init__(self,image,sender='2354912009'):self.chain=[image];self.sender_id=sender
        class Omni:
            data_dir=str(test.root)
            async def _process_and_save_images(self,refs,**kwargs):return [r for r in refs if r!='missing']
            async def _run_text2img_generation(self,event,prompt,count,refs):
                safe=await self._process_and_save_images(refs)
                test.backend.append(safe);return safe
            _run_selfie_generation=_run_text2img_generation
        self.Stage=Stage;self.Reply=Reply;self.Omni=Omni;self.omni=Omni()
        self.original=Stage._normalize_image_component
        self.original_process=Omni._process_and_save_images
        self.modules=patch.dict(sys.modules,{
            'astrbot.core.pipeline.preprocess_stage.stage':SimpleNamespace(PreProcessStage=Stage),
            'astrbot.api.message_components':SimpleNamespace(Reply=Reply),
        });self.modules.start()
        self.adapter=compat.ImageQuoteAdapter(lambda e:e.get_group_id()=='347440128')
        self.adapter.install(SimpleNamespace(get_registered_star=lambda name:SimpleNamespace(star_cls=self.omni)))
    async def asyncTearDown(self):
        self.adapter.restore()
        self.assertIs(self.Stage._normalize_image_component,self.original)
        self.assertIs(self.Omni._process_and_save_images,self.original_process)
        self.modules.stop();self.tmp.cleanup()
    def event(self,component,sender='2354912009',group='347440128',keys=True):
        extras={}
        async def action(name,**kwargs):
            self.key_calls.append(name)
            if not keys:raise RuntimeError('Unavailable')
            return [{'type':20,'rkey':'&rkey=fresh'}]
        return SimpleNamespace(plugins_name=None,bot=SimpleNamespace(call_action=action),get_group_id=lambda:group,get_self_id=lambda:'2354912009',get_messages=lambda:[self.Reply(component,sender)],get_extra=lambda k,default=None:extras.get(k,default),set_extra=lambda k,v:extras.update({k:v}))
    def component(self,token='unknown.png'):
        return SimpleNamespace(url='https://multimedia.nt.qq.com.cn/download?appid=1407&fileid=abc&rkey=old',file=token,path=None)
    async def test_own_generated_quote_uses_exact_hash_without_network(self):
        component=self.component(hashlib.md5(self.image.read_bytes()).hexdigest()+'.png')
        event=self.event(component)
        await self.Stage()._normalize_image_component(event,component)
        self.assertEqual(component.file,str(self.image))
        self.assertFalse(self.key_calls)
        self.assertEqual(self.calls,[str(self.image)])
        self.assertEqual(event.get_extra('qq_quote_image_recovered'),'local_generated_hash_match')
    async def test_failed_qq_url_refreshes_key_before_vision(self):
        component=self.component();event=self.event(component)
        await self.Stage()._normalize_image_component(event,component)
        self.assertEqual(self.key_calls,['get_rkey'])
        self.assertEqual(parse_qs(urlsplit(self.calls[-1]).query)['fileid'],['abc'])
        self.assertEqual(component.file,str(self.image))
        self.assertEqual(event.get_extra('qq_quote_image_recovered'),'refreshed_qq_rkey')
    async def test_unrecoverable_quote_does_not_use_different_cached_image(self):
        component=self.component('0'*32+'.png');event=self.event(component,keys=False)
        old=vars(component).copy()
        with self.assertRaises(ValueError):await self.Stage()._normalize_image_component(event,component)
        self.assertEqual(vars(component),old)
        self.assertTrue(event.get_extra('qq_quote_image_unavailable'))
    async def test_other_sender_does_not_claim_own_image_cache(self):
        component=self.component(hashlib.md5(self.image.read_bytes()).hexdigest()+'.png')
        event=self.event(component,sender='another-member')
        await self.Stage()._normalize_image_component(event,component)
        self.assertEqual(self.key_calls,['get_rkey'])
    async def test_missing_reference_never_calls_generation_backend(self):
        with self.assertRaisesRegex(ValueError,'停止'):
            await self.omni._run_text2img_generation(self.event(self.component()),'edit',1,refs=['missing'])
        self.assertFalse(self.backend)
    async def test_partial_reference_failure_stops_selfie_too(self):
        with self.assertRaises(ValueError):
            await self.omni._run_selfie_generation(self.event(self.component()),'edit',1,refs=['valid','missing'])
        self.assertFalse(self.backend)
    async def test_normal_creation_and_complete_edit_continue(self):
        event=self.event(self.component())
        self.assertEqual(await self.omni._run_text2img_generation(event,'new',1,refs=[]),[])
        self.assertEqual(await self.omni._run_text2img_generation(event,'edit',1,refs=['valid']),['valid'])
        self.assertEqual(len(self.backend),2)
    async def test_unallowed_group_keeps_original_behavior(self):
        event=self.event(self.component(),group='other')
        self.assertEqual(await self.omni._run_text2img_generation(event,'edit',1,refs=['missing']),[])
    async def test_rkey_replacement_is_host_restricted_and_deduplicated(self):
        for url in ['https://example.com/a','http://multimedia.nt.qq.com.cn/a','https://user:pass@multimedia.nt.qq.com.cn/a','https://multimedia.nt.qq.com.cn:123/a']:
            self.assertIsNone(compat.replace_qq_rkey(url,'fresh'))
        url=compat.replace_qq_rkey(self.component().url+'&rkey=other','&rkey=fresh')
        self.assertEqual(parse_qs(urlsplit(url).query)['rkey'],['fresh'])
    async def test_cache_mismatch_and_model_path_never_selected(self):
        self.assertIsNone(compat.matching_generated_image(self.root/'temp_images','../generated.png',{}))
        self.assertIsNone(compat.matching_generated_image(self.root/'temp_images','0'*32+'.png',{}))
    async def test_unavailable_reference_hides_generation_and_keeps_other_tools(self):
        class Tools:
            tools=[SimpleNamespace(name=n) for n in ('generate_image','generate_selfie','recall_long_term_memory')]
        source=Tools();req=SimpleNamespace(func_tool=source,system_prompt='人格原文')
        event=self.event(self.component());event.set_extra('qq_quote_image_unavailable',True)
        compat.apply_quote_image_policy(event,req)
        self.assertEqual([t.name for t in req.func_tool.tools],['recall_long_term_memory'])
        self.assertEqual(len(source.tools),3)
        self.assertIn('不要用此前对话中的图片',req.system_prompt)

if __name__=='__main__':unittest.main(verbosity=2)
