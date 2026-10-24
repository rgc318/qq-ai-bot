"""Recover QQ references before vision; never silently draw without supplied refs."""
import asyncio
from contextvars import ContextVar
from copy import copy
import functools
import hashlib
from pathlib import Path
import re
from urllib.parse import parse_qsl,urlencode,urlsplit,urlunsplit

_STRICT=ContextVar('qq_reference_strict',default=None)
_TOKEN=re.compile(r'([0-9a-fA-F]{32})\.(?:png|jpg|jpeg|gif|webp)',re.I)


def replace_qq_rkey(url,rkey):
    """Only replace credentials on QQ's fixed HTTPS media host."""
    parts=urlsplit(str(url))
    if parts.scheme!='https' or parts.hostname!='multimedia.nt.qq.com.cn' or parts.port not in (None,443) or parts.username or parts.password:
        return None
    key=str(rkey or '').removeprefix('&rkey=').removeprefix('rkey=')
    if not key:return None
    query=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True) if k!='rkey']
    query.append(('rkey',key))
    return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),''))


def matching_generated_image(root,token,cache):
    """Exact outgoing QQ MD5 only; no filename/path supplied by the model."""
    match=_TOKEN.fullmatch(str(token or ''))
    if not match:return None
    root=Path(root).resolve()
    if not root.is_dir():return None
    target=match[1].lower()
    from PIL import Image
    for path in list(root.iterdir())[:1000]:
        try:
            resolved=path.resolve()
            if not resolved.is_relative_to(root) or resolved.suffix.lower() not in ('.png','.jpg','.jpeg','.gif','.webp'):continue
            stat=resolved.stat()
            if not resolved.is_file() or stat.st_size>20*1024*1024:continue
            signature=(stat.st_size,stat.st_mtime_ns)
            saved=cache.get(str(resolved))
            if saved is None or saved[:2]!=signature:
                with resolved.open('rb') as stream:digest=hashlib.file_digest(stream,'md5').hexdigest()
                saved=(*signature,digest);cache[str(resolved)]=saved
            if saved[2]==target:
                with Image.open(resolved) as image:
                    if image.width*image.height>25_000_000:return None
                    image.verify()
                return str(resolved)
        except (OSError,ValueError):continue
    return None


class ImageQuoteAdapter:
    def __init__(self,scope):
        self.scope=scope;self.patches=[];self.hash_cache={};self.omni=None

    def allowed(self,event):
        if event is None or not self.scope(event):return False
        plugins=getattr(event,'plugins_name',None)
        return plugins is None or 'astrbot_plugin_qq_persona_models' in plugins

    @staticmethod
    def quoted(event,component,own=False):
        from astrbot.api.message_components import Reply
        return any(isinstance(c,Reply) and any(i is component for i in (c.chain or [])) and (not own or str(c.sender_id)==str(event.get_self_id())) for c in event.get_messages())

    def patch(self,cls,name,build):
        if any(c is cls and n==name and getattr(c,n) is w for c,n,w,_,_ in self.patches):return
        original=getattr(cls,name);own=name in cls.__dict__
        wrapper=build(original);setattr(cls,name,wrapper)
        self.patches.append((cls,name,wrapper,original,own))

    def install(self,context):
        from astrbot.core.pipeline.preprocess_stage.stage import PreProcessStage
        def normalize(original):
            @functools.wraps(original)
            async def wrapped(stage,event,component):
                if not self.allowed(event) or not getattr(event,'bot',None):return await original(stage,event,component)
                url=str(getattr(component,'url',None) or '')
                quoted=self.quoted(event,component)
                if not replace_qq_rkey(url,'probe'):
                    try:return await original(stage,event,component)
                    except Exception:
                        if quoted:event.set_extra('qq_quote_image_unavailable',True)
                        raise
                old={k:getattr(component,k,None) for k in ('url','file','path')}
                if quoted and self.quoted(event,component,own=True) and self.omni is not None:
                    local=await asyncio.to_thread(matching_generated_image,Path(self.omni.data_dir)/'temp_images',old['file'],self.hash_cache)
                    if local:
                        component.url=component.file=component.path=local
                        await original(stage,event,component)
                        event.set_extra('qq_quote_image_recovered','local_generated_hash_match')
                        return
                try:return await original(stage,event,component)
                except Exception as first:
                    try:
                        keys=await asyncio.wait_for(event.bot.call_action('get_rkey',self_id=int(event.get_self_id())),timeout=8)
                        key=next(k['rkey'] for k in keys if int(k.get('type',0))==(20 if event.get_group_id() else 10))
                        component.url=replace_qq_rkey(url,key)
                        await original(stage,event,component)
                        event.set_extra('qq_quote_image_recovered','refreshed_qq_rkey')
                        return
                    except Exception:
                        for key,value in old.items():setattr(component,key,value)
                        if quoted:event.set_extra('qq_quote_image_unavailable',True)
                        raise first
            return wrapped
        self.patch(PreProcessStage,'_normalize_image_component',normalize)
        metadata=context.get_registered_star('astrbot_plugin_omnidraw')
        self.omni=getattr(metadata,'star_cls',None)
        if self.omni is None:return
        cls=type(self.omni)
        def strict_scope(original):
            @functools.wraps(original)
            async def wrapped(instance,event,*args,**kwargs):
                token=_STRICT.set(id(instance) if self.allowed(event) else None)
                try:return await original(instance,event,*args,**kwargs)
                finally:_STRICT.reset(token)
            return wrapped
        def strict_processing(original):
            @functools.wraps(original)
            async def wrapped(instance,raw_images,*args,**kwargs):
                refs=list(raw_images or [])
                result=await original(instance,refs,*args,**kwargs)
                if _STRICT.get()==id(instance) and len(result)!=len([r for r in refs if r]):
                    raise ValueError('参考图未完整读取，已停止本次改图；请重新发送或引用原图，不会退回无参考生图')
                return result
            return wrapped
        self.patch(cls,'_run_text2img_generation',strict_scope)
        self.patch(cls,'_run_selfie_generation',strict_scope)
        self.patch(cls,'_process_and_save_images',strict_processing)

    def restore(self):
        for cls,name,wrapper,original,own in reversed(self.patches):
            if getattr(cls,name) is wrapper:
                if own:setattr(cls,name,original)
                else:delattr(cls,name)
        self.patches=[];self.omni=None


def apply_quote_image_policy(event,request):
    if not event.get_extra('qq_quote_image_unavailable'):
        if event.get_extra('qq_quote_image_recovered'):
            request.system_prompt=(request.system_prompt or '')+'\n[本轮引用原图已恢复]\n本轮图片是用户实际引用的原图，已提供给视觉输入。以这张图为准理解主体与修改要求，不用此前任务的文字描述替换原图内容。\n'
        return
    source=getattr(request,'func_tool',None)
    if source is not None:
        result=copy(source)
        result.tools=[t for t in source.tools if t.name not in ('generate_image','generate_selfie')]
        request.func_tool=result
    request.system_prompt=(request.system_prompt or '')+'\n[本轮引用图片不可用]\n当前引用图片下载失败，无法确认其画面。不要用此前对话中的图片或描述冒充这张图，不调用绘图工具猜着改图。向用户准确说明本张图片读取失败，请其重新发送原图；不要把一次工具失败扩大为所有真人或写实图片都不支持。\n'
