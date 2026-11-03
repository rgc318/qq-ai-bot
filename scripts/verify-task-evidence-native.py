"""Exercise the real AstrBot runner using synthetic providers and read tools."""
import asyncio
import importlib
import json
import time
from copy import deepcopy
from types import SimpleNamespace as NS


async def verify_guard(probe,runtime,event,request,release,root):
    from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
    from astrbot.core.agent.tool import ToolSet,FunctionTool
    from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
    from astrbot.core.provider.entities import LLMResponse,TokenUsage
    m=importlib.import_module(type(probe).__module__.rsplit('.',1)[0]+'.task_evidence')
    checks={};measurements=[];probes={}
    def check(k,v):checks[k]=bool(v);assert v,k
    def reply(text='好了',**extra):
        state={'status':'answered','image_ids':[],'document_ids':[],'actions':[],**extra}
        return LLMResponse(role='assistant',completion_text=text+m.OPEN+json.dumps(state)+m.CLOSE)
    original=ToolLoopAgentRunner._iter_llm_responses_with_fallback
    guard=m.TaskEvidenceGuard(probe);guard.install()
    try:
        async def scenario(name,outputs,delivered=0,budget=5,change_scope=False):
            e=event('synthetic task '+name);q=request(e);await runtime.prepare(e,q)
            guard.attach(e,q);e.set_extra('qq_generated_attachment_sends',delivered)
            state=e.get_extra(m.KEY);state['provided']={'seen'}
            calls=[];executed=[]
            async def reader(e,attachment_ids):
                executed.append(list(attachment_ids));e.get_extra(m.KEY)['viewed'].update(attachment_ids)
                return '已返回合成图片，供测试验证'
            async def image(e):raise AssertionError('Never execute image generation')
            q.func_tool=ToolSet(tools=[FunctionTool(name='view_context_images',description='synthetic reader',parameters={'type':'object','properties':{'attachment_ids':{'type':'array','items':{'type':'string'}}}},handler=reader),FunctionTool(name='generate_image',description='must not execute',parameters={'type':'object','properties':{}},handler=image)])
            class Provider:
                provider_config={'id':'synthetic-evidence','modalities':['text','image','tool_use']}
                def get_model(self):return 'synthetic-evidence'
                async def text_chat(self,**kw):
                    calls.append({'tools':kw['func_tool'].names() if kw.get('func_tool') else [],'contexts':kw.get('contexts',[])})
                    value=outputs[min(len(calls)-1,len(outputs)-1)]
                    if change_scope:e.set_extra('qq_reply_scope','changed-persona')
                    return value() if callable(value) else deepcopy(value)
            async def noop(*a):pass
            async def ended(ctx,tool,args,result):m.observe_result(e,tool.name,result)
            runner=ToolLoopAgentRunner()
            await runner.reset(provider=Provider(),request=q,run_context=NS(context=NS(event=e),messages=[],tool_call_timeout=5),
                tool_executor=FunctionToolExecutor,agent_hooks=NS(on_tool_start=noop,on_tool_end=ended,on_agent_begin=noop,on_agent_done=noop))
            public=[];started=time.perf_counter()
            async for item in runner.step_until_done(budget):
                chain=getattr(getattr(item,'data',None),'chain',None)
                public.append(''.join(getattr(p,'text','') for p in getattr(chain,'chain',[])))
            final=runner.get_final_llm_resp();text=final.completion_text if final else ''
            check(name+'_private_state_hidden',not any(m.OPEN in t for t in public) and m.OPEN not in text)
            result={'calls':calls,'state':state,'text':text,'public':public,'executed':executed,'q':q,'incomplete':e.get_extra('qq_task_incomplete'),'aborted':runner._is_stop_requested(),
                    'billed_input':runner.stats.token_usage.input,'occupancy':runner.stats.current_context_tokens}
            measurements.append((time.perf_counter()-started)*1000);await release(e)
            return result
        normal=await scenario('normal',[LLMResponse(role='assistant',completion_text='你好')])
        check('normal_exactly_one_call',len(normal['calls'])==1 and normal['state']['repairs']==0)
        direct=await scenario('provided_pixels',[reply('红色',image_ids=['seen'])])
        check('provided_pixels_no_retry',len(direct['calls'])==1)
        missing=await scenario('unseen_retry',[reply('编造的图',image_ids=['missing']),reply('资料不足',status='needs_input')])
        check('one_correction_and_wrong_answer_not_sent',len(missing['calls'])==2 and '编造的图' not in ''.join(missing['public']))
        read_call=LLMResponse(role='assistant',tools_call_name=['view_context_images'],tools_call_args=[{'attachment_ids':['old']}],tools_call_ids=['read-synthetic'])
        recovered=await scenario('recover_by_read',[reply('猜测',image_ids=['old']),read_call,reply('已核对',image_ids=['old'])])
        check('same_agent_can_retrieve_then_answer',len(recovered['calls'])==3 and recovered['executed']==[['old']] and recovered['text']=='已核对')
        failed=await scenario('bounded',[reply('虚构',image_ids=['missing'])])
        check('repeated_contradiction_stops_at_two_calls',len(failed['calls'])==2 and failed['incomplete'] and '虚构' not in failed['text'])
        sent=await scenario('sent_protected',[reply('还在后台画',status='working'),reply('图片已经发送')],delivered=1)
        check('correction_cannot_repeat_sent_images','generate_image' not in sent['calls'][1]['tools'] and not sent['executed'])
        rich=await scenario('malformed',[LLMResponse(role='assistant',completion_text='正文'+m.OPEN+'bad'),reply('资料不足',status='blocked')])
        check('malformed_private_metadata_repaired',len(rich['calls'])==2 and rich['text']=='资料不足')
        empty=await scenario('metadata_only',[reply(''),reply('资料已经核对。')])
        check('metadata_only_output_does_not_become_empty_reply',len(empty['calls'])==2 and empty['text']=='资料已经核对。')
        first=reply('未读取',image_ids=['missing']);first.usage=TokenUsage(input_other=10,output=1)
        second=reply('需要补充资料',status='needs_input');second.usage=TokenUsage(input_other=20,output=1)
        usage=await scenario('usage',[first,second])
        check('discarded_call_billed_without_inflating_context_window',usage['billed_input']==30 and usage['occupancy']==20)
        check('request_local_repair_budget',normal['state'] is not missing['state'] and normal['state']['repairs']==0)
        changed=await scenario('scope_changed',[reply('旧人格回答',image_ids=['missing'])],change_scope=True)
        check('scope_change_aborts_without_retry_or_old_reply',len(changed['calls'])==1 and changed['aborted'] and '旧人格回答' not in ''.join(changed['public']) and not changed['state']['repairs'])
        limited=await scenario('step_budget',[reply('未读取',image_ids=['missing'])],budget=1)
        check('correction_respects_native_step_budget',len(limited['calls'])==1 and limited['incomplete'])
        long_text='完全相同的群聊任务描述。'*40
        source=event(long_text,root/'front.png',sender='A',persona='dedup-evidence')
        await runtime.capture(source);await release(source)
        source=event('另一个成员转发同一图片',root/'front.png',sender='B',persona='dedup-evidence')
        await runtime.capture(source);await release(source)
        e=event('比较两位成员的图片',persona='dedup-evidence');q=request(e)
        q.contexts=[{'role':'user','content':long_text}]
        await runtime.prepare(e,q);guard.attach(e,q)
        stats=e.get_extra('qq_context_input_stats')
        check('identical_original_bytes_attached_once',stats['initial_history_images']==1 and stats['deduplicated_images']==1)
        check('source_aliases_do_not_merge_member_ids',len(e.get_extra(m.KEY)['provided'])==2 and len(m.known_images(e))==2)
        check('only_exact_formal_text_is_shortened',stats['deduplicated_chars']>0 and q.contexts[0]['content']==long_text)
        await release(e)
        for attach in (True,False):
            previous=runtime.settings.get('auto_attach',True);runtime.settings['auto_attach']=attach
            try:
                source=event('这是一张颜色样本。',root/'front.png',sender='A',persona='evidence-probe-'+str(attach))
                await runtime.capture(source);await release(source)
                e=event('请看A刚才的图片，图片的主要颜色是什么？',persona='evidence-probe-'+str(attach))
                q=request(e);await runtime.prepare(e,q);guard.attach(e,q)
                assembled=await q.assemble_context()
                probes['preview' if attach else 'catalog']={'messages':[{'role':'system','content':'你是群聊助手。\n'+q.system_prompt}]+(assembled if isinstance(assembled,list) else [assembled]),
                    'image_ids':sorted(m.known_images(e)),'initial_images':len(e.get_extra(m.KEY)['provided'])}
                await release(e)
            finally:runtime.settings['auto_attach']=previous
    finally:guard.restore()
    check('native_wrapper_restored',ToolLoopAgentRunner._iter_llm_responses_with_fallback is original)
    return {'passed':all(checks.values()),'checks':checks,'max_synthetic_agent_ms':round(max(measurements),3),'real_model_calls':0,'qq_messages_sent':0,'image_generations':0,'model_probes':probes}
