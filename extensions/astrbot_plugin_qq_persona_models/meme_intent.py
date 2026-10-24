"""Keep requests for existing reaction images out of paid image generation."""
import re

_MEME=re.compile(r'表情(?:包|图)?|贴图|\bsticker\b|\bmeme\b',re.I)
_SEND=re.compile(r'发|来|给|丢|贴|整|send',re.I)
_CREATE=re.compile(r'画|绘|生成|制作|设计|定制|重绘|改(?:图|成|一下)|做(?:一|个|张|套)|自拍|拍(?:一|个|张)')
_NEGATED_CREATE=re.compile(r'(?:不要|不用|别|无需)(?:重新|新)?(?:生成|画|绘制|制作)(?:新的|新图)?')
_EXPLANATION=re.compile(r'是什么意思|有什么区别|如何配置|怎么配置|为什么')

def wants_existing_meme(text):
    text=str(text or '').strip()
    if text.startswith('/') or not _MEME.search(text) or not _SEND.search(text) or _EXPLANATION.search(text):
        return False
    return not bool(_CREATE.search(_NEGATED_CREATE.sub('',text)))

def apply_existing_meme_policy(request,text):
    if not wants_existing_meme(text):
        return False
    request.system_prompt=(request.system_prompt or '')+'\n[本次现成表情请求]\n用户要从已配置的表情图库发送表情，不是要求创作新图片。按照上方表情分类协议选择一个贴切分类，输出对应 &&分类键&& 标记，可以只发标记或配一句简短文字。不要调用生图、自拍或视频工具，不声称正在制作新图。此前对话中的生图调用和报错只是历史，本轮图库发送不需要那些工具；不要照搬旧工具调用，也不要在未发生错误时声称本轮失败。\n'
    # Stock reactions require no tools. Old function-call traces can make some
    # models repeat a removed function despite the available tool schema.
    # Keep natural conversation, filtering traces only in this request's copy.
    request.func_tool=None
    contexts=getattr(request,'contexts',None)
    if isinstance(contexts,list):
        cleaned=[]
        for row in contexts:
            if not isinstance(row,dict):
                cleaned.append(row)
                continue
            if row.get('role') in ('tool','function'):
                continue
            if row.get('tool_calls') or row.get('function_call'):
                if not row.get('content'):
                    continue
                row={k:v for k,v in row.items() if k not in ('tool_calls','function_call')}
            cleaned.append(row)
        request.contexts=cleaned
    request.prompt=(request.prompt or '')+'\n\n[当前请求处理说明] 请直接从上述现有表情图库选择符合本轮情绪的表情，输出有效的 &&分类键&&。本轮无需工具调用；先前生图任务及其错误不代表本轮图库发送失败。'
    return True
