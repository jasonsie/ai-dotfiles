import importlib.util
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hooks', ROOT / 'scripts/install-hooks.py')
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)

THEIRS = {'hooks': [{'type': 'command', 'command': 'echo mine'}]}


class InstallHooksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hooks 空間 ')
        self.home = Path(self.temp.name).resolve()
        for folder in ('.claude', '.codex', '.gemini/config', '.pi/agent'):
            (self.home / folder).mkdir(parents=True)
        self.hook = self.home / 'repo/skills/learn/hooks/learn_hook.py'
        self.pi = self.home / 'repo/skills/learn/hooks/pi-learn.ts'

    def tearDown(self):
        self.temp.cleanup()

    def install(self, targets=hooks.TARGETS, apply=False):
        with redirect_stdout(io.StringIO()):
            return hooks.install(self.home, targets, apply, self.hook, self.pi)

    def read(self, cli):
        return json.loads((self.home / hooks.FILES[cli]).read_text())

    def test_preview_then_apply_then_nothing_left(self):
        self.assertEqual(self.install(), 4)
        self.assertFalse((self.home / hooks.FILES['claude']).exists())
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
        self.assertEqual(os.readlink(self.home / '.pi/agent' / hooks.PI_LINK), str(self.pi))

    def test_keeps_other_hooks_and_settings(self):
        path = self.home / hooks.FILES['claude']
        path.write_text(json.dumps({'model': 'opus', 'hooks': {'Stop': [THEIRS], 'PreToolUse': [THEIRS]}}))
        (self.home / hooks.FILES['agy']).write_text(json.dumps({'lint': {'Stop': [THEIRS['hooks'][0]]}}))
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
        self.pi = self.home / 'moved/skills/learn/hooks/pi-learn.ts'
        self.assertEqual(self.install(apply=True), 4)
        stop = self.read('codex')['hooks']['Stop']
        self.assertEqual(len(stop), 1)
        self.assertIn('moved', stop[0]['hooks'][0]['command'])
        self.assertEqual(self.install(), 0)

    def test_refuses_what_it_did_not_create(self):
        (self.home / hooks.FILES['agy']).write_text(json.dumps({'ai-dotfiles-learn-stop': {'Stop': [THEIRS['hooks'][0]]}}))
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(('agy',))
        (self.home / '.pi/agent/extensions').mkdir()
        (self.home / '.pi/agent' / hooks.PI_LINK).write_text('// mine')
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(('pi',))

    def test_refuses_symlinked_file(self):
        real = self.home / 'elsewhere.json'
        real.write_text('{}')
        (self.home / hooks.FILES['codex']).symlink_to(real)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.install(('codex',))

    def test_missing_script_still_exits_zero(self):
        command = hooks.handler('claude', 'prompt', self.home / 'gone/skills/learn/hooks/learn_hook.py')['command']
        run = subprocess.run(['sh', '-c', command], input='{}', capture_output=True, text=True)
        self.assertEqual(run.returncode, 0)
        self.assertTrue(hooks.is_ours({'command': command}))

    def test_skips_a_cli_that_is_not_set_up(self):
        (self.home / '.codex').rmdir()
        self.assertEqual(self.install(), 3)

    def test_failed_run_restores_files_and_link(self):
        (self.home / hooks.FILES['claude']).write_text('{"model": "opus"}\n')
        original, calls = hooks.settings.atomic_write, 0

        def fail_second(path, content, mode):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('injected')
            return original(path, content, mode)

        with patch.object(hooks.settings, 'atomic_write', fail_second), self.assertRaises(OSError):
            self.install(apply=True)
        self.assertEqual((self.home / hooks.FILES['claude']).read_text(), '{"model": "opus"}\n')
        self.assertFalse((self.home / hooks.FILES['codex']).exists())
        self.assertFalse((self.home / '.pi/agent' / hooks.PI_LINK).is_symlink())


if __name__ == '__main__':
    unittest.main()
