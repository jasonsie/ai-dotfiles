import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repair', ROOT / 'scripts/repair-local-config.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class ConfigRepairTest(unittest.TestCase):
    def test_gemini_preserves_custom_settings_and_disables_only_migrated_hooks(self):
        original = {'model': 'custom', 'theme': 'default', 'sandbox': False,
                    'security': {'auth': {'selectedType': 'oauth-personal'}},
                    'hooks': {'pre-tool': [{'command': 'old-script', 'matcher': ''}],
                              'AfterAgent': [{'hooks': [{'name': 'mine', 'type': 'command', 'command': 'x'}]}]}}
        result = repair.migrate_json('gemini', original)
        self.assertEqual(result['model'], {'name': 'custom'})
        self.assertEqual(result['security'], original['security'])
        self.assertEqual(result['tools'], {'sandbox': True})
        self.assertEqual(result['general']['defaultApprovalMode'], 'default')
        hook = result['hooks']['BeforeTool'][0]
        self.assertEqual(hook['hooks'][0]['type'], 'command')
        self.assertEqual(hook['matcher'], 'run_shell_command')
        self.assertNotIn('mine', result['hooksConfig']['disabled'])
        self.assertEqual(result, repair.migrate_json('gemini', result))
        self.assertIsInstance(original['model'], str)

    def test_pi_default_matches_scope(self):
        original = {'defaultProvider': 'openai-codex', 'defaultModel': 'old',
                    'enabledModels': ['google/other', 'openai-codex/new']}
        result = repair.migrate_json('pi', original)
        self.assertEqual(result['defaultModel'], 'new')
        self.assertEqual(result, repair.migrate_json('pi', result))
        original['enabledModels'] = ['openai-codex/*']
        self.assertEqual(original, repair.migrate_json('pi', original))
        original['enabledModels'] = ['google/other']
        with self.assertRaises(ValueError):
            repair.migrate_json('pi', original)

    def test_claude_preserves_plugins_and_restores_prompts(self):
        result = repair.migrate_json('claude', {'enabledPlugins': {'mine': True},
                                    'permissions': {'defaultMode': 'bypassPermissions'}})
        self.assertFalse(result['skipDangerousModePermissionPrompt'])
        self.assertFalse(result['skipAutoPermissionPrompt'])
        self.assertEqual(result['permissions']['defaultMode'], 'default')
        self.assertEqual(result['enabledPlugins'], {'mine': True})

    def test_codex_preserves_repositories_and_model(self):
        before = '''model = "chosen"
approval_mode = "auto"
sandbox = "workspace"
model_reasoning_effort = "high"

[projects."/home/test"]
trust_level = "trusted"

[projects."/home/test/repo"]
trust_level = "trusted"

[tui]
foo = true
'''
        result = repair.migrate_codex(before, Path('/home/test'))
        parsed = tomllib.loads(result)
        self.assertEqual(parsed['model'], 'chosen')
        self.assertEqual(parsed['approval_policy'], 'on-request')
        self.assertEqual(parsed['sandbox_mode'], 'workspace-write')
        self.assertNotIn('/home/test', parsed['projects'])
        self.assertIn('/home/test/repo', parsed['projects'])
        self.assertEqual(result, repair.migrate_codex(result, Path('/home/test')))

    def test_backup_idempotence_and_no_dry_run_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / '.gemini/settings.json'
            path.parent.mkdir()
            path.write_text('{"model": "custom"}\n')
            path.chmod(0o600)
            before = path.read_bytes()
            changes = repair.plan(home)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse((home / '.local').exists())
            backup = repair.apply(home, changes)
            self.assertEqual((backup / '.gemini/settings.json').read_bytes(), before)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(repair.plan(home), [])

    def test_concurrent_edits_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / '.claude/settings.json'
            path.parent.mkdir()
            path.write_text('{}')
            changes = repair.plan(home)
            path.write_text('{"model":"changed"}')
            with self.assertRaisesRegex(ValueError, 'Concurrent edit'):
                repair.apply(home, changes)
            self.assertEqual(json.loads(path.read_text()), {'model': 'changed'})

    def test_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for relative in ('.claude/settings.json', '.gemini/settings.json'):
                path = home / relative
                path.parent.mkdir()
                path.write_text('{}')
            changes = repair.plan(home)
            original = repair.atomic_write
            calls = 0

            def fail_once(*args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError('injected')
                return original(*args)

            with patch.object(repair, 'atomic_write', fail_once):
                with self.assertRaises(OSError):
                    repair.apply(home, changes)
            for path, before, _ in changes:
                self.assertEqual(path.read_bytes(), before)

    def test_claude_resource_links_preserve_user_files(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / 'tools/rules/core.md'
            source.parent.mkdir(parents=True)
            source.write_text('canonical')
            user = workspace / '.claude/rules/custom.md'
            user.parent.mkdir(parents=True)
            user.write_text('user-owned')
            (source.parent / 'custom.md').write_text('do not overwrite')
            env = {**os.environ, 'WORKSPACE_DIR': str(workspace), 'DRY_RUN': '0'}
            command = 'source scripts/adapters/claude.sh; _claude_link_resources'
            for _ in range(2):
                subprocess.run(['bash', '-c', command], cwd=ROOT, env=env,
                               check=True, capture_output=True)
            self.assertEqual((user.parent / 'core.md').resolve(), source.resolve())
            self.assertEqual(user.read_text(), 'user-owned')

    def test_templates_and_generated_gemini_hooks(self):
        template = json.loads((ROOT / 'tools/settings/gemini.json.tmpl').read_text())
        self.assertIsInstance(template['model'], dict)
        self.assertTrue(template['tools']['sandbox'])
        self.assertFalse(template['hooksConfig']['enabled'])
        codex = tomllib.loads((ROOT / 'tools/settings/codex.toml.tmpl').read_text())
        self.assertEqual(codex['sandbox_mode'], 'workspace-write')
        command = 'source scripts/adapters/gemini.sh; _gemini_build_hooks_json'
        result = subprocess.run(['bash', '-c', command], cwd=ROOT, capture_output=True, text=True, check=True)
        hooks = json.loads(result.stdout)
        self.assertEqual(set(hooks), set(repair.EVENTS.values()))
        for entries in hooks.values():
            self.assertEqual(entries[0]['hooks'][0]['type'], 'command')


if __name__ == '__main__':
    unittest.main()
