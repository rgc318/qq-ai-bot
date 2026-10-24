"""Exercise the live memory processor with synthetic dialogue, then clean up."""
import json
import time
from uuid import uuid4
from deployment_api import DeploymentAPI, write_report

api=DeploymentAPI()
prefix='/api/plug/astrbot_plugin_livingmemory/page'
session='deployment-summary-'+uuid4().hex
source=[]
for i,(role,text) in enumerate([('user','我是部署验收虚拟用户小甲。我长期喜欢喝乌龙茶，不喜欢咖啡，请记住这个偏好。'),('assistant','我会记下小甲的饮品偏好。'),('user','对，以后推荐饮品时优先考虑乌龙茶。')]):
    source.append({'id':i+1,'session_id':session,'role':role,'content':text,'sender_id':'synthetic-a' if role=='user' else 'synthetic-bot','sender_name':'验收虚拟用户小甲' if role=='user' else '验收机器人','group_id':'synthetic-group','platform':'deployment-test','timestamp':time.time()+i,'metadata':{'is_bot_message':role=='assistant'}})
payload={'format':'json','content':json.dumps([{'session_id':session,'persona_id':'大肥鱼','source_messages':source}],ensure_ascii=False),'duplicate_strategy':'skip'}
report={'synthetic_dialogue':True,'messages_sent_to_qq':0}
ids=[]
try:
    preview=api.call(prefix+'/memories/import',{**payload,'dry_run':True})['data']
    assert preview['summary_required_count']==1,preview
    actual=api.call(prefix+'/memories/import',{**payload,'dry_run':False},timeout=120)['data']
    ids=actual.get('imported_ids',[])
    report.update(summary_imported_count=actual.get('imported_count'),failed_count=actual.get('failed_count'))
    assert len(ids)==1,actual
    recall=api.call(prefix+'/recall/test',{'query':'虚拟用户小甲喜欢喝什么茶？','session_id':session,'k':3},timeout=40)['data']['results']
    own=[r for r in recall if r['memory_id'] in ids]
    report['summarized_preference_recalled']=any('乌龙' in r['content'] for r in own)
    report['passed']=report['summarized_preference_recalled']
finally:
    if ids:
        cleaned=api.call(prefix+'/memories/batch-delete',{'memory_ids':ids})['data']
        report['test_memories_removed']=cleaned['deleted_count']==len(ids)
    else:report['test_memories_removed']=True
    write_report('memory-summary-verification.json',report)
    print(json.dumps(report,ensure_ascii=False))
assert report.get('passed') and report['test_memories_removed']
