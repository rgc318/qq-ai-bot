"""Run inside AstrBot's image with this repository mounted at /workspace.

Only synthetic config in a temporary directory; no production config or models.
"""
import json
from pathlib import Path
import statistics
import sys
from tempfile import TemporaryDirectory
import time

sys.path.insert(0, '/AstrBot')
from astrbot.core.config.astrbot_config import AstrBotConfig

plugin = Path('/workspace/extensions/astrbot_plugin_qq_persona_models')
sys.path.insert(0, str(plugin))
from persona_bindings import binding_map, migrate_bindings

schema = json.loads((plugin / '_conf_schema.json').read_text(encoding='utf-8'))
original = {'whale-fixture': 'source/custom', 'dragon-fixture': 'source/sol'}
checks = {}
with TemporaryDirectory(prefix='persona-selector-') as tmp:
    path = Path(tmp) / 'config.json'
    path.write_text(json.dumps({'bindings': original}), encoding='utf-8')
    config = AstrBotConfig(str(path), schema=schema)
    checks['native_integrity_preserves_legacy_map'] = config['bindings'] == original
    checks['migration_performed'] = migrate_bindings(config)
    checks['exact_routes_preserved'] = binding_map(config) == original
    restarted = AstrBotConfig(str(path), schema=schema)
    checks['native_restart_preserves_selector_rows'] = restarted['bindings'] == config['bindings']
    checks['migration_idempotent'] = not migrate_bindings(restarted)
    restarted['bindings'][0]['provider_id'] = 'source/new'
    restarted.save_config()
    checks['native_save_updates_provider'] = binding_map(AstrBotConfig(str(path), schema=schema))['whale-fixture'] == 'source/new'
    fresh = AstrBotConfig(str(Path(tmp) / 'fresh.json'), schema=schema)
    checks['fresh_install_uses_selector_rows'] = isinstance(fresh['bindings'], list) and len(binding_map(fresh)) == 2
    latencies = []
    for _ in range(10000):
        start = time.perf_counter_ns()
        binding_map(restarted).get('whale-fixture')
        latencies.append(time.perf_counter_ns() - start)
report = {'passed': all(checks.values()), 'checks': checks, 'model_calls': 0, 'qq_messages_sent': 0,
          'lookup_p95_microseconds': round(sorted(latencies)[9499] / 1000, 3),
          'lookup_mean_microseconds': round(statistics.mean(latencies) / 1000, 3),
          'latency_scope': 'two synthetic binding rows; local lookup only, not end-to-end reply latency'}
print('SELECTOR_REPORT=' + json.dumps(report))
assert report['passed']
