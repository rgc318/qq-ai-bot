"""Bounded batch planning and narrow adapters for the existing OmniDraw pipeline."""
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import importlib
import time

MAX_IMAGES=4
_BATCH=ContextVar('qq_image_batch',default=None)


class BatchDispatchStopped(RuntimeError):pass


def validate_batch(args):
    count=args.get('count',1)
    if type(count) is not int or not 1<=count<=MAX_IMAGES:raise ValueError('count必须是1到4的整数，表示独立图片张数，不是拼图格数。')
    prompts=args.get('image_prompts',[])
    if not isinstance(prompts,list) or prompts and len(prompts)!=count:raise ValueError('image_prompts非空时必须逐张填写，长度与count一致；同主题随机变体可填[]。')
    if any(not isinstance(p,str) or not p.strip() or len(p)>3000 for p in prompts):raise ValueError('每张图片描述必须为非空文字，最多3000字符。')
    return {'count':count,'prompts':tuple(p.strip() for p in prompts)}


@dataclass
class BatchRun:
    event:object
    count:int
    prompts:tuple
    batch_id:str
    ordinal:int=0


class ImageBatchAdapter:
    def __init__(self,plugin,concurrency=2):
        self.plugin=plugin;self.semaphore=asyncio.Semaphore(concurrency);self.concurrency=concurrency
        self.patches=[];self.closed=False;self.ready=False

    def patch(self,owner,name,build):
        original=getattr(owner,name)
        current=original
        while current is not None:
            if getattr(current,'_qq_batch_owner',None) is self:return
            current=getattr(current,'__wrapped__',None)
        wrapper=build(original);wrapper._qq_batch_owner=self
        setattr(owner,name,wrapper);self.patches.append((owner,name,original,wrapper))

    def install(self,context):
        metadata=context.get_registered_star('astrbot_plugin_omnidraw')
        omni=getattr(metadata,'star_cls',None)
        if omni is None:return
        root=omni.__class__.__module__.rsplit('.',1)[0]
        chain=importlib.import_module(root+'.core.chain_manager').ChainManager
        service=self
        def generation(original):
            @wraps(original)
            async def wrapped(instance,event,prompt,count,*args,**kwargs):
                if service.closed or not event or not event.get_extra('qq_image_batch_enabled'):
                    return await original(instance,event,prompt,count,*args,**kwargs)
                plan=event.get_extra('qq_image_batch_plan') or {'count':count,'prompts':()}
                if count!=plan['count']:raise ValueError('实际生成张数与已校验任务不一致，停止执行')
                serial=int(event.get_extra('qq_image_batch_serial') or 0)+1;event.set_extra('qq_image_batch_serial',serial)
                run=BatchRun(event,count,plan['prompts'],'batch-'+str(serial))
                event.set_extra('qq_image_batch_report',None)
                state=event.get_extra('qq_image_failure_state')
                if state is not None:state['dispatch_started']=True
                token=_BATCH.set(run)
                try:
                    result=await original(instance,event,prompt,count,*args,**kwargs)
                    values=list(result.get('results') or [])
                    report={'batch_id':run.batch_id,'requested':count,'items':[{'index':i+1,'status':'not_started' if isinstance(value,BatchDispatchStopped) else 'generated_not_sent' if instance._get_image_result_url(value) else 'failed'} for i,value in enumerate(values)]}
                    report['_descriptions']=list(run.prompts) if run.prompts else list(result.get('prompts') or [])
                    event.set_extra('qq_image_batch_report',report)
                    return result
                finally:_BATCH.reset(token)
            return wrapped
        def optimizer(original):
            @wraps(original)
            async def wrapped(instance,raw_action,count=1,*args,**kwargs):
                run=_BATCH.get()
                if service.closed or not run or not run.prompts:return await original(instance,raw_action,count,*args,**kwargs)
                if count!=run.count:raise ValueError('逐张提示词数量与批次不一致')
                return [raw_action+'\n[本张独立画面，仅画这一张，不拼成多格]\n'+p for p in run.prompts]
            return wrapped
        def limited(original):
            @wraps(original)
            async def wrapped(instance,*args,**kwargs):
                run=_BATCH.get()
                if service.closed or run is None:return await original(instance,*args,**kwargs)
                run.ordinal+=1;index=run.ordinal
                if index>run.count:raise ValueError('图片节点调用数超过已校验批次')
                from .model_logging import model_operation,event_trace
                started=time.perf_counter()
                async with service.semaphore:
                    state=run.event.get_extra('qq_image_failure_state')
                    if state and state['blocked']:raise BatchDispatchStopped('前序图片已返回不可重试错误或失败预算耗尽，后续排队图片未执行')
                    meta={**event_trace(run.event),'batch_id':run.batch_id,'batch_index':index}
                    service.plugin.model_activity.emit('image_batch_item_started',**meta,seconds=round(time.perf_counter()-started,3),requested_images=run.count)
                    with model_operation('image_generation',meta):return await original(instance,*args,**kwargs)
            return wrapped
        def delivery(original):
            @wraps(original)
            async def wrapped(instance,event,results,*args,**kwargs):
                report=event.get_extra('qq_image_batch_report') if event else None
                if service.closed or not report:return await original(instance,event,results,*args,**kwargs)
                pending=[item for item in report['items'] if item['status']=='generated_not_sent']
                original_send=event.send;position=0
                async def sent(chain,*a,**kw):
                    nonlocal position
                    item=pending[position] if position<len(pending) else None
                    descriptions=report.get('_descriptions') or []
                    marker={'batch_id':report['batch_id'],'batch_index':item['index'],'batch_count':report['requested'],'image_prompt_excerpt':str(descriptions[item['index']-1])[:160] if item['index']<=len(descriptions) else ''} if item else None
                    event.set_extra('qq_image_batch_delivery',marker)
                    try:receipt=await original_send(chain,*a,**kw)
                    finally:
                        if event.get_extra('qq_image_batch_delivery') is marker:event.set_extra('qq_image_batch_delivery',None)
                    if position<len(pending):pending[position]['status']='sent';position+=1
                    return receipt
                event.send=sent
                try:return await original(instance,event,results,*args,**kwargs)
                finally:
                    if event.send is sent:event.send=original_send
            return wrapped
        for name in ('_run_text2img_generation','_run_selfie_generation'):self.patch(type(omni),name,generation)
        self.patch(type(omni.prompt_optimizer),'optimize',optimizer)
        self.patch(chain,'run_chain_with_metadata',limited)
        self.patch(type(omni),'_send_generated_images',delivery)
        self.ready=True

    def close(self):
        self.closed=True;self.ready=False
        for owner,name,original,wrapper in reversed(self.patches):
            if getattr(owner,name) is wrapper:setattr(owner,name,original)
        self.patches=[]
