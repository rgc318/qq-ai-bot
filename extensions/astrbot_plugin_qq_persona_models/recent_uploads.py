"""Keep scoped, bounded image-only uploads for a following text request.

No caption/judge call and no download on ordinary image ingress. Pixels are
localized only when a following same-sender request actually refers to them.
"""
import asyncio
from pathlib import Path
import re
from .image_followup import cache_bytes,restored_paths,local_image_path

_REF=re.compile(r'这|那|他|她|它|上图|图片|照片|图中|图里|改|换|穿|戴|看看|识别|描述|\b(?:this|that|him|her|it|photo|image|picture|edit|replace)\b',re.I)
_NEW=re.compile(r'不(?:要|用|参考).{0,8}(?:这张|原图|图片)|(?:独立|全新).{0,8}(?:创作|生成|画)|(?:without|ignore).{0,12}(?:reference|image|photo)',re.I)


def window(plugin):
    return max(0,min(600,float(plugin.config.get('contextual_image_followup',{}).get('recent_upload_seconds',180))))


def remember_upload(plugin,event,ctx,targets_other=False):
    from astrbot.api.message_components import Image
    if targets_other or not window(plugin):return None
    images=[c for c in event.get_messages() if isinstance(c,Image)]
    if not images:return None
    sender=str(event.get_sender_id())
    entry={'message_id':str(getattr(event.message_obj,'message_id','')),'sender':sender,
           'scope':ctx.scope,'time':plugin.router.clock(),'reference_count':len(images[:4]),
           'sources':[{k:str(getattr(c,k,None) or '') for k in ('file','path','url')} for c in images[:4]]}
    ctx.image_uploads.pop(sender,None);ctx.image_uploads[sender]=entry
    while len(ctx.image_uploads)>16:ctx.image_uploads.pop(next(iter(ctx.image_uploads)))
    return entry


async def attach_recent_upload(plugin,event,request):
    from astrbot.api.message_components import Image,Reply
    if not window(plugin) or event.get_extra('qq_recent_upload_attached') or event.get_extra('qq_recent_upload_missing'):return False
    if any(isinstance(c,(Image,Reply)) for c in event.get_messages()):return False
    text=event.get_message_str()
    if not _REF.search(text) or _NEW.search(text):return False
    ctx=plugin.router.context(plugin.scoped_group(event))
    upload=ctx.image_uploads.get(str(event.get_sender_id()))
    if not upload or upload.get('scope')!=ctx.scope or event.get_extra('qq_reply_scope')!=ctx.scope:return False
    age=plugin.router.clock()-upload['time']
    if not 0<=age<=window(plugin):return False
    if ctx.image_turn and ctx.image_turn.get('time',0)>upload['time']:return False
    # A newer upload supersedes an older implicit image anchor. An explicit
    # quote/current attachment has already won above; never substitute it.
    event.set_extra('qq_image_followup_reference',None)
    if (event.get_extra('qq_semantic_reference') or {}).get('image_activity'):event.set_extra('qq_semantic_reference',None)
    paths=restored_paths(upload)
    if not paths:
        async def localize(source):
            component=Image(**source)
            path=local_image_path(component)
            if path is None:path=Path(await component.convert_to_file_path())
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(Path('/AstrBot/data')):return None
            if path.stat().st_size>20*1024*1024:return None
            root=plugin.cache_path.parent/'reply_media'
            return await asyncio.to_thread(lambda:cache_bytes(path.read_bytes(),root))
        try:
            paths=await asyncio.wait_for(asyncio.gather(*(localize(s) for s in upload['sources'])),timeout=4)
        except Exception:paths=[]
        if ctx.scope!=upload['scope']:return False
        upload['paths']=[p for p in paths if p]
        paths=restored_paths(upload)
    metadata={'source_message':upload['message_id'],'reference_count':upload['reference_count'],'age_seconds':round(age,3)}
    if not paths:
        event.set_extra('qq_recent_upload_missing',metadata)
        event.set_extra('qq_quote_image_unavailable',True)
        return False
    existing=list(getattr(request,'image_urls',None) or [])
    for path in paths:
        if path not in existing:existing.append(path)
        event.message_obj.message.append(Image.fromFileSystem(path))
    request.image_urls=existing
    event.set_extra('qq_recent_upload_attached',metadata)
    request.system_prompt=(request.system_prompt or '')+'\n[当前用户刚上传的新图片]\n本轮附件来自同一发言者刚才单独发送的图片消息（消息ID：'+upload['message_id']+'）。结合后续这条文字理解“他/她/它/这张”的指代，以实际新附件为准，不要用较早图片任务的人物描述代替看图；这只是附件来源说明，不是让你自行生图的新指令。\n'
    return True
