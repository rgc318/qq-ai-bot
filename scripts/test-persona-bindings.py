"""Selector migration and real bind-hook behavior; no network or model calls."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'extensions/astrbot_plugin_qq_persona_models'
spec = importlib.util.spec_from_file_location('persona_bindings', PLUGIN / 'persona_bindings.py')
bindings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bindings)
tree = ast.parse((PLUGIN / 'main.py').read_text(encoding='utf-8'))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PersonaModelBindings')
hook = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'bind')
scope = {'binding_map': bindings.binding_map}
exec(compile(ast.Module(body=[hook], type_ignores=[]), '<real bind hook>', 'exec'), scope)


class Config(dict):
    saves = 0
    fail = False

    def save_config(self):
        if self.fail:
            raise OSError('fixture disk failure')
        self.saves += 1
        self.saved = deepcopy(dict(self))


class PersonaBindingTests(unittest.TestCase):
    def test_legacy_custom_ids_preserved_without_default_substitution(self):
        old = {'大肥鱼': 'source/custom-deepseek', 'ChatGPT龙娘': 'custom-sol', '新人格': 'other/provider'}
        config = Config(bindings=old, reply_conditions={'enabled': True})
        self.assertTrue(bindings.migrate_bindings(config))
        self.assertEqual(bindings.binding_map(config), old)
        self.assertEqual(config.saved['reply_conditions'], {'enabled': True})
        self.assertEqual(config.saves, 1)
        self.assertTrue(all(r['__template_key'] == 'binding' for r in config['bindings']))

    def test_migration_idempotent_after_restart(self):
        config = Config(bindings={'persona': 'provider'})
        bindings.migrate_bindings(config)
        before = deepcopy(config.saved)
        self.assertFalse(bindings.migrate_bindings(config))
        self.assertEqual(dict(config), before)
        self.assertEqual(config.saves, 1)

    def test_empty_legacy_map_does_not_restore_defaults(self):
        config = Config(bindings={})
        bindings.migrate_bindings(config)
        self.assertEqual(config['bindings'], [])
        self.assertEqual(bindings.binding_map(config), {})

    def test_save_failure_keeps_original_in_memory(self):
        config = Config(bindings={'persona': 'provider'})
        config.fail = True
        with self.assertRaises(OSError):
            bindings.migrate_bindings(config)
        self.assertEqual(config['bindings'], {'persona': 'provider'})

    def test_invalid_legacy_map_never_silently_discards_data(self):
        config = Config(bindings={'persona': {'unexpected': 'data'}})
        with self.assertRaises(ValueError):
            bindings.migrate_bindings(config)
        self.assertEqual(config['bindings'], {'persona': {'unexpected': 'data'}})
        self.assertEqual(config.saves, 0)

    def test_drafts_skip_without_overriding_complete_row(self):
        rows = bindings.binding_rows({'persona': 'provider'})
        rows.extend([None, {}, {'persona_id': 'persona', 'provider_id': ''},
                     {'persona_id': '', 'provider_id': 'other'}, {'persona_id': [], 'provider_id': 'other'}])
        self.assertEqual(bindings.binding_map({'bindings': rows}), {'persona': 'provider'})

    def test_duplicate_last_complete_row_wins(self):
        rows = bindings.binding_rows({'persona': 'old'}) + bindings.binding_rows({'persona': 'new'})
        self.assertEqual(bindings.binding_map({'bindings': rows}), {'persona': 'new'})

    def test_selector_edit_is_immediately_used_by_bind_hook(self):
        config = {'bindings': bindings.binding_rows({'persona': 'old'})}
        extras = {'user_policy_effective_persona_id': 'persona', 'selected_model': 'old-model'}
        event = SimpleNamespace(get_extra=extras.get, set_extra=extras.__setitem__)
        plugin = SimpleNamespace(config=config, context=SimpleNamespace(get_provider_by_id=lambda p: object()))
        scope['bind'](plugin, event)
        self.assertEqual(extras['selected_provider'], 'old')
        self.assertIsNone(extras['selected_model'])
        config['bindings'][0]['provider_id'] = 'new'
        scope['bind'](plugin, event)
        self.assertEqual(extras['selected_provider'], 'new')
        self.assertEqual(extras['meme_manager_resolved_persona_id'], 'persona')

    def test_missing_provider_does_not_override_existing_selection(self):
        config = {'bindings': bindings.binding_rows({'persona': 'removed-provider'})}
        extras = {'user_policy_decision': SimpleNamespace(persona_id='persona'), 'selected_provider': 'session-default'}
        event = SimpleNamespace(get_extra=extras.get, set_extra=extras.__setitem__)
        plugin = SimpleNamespace(config=config, context=SimpleNamespace(get_provider_by_id=lambda p: None))
        scope['bind'](plugin, event)
        self.assertEqual(extras['selected_provider'], 'session-default')

    def test_legacy_lookup_remains_supported(self):
        self.assertEqual(bindings.binding_map({'bindings': {'persona': 'provider'}}), {'persona': 'provider'})

    def test_schema_uses_native_selectors_and_matching_template_keys(self):
        schema = json.loads((PLUGIN / '_conf_schema.json').read_text(encoding='utf-8'))['bindings']
        self.assertEqual(schema['type'], 'template_list')
        items = schema['templates']['binding']['items']
        self.assertEqual(items['persona_id']['_special'], 'select_persona')
        self.assertEqual(items['provider_id']['_special'], 'select_provider')
        self.assertTrue(all(r['__template_key'] in schema['templates'] for r in schema['default']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
