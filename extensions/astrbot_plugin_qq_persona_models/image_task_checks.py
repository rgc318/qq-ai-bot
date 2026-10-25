"""Synthetic contract checks. No model, network, image generation or sends."""
from copy import deepcopy
from types import SimpleNamespace
from .image_task_contract import validate_task,consume_task,ImageTaskError,translate_reference_roles,complete_task
from .image_response_adapter import defer_notice


async def verify_image_tasks():
    checks={}
    edit={'image_task':{'operation':'edit','reason':'修改已有资料','independent_quote':''},'reference_ids':['A','B'],'reference_notes':[{'image_id':'A','purpose':'角色原设定'},{'image_id':'B','purpose':'另一成员提供的物件'}],'prompt':'fixture'}
    new={'image_task':{'operation':'independent','reason':'用户明确要独立画新图','independent_quote':'另画一张风景'},'reference_ids':[],'reference_notes':[],'prompt':'fixture'}
    def accepts(args,text='把它改成毛绒玩偶',state=None):
        try:validate_task(args,text,state if state is not None else {});return True
        except ImageTaskError:return False
    checks['edit_with_multiple_roles_accepted']=accepts(edit)
    checks['independent_with_current_evidence_accepted']=accepts(new,'忽略旧图，另画一张风景')
    empty=deepcopy(edit);empty['reference_ids']=[];empty['reference_notes']=[]
    checks['empty_edit_rejected']=not accepts(empty)
    reference=deepcopy(empty);reference['image_task']['operation']='reference'
    checks['empty_reference_generation_rejected']=not accepts(reference)
    missing=deepcopy(edit);missing.pop('image_task')
    checks['missing_declaration_rejected']=not accepts(missing)
    missing=deepcopy(edit);missing.pop('reference_ids')
    checks['missing_reference_set_rejected']=not accepts(missing)
    missing=deepcopy(edit);missing.pop('reference_notes')
    checks['missing_roles_rejected']=not accepts(missing)
    wrong=deepcopy(edit);wrong['reference_notes'][1]['image_id']='C'
    checks['roles_must_match_selected_set']=not accepts(wrong)
    wrong=deepcopy(edit);wrong['reference_ids']=['A','A']
    checks['duplicate_reference_id_rejected']=not accepts(wrong)
    checks['fabricated_independent_evidence_rejected']=not accepts(new,'把它改成毛绒玩偶')
    wrong=deepcopy(new);wrong['reference_ids']=['A'];wrong['reference_notes']=[{'image_id':'A','purpose':'fixture'}]
    checks['independent_with_reference_contradiction_rejected']=not accepts(wrong,'另画一张风景')
    state={};accepts(empty,state=state)
    checks['declared_edit_cannot_downgrade_on_repair']=not accepts(new,'另画一张风景',state)
    checks['new_request_has_fresh_intent_state']=accepts(new,'另画一张风景',{})
    completed={};accepts(edit,state=completed);complete_task(completed)
    checks['delivered_task_allows_next_independent_task']=accepts(new,'先修改角色，再另画一张风景',completed)
    args=deepcopy(edit);validate_task(args,'修改',{});consume_task(args);translate_reference_roles(args,args['reference_ids'])
    checks['task_and_role_helpers_consumed']='image_task' not in args and 'reference_notes' not in args and 'reference_number' in args['prompt']
    extras={'qq_image_task_contract_enabled':True,'qq_image_notice_defer_enabled':True}
    event=SimpleNamespace(get_extra=lambda k:extras.get(k),set_extra=lambda k,v:extras.__setitem__(k,v))
    response=SimpleNamespace(is_chunk=False,result_chain=None,tools_call_name=['generate_image'],tools_call_args=[{}],completion_text='我来保留造型，把材质改成绒布。')
    checks['same_response_notice_reused']=defer_notice(event,response) and response.tools_call_args[0]['pending_message'].startswith('我来保留') and not response.completion_text
    response=SimpleNamespace(is_chunk=False,result_chain=None,tools_call_name=['generate_image'],tools_call_args=[{'pending_message':'模型已经写好的对白'}],completion_text='不能先发出的另一句承诺')
    defer_notice(event,response);checks['explicit_model_notice_preserved']=response.tools_call_args[0]['pending_message']=='模型已经写好的对白' and not response.completion_text
    response=SimpleNamespace(is_chunk=False,result_chain=None,tools_call_name=['search','generate_image'],tools_call_args=[{},{}],completion_text='还有其他问题的回答')
    checks['mixed_tool_response_unchanged']=not defer_notice(event,response) and bool(response.completion_text)
    response=SimpleNamespace(is_chunk=True,result_chain=None,tools_call_name=['generate_image'],tools_call_args=[{}],completion_text='stream chunk')
    checks['stream_chunk_unchanged']=not defer_notice(event,response) and response.completion_text=='stream chunk'
    response=SimpleNamespace(is_chunk=False,result_chain=None,tools_call_name=[],tools_call_args=[],completion_text='普通聊天')
    checks['ordinary_reply_unchanged']=not defer_notice(event,response) and response.completion_text=='普通聊天'
    Plain=type('Plain',(),{})
    response=SimpleNamespace(is_chunk=False,result_chain=SimpleNamespace(chain=[Plain()]),tools_call_name=['generate_image'],tools_call_args=[{}],completion_text='使用真实Provider格式的开工文字')
    checks['provider_plain_chain_notice_deferred']=defer_notice(event,response) and response.result_chain is None and not response.completion_text and bool(response.tools_call_args[0].get('pending_message'))
    response=SimpleNamespace(is_chunk=False,result_chain=SimpleNamespace(chain=[object()]),tools_call_name=['generate_image'],tools_call_args=[{}],completion_text='独立的富消息内容')
    checks['rich_media_result_preserved']=not defer_notice(event,response) and response.result_chain is not None
    return {'passed':all(checks.values()),'checks':checks,'model_calls':0,'image_generations':0,'qq_messages_sent':0}
