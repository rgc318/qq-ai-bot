"""Authenticated, read-only QQ quote diagnostics. Never send messages."""
import asyncio
from urllib.parse import urlsplit,parse_qs,urlencode,urlunsplit


async def inspect_quoted_image(plugin,payload):
    import aiohttp
    from PIL import Image
    from io import BytesIO
    group=str(payload.get('group_id','347440128'))
    if group not in plugin.router.settings['allowed_groups']:raise ValueError('Group not allowed')
    platform=next(p for p in plugin.context.platform_manager.get_insts() if p.meta().id=='qq-snowluma')
    bot=platform.bot
    message=await bot.call_action('get_msg',message_id=int(payload.get('message_id',-638647607)),self_id=2354912009)
    if str(message.get('group_id'))!=group:raise ValueError('Message is not in allowed group')
    quote=next(s['data']['id'] for s in message.get('message',[]) if s['type']=='reply')
    original=await bot.call_action('get_msg',message_id=int(quote),self_id=2354912009)
    if str(original.get('group_id'))!=group:raise ValueError('Quote is not in allowed group')
    images=[s['data'] for s in original.get('message',[]) if s['type']=='image']
    omni=plugin.context.get_registered_star('astrbot_plugin_omnidraw').star_cls
    report={'message_id':message['message_id'],'quote_id':quote,'quote_sender':original.get('user_id'),'image_count':len(images),'images':[],'qq_messages_sent':0,'model_calls':0}
    if payload.get('verify_recovery'):
        from aiocqhttp import Event
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        from astrbot.core.pipeline.preprocess_stage.stage import PreProcessStage
        from astrbot.api.message_components import Reply,Image as ComponentImage
        from pathlib import Path
        import hashlib,time
        message['post_type']='message'
        message['self_id']=2354912009
        abm=await platform._convert_handle_message_event(Event.from_payload(message))
        event=AiocqhttpMessageEvent(abm.message_str,abm,platform.meta(),group,bot)
        stage=object.__new__(PreProcessStage)
        quoted=[i for c in event.get_messages() if isinstance(c,Reply) for i in c.chain or [] if isinstance(i,ComponentImage)]
        tokens=[str(i.file) for i in quoted]
        started=time.monotonic()
        for component in quoted:await stage._normalize_image_component(event,component)
        paths=[str(i.file) for i in quoted]
        refs=omni._get_event_images(event)
        safe=await omni._process_and_save_images(refs)
        checks={'reference_recovered':bool(paths) and all(Path(p).is_file() for p in paths),'exact_original_md5_match':all(hashlib.md5(Path(p).read_bytes()).hexdigest()==t.split('.')[0].lower() for p,t in zip(paths,tokens)),'drawing_tool_receives_same_original':safe==paths}
        report.update(checks=checks,passed=all(checks.values()),recovery=event.get_extra('qq_quote_image_recovered'),seconds=round(time.monotonic()-started,4),recovered_files=paths)
        if payload.get('call_model'):
            provider=plugin.context.get_provider_by_id(plugin.config['bindings']['大肥鱼'])
            response=await provider.text_chat(prompt='只根据这张图片，用一句话描述画面主体及其头顶的物体。不要参考其他对话。',image_urls=paths,contexts=[],func_tool=None)
            report.update(model_calls=1,vision_model=provider.get_model(),vision_description=response.completion_text)
        return report
    async with aiohttp.ClientSession() as session:
        for item in images[:3]:
            record={'segment_fields':list(item),'attempts':[]}
            record['file_shape']={'length':len(str(item.get('file',''))),'kind':str(item.get('file','')).split('://',1)[0] if '://' in str(item.get('file','')) else 'identifier'}
            refs=[('get_msg',item.get('url',''))]
            try:
                refreshed=await asyncio.wait_for(bot.call_action('get_image',file=item.get('file') or item.get('file_id'),self_id=2354912009),timeout=8)
                record['get_image_shape']={'fields':list(refreshed),'file_length':len(str(refreshed.get('file',''))),'file_kind':str(refreshed.get('file','')).split('://',1)[0] if '://' in str(refreshed.get('file','')) else 'identifier'}
                refs.append(('get_image',refreshed.get('url','')))
            except Exception as exc:record['refresh_error']=type(exc).__name__
            try:
                rkeys=await asyncio.wait_for(bot.call_action('get_rkey',self_id=2354912009),timeout=8)
                split=urlsplit(item.get('url',''));query=parse_qs(split.query)
                if split.hostname=='multimedia.nt.qq.com.cn':
                    for key in rkeys:
                        if int(key.get('type',0)) not in (10,20):continue
                        record.setdefault('rkey_matches',{})[str(key['type'])]=key.get('rkey','').removeprefix('&rkey=').removeprefix('rkey=') in query.get('rkey',[])
                        updated={k:v[-1] for k,v in query.items()};updated['rkey']=key.get('rkey','').removeprefix('&rkey=')
                        refs.append(('rkey_'+str(key['type']),urlunsplit((split.scheme,split.netloc,split.path,urlencode(updated),''))))
            except Exception as exc:record['rkey_error']=type(exc).__name__
            from pathlib import Path
            import re,hashlib
            token=str(item.get('file',''))
            match=re.fullmatch(r'([a-fA-F0-9]{32})\.[a-zA-Z0-9]{2,5}',token)
            if match:
                target=match[1].lower()
                def find_local():
                    root=Path(omni.data_dir)
                    found=[];count=0
                    for path in root.rglob('*'):
                        if not path.is_file() or path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.gif'):continue
                        if path.stat().st_size>20*1024*1024:continue
                        count+=1
                        if hashlib.md5(path.read_bytes()).hexdigest()==target:found.append(str(path))
                    return {'scanned_images':count,'matching_local_files':found}
                record['local_matches']=await asyncio.to_thread(find_local)
            for source,url in refs:
                split=urlsplit(url);query=parse_qs(split.query)
                attempt={'source':source,'host':split.hostname,'query_names':list(query),'rkey_present':bool(query.get('rkey')),'appid':query.get('appid')}
                try:
                    data,mime,_=await omni._download_remote_image(session,url,{'User-Agent':'Mozilla/5.0'})
                    with Image.open(BytesIO(data)) as image:attempt.update(success=True,bytes=len(data),format=image.format,size=list(image.size))
                except Exception as exc:attempt.update(success=False,error=str(exc)[:150])
                record['attempts'].append(attempt)
            report['images'].append(record)
    return report
