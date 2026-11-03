"""Native selector rows with backwards-compatible persona/provider lookup."""


def binding_rows(value):
    """Migrate the legacy mapping without substituting defaults or losing IDs."""
    if isinstance(value, dict):
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
            raise ValueError('人格模型旧配置必须是人格 ID 到 Provider ID 的字符串映射')
        return [
            {'__template_key': 'binding', 'persona_id': persona, 'provider_id': provider}
            for persona, provider in value.items()
        ]
    if isinstance(value, list):
        return value
    raise ValueError('人格模型绑定必须是配置条目列表或旧版映射')


def binding_map(config):
    """Skip unfinished UI rows; later complete rows override duplicate personas."""
    value = config.get('bindings', {})
    if isinstance(value, dict):
        return value
    return {
        row['persona_id']: row['provider_id']
        for row in binding_rows(value)
        if isinstance(row, dict)
        and isinstance(row.get('persona_id'), str) and row['persona_id']
        and isinstance(row.get('provider_id'), str) and row['provider_id']
    }


def migrate_bindings(config):
    """Persist once at plugin startup; request handling never writes config."""
    value = config.get('bindings', [])
    if not isinstance(value, dict):
        return False
    config['bindings'] = binding_rows(value)
    try:
        config.save_config()
    except BaseException:
        config['bindings'] = value
        raise
    return True
