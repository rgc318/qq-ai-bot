"""Executor-boundary guard regressions; no models, network, or message sends."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

path=Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models/image_tool_compat.py'
spec=importlib.util.spec_from_file_location('image_tools',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class ImageToolGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_unwrapped_handler_is_guarded_and_restored(self):
        async def handler(event,prompt):return prompt
        tool=SimpleNamespace(handler=handler)
        guard=module.ImageExecutionGuard();guard.install(tool);installed=tool.handler
        guard.install(tool)
        self.assertIs(installed,tool.handler)
        result=await tool.handler(None,prompt='blocked',**{module.IMAGE_GUARD_ERROR:'missing choice'})
        self.assertIn('未调用图片模型',result)
        guard.restore();self.assertIs(tool.handler,handler)

    async def test_blocked_coroutine_never_calls_original(self):
        called=[]
        async def handler(event,prompt):called.append(prompt);return 'unexpected'
        result=await module.guard_image_handler(handler)(None,prompt='fixture',**{module.IMAGE_GUARD_ERROR:'缺少参考图选择'})
        self.assertFalse(called)
        self.assertIn('本次未调用图片模型',result)

    async def test_allowed_coroutine_preserves_result(self):
        async def handler(event,prompt):return prompt
        self.assertEqual(await module.guard_image_handler(handler)(None,prompt='fixture'),'fixture')

    async def test_allowed_async_generator_preserves_chunks(self):
        async def handler(event,prompt):yield prompt;yield 'done'
        result=module.guard_image_handler(handler)(None,prompt='fixture')
        self.assertEqual([x async for x in result],['fixture','done'])

    async def test_blocked_async_generator_never_starts(self):
        called=[]
        async def handler(event,prompt):called.append(True);yield prompt
        result=await module.guard_image_handler(handler)(None,prompt='fixture',**{module.IMAGE_GUARD_ERROR:'不可用参考图'})
        self.assertFalse(called)
        self.assertIn('画图未执行',result)

    async def test_guard_is_per_call_and_does_not_poison_retry(self):
        async def handler(event,prompt):return prompt
        guarded=module.guard_image_handler(handler)
        blocked,allowed=await asyncio.gather(guarded(None,prompt='blocked',**{module.IMAGE_GUARD_ERROR:'缺少参数'}),guarded(None,prompt='allowed'))
        self.assertIn('未执行',blocked)
        self.assertEqual(allowed,'allowed')

    async def test_only_request_copy_is_wrapped(self):
        async def handler(event,prompt):return prompt
        tool=SimpleNamespace(name='generate_image',handler=handler,description='fixture',parameters={'type':'object','properties':{'prompt':{'type':'string'}},'required':['prompt']})
        other=SimpleNamespace(name='web_search',handler=handler)
        request=SimpleNamespace(func_tool=SimpleNamespace(tools=[tool,other]))
        module.prepare_chat_image_tools(request)
        self.assertIs(tool.handler,handler)
        self.assertIs(request.func_tool.tools[1],other)
        self.assertIsNot(request.func_tool.tools[0].handler,handler)
        self.assertEqual(await request.func_tool.tools[0].handler(None,prompt='ok'),'ok')


if __name__=='__main__':unittest.main(verbosity=2)
