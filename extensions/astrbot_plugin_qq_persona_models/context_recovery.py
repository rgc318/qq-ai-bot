"""Read existing persona-scoped history without changing conversations or sending."""
import json
import time


def plain_content(value):
    if isinstance(value,str):
        return value
    if isinstance(value,list):
        return '\n'.join(str(x.get('text','')) for x in value if isinstance(x,dict) and x.get('type') in ('text','input_text','output_text'))
    return ''


async def hydrate_history(context, router, event, persona):
    group=str(event.get_group_id())
    ctx=router.context(group)
    if ctx.last_ai or ctx.hydration_attempted:
        return False
    ctx.hydration_attempted=True
    conv=await read_persona_conversation(context,event,persona)
    if conv is None:return False
    age=time.time()-float(conv.updated_at)
    if age < -5 or age > float(router.settings.get('followup_window_seconds',1800)):
        return False
    history=json.loads(conv.history) if isinstance(conv.history,str) else conv.history
    rows=[{'role':row.get('role'),'text':plain_content(row.get('content'))[:1600]} for row in history[-48:] if isinstance(row,dict) and row.get('role') in ('user','assistant')]
    last=next((i for i in range(len(rows)-1,-1,-1) if rows[i]['role']=='assistant' and rows[i]['text']),None)
    if last is None:
        return False
    previous=next((rows[i]['text'] for i in range(last-1,-1,-1) if rows[i]['role']=='user'),'')
    router.note_ai(group,rows[last]['text'],request=previous)
    ctx.last_ai['time']-=max(0,age)
    ctx.messages.clear()
    ctx.messages.extend(rows[max(0,last-23):last+1])
    router.stats['history_recovered']+=1
    return True


async def read_persona_conversation(context,event,persona):
    manager=context.conversation_manager
    umo=event.unified_msg_origin
    decision=event.get_extra('user_policy_decision')
    cid=None
    policy=context.get_registered_star('astrbot_plugin_user_policy')
    isolation=getattr(getattr(policy,'star_cls',None),'memory_isolation',None)
    if isolation and decision:
        scope,_=isolation._scope(decision)
        entry=isolation.bindings.get('bindings',{}).get(scope,{})
        if decision.memory_isolation:
            cid=entry.get('personas',{}).get(persona or '__astrbot_default__')
            if not cid:return None
        else:
            cid=entry.get('shared_conversation_id')
    if not cid:
        cid=await manager.get_curr_conversation_id(umo)
    if not cid:
        return None
    conv=await manager.get_conversation(umo,cid)
    if conv is None or str(getattr(conv,'persona_id','') or '') != persona:
        return None
    return conv
