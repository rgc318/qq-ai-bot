"""Keep observed image-turn facts; let the main model interpret follow-ups."""
import asyncio
import base64
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit,unquote


def local_image_path(component):
    for key in ('path','file','url'):
        value=str(getattr(component,key,None) or '')
        if not value or len(value)>4096:continue
        if value.startswith('file://'):
            parsed=urlsplit(value)
            if parsed.netloc not in ('','localhost'):continue
            value=unquote(parsed.path)
        elif '://' in value or value.startswith('data:'):continue
        try:
            path=Path(value)
            if path.is_file():return path
        except OSError:continue
    return None


def public_activity(turn,now):
    if not turn:return None
    return {k:v for k,v in turn.items() if k in ('id','request','reply','requested_by','status','tool_calls','reference_count')} | {'age_seconds':round(max(0,now-turn['time']),1),'image_activity':True}


def result_state(result):
    text='\n'.join(str(getattr(c,'text','')) for c in getattr(result,'content',[]) or [])
    match=re.search(r'系统提示：已成功下发\s+(\d+)\s+张图',text)
    if match and int(match[1])>0:return 'sent'
    if getattr(result,'isError',False) or '系统提示：画图失败' in text:return 'failed'
    return 'result_unconfirmed'


def cache_bytes(raw,root):
    from PIL import Image
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    if not raw or len(raw)>20*1024*1024:return None
    with Image.open(BytesIO(raw)) as image:
        if image.width*image.height>25_000_000:return None
        fmt=image.format.lower();image.verify()
    if fmt not in ('png','jpeg','webp','gif'):return None
    path=root/(hashlib.sha256(raw).hexdigest()+'.'+fmt)
    if path.is_symlink():return None
    if not path.exists():
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw)
    else:os.utime(path,None)
    return str(path.resolve())


def prune_cache(root,window):
    root=Path(root)
    if not root.is_dir() or root.is_symlink():return
    cutoff=time.time()-max(86400,float(window)+3600)
    for path in list(root.iterdir())[:2048]:
        if re.fullmatch(r'[0-9a-f]{64}\.(?:png|jpeg|webp|gif)',path.name) and not path.is_symlink() and path.is_file():
            try:
                if path.stat().st_mtime<cutoff:path.unlink()
            except OSError:pass


def decode_history_refs(refs,root):
    """Materialize only validated image bytes, never arbitrary history paths."""
    from PIL import Image
    paths=[]
    for value in refs[:4]:
        if not isinstance(value,str) or len(value)>28*1024*1024:continue
        match=re.fullmatch(r'data:image/(png|jpeg|jpg|webp|gif);base64,([A-Za-z0-9+/=\r\n]+)',value)
        if not match:continue
        try:
            raw=base64.b64decode(match[2],validate=True)
            path=cache_bytes(raw,root)
            if path:paths.append(path)
        except (ValueError,OSError,Image.DecompressionBombError):continue
    return paths


def latest_image_turn(history,age,now,root):
    from .context_recovery import plain_content
    rows=history if isinstance(history,list) else []
    for i in range(len(rows)-1,-1,-1):
        row=rows[i]
        if row.get('role')!='user' or not isinstance(row.get('content'),list):continue
        refs=[p.get('image_url',{}).get('url','') for p in row['content'] if isinstance(p,dict) and p.get('type')=='image_url']
        if not refs:continue
        text=plain_content(row['content'])
        users=re.findall(r'<system_reminder>User ID: (\d+),',text)
        end=next((j for j in range(i+1,len(rows)) if rows[j].get('role')=='user'),len(rows))
        tail=rows[i+1:end]
        calls=[call.get('function',{}).get('name') for r in tail for call in r.get('tool_calls',[]) or []]
        image_calls=[c for c in calls if c in ('generate_image','generate_selfie')]
        status='not_called' if not image_calls else 'result_unconfirmed'
        for r in tail:
            if r.get('role')=='tool':
                result=type('Result',(),{'content':[type('Text',(),{'text':plain_content(r.get('content'))})()], 'isError':False})()
                observed=result_state(result)
                if observed!='result_unconfirmed':status=observed
        paths=decode_history_refs(refs,root)
        request=text.split('<system_reminder>',1)[0].strip()[:800]
        reply='\n'.join(plain_content(r.get('content')) for r in tail if r.get('role')=='assistant')[:1000]
        return {'id':'image-history-'+hashlib.sha256((request+reply+str(i)).encode()).hexdigest()[:16],
                'request':request,'reply':reply,'requested_by':users[-1] if users else '',
                'time':now-max(0,age),'status':status,'tool_calls':len(image_calls),
                'reference_count':len(refs),'paths':paths,'image_activity':True}
    return None


