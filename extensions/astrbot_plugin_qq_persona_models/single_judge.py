"""Use SelfReply 1.5.1's per-event ingress guard after a local classification.

No third-party source/global functions are patched. This existing guard is
normally set by its command handler; its only reader is message_ingress.py.
Normal commands, explicit mentions and messages not classified locally retain
their original path. Recheck the guard when upgrading SelfReply.
"""
import importlib


def skip_second_judge(context,event,verdict,enabled=True):
    if not enabled or verdict.get('route')!='ambient' or not verdict.get('judged'):
        return False
    metadata=context.get_registered_star('astrbot_plugin_self_initiated_reply')
    plugin=getattr(metadata,'star_cls',None)
    if plugin is None:
        return False
    module=importlib.import_module(plugin.__class__.__module__.rsplit('.',1)[0]+'.models')
    key=getattr(module,'COMMAND_HANDLED_KEY',None)
    if not key:
        return False
    event.set_extra(key,True)
    event.set_extra('qq_single_judge_complete',True)
    return True
