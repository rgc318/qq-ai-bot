"""Preserve the existing whale persona and insert richer, context-sensitive traits."""
import json
from deployment_api import DeploymentAPI,ROOT,write_report

api=DeploymentAPI()
rows=api.call('/api/persona/list')['data']
rows=rows if isinstance(rows,list) else rows.get('list',[])
whale=next(p for p in rows if p['persona_id']=='大肥鱼')
dragon=next(p for p in rows if p['persona_id']=='ChatGPT龙娘')
api.backup('whale-persona-before-personality-enrichment-20261023.json',whale)
before=whale['system_prompt']
extension=(ROOT/'config/personas/whale-personality-extension.txt').read_text(encoding='utf-8').strip()
marker='【性格的层次与变化】'
if marker in before:
    raise SystemExit('Personality extension already present; inspect before editing further.')
paragraphs=before.split('\n\n',2)
assert len(paragraphs)==3
after='\n\n'.join([paragraphs[0],paragraphs[1],extension,paragraphs[2]])
target=ROOT/'config/personas/whale-system-prompt.txt'
target.write_text(after+'\n',encoding='utf-8')
api.call('/api/persona/update',{'persona_id':'大肥鱼','system_prompt':after})
live=api.call('/api/persona/list')['data']
live=live if isinstance(live,list) else live.get('list',[])
actual=next(p for p in live if p['persona_id']=='大肥鱼')
actual_dragon=next(p for p in live if p['persona_id']=='ChatGPT龙娘')
checks={'prompt_saved':actual['system_prompt']==after,
    'original_content_preserved':after.replace('\n\n'+extension,'',1)==before,
    'tools_preserved':actual.get('tools')==whale.get('tools'),
    'skills_preserved':actual.get('skills')==whale.get('skills'),
    'dragon_unchanged':actual_dragon==dragon}
bindings=api.call('/api/plug/qq_persona_models/verify')['data']
checks['persona_models_unchanged']=all(x['passed'] for x in bindings)
report={'persona':'大肥鱼','before_characters':len(before),'after_characters':len(after),'checks':checks,'passed':all(checks.values()),'qq_messages_sent':0}
write_report('whale-personality-enrichment.json',report)
print(json.dumps(report,ensure_ascii=False))
assert report['passed']