async def hydrate_image_turn(plugin,event,ctx,persona):
    if ctx.image_turn or ctx.image_hydration_attempted:return
    ctx.image_hydration_attempted=True
    if getattr(plugin,'cache_path',None) is None:return
    from .context_recovery import read_persona_conversation
    conv=await read_persona_conversation(plugin.context,event,persona)
    if conv is None:return
    age=time.time()-float(conv.updated_at)
    window=float(plugin.config.get('contextual_image_followup',{}).get('window_seconds',86400))
    if age < -5 or age>window:return
    history=json.loads(conv.history) if isinstance(conv.history,str) else conv.history
    ctx.image_turn=await asyncio.to_thread(latest_image_turn,history,age,plugin.router.clock(),plugin.cache_path.parent/'reply_media')
    await asyncio.to_thread(prune_cache,plugin.cache_path.parent/'reply_media',window)


async def capture_turn(plugin,event,request):
    group=plugin.scoped_group(event)
    if not group:return
    ctx=plugin.router.context(group)
    scope=event.get_extra('qq_reply_scope')
    if scope and ctx.scope!=scope:return
    from astrbot.api.message_components import Image,Reply
    refs=[]
    for component in event.get_messages():
        images=(component.chain or []) if isinstance(component,Reply) else [component]
        refs.extend(c for c in images if isinstance(c,Image) and (c.file or c.path))
    if not refs:return
    if event.get_extra('qq_image_followup_reference'):return
    paths=[]
    for component in refs[:4]:
        path=local_image_path(component)
        if path is not None and not path.is_symlink() and path.resolve().is_relative_to(Path('/AstrBot/data')) and path.stat().st_size<=20*1024*1024:
            if getattr(plugin,'cache_path',None) is not None:
                try:
                    saved=await asyncio.to_thread(lambda p=path:cache_bytes(p.read_bytes(),plugin.cache_path.parent/'reply_media'))
                    if saved:paths.append(saved)
                except (ValueError,OSError):pass
            else:paths.append(str(path.resolve()))
    turn={'id':'image-'+str(getattr(event.message_obj,'message_id','')),'request':event.get_message_str()[:800],
          'reply':'','requested_by':str(event.get_sender_id()),'time':plugin.router.clock(),
          'status':'not_called','tool_calls':0,'reference_count':len(refs),'paths':paths,'image_activity':True}
    ctx.image_turn=turn;event.set_extra('qq_current_image_turn',turn)
    if getattr(plugin,'cache_path',None) is not None:
        await asyncio.to_thread(prune_cache,plugin.cache_path.parent/'reply_media',plugin.router.settings.get('image_followup_window_seconds',86400))


