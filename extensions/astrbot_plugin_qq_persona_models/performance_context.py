"""Bound request history and old media without mutating the source records."""
from copy import deepcopy
import re

_IMAGE_REFERENCE=re.compile(r'这|那|上图|上一|上面|前面|刚才|之前|原图|参考图|图片|照片|漫画|图里|图中|改图|换成|改成|重画|它|她|他')
_IMAGE_TYPES={'image_url','input_image','image'}

def plan_history(contexts,text,settings):
    source=contexts if isinstance(contexts,list) else []
    turns=max(1,int(settings.get('history_turns',12)))
    image_turns=max(0,int(settings.get('history_image_turns',2)))
    user_indexes=[i for i,row in enumerate(source) if isinstance(row,dict) and row.get('role')=='user']
    start=user_indexes[-turns] if len(user_indexes)>turns else 0
    history=deepcopy(source[start:])
    remaining_users=[i for i,row in enumerate(history) if isinstance(row,dict) and row.get('role')=='user']
    image_start=remaining_users[-image_turns] if image_turns and len(remaining_users)>=image_turns else 0
    keep_images=bool(image_turns and _IMAGE_REFERENCE.search(str(text or '')))
    removed_images=0
    kept_images=0
    for i,row in enumerate(history):
        if not isinstance(row,dict) or not isinstance(row.get('content'),list):
            continue
        parts=[]
        for part in row['content']:
            if isinstance(part,dict) and part.get('type') in _IMAGE_TYPES:
                if keep_images and i>=image_start:
                    parts.append(part)
                    kept_images+=1
                else:
                    parts.append({'type':'text','text':'[此前附带的图片本轮未重传；需要查看时请引用或重发原图。]'})
                    removed_images+=1
            else:
                parts.append(part)
        row['content']=parts
    return history,{'before_messages':len(source),'after_messages':len(history),'dropped_messages':start,'removed_history_images':removed_images,'kept_history_images':kept_images,'changed':history!=source}
