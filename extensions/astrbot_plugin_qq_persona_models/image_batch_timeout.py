"""Scoped image deadlines; retain native executor permissions and SIR cleanup."""
import ast
import asyncio
from functools import wraps
import importlib
import inspect
import textwrap


async def wait_for_image_activity(awaitable,*,timeout,event,image_timeout=660):
    signal=event.get_extra('qq_image_batch_signal') if event else None
    if not signal or not event.get_extra('qq_image_batch_enabled'):
        return await asyncio.wait_for(awaitable,timeout=timeout)
    watcher=asyncio.create_task(signal.wait())
    try:
        done,_=await asyncio.wait({awaitable,watcher},timeout=timeout,return_when=asyncio.FIRST_COMPLETED)
        if awaitable in done:return await awaitable
        if watcher not in done:
            awaitable.cancel();raise asyncio.TimeoutError
        # Only a validated image call sets this event. No polling or fixed wait.
        done,_=await asyncio.wait({awaitable},timeout=max(timeout,image_timeout))
        if awaitable not in done:
            awaitable.cancel();raise asyncio.TimeoutError
        return await awaitable
    except BaseException:
        if not awaitable.done():awaitable.cancel()
        raise
    finally:
        watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)


def adapt_generation_wait(original,helper=wait_for_image_activity):
    tree=ast.parse(textwrap.dedent(inspect.getsource(original)));changed=0
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute) or not isinstance(node.func.value,ast.Name) or node.func.value.id!='asyncio' or node.func.attr!='wait_for':continue
        if not any(k.arg=='timeout' and ast.unparse(k.value).endswith('.generation_timeout_sec') for k in node.keywords):continue
        node.func=ast.Name(id='_qq_batch_wait',ctx=ast.Load())
        node.keywords.append(ast.keyword(arg='event',value=ast.Attribute(value=ast.Name(id='run',ctx=ast.Load()),attr='last_event',ctx=ast.Load())))
        changed+=1
    if changed!=1:raise ValueError('业镜生成等待接口不匹配，拒绝静默改变超时逻辑')
    namespace={**original.__globals__,'_qq_batch_wait':helper}
    exec(compile(ast.fix_missing_locations(tree),original.__code__.co_filename,'exec'),namespace)
    return wraps(original)(namespace[original.__name__])


class ImageTimeoutAdapter:
    def __init__(self):self.patches=[];self.ready=False
    def install(self,context):
        from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
        descriptor=inspect.getattr_static(FunctionToolExecutor,'_execute_local')
        if getattr(descriptor.__func__,'_qq_image_timeout_owner',None) is not self:
            original_executor=descriptor.__func__
            @wraps(original_executor)
            async def execute(cls,tool,run_context,*,tool_call_timeout=None,**kwargs):
                event=getattr(getattr(run_context,'context',None),'event',None)
                if tool.name in ('generate_image','generate_selfie') and event and event.get_extra('qq_image_batch_enabled'):
                    tool_call_timeout=max(tool_call_timeout or run_context.tool_call_timeout,600)
                iterator=original_executor(cls,tool,run_context,tool_call_timeout=tool_call_timeout,**kwargs)
                try:
                    async for result in iterator:yield result
                finally:await iterator.aclose()
            execute._qq_image_timeout_owner=self;wrapper=classmethod(execute)
            setattr(FunctionToolExecutor,'_execute_local',wrapper)
            self.patches.append((FunctionToolExecutor,'_execute_local',descriptor,wrapper,True))
        metadata=context.get_registered_star('astrbot_plugin_self_initiated_reply')
        plugin=getattr(metadata,'star_cls',None)
        if plugin:
            root=plugin.__class__.__module__.rsplit('.',1)[0];module=importlib.import_module(root+'.generation')
            owner=next(v for v in vars(module).values() if isinstance(v,type) and v.__module__==module.__name__ and hasattr(v,'_run_agent_with_grace'))
            original_wait=owner._run_agent_with_grace
            if getattr(original_wait,'_qq_image_timeout_owner',None) is not self:
                wrapper=adapt_generation_wait(original_wait);wrapper._qq_image_timeout_owner=self
                setattr(owner,'_run_agent_with_grace',wrapper);self.patches.append((owner,'_run_agent_with_grace',original_wait,wrapper,False))
        self.ready=True
    def close(self):
        for owner,name,original,wrapper,descriptor in reversed(self.patches):
            current=inspect.getattr_static(owner,name) if descriptor else getattr(owner,name)
            if current is wrapper:setattr(owner,name,original)
        self.patches=[];self.ready=False