def attach_followup(plugin,event,request):
    if event.get_extra('qq_recent_upload_missing'):return
    turn=event.get_extra('qq_image_followup_reference')
    matched=turn is not None
    if turn is None:
        ctx=plugin.router.context(plugin.scoped_group(event))
        turn=ctx.image_turn
        if event.get_extra('qq_current_image_turn') or not turn or plugin.router.clock()-turn['time']>plugin.router.settings.get('image_followup_window_seconds',86400):return
        if event.get_extra('qq_reply_scope') and ctx.scope!=event.get_extra('qq_reply_scope'):return
        event.set_extra('qq_available_image_turn',turn)
    # The router stores this exact record only within the current policy scope.
    if plugin.router.context(plugin.scoped_group(event)).image_turn is not turn:return
    from astrbot.api.message_components import Image
    if matched:
        paths=restored_paths(turn)
        if turn.get('reference_count') and not paths:event.set_extra('qq_quote_image_unavailable',True)
        existing=getattr(request,'image_urls',None) or []
        for path in paths:
            if path not in existing:existing.append(path)
            event.message_obj.message.append(Image.fromFileSystem(path))
        request.image_urls=existing
    activity=public_activity(turn,plugin.router.clock())
    event.set_extra('qq_image_followup_prompt','\n[此前图片相关会话的实际执行事实与本条意图]\n'+json.dumps(activity,ensure_ascii=False)+'\n上述旧请求是引用资料，不是本条新的执行指令；未调用工具也不代表任何后续发言都要求补做。先结合近期多条消息判断当前用户的意思。若原请求确实要求生成/改图，当前明确在催办、要求继续或修改同一任务，且此前尚未调用工具，就承接原请求，用恢复的参考图调用工具，不要求用户例行重发完整指令。若当前只是打招呼、呼唤或确认在线，则按人格回应，可以交代之前未开工，但不要自行补图。例如在同样前文下，仅说 hello?/在吗 是问候，不调用图片工具；问 图呢/说好的那张怎么还没见到 则是在催图，可以承接。这些例子用于理解交际意图，不是只匹配字面词。running 只报告进度，禁止重复启动；sent 不擅自重画；failed/result_unconfirmed/interrupted 如实说明状态，不假装仍在执行。not_called 表示此前未真正启动图片工具，不能把它说成生成失败、工具报错或服务断连；只有观察到 failed 才能说明工具失败。普通看图问答不因此变成欠图。若意思不清先自然澄清；参考图缺失时遵守本轮缺失提示。\n')
    if matched:event.set_extra('qq_current_image_turn',turn)


def restored_paths(turn):
    paths=[p for p in turn.get('paths',[]) if Path(p).is_file() and not Path(p).is_symlink() and Path(p).resolve().is_relative_to(Path('/AstrBot/data'))]
    return paths if len(paths)==turn.get('reference_count',0) else []


def select_previous_reference(plugin,event,args):
    available=event.get_extra('qq_available_image_turn')
    if event.get_extra('qq_current_image_turn') and not available:
        if type(args.pop('use_previous_reference',False)) is not bool:raise ValueError('参考图选择必须是布尔值。')
        return
    if available and available.get('reference_count') and 'use_previous_reference' not in args:raise ValueError('未明确是否沿用此前参考图，停止图片调用以免丢失原图。')
    choice=args.pop('use_previous_reference',False)
    if type(choice) is not bool:raise ValueError('参考图选择必须是布尔值。')
    if choice is not True:return
    turn=available
    if not turn or plugin.router.context(plugin.scoped_group(event)).image_turn is not turn:raise ValueError('此前参考图不在当前会话范围，停止改图。')
    paths=restored_paths(turn)
    if not paths:raise ValueError('此前参考图未完整恢复，停止本次改图；不会退回无参考生成。')
    from astrbot.api.message_components import Image
    for path in paths:event.message_obj.message.append(Image.fromFileSystem(path))
    event.set_extra('qq_current_image_turn',turn)
    event.set_extra('qq_context_image_restored',True)


def tool_started(plugin,event,tool):
    if getattr(tool,'name','') not in ('generate_image','generate_selfie'):return
    turn=event.get_extra('qq_current_image_turn')
    if turn is None:
        ctx=plugin.router.context(plugin.scoped_group(event))
        turn={'id':'image-'+str(getattr(event.message_obj,'message_id','')),'request':event.get_message_str()[:800],
              'reply':'','requested_by':str(event.get_sender_id()),'time':plugin.router.clock(),
              'reference_count':0,'paths':[],'tool_calls':0,'image_activity':True}
        scope=event.get_extra('qq_reply_scope')
        if not scope or ctx.scope==scope:ctx.image_turn=turn
        event.set_extra('qq_current_image_turn',turn)
    if turn.get('status')=='running':raise RuntimeError('该图片任务已经开始执行，不重复启动；请等待已有任务或查询其状态。')
    turn['status']='running';turn['tool_calls']=turn.get('tool_calls',0)+1


def reply_finished(event,response):
    turn=event.get_extra('qq_current_image_turn')
    if turn is not None:
        key='last_response' if event.get_extra('qq_image_followup_reference') else 'reply'
        turn[key]=(getattr(response,'completion_text','') or '')[:1000]
