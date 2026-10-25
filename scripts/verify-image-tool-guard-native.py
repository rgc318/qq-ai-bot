"""Native permission-proxy + real local hook regression. Synthetic, no network."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0,'/workspace')
sys.path.insert(0,'/AstrBot')


async def main():
    from astrbot.core.agent.tool import FunctionTool,ToolSet
    from astrbot.core.provider.func_tool_manager import _PermissionGuardedTool
    from astrbot.core.provider.entities import ProviderRequest,LLMResponse
    from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
    from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
    from extensions.astrbot_plugin_qq_persona_models.main import PersonaModelBindings
    from extensions.astrbot_plugin_qq_persona_models.image_tool_compat import ImageExecutionGuard,prepare_chat_image_tools
    checks={};executed=[];permissions=[];responses=[];requests=[]
    class Event:
        def __init__(self):self.extra={'qq_attachment_snapshot':{'scope':'fixture'},'qq_diagnostic':True}
        def get_extra(self,key,default=None):return self.extra.get(key,default)
        def set_extra(self,key,value):self.extra[key]=value
    event=Event()
    probe=object.__new__(PersonaModelBindings)
    probe.scoped_group=lambda e:'fixture'
    probe.router=SimpleNamespace(settings={'image_context_enabled':False})
    async def select(e,args):
        if 'reference_ids' not in args:raise ValueError('合成检查：缺少参考图选择')
        args.pop('reference_ids')
    probe.attachments=SimpleNamespace(enabled=lambda:True,select_references=select)
    probe.image_execution_guard=ImageExecutionGuard()
    async def image_handler(e,prompt):
        executed.append(prompt)
        return 'synthetic generated'
    raw=FunctionTool(name='generate_image',description='synthetic',parameters={
        'type':'object','properties':{'prompt':{'type':'string'}},'required':['prompt']},handler=image_handler)
    async def permission(name,ctx):permissions.append(name);return None
    proxy=_PermissionGuardedTool(raw,SimpleNamespace(_check_tool_permission=permission))
    req=ProviderRequest(prompt='synthetic guard check',func_tool=ToolSet(tools=[proxy]))
    prepare_chat_image_tools(req,indexed_references=True)
    guarded=req.func_tool.tools[0]
    checks['outer_proxy_remains_permission_controlled']=guarded.handler is None
    checks['global_registry_handler_unchanged']=proxy._wrapped is raw and raw.handler is image_handler
    async def start(ctx,tool,args):await probe.normalize_image_arguments(event,tool,args)
    async def end(*args):pass
    hooks=SimpleNamespace(on_tool_start=start,on_tool_end=end,on_agent_done=end,on_agent_begin=end)
    class Provider:
        provider_config={'id':'synthetic-guard','modalities':['text','tool_use']}
        def get_model(self):return 'synthetic-guard'
        async def text_chat(self,**kwargs):
            contexts=deepcopy(kwargs['contexts']);requests.append(contexts)
            if len(requests)==1:
                return LLMResponse(role='assistant',tools_call_name=['generate_image'],tools_call_args=[{'prompt':'must not execute'}],tools_call_ids=['guard-missing'])
            if len(requests)==2:
                text=' '.join(str(r.get('content','')) for r in contexts if r.get('role')=='tool')
                responses.append(text)
                return LLMResponse(role='assistant',tools_call_name=['generate_image'],tools_call_args=[{'prompt':'corrected','reference_ids':[]}],tools_call_ids=['guard-corrected'])
            return LLMResponse(role='assistant',completion_text='synthetic done')
    runner=ToolLoopAgentRunner()
    try:
        await runner.reset(provider=Provider(),request=req,
            run_context=SimpleNamespace(context=SimpleNamespace(event=event),messages=[],tool_call_timeout=5),
            tool_executor=FunctionToolExecutor,agent_hooks=hooks)
        async for _ in runner.step_until_done(5):pass
        checks['actual_hook_returns_guard_feedback']=bool(responses) and '本次未调用图片模型' in responses[0]
        checks['no_internal_kwarg_typeerror']='unexpected keyword' not in ' '.join(responses)
        checks['missing_selection_never_executes_handler']=executed==['corrected']
        checks['permission_checked_on_each_invocation']=permissions==['generate_image','generate_image']
        checks['normal_retry_preserves_native_execution']=len(requests)==3
        async def deny(name,ctx):return 'native permission denied'
        proxy._mgr=SimpleNamespace(_check_tool_permission=deny)
        await proxy.call(SimpleNamespace(context=SimpleNamespace(event=event)),prompt='denied')
        checks['permission_denial_still_prevents_handler']=executed==['corrected']
        checks['outer_handler_not_replaced']=guarded.handler is None
    finally:probe.image_execution_guard.restore()
    print('GUARD_REPORT='+json.dumps({'passed':all(checks.values()),'checks':checks,
        'model_calls':0,'image_generations':0,'qq_messages_sent':0},ensure_ascii=False),flush=True)
    assert all(checks.values()),'Native guard check failed'


if __name__=='__main__':asyncio.run(main())
