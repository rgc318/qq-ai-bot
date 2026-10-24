"""Honor saved group policy administrators without granting global privileges."""
import functools


class GroupPermissionAdapter:
    def __init__(self,groups):
        self.groups=groups
        self.target=None
        self.wrappers={}
        self.originals={}

    def in_scope(self,event):
        return not event.is_private_chat() and str(event.get_group_id()) in self.groups()

    def install(self,context):
        metadata=context.get_registered_star('astrbot_plugin_user_policy')
        plugin=getattr(metadata,'star_cls',None)
        if plugin is None:return False
        cls=type(plugin)
        if self.target is cls and all(getattr(cls,n) is w for n,w in self.wrappers.items()):return True
        self.restore()
        self.target=cls
        self.originals={name:getattr(cls,name) for name in ('_group_rule_for_event','_can_use_query_command')}
        original_rule=self.originals['_group_rule_for_event']
        original_query=self.originals['_can_use_query_command']

        @functools.wraps(original_rule)
        def group_rule(instance,event):
            if not self.in_scope(event) or instance.store is None:return original_rule(instance,event)
            # The native selector checks actual membership before accepting an
            # alias; the older rule getter accepts {} on the first missing alias.
            key=instance._group_policy_id_for_event(event)
            rule=instance.store.config.get('groups',{}).get(key)
            return rule if isinstance(rule,dict) else {}

        @functools.wraps(original_query)
        def can_query(instance,event,decision):
            if original_query(instance,event,decision):return True
            if not self.in_scope(event) or getattr(decision,'is_blocked',False):return False
            rule=instance._group_rule_for_event(event)
            return instance._event_user_id(event) in {str(user) for user in rule.get('policy_admins',[])}

        self.wrappers={'_group_rule_for_event':group_rule,'_can_use_query_command':can_query}
        for name,method in self.wrappers.items():setattr(cls,name,method)
        return True

    def restore(self):
        if self.target is not None:
            for name,wrapper in self.wrappers.items():
                if getattr(self.target,name) is wrapper:setattr(self.target,name,self.originals[name])
        self.target=None;self.wrappers={};self.originals={}
