"""Read final deployment state; isolated checks never send QQ messages."""
import json
from deployment_api import DeploymentAPI,write_report

api=DeploymentAPI()
name='astrbot_plugin_qq_persona_models'
config=api.call('/api/v1/plugins/'+name+'/config')['data']['config']
status=api.call('/api/plug/qq_persona_models/chat_history/status')['data']
binding=api.call('/api/plug/qq_persona_models/verify')
tools=api.call('/api/v1/tools')['data']
enabled={tool['name'] for tool in tools if tool.get('active')}
plugin=next(p for p in api.call('/api/v1/plugins')['data'] if p['name']==name)
# Do not serialize provider credentials or full plugin settings.
checks={
    'plugin_active':plugin['activated'],
    'version_1_4_0':plugin['version']=='1.4.0',
    'index_enabled_and_ready':status['enabled'] and not status['initializing'] and 'error_type' not in status['bootstrap'],
    'local_index_has_verified_history':status['counts']['documents']>0,
    'tools_enabled':{'search_chat_history','read_chat_history'}.issubset(enabled),
    'memory_tools_preserved':{'recall_long_term_memory','memorize_long_term_memory'}.issubset(enabled),
    'persona_bindings_preserved':all(x['passed'] for x in binding['data']),
    'gif_upload_adapter_active':binding['image_upload_adapter_active'],
    'twelve_turn_history_preserved':config.get('performance',{}).get('history_turns')==12,
    'model_image_notice_preserved':config.get('image_pending_notice',{}).get('model_generated') is True,
}
native=api.call('/api/plug/qq_persona_models/chat_history/verify',{'call_model':False})['data']
checks['native_isolation_and_post_send_save']=native['passed']
report={'checks':checks,'passed':all(checks.values()),'status':status,'version':plugin['version'],'settings':config.get('history_recall'), 'qq_messages_sent':0,'native_test_production_index_writes':native['production_index_writes']}
write_report('history-recall-final-status.json',report)
print(json.dumps(report,ensure_ascii=False))
assert report['passed']
