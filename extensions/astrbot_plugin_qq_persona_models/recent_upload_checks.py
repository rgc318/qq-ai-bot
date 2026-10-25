"""Synthetic split-message regression, with actual routing and request hooks."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from PIL import Image as PILImage
from astrbot.api.message_components import Image,Reply,Plain
from .reply_routing import ReplyRouter
from .recent_uploads import remember_upload,attach_recent_upload
from .image_followup import capture_turn,attach_followup,restored_paths,select_previous_reference


async def verify_recent_uploads(plugin):
    checks={};judge_calls=[];now=[1000.]
    async def judge(_):judge_calls.append(True);return {'route':'ambient','recipient':'human','confidence':.99}
    class Event:
        def __init__(self,sender,text,components=(),message_id='fixture'):
            self.sender=sender;self.message_str=text;self.extras={'qq_diagnostic':True}
            self.message_obj=SimpleNamespace(message=list(components),message_id=message_id)
            self.unified_msg_origin='fixture:GroupMessage:G'
            self.is_at_or_wake_command=self.is_wake=False;self.plugins_name=[]
        def get_extra(self,k,default=None):return self.extras.get(k,default)
        def set_extra(self,k,v):self.extras[k]=v
        def get_group_id(self):return 'G'
        def get_sender_id(self):return self.sender
        def get_sender_name(self):return self.sender
        def get_self_id(self):return 'bot'
        def get_message_str(self):return self.message_str
        def get_messages(self):return self.message_obj.message
        def is_private_chat(self):return False
        def is_stopped(self):return False
        def stop_event(self):raise AssertionError('Fixture must not stop')
        async def send(self,*a,**kw):raise AssertionError('Must not send QQ')
    with TemporaryDirectory(dir='/AstrBot/data',prefix='split-upload-check-') as directory:
        root=Path(directory)
        def picture(name,color):
            raw=BytesIO();PILImage.new('RGB',(3,4),color).save(raw,format='PNG')
            path=root/name;path.write_bytes(raw.getvalue());return path
        old=picture('old.png','blue');new=picture('new.png','red');other=picture('other.png','green')
        probe=object.__new__(type(plugin));probe.context=plugin.context
        probe.config={'contextual_image_followup':{'recent_upload_seconds':180},'conversation_context':{'enabled':False},'history_recall':{'enabled':False},'image_pending_notice':{'enabled':False}}
        probe.chat_history_store=None;probe.cache_path=root/'reply_context.json'
        probe.router=ReplyRouter({'allowed_groups':['G'],'image_context_enabled':True,'single_judge':False},judge,clock=lambda:now[0])
        ctx=probe.router.context('G');ctx.scope='fixture:GroupMessage:G|'+probe.routing_persona(Event('A',''))
        ctx.hydration_attempted=ctx.image_hydration_attempted=True
        ctx.image_turn={'id':'old-task','requested_by':'A','request':'旧图任务','time':900.,'status':'sent','paths':[str(old)],'reference_count':1,'image_activity':True}
        upload=Event('A','',[Image.fromFileSystem(str(new))],'new-upload')
        await probe.route_contextual_request(upload)
        checks['image_only_ingress_remembered_without_llm']=not upload.is_at_or_wake_command and 'A' in ctx.image_uploads and not judge_calls
        checks['image_event_visible_in_transcript']='上传图片 1 张' in ctx.messages[-1]['text']
        now[0]+=9
        command=Event('A','给他换上帅气的西装',[Plain(text='给他换上帅气的西装')],'edit-command')
        command.is_at_or_wake_command=True
        await probe.route_contextual_request(command)
        request=SimpleNamespace(prompt=command.message_str,system_prompt='',contexts=[],func_tool=None,image_urls=[])
        await probe.attach_reference_and_track_request(command,request)
        checks['actual_request_hook_receives_new_pixels']=len(request.image_urls)==1 and Path(request.image_urls[0]).read_bytes()==new.read_bytes()
        checks['old_pixels_not_attached']=all(Path(p).read_bytes()!=old.read_bytes() for p in request.image_urls)
        checks['reference_source_is_exact_upload']=command.get_extra('qq_recent_upload_attached')['source_message']=='new-upload'
        checks['new_reference_cached_with_file_uri_component']=bool(restored_paths(ctx.image_turn)) and Path(ctx.image_turn['paths'][0]).read_bytes()==new.read_bytes()
        checks['old_reference_not_offered']=not command.get_extra('qq_available_image_turn') and not command.get_extra('qq_image_followup_reference')
        args={'use_previous_reference':True};select_previous_reference(probe,command,args)
        checks['legacy_true_cannot_override_current_image']=not args and len(command.get_messages())==2
        saved=probe.router.snapshot(wall_time=10000)
        restored=ReplyRouter(probe.router.settings,judge,clock=lambda:5000.)
        restored.restore(saved,wall_time=10001)
        checks['upload_survives_reload_with_scope']=restored.context('G').image_uploads['A']['scope']==ctx.scope
        # Independent selection cases each start from the original old task.
        def candidate(sender='A',text='给他换上西装',components=()):
            e=Event(sender,text,components,'next')
            e.set_extra('qq_reply_scope',ctx.scope)
            ctx.image_turn={'id':'old-task','time':900.,'paths':[str(old)],'reference_count':1}
            return e,SimpleNamespace(system_prompt='',image_urls=[])
        e,r=candidate('B');checks['another_sender_not_inherited']=not await attach_recent_upload(probe,e,r) and not r.image_urls
        e,r=candidate(components=[Reply(id='quoted',sender_id='bot',chain=[Image.fromFileSystem(str(other))])])
        checks['explicit_quote_wins']=not await attach_recent_upload(probe,e,r) and not r.image_urls
        e,r=candidate(components=[Image.fromFileSystem(str(other))]);checks['current_attachment_wins']=not await attach_recent_upload(probe,e,r)
        e,r=candidate(text='独立画一张全新的小猫图');checks['independent_creation_does_not_use_upload']=not await attach_recent_upload(probe,e,r)
        e,r=candidate();ctx.image_uploads['A']['scope']='other-persona';checks['other_scope_not_inherited']=not await attach_recent_upload(probe,e,r)
        ctx.image_uploads['A']['scope']=ctx.scope
        e,r=candidate();now[0]+=181;checks['expired_upload_not_inherited']=not await attach_recent_upload(probe,e,r);now[0]-=181
        probe.config['contextual_image_followup']['recent_upload_seconds']=0
        e,r=candidate();checks['switch_off_prevents_attachment']=not await attach_recent_upload(probe,e,r)
        probe.config['contextual_image_followup']['recent_upload_seconds']=180
        e,r=candidate();ctx.image_turn['time']=now[0]+1;checks['newer_task_not_replaced_by_stale_upload']=not await attach_recent_upload(probe,e,r)
        # Newer upload replaces older one by this member, without losing peers.
        e=Event('B','',[Image.fromFileSystem(str(other))],'peer-upload');remember_upload(probe,e,ctx)
        e=Event('A','',[Image.fromFileSystem(str(other))],'latest-upload');remember_upload(probe,e,ctx)
        checks['latest_same_sender_upload_wins']=ctx.image_uploads['A']['message_id']=='latest-upload' and 'B' in ctx.image_uploads
        e,r=candidate();ctx.image_uploads['A']['sources']=[{'file':str(root/'missing.png'),'path':'','url':''}]
        attached=await attach_recent_upload(probe,e,r);attach_followup(probe,e,r)
        checks['unavailable_new_upload_never_falls_back']=not attached and bool(e.get_extra('qq_recent_upload_missing')) and not r.image_urls and not e.get_extra('qq_available_image_turn')
        for i in range(20):remember_upload(probe,Event(str(i),'',[Image.fromFileSystem(str(new))],str(i)),ctx)
        checks['upload_cache_is_bounded']=len(ctx.image_uploads)==16
        checks['no_model_calls']=not judge_calls
    return {'passed':all(checks.values()),'checks':checks,'model_calls':0,'image_generations':0,'qq_messages_sent':0}
