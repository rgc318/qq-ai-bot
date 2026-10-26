"""Synthetic contract checks. No model, network, image generation or sends."""
from copy import deepcopy
from types import SimpleNamespace
from .image_task_contract import validate_task,consume_task,ImageTaskError,translate_reference_roles,complete_task
from .image_response_adapter import defer_notice,stop_blocked_image_response


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
    from astrbot.core.agent.tool import FunctionTool,ToolSet
    from .image_tool_compat import prepare_chat_image_tools
    from .model_logging import image_tool_contract_metadata
    original=FunctionTool(name='generate_image',description='fixture SECRET_SCHEMA_SENTINEL',parameters={'type':'object','properties':{'prompt':{'type':'string'}}})
    request=SimpleNamespace(func_tool=ToolSet(tools=[original]))
    prepare_chat_image_tools(request,model_notice=True,indexed_references=True,task_contract=True,batch_images=True)
    wire=request.func_tool.get_func_desc_openai_style()[0]['function']
    keys={'image_task','reference_ids','reference_notes','pending_message'}
    checks['provider_serializer_preserves_task_required_fields']=keys.issubset(wire['parameters']['required']) and keys.issubset(wire['parameters']['properties'])
    checks['task_contract_visible_in_tool_description']='image_task=' in wire['description'] and 'reference_notes=' in wire['description']
    metadata=image_tool_contract_metadata(request.func_tool)
    checks['contract_metadata_has_required_flags_without_payload']=all(metadata['generate_image'][key]=={'present':True,'required':True} for key in keys) and 'SECRET_SCHEMA_SENTINEL' not in str(metadata) and metadata['generate_image']['count_maximum']==4
    checks['contract_changes_do_not_mutate_registered_schema']='image_task' not in original.parameters['properties']
    extras['qq_image_failure_state']={'blocked':True,'reason':'参数校验连续两次未通过（missing_task）','delivered_images':0}
    def retry(names=None):return SimpleNamespace(is_chunk=False,result_chain=None,tools_call_name=names if names is not None else ['generate_image'],tools_call_args=[{}],tools_call_ids=['blocked'],completion_text='图片工具不存在')
    response=retry()
    checks['blocked_retry_ends_with_actual_reason']=stop_blocked_image_response(event,response) and 'missing_task' in response.completion_text and '工具不存在' not in response.completion_text and not response.tools_call_name and not response.tools_call_args and not response.tools_call_ids
    extras['qq_image_failure_state']['delivered_images']=2;response=retry()
    checks['blocked_retry_preserves_partial_delivery_count']=stop_blocked_image_response(event,response) and '已发送2张' in response.completion_text
    response=retry(['search','generate_image'])
    checks['blocked_mixed_response_is_not_replaced']=not stop_blocked_image_response(event,response) and response.tools_call_name==['search','generate_image']
    extras['qq_image_failure_state']['blocked']=False;response=retry()
    checks['valid_image_retry_is_not_replaced']=not stop_blocked_image_response(event,response) and response.tools_call_name==['generate_image']
    from .image_history_compat import normalize_image_history
    import json
    old={'role':'assistant','content':'之前正在改图','tool_calls':[{'id':'old','type':'function','function':{'name':'generate_image','arguments':json.dumps({'prompt':'把角色保留蓝发，加入红花','count':1,'_qq_image_guard_error':'old private error'})}}, {'id':'search','type':'function','function':{'name':'search','arguments':'{}'}}]}
    pixels={'type':'image_url','image_url':{'url':'data:image/png;base64,c3ludGhldGlj'}}
    history=[old,{'role':'tool','tool_call_id':'old','content':[{'type':'text','text':'当时没有执行'},pixels]}, {'role':'tool','tool_call_id':'search','content':'其他工具结果'}, {'role':'user','content':'再试一下'}]
    before=deepcopy(history);normalized,stats=normalize_image_history(history);dump=json.dumps(normalized,ensure_ascii=False)
    checks['legacy_history_normalization_does_not_mutate_source']=history==before
    checks['legacy_execution_private_keys_not_shown_to_model']='_qq_image_guard_error' not in dump and 'old private error' not in dump
    checks['legacy_task_and_result_facts_retained']='蓝发，加入红花' in dump and '当时没有执行' in dump
    checks['legacy_result_media_preserved']=pixels in normalized[0]['content']
    checks['mixed_tool_ids_and_adjacency_preserved']=normalized[0]['tool_calls']==[old['tool_calls'][1]] and normalized[1]['tool_call_id']=='search'
    checks['legacy_call_and_result_counts']=stats=={'legacy_image_calls':1,'legacy_image_results':1}
    valid={'role':'assistant','tool_calls':[{'id':'valid','type':'function','function':{'name':'generate_image','arguments':json.dumps(edit)}}]}
    normalized,stats=normalize_image_history([valid])
    checks['valid_modern_image_history_unchanged']=normalized==[valid] and not stats['legacy_image_calls']
    checks['ordinary_history_no_change']=normalize_image_history([{'role':'user','content':'你好'}])[0]==[{'role':'user','content':'你好'}]
    return {'passed':all(checks.values()),'checks':checks,'model_calls':0,'image_generations':0,'qq_messages_sent':0}
