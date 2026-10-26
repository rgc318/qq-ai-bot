"""Defer image-only non-stream text to the existing post-validation notice hook."""
from functools import wraps
from copy import copy,deepcopy

IMAGE_TOOLS={'generate_image','generate_selfie'}


def stop_blocked_image_response(event,response):
    """Finish a known blocked image retry before native lookup says not found."""
    if not event or not event.get_extra('qq_image_task_contract_enabled') or getattr(response,'is_chunk',False):return False
    state=event.get_extra('qq_image_failure_state') or {}
    names=getattr(response,'tools_call_name',None) or []
    if not state.get('blocked') or not names or not set(names).issubset(IMAGE_TOOLS):return False
    sent=int(state.get('delivered_images',0))
    prefix='本轮已发送'+str(sent)+'张图片，成功图片保留。' if sent else '这次没有启动新的图片生成。'
    response.result_chain=None
    response.completion_text=prefix+str(state.get('reason') or '本轮图片执行已停止')+'。这不是图片服务离线的检测结果；本轮已停止图片工具，不会在后台自动补画。'
    response.tools_call_name=[];response.tools_call_args=[];response.tools_call_ids=[]
    event.set_extra('qq_image_blocked_response_stopped',True)
    return True


def defer_notice(event,response):
    if not event or not event.get_extra('qq_image_task_contract_enabled') or not event.get_extra('qq_image_notice_defer_enabled') or getattr(response,'is_chunk',False):return False
    names=getattr(response,'tools_call_name',None) or []
    if not names or not set(names).issubset(IMAGE_TOOLS):return False
    # OpenAI-compatible providers use a MessageChain even for plain text.
    # Defer all-Plain chains, while preserving any independent rich media.
    chain=getattr(response,'result_chain',None)
    if chain and any(type(part).__name__!='Plain' for part in getattr(chain,'chain',[])):return False
    text=' '.join((getattr(response,'completion_text','') or '').split())
    args=getattr(response,'tools_call_args',None) or []
    if not all(isinstance(a,dict) for a in args) or len(args)!=len(names):return False
    source='existing_parameter'
    if text and len(text)<=160:
        for a in args:
            existing=a.get('pending_message')
            if not isinstance(existing,str) or not 0<len(existing.strip())<=160:
                a['pending_message']=text;source='same_response_text'
    response.result_chain=None
    response.completion_text=''
    event.set_extra('qq_deferred_notice_source',source)
    return bool(text)


class ImageResponseAdapter:
    def __init__(self):self.patch=None;self.args_patch=None
    def install(self):
        if self.patch:return
        from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
        owner=ToolLoopAgentRunner;original=owner._iter_llm_responses_with_fallback
        @wraps(original)
        async def wrapped(runner,*args,**kwargs):
            iterator=original(runner,*args,**kwargs)
            try:
                async for response in iterator:
                    if not getattr(runner,'streaming',True):
                        event=getattr(getattr(getattr(runner,'run_context',None),'context',None),'event',None)
                        if not stop_blocked_image_response(event,response):defer_notice(event,response)
                    yield response
            finally:await iterator.aclose()
        owner._iter_llm_responses_with_fallback=wrapped
        self.patch=(owner,original,wrapped)
        execute_original=owner._handle_function_tools
        @wraps(execute_original)
        async def execute(runner,request,response):
            event=getattr(getattr(getattr(runner,'run_context',None),'context',None),'event',None)
            if event and event.get_extra('qq_image_task_contract_enabled') and any(n in IMAGE_TOOLS for n in response.tools_call_name or []):
                for name,args in zip(response.tools_call_name,response.tools_call_args):
                    if name in IMAGE_TOOLS and isinstance(args,dict):args.pop('_qq_image_guard_error',None)
                # Native permission proxies alias valid_params to response args.
                # Hooks consume helpers and add private execution errors. Keep
                # those mutations off the response later serialized as history.
                execution=copy(response)
                execution.tools_call_args=[deepcopy(a) if n in IMAGE_TOOLS else a for n,a in zip(response.tools_call_name,response.tools_call_args)]
            else:execution=response
            iterator=execute_original(runner,request,execution)
            try:
                async for result in iterator:yield result
            finally:await iterator.aclose()
        owner._handle_function_tools=execute;self.args_patch=(owner,execute_original,execute)
    def restore(self):
        if self.args_patch:
            owner,original,wrapped=self.args_patch
            if owner._handle_function_tools is wrapped:owner._handle_function_tools=original
            self.args_patch=None
        if self.patch:
            owner,original,wrapped=self.patch
            if owner._iter_llm_responses_with_fallback is wrapped:owner._iter_llm_responses_with_fallback=original
            self.patch=None
