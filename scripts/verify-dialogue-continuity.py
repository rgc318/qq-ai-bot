"""Isolated live classifier probes; no main-model generation, writes or QQ sends."""
import json
import sys

from deployment_api import DeploymentAPI, write_report


api=DeploymentAPI()
history=[{'role':'user','sender':'A','text':'重新生成一下','directed_to_bot':True,'age_seconds':183},
    {'role':'assistant','sender':'A','text':'','request':'重新生成一下','pending':True,'age_seconds':183}]
cases=[('identity_no_classifier',{'sender':'A','message':'你是谁','history':history},True,True),
    ('ambiguous_continuation_classifier',{'sender':'A','message':'现在运行的是什么模型？','history':history},True,False),
    ('human_handoff_classifier',{'sender':'A','message':'你是哪个班的？','history':[{**row,'age_seconds':60} for row in history]+[
        {'role':'user','sender':'B','text':'小张：刚才我没看到，A你问我什么？','age_seconds':20},
        {'role':'user','sender':'A','text':'小张，我问的是你，不是机器人。','targets_other':True,'age_seconds':10}]},False,False),
    ('named_human_without_other_speaker',{'sender':'A','message':'你是谁？','history':[{**row,'age_seconds':60} for row in history]+[
        {'role':'user','sender':'A','text':'小张，我现在问你，不是问机器人。','age_seconds':10}]},False,False)]
report_name='dialogue-continuity-verification.json'
if len(sys.argv)>1:
    cases=[case for case in cases if case[0]==sys.argv[1]]
    assert cases, 'Unknown diagnostic case'
    report_name='dialogue-continuity-'+cases[0][0]+'.json'
report={'qq_messages_sent':0,'main_model_calls':0,'image_generations':0,'cases':{}}
for name,payload,want_reply,local in cases:
    row=api.call('/api/plug/qq_persona_models/reply_conditions/test',payload,timeout=25)['data']
    row['passed']=row['normal_pipeline_eligible']==want_reply
    if local:row['passed']=row['passed'] and row['reason']=='same_speaker_dialogue' and row['judge_seconds']==0 and row['selfreply_sees_direct_call']
    report['cases'][name]=row
    write_report(report_name,report)
    print(json.dumps({'case':name,**row},ensure_ascii=False),flush=True)
for name,payload in [('model_logging',{'model_logging_only':True}),('image_references',{'image_reference_only':True})]:
    row=api.call('/api/plug/qq_persona_models/verify_memory_meme',payload)['data']
    assert 'checks' in row and row.get('qq_messages_sent')==0, 'Unexpected diagnostic mode'
    report[name]={'passed':row['passed'],'checks':len(row['checks'])}
    print(name,report[name],flush=True)
report['passed']=all(row['passed'] for row in report['cases'].values()) and all(report[name]['passed'] for name in ('model_logging','image_references'))
report['judge_requests']=sum(row['judge_seconds']>0 for row in report['cases'].values())
write_report(report_name,report)
assert report['passed'], 'See per-case report; classifier transport timeouts are not positive decisions'
