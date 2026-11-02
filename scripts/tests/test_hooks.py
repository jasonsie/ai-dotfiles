import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT, load, registry
import installer

hooks = load('install/hooks.py')

OTHERS = {'type': 'command', 'command': 'echo mine'}  # a handler this script did not write
THEIRS = {'hooks': [OTHERS]}  # and a group holding only it
AGY_TOOL, AGY_STOP = 'ai-dotfiles-daily-log-tool', 'ai-dotfiles-daily-log-stop'


class InstallHooksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hooks 空間 ')
        self.home = Path(self.temp.name).resolve()
        for folder in ('.claude', '.codex', '.gemini/config'):
            (self.home / folder).mkdir(parents=True)
        self.hook = self.home / 'repo/skills/daily-log/scripts/daily_log.py'
        self.output = ''

    def tearDown(self):
        self.temp.cleanup()

    def install(self, clis=tuple(hooks.EVENTS), apply=False, uninstall=False):
        out = io.StringIO()
        with redirect_stdout(out):
            count = hooks.install(self.home, () if uninstall else clis, clis if uninstall else (), apply, self.hook)
        self.output = out.getvalue()
        return count

    def path(self, cli):
        return installer.path(self.home, cli, 'hooks')

    def read(self, cli):
        return json.loads(self.path(cli).read_text())

    def write(self, cli, data):
        self.path(cli).write_text(json.dumps(data))

    def command(self, cli, mode):
        return shlex.join(['python3', str(self.hook), 'hook', mode, '--cli', cli]) + ' || true'

    def test_the_marker_names_the_script_the_hooks_run(self):
        self.assertEqual(hooks.HOOK, ROOT / hooks.MARK)
        self.assertTrue(hooks.HOOK.is_file())

    def test_the_registry_and_the_event_table_agree_on_which_clis_have_a_hook_file(self):
        have = {cli for cli in installer.clis() if installer.path(self.home, cli, 'hooks')}
        self.assertEqual(have, set(hooks.EVENTS))

    def test_preview_then_apply_then_nothing_left(self):
        self.assertEqual(self.install(), 3)
        self.assertNotIn('approve', self.output)
        self.assertFalse(self.path('claude').exists())
        self.install(apply=True)
        self.assertIn('Codex: approve the new hooks once with /hooks', self.output)
        self.assertEqual(self.install(), 0)  # agy too: its entries are recognised as ours
        claude = self.read('claude')['hooks']
        self.assertEqual(claude, {
            'PostToolUse': [{'matcher': 'Edit|Write|NotebookEdit', 'hooks': [
                {'type': 'command', 'command': self.command('claude', 'tool'), 'timeout': 10}]}],
            'Stop': [{'hooks': [{'type': 'command', 'command': self.command('claude', 'stop'), 'timeout': 10}]}],
        })
        self.assertIn(str(self.hook), claude['Stop'][0]['hooks'][0]['command'].replace("'", ''))
        codex = self.read('codex')['hooks']
        self.assertEqual(codex['PostToolUse'][0]['matcher'], 'Edit|Write')
        self.assertIn('hook tool --cli codex', codex['PostToolUse'][0]['hooks'][0]['command'])
        self.assertNotIn('matcher', codex['Stop'][0])
        self.assertIn('hook stop --cli codex', codex['Stop'][0]['hooks'][0]['command'])

    def test_antigravity_gets_two_named_entries_in_its_two_shapes(self):
        self.install(('agy',), apply=True)
        self.assertEqual(self.read('agy'), {
            AGY_TOOL: {'PostToolUse': [{
                'matcher': 'write_to_file|replace_file_content|multi_replace_file_content',
                'hooks': [{'type': 'command', 'command': self.command('agy', 'tool'), 'timeout': 10}]}]},
            AGY_STOP: {'Stop': [{'type': 'command', 'command': self.command('agy', 'stop'), 'timeout': 10}]},
        })

    def test_pi_has_no_hook_file(self):
        self.assertIsNone(self.path('pi'))
        self.assertEqual(self.install(('pi',), apply=True), 0)

    def test_a_hook_file_without_a_format_is_refused(self):
        data = json.loads(installer.REGISTRY.read_text())
        data['clis']['pi']['hooks'] = '~/.pi/agent/hooks.json'
        listed = self.home / 'ai-clis.json'
        listed.write_text(json.dumps(data))
        with patch.object(installer, 'REGISTRY', listed), self.assertRaisesRegex(ValueError, 'No hook format for pi'):
            self.install(('pi',))

    def test_keeps_other_hooks_and_settings(self):
        bash = {'matcher': 'Bash', 'hooks': [OTHERS]}
        self.write('claude', {'model': 'opus', 'hooks': {'Stop': [THEIRS], 'PostToolUse': [bash], 'PreToolUse': [THEIRS]}})
        self.write('agy', {'lint': {'Stop': [OTHERS]}})
        self.install(apply=True)
        data = self.read('claude')
        self.assertEqual(data['model'], 'opus')
        self.assertEqual(data['hooks']['PreToolUse'], [THEIRS])
        self.assertEqual(data['hooks']['Stop'][0], THEIRS)  # theirs first, ours appended
        self.assertEqual(len(data['hooks']['Stop']), 2)
        self.assertEqual(data['hooks']['PostToolUse'][0], bash)
        self.assertEqual(len(data['hooks']['PostToolUse']), 2)
        self.assertEqual(self.read('agy')['lint'], {'Stop': [OTHERS]})

    def test_moved_repo_replaces_its_own_entry_in_place(self):
        self.install(apply=True)
        self.hook = self.home / 'moved/skills/daily-log/scripts/daily_log.py'
        self.assertEqual(self.install(apply=True), 3)
        for event in ('PostToolUse', 'Stop'):
            groups = self.read('codex')['hooks'][event]
            self.assertEqual(len(groups), 1)
            self.assertIn('moved', groups[0]['hooks'][0]['command'])
        agy = self.read('agy')
        self.assertIn('moved', agy[AGY_TOOL]['PostToolUse'][0]['hooks'][0]['command'])
        self.assertIn('moved', agy[AGY_STOP]['Stop'][0]['command'])
        self.assertEqual(self.install(), 0)

    def test_a_foreign_handler_in_our_group_survives_a_reinstall_and_stays_put(self):
        self.install(('claude',), apply=True)
        data = self.read('claude')
        data['hooks']['Stop'][0]['hooks'].append(OTHERS)  # added by hand beside ours
        data['hooks']['PostToolUse'].insert(0, THEIRS)
        self.write('claude', data)
        self.hook = self.home / 'moved/skills/daily-log/scripts/daily_log.py'
        self.assertEqual(self.install(('claude',), apply=True), 1)
        events = self.read('claude')['hooks']
        self.assertEqual(len(events['Stop']), 2)
        self.assertIn('moved', events['Stop'][0]['hooks'][0]['command'])  # ours, where our group stood
        self.assertEqual(events['Stop'][1], THEIRS)
        self.assertEqual(events['PostToolUse'][0], THEIRS)
        self.assertIn('moved', events['PostToolUse'][1]['hooks'][0]['command'])
        self.assertEqual(self.install(('claude',)), 0)

    def test_a_repeated_group_of_ours_collapses_to_one(self):
        self.install(('codex',), apply=True)
        data = self.read('codex')
        data['hooks']['Stop'] = [copy.deepcopy(data['hooks']['Stop'][0]), THEIRS, data['hooks']['Stop'][0]]
        self.write('codex', data)
        self.assertEqual(self.install(('codex',), apply=True), 1)
        stop = self.read('codex')['hooks']['Stop']
        self.assertEqual([hooks.holds_ours(group) for group in stop], [True, False])
        self.assertEqual(stop[1], THEIRS)
        self.assertEqual(self.install(('codex',)), 0)

    def test_refuses_what_it_did_not_create(self):
        ours = hooks.handler('agy', 'stop', self.hook)
        refused = {
            'bare handler in the stop entry': {AGY_STOP: {'Stop': [OTHERS]}},
            'matcher group in the tool entry': {AGY_TOOL: {'PostToolUse': [{'matcher': 'x', 'hooks': [OTHERS]}]}},
            'ours and theirs together': {AGY_STOP: {'Stop': [ours, OTHERS]}},
            'theirs inside a group of ours': {AGY_TOOL: {'PostToolUse': [{'hooks': [ours, OTHERS]}]}},
            'an empty entry': {AGY_TOOL: {}},
            'a list where an entry belongs': {AGY_STOP: [ours]},
        }
        for what, seed in refused.items():
            with self.subTest(what):
                self.write('agy', seed)
                before = self.path('agy').read_bytes()
                for apply in (False, True):
                    with self.assertRaisesRegex(ValueError, 'refusing'):
                        self.install(('agy',), apply=apply)
                self.assertEqual(self.path('agy').read_bytes(), before)  # the other entry was not written either

    def test_recognises_its_own_entry_in_either_shape(self):
        ours = hooks.handler('agy', 'tool', self.hook)
        for entry in ({'PostToolUse': [ours]}, {'PostToolUse': [{'matcher': 'x', 'hooks': [ours]}]},
                      {'enabled': False, 'Stop': [ours], 'PostToolUse': [{'hooks': [ours]}]}):
            hooks.check_agy_entry({AGY_TOOL: entry}, AGY_TOOL)
        hooks.check_agy_entry({}, AGY_TOOL)  # nothing there yet

    def test_antigravity_keeps_the_enabled_switch_on_its_entries(self):
        self.install(('agy',), apply=True)
        data = self.read('agy')
        data[AGY_TOOL] = {'enabled': False, **data[AGY_TOOL]}
        self.write('agy', data)
        self.assertEqual(self.install(('agy',)), 0)
        self.hook = self.home / 'moved/skills/daily-log/scripts/daily_log.py'
        self.assertEqual(self.install(('agy',), apply=True), 1)
        entry = self.read('agy')[AGY_TOOL]
        self.assertIs(entry['enabled'], False)
        self.assertIn('moved', entry['PostToolUse'][0]['hooks'][0]['command'])
        self.assertEqual(self.install(('agy',), apply=True, uninstall=True), 1)
        self.assertEqual(self.read('agy'), {})

    def test_refuses_symlinked_file(self):
        real = self.home / 'elsewhere.json'
        real.write_text('{}')
        for cli in hooks.EVENTS:
            with self.subTest(cli):
                self.path(cli).symlink_to(real)
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    self.install((cli,), apply=True)
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    self.install((cli,), apply=True, uninstall=True)
                self.path(cli).unlink()
        self.assertEqual(real.read_text(), '{}')

    def test_refuses_a_file_that_is_not_a_json_object(self):
        for text in ('[]', '{"hooks": []}', '{"hooks": {"Stop": {}}}'):
            with self.subTest(text):
                self.path('claude').write_text(text)
                with self.assertRaises(ValueError):
                    self.install(('claude',), apply=True)
                self.assertEqual(self.path('claude').read_text(), text)

    def test_missing_script_still_exits_zero(self):
        for mode in ('tool', 'stop'):
            command = hooks.handler('claude', mode, self.home / 'gone/skills/daily-log/scripts/daily_log.py')['command']
            run = subprocess.run(['sh', '-c', command], input='{}', capture_output=True, text=True)
            self.assertEqual(run.returncode, 0)
            self.assertTrue(hooks.is_ours({'command': command}))

    def test_skips_a_cli_that_is_not_set_up(self):
        (self.home / '.codex').rmdir()
        self.assertEqual(self.install(), 2)
        self.assertFalse((self.home / '.codex').exists())  # nothing is created for it

    def test_backs_up_what_it_replaces(self):
        self.write('claude', {'model': 'opus'})
        original = self.path('claude').read_text()
        self.install(apply=True)
        (backup,) = (self.home / installer.STATE / 'settings').glob('backup-*')
        self.assertEqual((backup / '.claude/settings.json').read_text(), original)
        self.assertFalse((backup / '.codex/hooks.json').exists())  # it did not exist yet

    def test_a_failed_write_puts_every_file_back(self):
        seeds = self.seed()
        original, last, failed = installer.put, self.path('agy'), []

        def fail_last(path, wanted):
            if path == last and not failed:  # the last file to be written, once; the rollback goes through
                failed.append(path)
                raise OSError('injected')
            original(path, wanted)

        with patch.object(installer, 'put', fail_last), self.assertRaises(OSError):
            self.install(apply=True)
        for cli, data in seeds.items():
            self.assertEqual(self.read(cli), data)

    def seed(self):
        seeds = {
            'claude': {'model': 'opus', 'hooks': {'Stop': [THEIRS], 'PreToolUse': [THEIRS]}},
            'codex': {'hooks': {'PostToolUse': [{'matcher': 'Bash', 'hooks': [OTHERS]}]}},
            'agy': {'lint': {'Stop': [OTHERS]}},
        }
        for cli, data in seeds.items():
            self.write(cli, data)
        return seeds

    def test_uninstall_restores_each_file(self):
        seeds = self.seed()
        self.install(apply=True)
        self.assertNotEqual(self.read('claude'), seeds['claude'])
        self.assertEqual(self.install(apply=True, uninstall=True), 3)
        for cli, data in seeds.items():
            self.assertEqual(self.read(cli), data)

    def test_uninstall_drops_emptied_events_and_hooks_key(self):
        self.install(apply=True)
        self.assertEqual(self.install(apply=True, uninstall=True), 3)
        for cli in hooks.EVENTS:
            self.assertEqual(self.read(cli), {})

    def test_uninstall_keeps_foreign_handler_in_our_group(self):
        self.install(('claude',), apply=True)
        data = self.read('claude')
        for event in ('PostToolUse', 'Stop'):
            data['hooks'][event][0]['hooks'].append(OTHERS)
        self.write('claude', data)
        self.install(('claude',), apply=True, uninstall=True)
        self.assertEqual(self.read('claude'), {'hooks': {
            'PostToolUse': [{'matcher': 'Edit|Write|NotebookEdit', 'hooks': [OTHERS]}], 'Stop': [THEIRS]}})

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
        self.write('agy', {AGY_STOP: {'Stop': [OTHERS]}})
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(('agy',), apply=True, uninstall=True)
        self.write('agy', {AGY_TOOL: {'PostToolUse': [{'matcher': 'x', 'hooks': [OTHERS]}]}})
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
            self.assertEqual(hooks.run(self.home, 'all', True, False, self.hook), 3)  # + the guard; agy out
            self.assertEqual(hooks.run(self.home, 'all', False, False, self.hook), 0)
        self.assertEqual(self.read('agy'), seeds['agy'])
        self.assertEqual(sorted(self.read('claude')['hooks']), ['PostToolUse', 'PreToolUse', 'SessionEnd', 'Stop'])

    def test_run_installs_the_guard_beside_daily_log_and_uninstall_takes_both(self):
        guard = self.home / 'repo/skills/worktree-guard/scripts/worktree_guard.py'

        def guard_command(cli, kind):
            return shlex.join(['python3', str(guard), 'hook', kind, '--cli', cli]) + ' || true'

        with redirect_stdout(io.StringIO()):
            self.assertEqual(hooks.run(self.home, 'all', True, False, self.hook), 3)
        claude = self.read('claude')['hooks']
        self.assertEqual(claude['PreToolUse'], [{'matcher': 'Edit|Write|NotebookEdit|Bash', 'hooks': [
            {'type': 'command', 'command': guard_command('claude', 'pre'), 'timeout': 60}]}])
        self.assertEqual(claude['SessionEnd'], [{'hooks': [
            {'type': 'command', 'command': guard_command('claude', 'end'), 'timeout': 60}]}])
        self.assertEqual(claude['Stop'][0]['hooks'][0]['command'], self.command('claude', 'stop'))
        self.assertEqual(self.read('codex')['hooks']['PreToolUse'][0]['matcher'], 'Edit|Write|Bash')
        agy = self.read('agy')
        self.assertEqual(sorted(agy), [AGY_STOP, AGY_TOOL, 'ai-dotfiles-worktree-guard-pre'])
        pre = agy['ai-dotfiles-worktree-guard-pre']['PreToolUse'][0]
        self.assertIn('run_command', pre['matcher'])
        self.assertIn('view_file', pre['matcher'])
        self.assertEqual(pre['hooks'][0]['command'], guard_command('agy', 'pre'))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(hooks.run(self.home, 'all', False, False, self.hook), 0)
            self.assertEqual(hooks.run(self.home, 'all', True, True, self.hook), 3)
        for cli in hooks.EVENTS:
            self.assertEqual(self.read(cli), {})

    def test_every_feature_script_exists(self):
        for feature in hooks.features():
            self.assertTrue(feature.script.is_file(), feature.name)
            self.assertEqual(feature.script, ROOT / feature.mark)

    def test_run_follows_the_target_and_uninstall_ignores_the_switches(self):
        with patch.object(installer, 'REGISTRY', registry(self.home, agy=False)), redirect_stdout(io.StringIO()):
            self.assertEqual(hooks.run(self.home, 'all', True, False, self.hook), 2)  # agy is off: no file
            self.assertFalse(self.path('agy').exists())
            self.assertEqual(hooks.run(self.home, 'claude', True, True, self.hook), 1)
            self.assertEqual(self.read('claude'), {})
            self.assertIn('hooks', self.read('codex'))  # not selected
            self.assertEqual(hooks.run(self.home, 'agy', True, True, self.hook), 0)  # nothing of ours there
            with self.assertRaisesRegex(ValueError, 'unknown target'):
                hooks.run(self.home, 'gemini', False, False, self.hook)


if __name__ == '__main__':
    unittest.main()
