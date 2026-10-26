"""Normalize obsolete image protocol in a request copy; retain task facts/media."""
from copy import deepcopy
import json

IMAGE_TOOLS={'generate_image','generate_selfie'}
REQUIRED={'image_task','reference_ids','reference_notes'}


def normalize_image_history(contexts):
    source=contexts if isinstance(contexts,list) else []
    obsolete={};replacements={}
    for index,row in enumerate(source):
        if not isinstance(row,dict) or row.get('role')!='assistant':continue
        keep=[];notes=[]
        for call in row.get('tool_calls') or []:
            fn=call.get('function') or {}
            if fn.get('name') not in IMAGE_TOOLS:keep.append(call);continue
            try:args=json.loads(fn.get('arguments') or '{}')
            except (ValueError,TypeError):args={}
            if isinstance(args,dict) and REQUIRED.issubset(args) and not any(k.startswith('_qq_') for k in args):keep.append(call);continue
            obsolete[call.get('id')]=index
            text=(args.get('prompt') or args.get('action')) if isinstance(args,dict) else ''
            note='[历史图片任务，仅作资料；旧接口参数不适用于本轮，请按当前工具定义调用]\n'+str(text or '原参数记录不完整')
            if isinstance(args,dict):
                for key,label in [('count','当时请求张数'),('aspect_ratio','当时比例'),('pending_message','当时开工对白')]:
                    if key in args:note+='\n'+label+'：'+str(args[key])
            notes.append(note)
        if notes:
            changed=deepcopy(row);content=changed.get('content')
            note='\n'.join(notes)
            changed['content']=content+[{'type':'text','text':note}] if isinstance(content,list) else str(content or '')+'\n'+note
            if keep:changed['tool_calls']=deepcopy(keep)
            else:changed.pop('tool_calls',None)
            replacements[index]=changed
    results=0;removed=set()
    for index,row in enumerate(source):
        if isinstance(row,dict) and row.get('role')=='tool' and row.get('tool_call_id') in obsolete:
            prefix='[历史图片执行结果，只反映当时的执行情况，不代表本轮工具或图片服务状态]\n'
            owner=replacements[obsolete[row['tool_call_id']]];content=row.get('content')
            # Attach facts to the original assistant message. In a mixed tool
            # turn, remaining tool results must stay adjacent to their calls.
            parts=owner['content'] if isinstance(owner['content'],list) else [{'type':'text','text':owner['content']}]
            parts+=[{'type':'text','text':prefix}]+deepcopy(content) if isinstance(content,list) else [{'type':'text','text':prefix+str(content or '')}]
            owner['content']=parts;removed.add(index);results+=1
    out=[replacements.get(index,row) for index,row in enumerate(source) if index not in removed]
    return out,{'legacy_image_calls':len(obsolete),'legacy_image_results':results}
