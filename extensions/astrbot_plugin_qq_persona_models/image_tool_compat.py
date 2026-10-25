"""Keep plugin-only image parameters out of ordinary chat tool requests."""
from copy import copy,deepcopy
from functools import wraps

IMAGE_TOOLS={'generate_image','generate_selfie'}
IMAGE_GUARD_ERROR='_qq_image_guard_error'


def guard_image_handler(handler):
    """Return validation failures from the executor, not a swallowed event hook."""
    if getattr(handler,'_qq_image_guarded',False):return handler
    @wraps(handler)
    def guarded(*args,**kwargs):
        error=kwargs.pop(IMAGE_GUARD_ERROR,None)
        if error:
            async def rejected():
                return '系统提示：画图未执行（'+str(error)+'）。本次未调用图片模型，也未发送图片。请修正参数或澄清后再决定是否调用；不要声称已完成。'
            return rejected()
        return handler(*args,**kwargs)
    guarded._qq_image_guarded=True
    return guarded


def guarded_image_tool_copy(tool,seen=()):
    """Clone the native permission proxy chain; never replace its call() path.

    Core keeps _PermissionGuardedTool.handler=None and calls _wrapped.handler
    after authorization. Guarding only the outer handler misses that path;
    assigning an outer handler would bypass the native permission check.
    """
    if id(tool) in seen or len(seen)>=32:raise ValueError('图片工具包装链无效')
    cloned=copy(tool)
    wrapped=getattr(tool,'_wrapped',None)
    if wrapped is not None:cloned._wrapped=guarded_image_tool_copy(wrapped,(*seen,id(tool)))
    handler=getattr(tool,'handler',None)
    if callable(handler):cloned.handler=guard_image_handler(handler)
    return cloned


class ImageExecutionGuard:
    """Guard the tool actually passed to native hooks, including unwrapped ones."""
    def __init__(self):self.patches=[]

    def install(self,tool):
        seen=set()
        while tool is not None and id(tool) not in seen and len(seen)<32:
            seen.add(id(tool))
            handler=getattr(tool,'handler',None)
            if callable(handler) and not getattr(handler,'_qq_image_guarded',False):
                wrapper=guard_image_handler(handler)
                tool.handler=wrapper
                self.patches.append((tool,handler,wrapper))
            tool=getattr(tool,'_wrapped',None)

    def restore(self):
        for tool,original,wrapper in reversed(self.patches):
            if tool.handler is wrapper:tool.handler=original
        self.patches=[]

def prepare_chat_image_tools(request,model_notice=False,contextual_reference=False,indexed_references=False):
    source=getattr(request,'func_tool',None)
    if source is None:
        return
    result=copy(source)
    result.tools=[]
    for tool in source.tools:
        if tool.name not in IMAGE_TOOLS:
            result.tools.append(tool)
            continue
        cloned=guarded_image_tool_copy(tool)
        cloned.parameters=deepcopy(tool.parameters)
        properties=cloned.parameters.get('properties',{})
        for key in ('return_result','refs'):
            properties.pop(key,None)
        if 'required' in cloned.parameters:
            cloned.parameters['required']=[key for key in cloned.parameters['required'] if key not in ('return_result','refs')]
        if model_notice:
            properties['pending_message']={'type':'string','description':'开始生图前发给用户的一句自然回应。结合当前人格、对话和本次绘图/改图要求，自行创作一句简短对白；不是绘图提示词。只说明准备做什么，不声称已经完成，不承诺耗时，不解释工具或模型，勿套用固定模板。最多80个中文字符。'}
            required=cloned.parameters.setdefault('required',[])
            if 'pending_message' not in required:
                required.append('pending_message')
        if contextual_reference:
            properties['use_previous_reference']={'type':'boolean','description':'本轮没有新附件，但系统提供了此前图片会话事实。若当前是在承接/修改那张旧图，填true，程序会从同一会话恢复原图给绘图模型；独立创作新图填false。只因存在旧图不能自动沿用。'}
            required=cloned.parameters.setdefault('required',[])
            if 'use_previous_reference' not in required:required.append('use_previous_reference')
        if indexed_references:
            properties['reference_ids']={'type':'array','items':{'type':'string'},'maxItems':4,'description':'必须明确选择：改图填本轮附件目录或read_group_message给出的完整图片ID集合；独立新图填[]。不填写文件路径。多图用途写在绘图描述中。'}
            properties.pop('use_previous_reference',None)
            cloned.parameters['required']=[k for k in cloned.parameters.get('required',[]) if k!='use_previous_reference']
            if 'reference_ids' not in cloned.parameters['required']:cloned.parameters['required'].append('reference_ids')
        cloned.description=str(tool.description).split('Args:',1)[0].strip()+' 当前为普通聊天：生成后自动发送图片；参考图由程序从当前消息和引用的图片中自动获取，不填写本地文件路径或插件内部参数。'
        if indexed_references:
            cloned.description=str(tool.description).split('Args:',1)[0].strip()+' 生成后自动发送图片。用reference_ids明确选择参考集合，独立新图填[]；先确认所选图的内容与来源，不填写文件路径。'
        if model_notice:
            cloned.description+=' 同一次工具调用中填写 pending_message，程序会在开始生图前先发送这句人格对白，无需另外调用发送消息工具。'
        result.tools.append(cloned)
    request.func_tool=result

def normalize_chat_image_arguments(tool_name,args):
    if tool_name not in IMAGE_TOOLS or not isinstance(args,dict):
        return
    args.pop('return_result',None)
    args.pop('refs',None)
