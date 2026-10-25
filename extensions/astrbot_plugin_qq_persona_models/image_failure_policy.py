"""Request-local image failure classification; zero model calls or sleeps."""
from collections import OrderedDict
import re


class ImageFailurePolicy:
    def __init__(self,max_attempts=2):
        self.states=OrderedDict();self.max_attempts=max_attempts;self.max_images=4;self.max_image_attempts=5

    def track(self,event,request):
        from .model_logging import event_trace
        trace=event_trace(event)['trace']
        state=event.get_extra('qq_image_failure_state')
        if state is None:
            state={'attempts':0,'blocked':False,'reason':'','request':request,'attempted_images':0,'delivered_images':0,'failed_items':set()}
            event.set_extra('qq_image_failure_state',state)
        state['request']=request
        self.states[trace]=state;self.states.move_to_end(trace)
        while len(self.states)>128:self.states.popitem(last=False)

    def forget(self,event):
        trace=event.get_extra('qq_model_trace') or {}
        state=self.states.pop(trace.get('trace'),None)
        if state:state['request']=None

    def check(self,event,count=1):
        state=event.get_extra('qq_image_failure_state')
        if not state:return
        if state['blocked']:raise ValueError(state['reason']+'；本轮停止自动重试，请明确告知用户')
        if state['delivered_images']+count>self.max_images:raise ValueError('本轮最多成功交付4张图，仅剩'+str(max(0,self.max_images-state['delivered_images']))+'张；不要重复生成已发送图片。')
        if state['attempted_images']+count>self.max_image_attempts:raise ValueError('本轮图片生成尝试预算已用完或不足，不能整批重画已完成图片。')

    def started(self,event,count=1):
        state=event.get_extra('qq_image_failure_state')
        if state:
            state['attempts']+=1;state['attempted_images']+=count;state['pending_count']=count;state['dispatch_started']=False
            state['send_before']=int(event.get_extra('qq_generated_attachment_sends') or 0)

    def validation_rejected(self,event,code):
        state=event.get_extra('qq_image_failure_state')
        if not state or state['blocked']:return
        state['validation_failures']=state.get('validation_failures',0)+1
        if state['validation_failures']>=2:
            state.update(blocked=True,reason='图片任务/素材校验连续两次未通过（'+code+'），本轮没有启动这次生成；请澄清任务或提供可用来源')

    def record_failure(self,meta,error):
        state=self.states.get(meta.get('trace'))
        if not state:return
        text=str(error)[:12000].lower()
        reason=''
        if 'moderation_blocked' in text:reason='图片上游返回审核拒绝（moderation_blocked），并非已确认的服务离线'
        elif any(t in text for t in ('invalid_image_file','invalid image data')):reason='图片上游拒绝了参考图数据，需要检查或重新提供素材'
        elif re.search(r'\bhttp\s+(401|403)\b',text) or getattr(error,'status_code',None) in (401,403):reason='图片接口身份或访问权限被拒绝，需要管理员处理'
        state['failed_items'].add((meta.get('batch_id') or str(state['attempts']),meta.get('batch_index',0)))
        if reason:state.update(blocked=True,reason=reason)
        elif len(state['failed_items'])>=self.max_attempts:state.update(blocked=True,reason='图片请求持续失败，本轮失败重试预算已用完')

    def feedback(self,event,result):
        state=event.get_extra('qq_image_failure_state')
        if not state:return
        if state.get('feedback_attempt')!=state['attempts']:
            sent=max(0,int(event.get_extra('qq_generated_attachment_sends') or 0)-state.get('send_before',0))
            state['delivered_images']+=sent;state['last_delivered']=sent;state['feedback_attempt']=state['attempts']
            if event.get_extra('qq_image_batch_enabled') and not state.get('dispatch_started'):
                state['attempted_images']-=state.get('pending_count',0)
        if state['blocked'] and hasattr(result,'content'):
            from mcp.types import TextContent
            if state.get('last_delivered'):
                result.content.append(TextContent(type='text',text='系统提示：本批次部分图片已发送，成功图片保留；失败项原因：'+state['reason']+'。不再自动重试失败项，不要把整批说成没有生成。'))
            else:result.content=[TextContent(type='text',text='系统提示：本次失败调用没有生成图片。'+state['reason']+'。本轮不再调用图片工具；此前成功图片保留，请说明已确认的原因，不承诺后台自动补发。')]
            result.isError=True
        request=state.get('request');tools=getattr(request,'func_tool',None)
        if tools is not None and (state['blocked'] or state['delivered_images']>=self.max_images or state['attempted_images']>=self.max_image_attempts):
            tools.tools=[t for t in tools.tools if t.name not in ('generate_image','generate_selfie')]
