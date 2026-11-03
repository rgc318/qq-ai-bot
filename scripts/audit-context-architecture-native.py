"""Verify architecture corrections with synthetic native inputs, no network/data."""
import asyncio
import importlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from types import ModuleType,SimpleNamespace

sys.path.insert(0,'/AstrBot')


async def run():
    from PIL import Image as PILImage
    from astrbot.api.message_components import Image,Plain
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage,MessageMember,Group
    from astrbot.core.platform.message_type import MessageType
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot.core.provider.entities import ProviderRequest
    from astrbot.core.agent.tool import ToolSet,FunctionTool
    evidence={};checks={};probes={}
    def check(name,value):checks[name]=bool(value);assert value,name
    with TemporaryDirectory(dir='/AstrBot/data',prefix='architecture-audit-') as temp:
        root=Path(temp);code=root/'plugin'
        shutil.copytree('/workspace/extensions/astrbot_plugin_qq_persona_models',code,ignore=shutil.ignore_patterns('__pycache__','_ca_runtime'))
        shutil.copytree('/workspace/integrations/contextaware',code/'_ca_runtime',ignore=shutil.ignore_patterns('__pycache__'))
        package=ModuleType('architecture_fixture');package.__path__=[str(code)];sys.modules[package.__name__]=package
        Main=importlib.import_module('architecture_fixture.main').PersonaModelBindings
        Archive=importlib.import_module('architecture_fixture.attachment_context').AttachmentContext
        Runtime=importlib.import_module('architecture_fixture.context_runtime').ContextRuntime
        Router=importlib.import_module('architecture_fixture.reply_routing').ReplyRouter
        plan_history=importlib.import_module('architecture_fixture.performance_context').plan_history
        async def native_group(*args):pass
        registered={'astrbot_plugin_user_policy':SimpleNamespace(star_cls=SimpleNamespace(memory_isolation=SimpleNamespace(_scope=lambda d:('public:G','group')))),
                    'astrbot':SimpleNamespace(star_cls=SimpleNamespace(group_chat_context=SimpleNamespace(on_req_llm=native_group)))}
        context=SimpleNamespace(get_registered_star=lambda name:registered.get(name),get_config=lambda **kw:{'wake_prefix':[]},get_using_provider=lambda **kw:SimpleNamespace(provider_config={'modalities':['text','image','tool_use']}))
        calls=[]
        async def judge(payload):calls.append(payload);return {'route':'addressed','recipient':'bot','silence_requested':False,'confidence':0.99}
        probe=object.__new__(Main);probe.context=context;probe.config={'multimodal_context':{'enabled':True}}
        probe.router=Router({'allowed_groups':['G'],'aliases':['AI']},judge)
        probe.routing_persona=lambda e:e.get_extra('user_policy_effective_persona_id');probe.model_activity=SimpleNamespace(active={},emit=lambda *a,**kw:None)
        archive=Archive(probe,root/'archive',{'enabled':True,'auto_attach':True,'auto_attach_seconds':180})
        runtime=Runtime(probe,archive,Path('/candidate'));probe.attachments=runtime
        ordinal=0
        def event(text='',picture=None,sender='A',persona='whale'):
            nonlocal ordinal
            ordinal+=1
            raw=AstrBotMessage();raw.type=MessageType.GROUP_MESSAGE;raw.self_id='bot';raw.session_id='G';raw.group=Group(group_id='G')
            raw.message_id=str(ordinal);raw.sender=MessageMember(user_id=sender,nickname=sender);raw.message_str=text;raw.message=[Plain(text=text)];raw.raw_message={}
            if picture:raw.message.append(Image.fromFileSystem(str(picture)))
            e=AstrMessageEvent(text,raw,PlatformMetadata(name='aiocqhttp',description='fixture',id='fixture'),'G')
            e.plugins_name=['astrbot_plugin_qq_persona_models'];e.set_extra('user_policy_effective_persona_id',persona)
            e.set_extra('user_policy_decision',SimpleNamespace(is_blocked=False,memory_isolation=True,persona_id=persona,identity=SimpleNamespace(is_private=False,platform='aiocqhttp',group_id='G',user_id=sender)))
            return e
        async def request(e,proactive=False):
            async def noop(*a,**kw):raise AssertionError('No tools executed')
            req=ProviderRequest(prompt='请根据群聊自然接一句话。' if proactive else e.message_str,func_tool=ToolSet(tools=[FunctionTool(name='view_context_images',description='fixture',parameters={'type':'object'},handler=noop)]))
            if proactive:e.set_extra('self_initiated_reply',True)
            await runtime.prepare(e,req);return req
        def image_count(req):return len(req.image_urls)+sum((p.get('type') if isinstance(p,dict) else getattr(p,'type',None))=='image_url' for p in req.extra_user_content_parts)
        async def model_probe(name,req,expected):
            from astrbot.core.agent.message import Message,dump_messages_with_checkpoints
            import astrbot.core.provider.sources.openai_source as native
            cls=next(c for c in vars(native).values() if isinstance(c,type) and c.__module__==native.__name__ and callable(getattr(c,'assemble_context',None)))
            async def image_part(url):return {'type':'image_url','image_url':{'url':url}}
            wire=await cls.assemble_context(SimpleNamespace(_resolve_image_part=image_part),req.prompt,req.image_urls,req.audio_urls,req.extra_user_content_parts)
            check(name+'_native_provider_accepts_temporary_multimodal_parts',sum(p.get('type')=='image_url' for p in wire['content'])==image_count(req))
            stored=dump_messages_with_checkpoints([Message.model_validate(await req.assemble_context())])
            check(name+'_previews_and_fact_copies_not_persisted',not any(p.get('type')=='image_url' for row in stored for p in row.get('content',[]) if isinstance(p,dict)))
            probes[name]={'messages':[{'role':'system','content':'你是群聊助手。依据实际提供的图像与发言者来源简洁回答，不猜未见图片。\n'+req.system_prompt},wire],
                          'expected':expected,'initial_images':image_count(req)}
        async def release(e):e.cleanup_temporary_local_files();await asyncio.sleep(0)
        await runtime.initialize();await runtime.switch('contextaware')
        try:
            image=root/'front.png';PILImage.new('RGB',(64,64),'red').save(image)
            upload=event('',image);await runtime.capture(upload);await release(upload)
            q=event('之前A发的图片背景是什么颜色？请直接回答颜色。');req=await request(q)
            evidence['same_auto_attach_configuration']={'configured':archive.settings['auto_attach'],'contextaware_image_candidates':len(runtime.candidate.catalog(q)),'contextaware_initial_images':image_count(req)}
            check('contextaware_delivers_recent_pixels_directly',len(runtime.candidate.catalog(q))==1 and image_count(req)==1)
            await model_probe('direct_single_image',req,['红'])
            q.set_extra('qq_context_images_viewed',['synthetic-id'])
            await release(q)
            evidence['completed_event_retains_diagnostic_fields']={'catalog':bool(q.get_extra('qq_context_catalog_stats')),'viewed_images':bool(q.get_extra('qq_context_images_viewed'))}
            check('request_cleanup_clears_read_diagnostics',not any(evidence['completed_event_retains_diagnostic_fields'].values()))
            proactive_event=event('之前A发的图片背景是什么颜色？请直接回答颜色。');proactive_req=await request(proactive_event,True)
            check('proactive_uses_real_request_with_same_initial_pixels',proactive_req.prompt==proactive_event.get_message_str() and image_count(proactive_req)==1)
            await model_probe('proactive_single_image',proactive_req,['红'])
            await release(proactive_event)
            blue=root/'side.png';PILImage.new('RGB',(64,64),'blue').save(blue)
            upload2=event('',blue,sender='B');await runtime.capture(upload2);await release(upload2)
            comparison=event('请分别说出A和B发的图片背景颜色。用“A：颜色；B：颜色”回答。',sender='C');comparison_req=await request(comparison)
            check('multiple_members_images_have_independent_source_ids',image_count(comparison_req)==2 and len(comparison.get_extra('qq_initial_image_ids'))==2)
            await model_probe('two_members_two_images',comparison_req,['A','红','B','蓝'])
            original_ids=list(comparison.get_extra('qq_initial_image_ids'));await release(comparison)
            edit=event('把A和B刚才发的两张图拼接成一张图，保留各自内容。',sender='C');edit_req=await request(edit)
            await model_probe('edit_reference_pair',edit_req,[])
            probes['edit_reference_pair']['expected_reference_ids']=list(edit.get_extra('qq_initial_image_ids'))
            probes['edit_reference_pair']['current_text']=edit.get_message_str();await release(edit)
            independent=event('画一个黄色三角形，独立创作，不使用之前任何图片。');independent_req=await request(independent)
            await model_probe('independent_generation',independent_req,[])
            probes['independent_generation']['expected_reference_ids']=[]
            probes['independent_generation']['current_text']=independent.get_message_str();await release(independent)
            foreign=event('其他人格',persona='dragon');foreign_req=await request(foreign)
            check('shared_compiler_preserves_persona_isolation',image_count(foreign_req)==0 and not runtime.candidate.catalog(foreign));await release(foreign)
            from architecture_fixture.request_context import ensure_call_request
            from astrbot.api.message_components import At
            call=event('');call.message_obj.message=[At(qq='bot')];call.is_at_or_wake_command=True
            check('empty_mention_uses_core_request_without_mutating_original',ensure_call_request(call) and call.get_message_str()=='' and bool(call.get_extra('provider_request').prompt))
            archive.settings['auto_attach']=False
            disabled=event('查看历史图');disabled_req=await request(disabled)
            check('auto_attach_switch_keeps_catalog_but_disables_pixels',image_count(disabled_req)==0 and len(runtime.candidate.catalog(disabled))==2);await release(disabled)
            archive.settings['auto_attach']=True;archive.settings['recent_input']={'max_images':1}
            bounded=event('简短回应');bounded_req=await request(bounded)
            check('preview_count_budget_enforced',image_count(bounded_req)==1);await release(bounded)
            archive.settings['recent_input']={}
            await runtime.switch('builtin')
            q2=event('请解读这张图片');req2=await request(q2)
            evidence['same_auto_attach_configuration']['builtin_initial_images']=image_count(req2)
            check('builtin_uses_same_multimodal_budget',image_count(req2)==2)
            observations=list(q2.get_extra('qq_recent_facts'))
            await release(q2)
            text_router=Router({'allowed_groups':['G'],'aliases':['AI']},judge)
            await text_router.decide('G','A','',message_id='photo')
            verdict=await text_router.decide('G','A','我让你解读一下图片',message_id='question',observations=observations,self_id='bot')
            evidence['cold_image_request_route']={'route':verdict['route'],'reason':verdict['reason'],'judge_calls':len(calls),'image_metadata_in_router':any('image_count' in row or 'attachments' in row for row in text_router.context('G').messages)}
            check('cold_picture_request_uses_shared_facts_and_one_judge',verdict['route']=='fast' and len(calls)==1 and evidence['cold_image_request_route']['image_metadata_in_router'])
            check('judge_payload_keeps_both_image_sources',any(r.get('image_count') for r in calls[0]['recent_messages']))
            image_reply=await text_router.decide('G','D','',message_id='image-reply',observations=observations,self_id='bot',metadata={'image_count':1,'attachments':[{'type':'image','state':'ready'}]})
            check('media_only_turn_is_semantically_judged_from_shared_facts',image_reply['judged'] and len(calls)==2 and calls[-1]['latest_message']['image_count']==1)
            history=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,synthetic'}}]},{'role':'assistant','content':'fixture'}]
            planned,stats=plan_history(history,'你好',{'history_turns':12,'history_image_turns':2})
            evidence['legacy_prompt']={'removed_images':stats['removed_history_images'],'asks_reupload':('引用或重发' in json.dumps(planned,ensure_ascii=False))}
            check('legacy_pruning_no_longer_requests_reupload',not evidence['legacy_prompt']['asks_reupload'])
            text_router.note_ai('G','first pending',request='Task A',sender='A',pending=True,message_id='task-A')
            first=text_router.context('G').last_ai['id']
            text_router.note_ai('G','second pending',request='Task B',sender='B',pending=True,message_id='task-B')
            evidence['parallel_tasks']={'current_requester':text_router.context('G').last_ai['requested_by'],'previous_anchor_remains':any(r['id']==first for r in text_router.context('G').tasks.values())}
            check('new_member_task_does_not_erase_other_requests',evidence['parallel_tasks']['previous_anchor_remains'] and len(text_router.context('G').tasks)==2)
            text_router.note_ai('G','Task A result',request='Task A',sender='A',message_id='task-A')
            check('delivery_updates_only_its_own_request',text_router.context('G').tasks['request:task-A']['status']=='sent' and text_router.context('G').tasks['request:task-B']['status']=='pending')
            restored=Router({'allowed_groups':['G']},judge);restored.restore(text_router.snapshot())
            check('restart_retains_tasks_without_faking_background_work',len(restored.context('G').tasks)==2 and restored.context('G').tasks['request:task-B']['status']=='interrupted')
            text_router.select_scope('G','G|whale');text_router.note_ai('G','',request='old persona task',sender='A',pending=True,message_id='old-persona')
            text_router.select_scope('G','G|dragon');text_router.note_ai('G','',request='new persona task',sender='A',pending=True,message_id='new-persona')
            text_router.note_ai('G','old persona result',request='old persona task',sender='A',message_id='old-persona',scope='G|whale')
            check('persona_switch_does_not_misattribute_inflight_completion',text_router.context('G').tasks['request:new-persona']['status']=='pending' and text_router.request_context('G','G|whale').tasks['request:old-persona']['status']=='sent')
        finally:await runtime.close()
    print('RUNTIME_REPORT='+json.dumps({'passed':all(checks.values()),'meaning':'Isolated architecture correction checks, not a production behavior guarantee.','checks':checks,'evidence':evidence,'model_probes':probes,'model_calls':0,'qq_messages_sent':0,'image_generations':0,'real_history_replayed':False},ensure_ascii=False))


if __name__=='__main__':asyncio.run(run())
