"""Keep plugin-only image parameters out of ordinary chat tool requests."""
from copy import copy,deepcopy

IMAGE_TOOLS={'generate_image','generate_selfie'}

def prepare_chat_image_tools(request,model_notice=False):
    source=getattr(request,'func_tool',None)
    if source is None:
        return
    result=copy(source)
    result.tools=[]
    for tool in source.tools:
        if tool.name not in IMAGE_TOOLS:
            result.tools.append(tool)
            continue
        cloned=copy(tool)
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
        cloned.description=str(tool.description).split('Args:',1)[0].strip()+' 当前为普通聊天：生成后自动发送图片；参考图由程序从当前消息和引用的图片中自动获取，不填写本地文件路径或插件内部参数。'
        if model_notice:
            cloned.description+=' 同一次工具调用中填写 pending_message，程序会在开始生图前先发送这句人格对白，无需另外调用发送消息工具。'
        result.tools.append(cloned)
    request.func_tool=result

def normalize_chat_image_arguments(tool_name,args):
    if tool_name not in IMAGE_TOOLS or not isinstance(args,dict):
        return
    args.pop('return_result',None)
    args.pop('refs',None)
