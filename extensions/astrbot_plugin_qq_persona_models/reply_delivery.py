"""Skip only the first native segment's artificial wait, per request.

Keep the native sender, headers, error handling and subsequent intervals.
No global sleep patch, background sender or additional model request.
"""
from contextvars import ContextVar
from functools import wraps
import inspect
import time

_DELIVERY = ContextVar('qq_reply_delivery', default=None)


class ReplyDeliveryAdapter:
    def __init__(self, plugin):self.plugin=plugin;self.patches=[]

    def enabled(self,event,stage):
        if not self.plugin.config.get('reply_delivery',{}).get('first_segment_immediate',True):return False
        if not self.plugin.scoped_group(event):return False
        permitted=getattr(event,'plugins_name',None)
        if permitted is not None and 'astrbot_plugin_qq_persona_models' not in permitted:return False
        result=event.get_result()
        if result is None or not result.is_model_result():return False
        if event.get_extra('_streaming_finished'):return False
        return stage.is_seg_reply_required(event)

    def install(self):
        if self.patches:return
        from astrbot.core.pipeline.respond.stage import RespondStage
        original_process=RespondStage.process;original_interval=RespondStage._calc_comp_interval
        if not inspect.iscoroutinefunction(original_process) or not inspect.iscoroutinefunction(original_interval):
            raise RuntimeError('当前 AstrBot 分段发送接口不兼容，未安装首段发送适配器')

        @wraps(original_interval)
        async def interval(stage,component):
            state=_DELIVERY.get()
            if state is not None and state['stage'] is stage:
                state['segments']+=1
                if state['segments']==1:return 0.0
            return await original_interval(stage,component)

        @wraps(original_process)
        async def process(stage,event):
            if not self.enabled(event,stage):return await original_process(stage,event)
            state={'stage':stage,'segments':0,'first_sent':False,'closed':False,'started':time.monotonic()}
            # This is an instance override only while native RespondStage is
            # running; preserve any earlier instance-level plugin override.
            had_override='send' in vars(event);previous_override=vars(event).get('send')
            native_send=event.send
            @wraps(native_send)
            async def send(*args,**kwargs):
                began=time.monotonic();result=await native_send(*args,**kwargs)
                if not state['closed'] and not state['first_sent']:
                    state['first_sent']=True
                    logger=getattr(self.plugin,'model_activity',None)
                    if logger:
                        from .model_logging import event_trace
                        started=event.get_extra('qq_model_trace_started') or state['started']
                        logger.emit('first_segment_sent',**event_trace(event),seconds=round(time.monotonic()-started,4),
                            send_seconds=round(time.monotonic()-began,4),delivery_seconds=round(time.monotonic()-state['started'],4),
                            segment_index=state['segments'],wait_seconds=0.0,outcome='platform_send_returned')
                return result
            event.send=send;token=_DELIVERY.set(state)
            try:return await original_process(stage,event)
            finally:
                state['closed']=True
                _DELIVERY.reset(token)
                if vars(event).get('send') is send:
                    if had_override:event.send=previous_override
                    else:delattr(event,'send')

        RespondStage._calc_comp_interval=interval
        self.patches.append((RespondStage,'_calc_comp_interval',original_interval,interval))
        RespondStage.process=process
        self.patches.append((RespondStage,'process',original_process,process))

    def restore(self):
        for owner,name,original,wrapper in reversed(self.patches):
            if getattr(owner,name,None) is wrapper:setattr(owner,name,original)
        self.patches.clear()

    def status(self):
        return {'installed':bool(self.patches),'first_segment_immediate':self.plugin.config.get('reply_delivery',{}).get('first_segment_immediate',True),
                'subsequent_interval':'native','mode':'native_non_stream'}
