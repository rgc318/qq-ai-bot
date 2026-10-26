"""Validate a model's declared image task; never infer semantics or choose pixels."""
import time

OPERATIONS={'independent','edit','reference'}


class ImageTaskError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code


def task_schema():
    return {'type':'object','properties':{
        'operation':{'type':'string','enum':sorted(OPERATIONS),'description':'independent是用户要独立新图；edit是修改已有图片；reference是利用已有图片创作。不能因暂时没找到图，把改图降级为independent。'},
        'reason':{'type':'string','maxLength':240,'description':'结合当前请求和消息来源说明任务判断与选图理由；目录不等于已看过像素。'},
        'independent_quote':{'type':'string','maxLength':160,'description':'仅独立新图填写：从本条用户请求逐字引用支持独立创作的原话；其他类型填空。'}},
        'required':['operation','reason','independent_quote'],'additionalProperties':False}


def notes_schema():
    return {'type':'array','maxItems':4,'items':{'type':'object','properties':{
        'image_id':{'type':'string'},'purpose':{'type':'string','maxLength':240}},'required':['image_id','purpose'],'additionalProperties':False},
        'description':'与reference_ids一一对应，逐张说明保留、参考或替换哪些内容。独立新图填写[]；参考图不可仅因较旧或来自其他成员就忽略。'}


def validate_task(args,current_text,state):
    """All checks precede mutation/freezing. A declared reference intent is sticky."""
    started=time.perf_counter()
    plan=args.get('image_task')
    if not isinstance(plan,dict):raise ImageTaskError('missing_task','参数校验失败，图片工具存在但尚未执行，也没有检测图片接口是否可用。请按当前工具schema补齐image_task={"operation":"edit或reference或independent","reason":"结合来源判断的依据","independent_quote":"独立新图逐字引用本条原话，否则空串"}、reference_ids和逐图reference_notes；真实图片ID来自本轮目录或历史读取，不能编造或为通过校验直接填空参考。')
    operation=plan.get('operation')
    if operation not in OPERATIONS:raise ImageTaskError('invalid_operation','image_task.operation必须为independent、edit或reference')
    if operation in ('edit','reference'):state['requires_reference']=True
    if state.get('requires_reference') and operation=='independent':raise ImageTaskError('intent_downgrade','本轮已声明沿用图片，不能在纠错时改为无参考新图；请找回素材或向用户澄清。')
    reason=plan.get('reason')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>240:raise ImageTaskError('missing_reason','请用简短理由说明任务类型及资料选择。')
    choice=args.get('reference_ids')
    if not isinstance(choice,list) or len(choice)>4 or any(not isinstance(i,str) or not i for i in choice) or len(set(choice))!=len(choice):raise ImageTaskError('invalid_reference_set','reference_ids必须是最多4个互不重复的有效图片ID；不可省略。')
    if operation in ('edit','reference') and not choice:raise ImageTaskError('empty_edit','修改或参考已有图片必须提供参考图；先用历史/看图工具找回来源，找不到就澄清，不调用无参考生成。')
    if operation=='independent':
        if choice:raise ImageTaskError('independent_with_refs','独立新图不能同时声明参考图片；如果要利用图片内容，应选择edit或reference。')
        quote=plan.get('independent_quote')
        normalize=lambda s:' '.join(str(s or '').split())
        if not isinstance(quote,str) or not quote.strip() or len(quote)>160 or normalize(quote) not in normalize(current_text):raise ImageTaskError('missing_independence_evidence','独立新图需在independent_quote逐字引用本条用户请求支持独立创作的原话；有指代或不确定时先查来源或澄清。')
    notes=args.get('reference_notes')
    if not isinstance(notes,list) or len(notes)!=len(choice):raise ImageTaskError('missing_reference_roles','reference_notes必须与参考集合一一对应；独立新图填[]。')
    seen=set()
    for item in notes:
        if not isinstance(item,dict) or not isinstance(item.get('image_id'),str) or item['image_id'] not in choice or item['image_id'] in seen or not isinstance(item.get('purpose'),str) or not item['purpose'].strip() or len(item['purpose'])>240:raise ImageTaskError('invalid_reference_role','每张参考图都需一个不重复的image_id及简短用途，不能漏选或重复说明。')
        seen.add(item['image_id'])
    state['operation']=operation
    return {'operation':operation,'reference_count':len(choice),'validation_ms':round((time.perf_counter()-started)*1000,3)}


def consume_task(args):
    args.pop('image_task',None)


def complete_task(state):
    """A delivered task ends its repair lock; another requested task is distinct."""
    state.clear()


def translate_reference_roles(args,choice):
    """Builtin and CA share the same purpose contract; IDs remain local helpers."""
    notes=args.pop('reference_notes',[])
    purposes={item['image_id']:item['purpose'] for item in notes}
    if choice and purposes:
        import json
        key='action' if 'action' in args and 'prompt' not in args else 'prompt'
        args[key]=str(args.get(key,'') or '')+'\n参考图用途（实际附图顺序）：'+json.dumps([{'reference_number':i,'purpose':purposes[source]} for i,source in enumerate(choice,1)],ensure_ascii=False)
