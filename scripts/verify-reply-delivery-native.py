"""Real RespondStage, fake platform sends and module-local interval draws."""
import asyncio
from copy import deepcopy
import importlib
from types import SimpleNamespace as NS
from unittest.mock import patch


async def verify_delivery(probe,event,release):
    from astrbot.core.pipeline.respond import stage as native
    module=importlib.import_module(type(probe).__module__.rsplit('.',1)[0]+'.reply_delivery')
    checks={};records=[];draws=[];timeline=[]
    def check(k,v):checks[k]=bool(v);assert v,k
    def uniform(lo,hi):draws.append((lo,hi));timeline.append('wait');return 0.0
    async def no_hooks(*args):return False
    previous=probe.config.get('reply_delivery');old_activity=probe.model_activity
    probe.model_activity=NS(emit=lambda state,**kw:records.append({'event':state,**kw}))
    adapter=module.ReplyDeliveryAdapter(probe)
    original_process=native.RespondStage.process;original_interval=native.RespondStage._calc_comp_interval
    adapter.install();adapter.install()
    async def make(parts=('one','two','three'),enabled=True,permitted=True,model=True,segmented=True,method='random'):
        probe.config['reply_delivery']={'first_segment_immediate':enabled}
        e=event('synthetic delivery');e.plugins_name=['astrbot_plugin_qq_persona_models'] if permitted else []
        result=e.plain_result('placeholder');result.chain=[native.Comp.Plain(text=t) for t in parts]
        if model:result.result_content_type=native.ResultContentType.LLM_RESULT
        e.set_result(result)
        s=native.RespondStage()
        cfg={'platform_settings':{'reply_with_mention':False,'reply_with_quote':False,'segmented_reply':{'enable':segmented,'only_llm_result':True,'interval_method':method,'interval':'0.3,0.8','log_base':2.6}}}
        await s.initialize(NS(astrbot_config=cfg))
        return e,s
    async def run(**kw):
        e,s=await make(**kw);sent=[]
        async def send(chain,*a,**k):
            timeline.append('send');sent.append(deepcopy(chain.chain))
        e.send=send;draws.clear();timeline.clear();records.clear()
        await s.process(e)
        result={'sent':sent,'draws':list(draws),'timeline':list(timeline),'records':list(records),'restored':e.send is send,'context_reset':module._DELIVERY.get() is None}
        await release(e);return result
    try:
        with patch.object(native,'random',NS(uniform=uniform)),patch.object(native,'call_event_hook',no_hooks):
            normal=await run()
            check('first_segment_has_no_draw_or_wait',normal['timeline']==['send','wait','send','wait','send'])
            check('later_intervals_preserved',normal['draws']==[(0.3,0.8),(0.3,0.8)])
            check('content_and_order_preserved',[[c.text for c in chain] for chain in normal['sent']]==[['one'],['two'],['three']])
            check('first_actual_send_logged_once',len(normal['records'])==1 and normal['records'][0]['event']=='first_segment_sent' and normal['records'][0]['segment_index']==1)
            check('instance_send_restored_and_context_cleared',normal['restored'] and normal['context_reset'])
            disabled=await run(enabled=False)
            check('disabled_retains_all_native_waits',disabled['timeline']==['wait','send','wait','send','wait','send'] and not disabled['records'])
            foreign=await run(permitted=False)
            check('plugin_permissions_preserved',len(foreign['draws'])==3 and not foreign['records'])
            command=await run(model=False)
            check('non_model_reply_unchanged',len(command['sent'])==1 and not command['draws'] and not command['records'])
            whole=await run(segmented=False)
            check('native_segmentation_switch_preserved',len(whole['sent'])==1 and not whole['draws'] and not whole['records'])
            logarithmic=await run(method='log')
            check('log_interval_only_skips_first',len(logarithmic['draws'])==2 and logarithmic['timeline'][0]=='send')
            e,s=await make();r=e.get_result();r.chain=[native.Comp.Reply(id='quote-id'),native.Comp.At(qq='A'),*r.chain]
            sent=[]
            async def headers(chain,*a,**kw):sent.append(deepcopy(chain.chain))
            e.send=headers;await s.process(e)
            check('quote_and_mention_sent_once',len(sent)==3 and [type(c).__name__ for c in sent[0]][:2]==['Reply','At'] and all(len(chain)==1 for chain in sent[1:]))
            await release(e)
            e,s=await make()
            async def cancel(*a,**k):raise asyncio.CancelledError()
            e.send=cancel
            try:await s.process(e);cancelled=False
            except asyncio.CancelledError:cancelled=True
            check('cancellation_restores_instance_and_context',cancelled and e.send is cancel and module._DELIVERY.get() is None)
            await release(e)
            a,sa=await make();b,sb=await make();records.clear();draws.clear()
            await asyncio.gather(sa.process(a),sb.process(b))
            check('parallel_requests_each_skip_one_wait',len(draws)==4 and len(records)==2 and all(r['segment_index']==1 for r in records))
            check('parallel_context_does_not_leak',module._DELIVERY.get() is None)
            await release(a);await release(b)
    finally:
        adapter.restore();probe.model_activity=old_activity
        if previous is None:probe.config.pop('reply_delivery',None)
        else:probe.config['reply_delivery']=previous
    check('unload_restores_native_methods',native.RespondStage.process is original_process and native.RespondStage._calc_comp_interval is original_interval)
    return {'passed':all(checks.values()),'checks':checks,'model_calls':0,'qq_messages_sent':0,'platform_sends':'synthetic_only'}
