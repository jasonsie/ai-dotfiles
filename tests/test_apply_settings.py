import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('settings', ROOT / 'scripts/apply-settings.py')
settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings)

MANAGED = {
    'claude': {'model': 'opus', 'skipAutoPermissionPrompt': False},
    'codex': {'model': 'm', 'approval_policy': 'on-request', 'sandbox_mode': 'workspace-write'},
    'gemini': {'model.name': 'g', 'tools.sandbox': True},
    'pi': {'defaultProvider': 'p', 'defaultModel': 'x'},
}


class ApplySettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='settings 空間 ')
        self.home = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def seed(self, cli, text, mode=0o600):
        path = self.home / settings.FILES[cli]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(mode)
        return path

    def test_managed_repo_file_is_valid(self):
        managed = json.loads(settings.MANAGED.read_text())
        self.assertLessEqual(set(managed) - {'version'}, set(settings.FILES))
        for key in managed['codex']:
            self.assertNotIn('.', key)

    def test_json_merge_preserves_unmanaged_keys(self):
        original = {'enabledPlugins': {'mine': True}, 'permissions': {'allow': ['Bash(ls)']},
                    'model': 'sonnet', 'security': {'auth': {'selectedType': 'oauth'}}}
        result = json.loads(settings.merge_json('claude', json.dumps(original), MANAGED['claude']))
        self.assertEqual(result['model'], 'opus')
        self.assertFalse(result['skipAutoPermissionPrompt'])
        for key in ('enabledPlugins', 'permissions', 'security'):
            self.assertEqual(result[key], original[key])

    def test_dotted_keys_replace_legacy_scalars(self):
        result = json.loads(settings.merge_json('gemini', '{"model": "legacy", "ui": {"theme": "x"}}',
                                                MANAGED['gemini']))
        self.assertEqual(result['model'], {'name': 'g'})
        self.assertEqual(result['tools'], {'sandbox': True})
        self.assertEqual(result['ui'], {'theme': 'x'})

    def test_unchanged_json_keeps_original_bytes(self):
        text = '{"model":   "opus", "skipAutoPermissionPrompt": false}'
        self.assertEqual(settings.merge_json('claude', text, MANAGED['claude']), text)

    def test_pi_refuses_default_outside_enabled_models(self):
        text = json.dumps({'enabledModels': ['p/other']})
        with self.assertRaisesRegex(ValueError, 'enabledModels'):
            settings.merge_json('pi', text, MANAGED['pi'])
        ok = json.loads(settings.merge_json('pi', json.dumps({'enabledModels': ['p/*']}), MANAGED['pi']))
        self.assertEqual(ok['defaultModel'], 'x')

    def test_toml_upserts_header_and_keeps_tables(self):
        before = '''# comment kept
model = "old"
model_reasoning_effort = "high"

[projects."/home/test/repo"]
trust_level = "trusted"

[mcp_servers.mine]
command = "x"
'''
        result = settings.merge_toml(before, MANAGED['codex'])
        parsed = tomllib.loads(result)
        self.assertEqual(parsed['model'], 'm')
        self.assertEqual(parsed['model_reasoning_effort'], 'high')
        self.assertEqual(parsed['sandbox_mode'], 'workspace-write')
        self.assertIn('/home/test/repo', parsed['projects'])
        self.assertEqual(parsed['mcp_servers']['mine']['command'], 'x')
        self.assertTrue(result.startswith('# comment kept\n'))
        self.assertEqual(settings.merge_toml(result, MANAGED['codex']), result)

    def test_toml_rejects_nested_keys(self):
        with self.assertRaisesRegex(ValueError, 'top-level'):
            settings.merge_toml('', {'tui.x': True})

    def test_plan_skips_uninstalled_cli_and_is_idempotent(self):
        path = self.seed('gemini', '{}')
        changes = settings.plan(self.home, tuple(settings.FILES), MANAGED)
        self.assertEqual([c[0] for c in changes], [path])
        self.assertFalse((self.home / '.claude').exists())
        self.assertFalse((self.home / '.local').exists())  # dry-run writes nothing
        backup = settings.apply(self.home, changes)
        self.assertEqual((backup / '.gemini/settings.json').read_text(), '{}')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(settings.plan(self.home, tuple(settings.FILES), MANAGED), [])

    def test_missing_file_in_existing_dir_is_created_private(self):
        (self.home / '.codex').mkdir()
        settings.apply(self.home, settings.plan(self.home, ('codex',), MANAGED))
        path = self.home / '.codex/config.toml'
        self.assertEqual(tomllib.loads(path.read_text())['model'], 'm')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_symlinked_settings_refused(self):
        target = self.home / 'shared.json'
        target.write_text('{}')
        (self.home / '.claude').mkdir()
        (self.home / '.claude/settings.json').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            settings.plan(self.home, ('claude',), MANAGED)

    def test_concurrent_edits_refused(self):
        path = self.seed('claude', '{}')
        changes = settings.plan(self.home, ('claude',), MANAGED)
        path.write_text('{"model":"changed"}')
        with self.assertRaisesRegex(ValueError, 'Concurrent edit'):
            settings.apply(self.home, changes)
        self.assertEqual(json.loads(path.read_text()), {'model': 'changed'})

    def test_failure_rolls_back(self):
        self.seed('claude', '{}')
        self.seed('gemini', '{}')
        (self.home / '.codex').mkdir()
        changes = settings.plan(self.home, ('claude', 'gemini', 'codex'), MANAGED)
        original = settings.atomic_write
        calls = 0

        def fail_third(*args):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('injected')
            return original(*args)

        with patch.object(settings, 'atomic_write', fail_third):
            with self.assertRaises(OSError):
                settings.apply(self.home, changes)
        for path, before, _ in changes:
            self.assertEqual(settings.current(path), before)
        self.assertFalse((self.home / '.codex/config.toml').exists())


if __name__ == '__main__':
    unittest.main()
