"""Pure batch/budget regressions; no network/model/image/send operations."""
from types import SimpleNamespace
import asyncio
from .image_batch import validate_batch
from .image_failure_policy import ImageFailurePolicy


async def verify_image_batches():
    checks={}
    checks['four_same_theme_images_valid']=validate_batch({'count':4})=={'count':4,'prompts':()}
    checks['different_prompts_preserve_order']=validate_batch({'count':3,'image_prompts':['早餐','午餐','晚餐']})['prompts']==('早餐','午餐','晚餐')
    for label,args in [('zero',{'count':0}),('too_many',{'count':5}),('bool',{'count':True}),('float',{'count':2.1}),('string',{'count':'4'}),('mismatch',{'count':3,'image_prompts':['one']}),('empty_item',{'count':2,'image_prompts':['one','']})]:
        try:validate_batch(args);bad=False
        except ValueError:bad=True
        checks[label+'_rejected']=bad
    def event():
        extras={'qq_model_trace':{'trace':'batch-fixture'},'qq_image_batch_enabled':True}
        e=SimpleNamespace(get_extra=lambda k,default=None:extras.get(k,default),set_extra=lambda k,v:extras.__setitem__(k,v),get_group_id=lambda:'fixture')
        return e
    from mcp.types import CallToolResult,TextContent
    result=lambda text:CallToolResult(content=[TextContent(type='text',text=text)])
    policy=ImageFailurePolicy();e=event();req=SimpleNamespace(func_tool=SimpleNamespace(tools=[SimpleNamespace(name='generate_image')]))
    policy.track(e,req)
    for i in range(4):
        policy.check(e);policy.started(e);e.get_extra('qq_image_failure_state')['dispatch_started']=True
        e.set_extra('qq_generated_attachment_sends',i+1);policy.feedback(e,result('成功'))
    checks['four_successful_calls_do_not_consume_failure_budget']=e.get_extra('qq_image_failure_state')['delivered_images']==4 and not e.get_extra('qq_image_failure_state')['blocked']
    checks['tools_removed_after_four_deliveries']=not req.func_tool.tools
    try:policy.check(e);blocked=False
    except ValueError:blocked=True
    checks['fifth_success_rejected']=blocked
    e=event();policy.track(e,SimpleNamespace(func_tool=None));policy.check(e,4);policy.started(e,4)
    e.get_extra('qq_image_failure_state')['dispatch_started']=True;e.set_extra('qq_generated_attachment_sends',3)
    policy.record_failure({'trace':'batch-fixture','batch_id':'one','batch_index':3},RuntimeError('HTTP 503'))
    policy.feedback(e,result('系统提示：已成功下发 3 张图。'))
    try:policy.check(e,1);allowed=True
    except ValueError:allowed=False
    checks['partial_failure_allows_one_missing_image']=allowed
    try:policy.check(e,4);blocked=False
    except ValueError:blocked=True
    checks['partial_failure_cannot_repeat_whole_batch']=blocked
    policy.started(e,1);e.get_extra('qq_image_failure_state')['dispatch_started']=True;e.set_extra('qq_generated_attachment_sends',4);policy.feedback(e,result('成功'))
    checks['retry_and_success_budget_separate']=e.get_extra('qq_image_failure_state')['attempted_images']==5 and e.get_extra('qq_image_failure_state')['delivered_images']==4
    e=event();policy.track(e,SimpleNamespace(func_tool=SimpleNamespace(tools=[SimpleNamespace(name='generate_image')])));policy.started(e,4)
    e.get_extra('qq_image_failure_state')['dispatch_started']=True;e.set_extra('qq_generated_attachment_sends',2)
    policy.record_failure({'trace':'batch-fixture','batch_id':'one','batch_index':3},RuntimeError('HTTP 400 moderation_blocked'))
    r=result('系统提示：已成功下发 2 张图。');policy.feedback(e,r)
    text=''.join(p.text for p in r.content)
    checks['fatal_partial_failure_preserves_success_report']='成功下发 2' in text and '部分图片已发送' in text
    checks['fatal_partial_failure_removes_retry_tools']=not e.get_extra('qq_image_failure_state')['request'].func_tool.tools
    e=event();policy.track(e,SimpleNamespace(func_tool=None));policy.started(e,4);policy.feedback(e,result('额度不足'))
    checks['quota_denial_does_not_spend_generation_attempts']=e.get_extra('qq_image_failure_state')['attempted_images']==0
    from .image_batch_timeout import wait_for_image_activity,adapt_generation_wait
    class GraceFixture:
        async def _run_agent_with_grace(self,run):
            task=asyncio.create_task(run.work())
            try:
                await asyncio.wait_for(asyncio.shield(task),timeout=self.settings.generation_timeout_sec)
            except (asyncio.TimeoutError,asyncio.CancelledError):
                self.cleaned=True;task.cancel();await asyncio.gather(task,return_exceptions=True);raise
    helper=lambda future,**kw:wait_for_image_activity(future,image_timeout=.1,**kw)
    adapted=adapt_generation_wait(GraceFixture._run_agent_with_grace,helper)
    async def work():await asyncio.sleep(.03)
    e=event();signal=asyncio.Event();e.set_extra('qq_image_batch_signal',signal)
    fixture=SimpleNamespace(settings=SimpleNamespace(generation_timeout_sec=.01),cleaned=False)
    run=SimpleNamespace(work=work,last_event=e)
    try:await adapted(fixture,run);timed_out=False
    except asyncio.TimeoutError:timed_out=True
    checks['ordinary_reply_keeps_original_deadline_and_cleanup']=timed_out and fixture.cleaned
    fixture.cleaned=False
    async def start_image():await asyncio.sleep(.003);signal.set()
    trigger=asyncio.create_task(start_image());await adapted(fixture,run);await trigger
    checks['validated_image_signal_extends_only_active_reply']=not fixture.cleaned and fixture.settings.generation_timeout_sec==.01
    job=asyncio.create_task(adapted(fixture,run));await asyncio.sleep(.003);job.cancel()
    await asyncio.gather(job,return_exceptions=True)
    checks['image_deadline_preserves_native_cancellation_cleanup']=fixture.cleaned and job.cancelled()
    return {'passed':all(checks.values()),'checks':checks,'model_calls':0,'image_generations':0,'qq_messages_sent':0}
