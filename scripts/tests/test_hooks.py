import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from support import load, registry
import installer

hooks = load('install/hooks.py')

THEIRS = {'hooks': [{'type': 'command', 'command': 'echo mine'}]}


class InstallHooksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hooks 空間 ')
        self.home = Path(self.temp.name).resolve()
        for folder in ('.claude', '.codex', '.gemini/config'):
            (self.home / folder).mkdir(parents=True)
        self.hook = self.home / 'repo/skills/learn/hooks/learn_hook.py'

    def tearDown(self):
        self.temp.cleanup()

    def install(self, clis=tuple(hooks.EVENTS), apply=False, uninstall=False):
        with redirect_stdout(io.StringIO()):
            return hooks.install(self.home, () if uninstall else clis, clis if uninstall else (), apply, self.hook)

    def path(self, cli):
        return installer.path(self.home, cli, 'hooks')

    def read(self, cli):
        return json.loads(self.path(cli).read_text())

    def test_preview_then_apply_then_nothing_left(self):
        self.assertEqual(self.install(), 3)
        self.assertFalse(self.path('claude').exists())
        self.install(apply=True)
        self.assertEqual(self.install(), 0)
        claude = self.read('claude')['hooks']
        self.assertEqual(sorted(claude), ['Stop', 'UserPromptSubmit'])
        command = claude['Stop'][0]['hooks'][0]['command']
        self.assertIn('stop --cli claude', command)
        self.assertIn(str(self.hook), command.replace("'", ''))
        self.assertEqual(self.read('codex')['hooks']['UserPromptSubmit'][0]['hooks'][0]['timeout'], 10)
        agy = self.read('agy')
        self.assertIn('--cli agy', agy['ai-dotfiles-learn-prompt']['PreInvocation'][0]['command'])
        self.assertIn('Stop', agy['ai-dotfiles-learn-stop'])

    def test_pi_has_no_hook_file(self):
        self.assertEqual(self.install(('pi',), apply=True), 0)

    def test_keeps_other_hooks_and_settings(self):
        self.path('claude').write_text(json.dumps({'model': 'opus', 'hooks': {'Stop': [THEIRS], 'PreToolUse': [THEIRS]}}))
        self.path('agy').write_text(json.dumps({'lint': {'Stop': [THEIRS['hooks'][0]]}}))
        self.install(apply=True)
        data = self.read('claude')
        self.assertEqual(data['model'], 'opus')
        self.assertEqual(data['hooks']['PreToolUse'], [THEIRS])
        self.assertEqual(data['hooks']['Stop'][0], THEIRS)
        self.assertEqual(len(data['hooks']['Stop']), 2)
        self.assertIn('lint', self.read('agy'))

    def test_moved_repo_replaces_its_own_entry_in_place(self):
        self.install(apply=True)
        self.hook = self.home / 'moved/skills/learn/hooks/learn_hook.py'
        self.assertEqual(self.install(apply=True), 3)
        stop = self.read('codex')['hooks']['Stop']
        self.assertEqual(len(stop), 1)
        self.assertIn('moved', stop[0]['hooks'][0]['command'])
        self.assertEqual(self.install(), 0)

    def test_refuses_what_it_did_not_create(self):
        self.path('agy').write_text(json.dumps({'ai-dotfiles-learn-stop': {'Stop': [THEIRS['hooks'][0]]}}))
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(('agy',))

    def test_refuses_symlinked_file(self):
        real = self.home / 'elsewhere.json'
        real.write_text('{}')
        self.path('codex').symlink_to(real)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.install(('codex',))

    def test_missing_script_still_exits_zero(self):
        command = hooks.handler('claude', 'prompt', self.home / 'gone/skills/learn/hooks/learn_hook.py')['command']
        run = subprocess.run(['sh', '-c', command], input='{}', capture_output=True, text=True)
        self.assertEqual(run.returncode, 0)
        self.assertTrue(hooks.is_ours({'command': command}))

    def test_skips_a_cli_that_is_not_set_up(self):
        (self.home / '.codex').rmdir()
        self.assertEqual(self.install(), 2)

    def seed(self):
        seeds = {
            'claude': {'model': 'opus', 'hooks': {'Stop': [THEIRS], 'PreToolUse': [THEIRS]}},
            'codex': {'hooks': {'UserPromptSubmit': [THEIRS]}},
            'agy': {'lint': {'Stop': [THEIRS['hooks'][0]]}},
        }
        for cli, data in seeds.items():
            self.path(cli).write_text(json.dumps(data))
        return seeds

    def test_uninstall_restores_each_file(self):
        seeds = self.seed()
        self.install(apply=True)
        self.assertNotEqual(self.read('claude'), seeds['claude'])
        self.assertEqual(self.install(apply=True, uninstall=True), 3)
        for cli, data in seeds.items():
            self.assertEqual(self.read(cli), data)

    def test_uninstall_drops_emptied_events_and_hooks_key(self):
        self.install(('claude', 'agy'), apply=True)
        self.assertEqual(self.install(('claude', 'agy'), apply=True, uninstall=True), 2)
        self.assertEqual(self.read('claude'), {})
        self.assertEqual(self.read('agy'), {})

    def test_uninstall_keeps_foreign_handler_in_our_group(self):
        self.install(('claude',), apply=True)
        data = self.read('claude')
        data['hooks']['Stop'][0]['hooks'].append(THEIRS['hooks'][0])
        self.path('claude').write_text(json.dumps(data))
        self.install(('claude',), apply=True, uninstall=True)
        self.assertEqual(self.read('claude'), {'hooks': {'Stop': [THEIRS]}})

    def test_uninstall_is_idempotent(self):
        self.seed()
        self.install(apply=True)
        self.install(apply=True, uninstall=True)
        self.assertEqual(self.install(apply=True, uninstall=True), 0)
        self.assertEqual(self.install(uninstall=True), 0)

    def test_uninstall_dry_run_writes_nothing(self):
        self.seed()
        self.install(apply=True)
        before = {cli: self.path(cli).read_bytes() for cli in hooks.EVENTS}
        self.assertEqual(self.install(uninstall=True), 3)
        for cli, data in before.items():
            self.assertEqual(self.path(cli).read_bytes(), data)

    def test_uninstall_refuses_what_it_did_not_create(self):
        self.path('agy').write_text(json.dumps({'ai-dotfiles-learn-stop': {'Stop': [THEIRS['hooks'][0]]}}))
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(('agy',), apply=True, uninstall=True)

    def test_uninstall_with_nothing_installed_or_no_cli(self):
        self.assertEqual(self.install(apply=True, uninstall=True), 0)
        (self.home / '.codex').rmdir()
        self.assertEqual(self.install(uninstall=True), 0)

    def test_a_cli_switched_off_loses_its_hooks(self):
        seeds = self.seed()
        self.install(apply=True)
        with patch.object(installer, 'REGISTRY', registry(self.home, agy=False)), redirect_stdout(io.StringIO()):
            self.assertEqual(hooks.run(self.home, 'all', True, False, self.hook), 1)
            self.assertEqual(hooks.run(self.home, 'all', False, False, self.hook), 0)
        self.assertEqual(self.read('agy'), seeds['agy'])
        self.assertIn('UserPromptSubmit', self.read('claude')['hooks'])


if __name__ == '__main__':
    unittest.main()
