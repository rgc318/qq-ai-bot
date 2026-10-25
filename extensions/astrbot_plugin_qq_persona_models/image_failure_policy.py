"""Request-local image failure classification; zero model calls or sleeps."""
from collections import OrderedDict
import re


class ImageFailurePolicy:
    def __init__(self,max_attempts=2):self.states=OrderedDict();self.max_attempts=max_attempts

    def track(self,event,request):
        from .model_logging import event_trace
        trace=event_trace(event)['trace']
        state=event.get_extra('qq_image_failure_state')
        if state is None:
            state={'attempts':0,'blocked':False,'reason':'','request':request}
            event.set_extra('qq_image_failure_state',state)
        state['request']=request
        self.states[trace]=state;self.states.move_to_end(trace)
        while len(self.states)>128:self.states.popitem(last=False)

    def forget(self,event):
        trace=event.get_extra('qq_model_trace') or {}
        state=self.states.pop(trace.get('trace'),None)
        if state:state['request']=None

    def check(self,event):
        state=event.get_extra('qq_image_failure_state')
        if not state:return
        if state['blocked']:raise ValueError(state['reason']+'；本轮停止自动重试，请明确告知用户')
        if state['attempts']>=self.max_attempts:raise ValueError('本轮图片执行次数已达上限，请说明失败，等待用户下一条明确请求')

    def started(self,event):
        state=event.get_extra('qq_image_failure_state')
        if state:state['attempts']+=1

    def record_failure(self,meta,error):
        state=self.states.get(meta.get('trace'))
        if not state:return
        text=str(error)[:12000].lower()
        reason=''
        if 'moderation_blocked' in text:reason='图片上游返回审核拒绝（moderation_blocked），并非已确认的服务离线'
        elif any(t in text for t in ('invalid_image_file','invalid image data')):reason='图片上游拒绝了参考图数据，需要检查或重新提供素材'
        elif re.search(r'\bhttp\s+(401|403)\b',text) or getattr(error,'status_code',None) in (401,403):reason='图片接口身份或访问权限被拒绝，需要管理员处理'
        if reason:state.update(blocked=True,reason=reason)
        elif state['attempts']>=self.max_attempts:state.update(blocked=True,reason='图片请求持续失败，本轮重试预算已用完')

    def feedback(self,event,result):
        state=event.get_extra('qq_image_failure_state')
        if not state or not state['blocked']:return
        if hasattr(result,'content'):
            from mcp.types import TextContent
            result.content=[TextContent(type='text',text='系统提示：本次没有生成图片。'+state['reason']+'。本轮不再调用图片工具；请向用户说明已确认的原因，不承诺后台自动补发。')]
            result.isError=True
        request=state.get('request');tools=getattr(request,'func_tool',None)
        if tools is not None:tools.tools=[t for t in tools.tools if t.name not in ('generate_image','generate_selfie')]
