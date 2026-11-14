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
agent_hooks = load('agent_hooks.py')

OTHERS = {'type': 'command', 'command': 'echo mine'}  # a handler this script did not write
THEIRS = {'hooks': [OTHERS]}  # and a group holding only it
AGY_PRE = 'ai-dotfiles-worktree-guard-pre'
AGY_COMMITS = 'ai-dotfiles-small-commits-pre'
OLD_MARK = 'skills/daily-log/scripts/daily_log.py'  # the retired Stop nudge
OLD_TOOL, OLD_STOP = 'ai-dotfiles-daily-log-tool', 'ai-dotfiles-daily-log-stop'


def old_handler(cli, mode, repo='/elsewhere/repo'):
    command = shlex.join(['python3', f'{repo}/{OLD_MARK}', 'hook', mode, '--cli', cli]) + ' || true'
    return {'type': 'command', 'command': command, 'timeout': 10}


class InstallHooksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hooks 空間 ')
        self.home = Path(self.temp.name).resolve()
        for folder in ('.claude', '.codex', '.gemini/config'):
            (self.home / folder).mkdir(parents=True)
        self.repo = self.home / 'repo'
        self.output = ''

    def tearDown(self):
        self.temp.cleanup()

    @property
    def guard(self):
        return self.repo / hooks.GUARD_MARK

    @property
    def commits(self):
        return self.repo / hooks.COMMITS_MARK

    def install(self, clis=agent_hooks.HOOK_FILE_CLIS, apply=False, uninstall=False):
        out = io.StringIO()
        with redirect_stdout(out):
            count = hooks.install(self.home, () if uninstall else clis, clis if uninstall else (), apply,
                                  hooks.features(self.repo))
        self.output = out.getvalue()
        return count

    def path(self, cli):
        return installer.path(self.home, cli, 'hooks')

    def read(self, cli):
        return json.loads(self.path(cli).read_text())

    def write(self, cli, data):
        self.path(cli).write_text(json.dumps(data))

    def command(self, cli, mode, script=None):
        return shlex.join(['python3', str(script or self.guard), 'hook', mode, '--cli', cli]) + ' || true'

    def test_the_marker_names_the_script_the_hooks_run(self):
        guard, commits = hooks.features()
        for feature, mark in ((guard, hooks.GUARD_MARK), (commits, hooks.COMMITS_MARK)):
            self.assertEqual(feature.script, ROOT / mark)
            self.assertEqual(feature.mark, mark)
            self.assertTrue(feature.script.is_file())

    def test_a_cloud_install_takes_the_commit_gate_and_leaves_the_guard_out(self):
        """A cloud session already works alone on its own branch, so worktree-guard stays off its VM."""
        self.assertEqual([f.name for f in hooks.features(self.repo, cloud=True)], ['small-commits'])
        with redirect_stdout(io.StringIO()):
            hooks.run(self.home, 'claude', True, False, repo=self.repo, cloud=True)
        data = json.loads((self.home / '.claude/settings.json').read_text())
        self.assertEqual(sorted(data['hooks']), ['PreToolUse'])
        commands = [h['command'] for group in data['hooks']['PreToolUse'] for h in group['hooks']]
        self.assertEqual(len(commands), 1)
        self.assertIn(hooks.COMMITS_MARK, commands[0])

    def test_the_registry_and_the_hook_formats_agree_on_which_clis_have_a_hook_file(self):
        have = {cli for cli in installer.clis() if installer.path(self.home, cli, 'hooks')}
        self.assertEqual(have, set(agent_hooks.HOOK_FILE_CLIS))

    def test_preview_then_apply_then_nothing_left(self):
        self.assertEqual(self.install(), 3)
        self.assertNotIn('approve', self.output)
        self.assertFalse(self.path('claude').exists())
        self.install(apply=True)
        self.assertIn('Codex: approve the new hooks once with /hooks', self.output)
        self.assertEqual(self.install(), 0)  # agy too: its entry is recognised as ours
        claude = self.read('claude')['hooks']
        self.assertEqual(claude, {
            'PreToolUse': [
                {'matcher': 'Edit|Write|NotebookEdit|Bash', 'hooks': [
                    {'type': 'command', 'command': self.command('claude', 'pre'), 'timeout': 60}]},
                {'matcher': 'Bash', 'hooks': [
                    {'type': 'command', 'command': self.command('claude', 'pre', self.commits), 'timeout': 30}]}],
            'SessionEnd': [{'hooks': [{'type': 'command', 'command': self.command('claude', 'end'), 'timeout': 60}]}],
            'WorktreeCreate': [{'hooks': [{'type': 'command', 'command': self.command('claude', 'create'), 'timeout': 60}]}],
            'WorktreeRemove': [{'hooks': [{'type': 'command', 'command': self.command('claude', 'remove'), 'timeout': 60}]}],
        })
        self.assertIn(str(self.guard), claude['SessionEnd'][0]['hooks'][0]['command'].replace("'", ''))
        codex = self.read('codex')['hooks']
        self.assertEqual([g['matcher'] for g in codex['PreToolUse']], ['Edit|Write|Bash', 'Bash'])
        self.assertIn('hook pre --cli codex', codex['PreToolUse'][0]['hooks'][0]['command'])
        self.assertIn(str(self.commits), codex['PreToolUse'][1]['hooks'][0]['command'].replace("'", ''))
        self.assertEqual(sorted(codex), ['PreToolUse', 'SessionEnd'])  # worktree events are Claude's alone
        self.assertNotIn('matcher', codex['SessionEnd'][0])
        self.assertIn('hook end --cli codex', codex['SessionEnd'][0]['hooks'][0]['command'])

    def test_antigravity_gets_one_named_entry_with_a_matcher_group_and_no_session_end(self):
        self.install(('agy',), apply=True)
        data = self.read('agy')
        self.assertEqual(list(data), [AGY_PRE, AGY_COMMITS])
        (pre,) = data[AGY_PRE]['PreToolUse']
        for tool in ('write_to_file', 'run_command', 'view_file'):
            self.assertIn(tool, pre['matcher'])
        self.assertEqual(pre['hooks'], [{'type': 'command', 'command': self.command('agy', 'pre'), 'timeout': 60}])
        (commits,) = data[AGY_COMMITS]['PreToolUse']
        self.assertEqual(commits, {'matcher': 'run_command', 'hooks': [
            {'type': 'command', 'command': self.command('agy', 'pre', self.commits), 'timeout': 30}]})

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
        self.write('claude', {'model': 'opus', 'hooks': {'SessionEnd': [THEIRS], 'PreToolUse': [bash], 'Stop': [THEIRS]}})
        self.write('agy', {'lint': {'Stop': [OTHERS]}})
        self.install(apply=True)
        data = self.read('claude')
        self.assertEqual(data['model'], 'opus')
        self.assertEqual(data['hooks']['Stop'], [THEIRS])
        self.assertEqual(data['hooks']['SessionEnd'][0], THEIRS)  # theirs first, ours appended
        self.assertEqual(len(data['hooks']['SessionEnd']), 2)
        self.assertEqual(data['hooks']['PreToolUse'][0], bash)
        self.assertEqual(len(data['hooks']['PreToolUse']), 3)  # theirs, then one group per feature
        self.assertEqual(self.read('agy')['lint'], {'Stop': [OTHERS]})

    def test_moved_repo_replaces_its_own_entry_in_place(self):
        self.install(apply=True)
        self.repo = self.home / 'moved'
        self.assertEqual(self.install(apply=True), 3)
        for event, count in (('PreToolUse', 2), ('SessionEnd', 1)):
            groups = self.read('codex')['hooks'][event]
            self.assertEqual(len(groups), count)
            for group in groups:
                self.assertIn('moved', group['hooks'][0]['command'])
        for name in (AGY_PRE, AGY_COMMITS):
            self.assertIn('moved', self.read('agy')[name]['PreToolUse'][0]['hooks'][0]['command'])
        self.assertEqual(self.install(), 0)

    def test_a_foreign_handler_in_our_group_survives_a_reinstall_and_stays_put(self):
        self.install(('claude',), apply=True)
        data = self.read('claude')
        data['hooks']['SessionEnd'][0]['hooks'].append(OTHERS)  # added by hand beside ours
        data['hooks']['PreToolUse'].insert(0, THEIRS)
        self.write('claude', data)
        self.repo = self.home / 'moved'
        self.assertEqual(self.install(('claude',), apply=True), 1)
        events = self.read('claude')['hooks']
        self.assertEqual(len(events['SessionEnd']), 2)
        self.assertIn('moved', events['SessionEnd'][0]['hooks'][0]['command'])  # ours, where our group stood
        self.assertEqual(events['SessionEnd'][1], THEIRS)
        self.assertEqual(events['PreToolUse'][0], THEIRS)
        self.assertIn('moved', events['PreToolUse'][1]['hooks'][0]['command'])
        self.assertEqual(self.install(('claude',)), 0)

    def test_a_repeated_group_of_ours_collapses_to_one(self):
        self.install(('codex',), apply=True)
        data = self.read('codex')
        ours = data['hooks']['SessionEnd'][0]
        data['hooks']['SessionEnd'] = [copy.deepcopy(ours), THEIRS, ours]
        self.write('codex', data)
        self.assertEqual(self.install(('codex',), apply=True), 1)
        end = self.read('codex')['hooks']['SessionEnd']
        self.assertEqual([hooks.holds_ours(group, hooks.GUARD_MARK) for group in end], [True, False])
        self.assertEqual(end[1], THEIRS)
        self.assertEqual(self.install(('codex',)), 0)

    def test_refuses_what_it_did_not_create(self):
        ours = hooks.handler('agy', 'pre', self.guard, 60)
        refused = {
            'bare handler in our entry': {AGY_PRE: {'PreToolUse': [OTHERS]}},
            'matcher group with theirs': {AGY_PRE: {'PreToolUse': [{'matcher': 'x', 'hooks': [OTHERS]}]}},
            'ours and theirs together': {AGY_PRE: {'PreToolUse': [ours, OTHERS]}},
            'theirs inside a group of ours': {AGY_PRE: {'PreToolUse': [{'hooks': [ours, OTHERS]}]}},
            'an empty entry': {AGY_PRE: {}},
            'a list where an entry belongs': {AGY_PRE: [ours]},
        }
        for what, seed in refused.items():
            with self.subTest(what):
                self.write('agy', seed)
                before = self.path('agy').read_bytes()
                for apply in (False, True):
                    with self.assertRaisesRegex(ValueError, 'refusing'):
                        self.install(('agy',), apply=apply)
                self.assertEqual(self.path('agy').read_bytes(), before)

    def test_recognises_its_own_entry_in_either_shape(self):
        ours = hooks.handler('agy', 'pre', self.guard, 60)
        for entry in ({'PreToolUse': [ours]}, {'PreToolUse': [{'matcher': 'x', 'hooks': [ours]}]},
                      {'enabled': False, 'PreToolUse': [{'hooks': [ours]}]}):
            hooks.check_agy_entry({AGY_PRE: entry}, AGY_PRE, hooks.GUARD_MARK)
        hooks.check_agy_entry({}, AGY_PRE, hooks.GUARD_MARK)  # nothing there yet

    def test_antigravity_keeps_the_enabled_switch_on_its_entry(self):
        self.install(('agy',), apply=True)
        data = self.read('agy')
        data[AGY_PRE] = {'enabled': False, **data[AGY_PRE]}
        self.write('agy', data)
        self.assertEqual(self.install(('agy',)), 0)
        self.repo = self.home / 'moved'
        self.assertEqual(self.install(('agy',), apply=True), 1)
        entry = self.read('agy')[AGY_PRE]
        self.assertIs(entry['enabled'], False)
        self.assertIn('moved', entry['PreToolUse'][0]['hooks'][0]['command'])
        self.assertEqual(self.install(('agy',), apply=True, uninstall=True), 1)
        self.assertEqual(self.read('agy'), {})

    def test_refuses_symlinked_file(self):
        real = self.home / 'elsewhere.json'
        real.write_text('{}')
        for cli in agent_hooks.HOOK_FILE_CLIS:
            with self.subTest(cli):
                self.path(cli).symlink_to(real)
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    self.install((cli,), apply=True)
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    self.install((cli,), apply=True, uninstall=True)
                self.path(cli).unlink()
        self.assertEqual(real.read_text(), '{}')

    def test_refuses_a_file_that_is_not_a_json_object(self):
        for text in ('[]', '{"hooks": []}', '{"hooks": {"PreToolUse": {}}}'):
            with self.subTest(text):
                self.path('claude').write_text(text)
                with self.assertRaises(ValueError):
                    self.install(('claude',), apply=True)
                self.assertEqual(self.path('claude').read_text(), text)

    def test_missing_script_still_exits_zero(self):
        for mode in ('pre', 'end'):
            command = hooks.handler('claude', mode, self.home / 'gone' / hooks.GUARD_MARK, 60)['command']
            run = subprocess.run(['sh', '-c', command], input='{}', capture_output=True, text=True)
            self.assertEqual(run.returncode, 0)
            self.assertTrue(hooks.is_ours({'command': command}, hooks.GUARD_MARK))

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
            'claude': {'model': 'opus', 'hooks': {'Stop': [THEIRS], 'SessionEnd': [THEIRS]}},
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
        for cli in agent_hooks.HOOK_FILE_CLIS:
            self.assertEqual(self.read(cli), {})

    def test_uninstall_keeps_foreign_handler_in_our_group(self):
        self.install(('claude',), apply=True)
        data = self.read('claude')
        for event in ('PreToolUse', 'SessionEnd'):
            data['hooks'][event][0]['hooks'].append(OTHERS)
        self.write('claude', data)
        self.install(('claude',), apply=True, uninstall=True)
        self.assertEqual(self.read('claude'), {'hooks': {
            'PreToolUse': [{'matcher': 'Edit|Write|NotebookEdit|Bash', 'hooks': [OTHERS]}], 'SessionEnd': [THEIRS]}})

    def test_the_worktree_entries_are_claudes_alone_and_uninstall_takes_back_only_ours(self):
        self.write('claude', {'hooks': {'WorktreeCreate': [THEIRS]}})
        self.install(apply=True)
        data = self.read('claude')['hooks']
        self.assertEqual(data['WorktreeCreate'][0], THEIRS)  # theirs first, ours appended
        self.assertEqual([g['hooks'][0]['command'] for g in data['WorktreeCreate'][1:]], [self.command('claude', 'create')])
        self.assertEqual(self.install(), 0)
        for cli in ('codex', 'agy'):
            self.assertNotIn('Worktree', json.dumps(self.read(cli)), cli)
        self.install(apply=True, uninstall=True)
        self.assertEqual(self.read('claude'), {'hooks': {'WorktreeCreate': [THEIRS]}})

    def test_uninstall_is_idempotent(self):
        self.seed()
        self.install(apply=True)
        self.install(apply=True, uninstall=True)
        self.assertEqual(self.install(apply=True, uninstall=True), 0)
        self.assertEqual(self.install(uninstall=True), 0)

    def test_uninstall_dry_run_writes_nothing(self):
        self.seed()
        self.install(apply=True)
        before = {cli: self.path(cli).read_bytes() for cli in agent_hooks.HOOK_FILE_CLIS}
        self.assertEqual(self.install(uninstall=True), 3)
        for cli, data in before.items():
            self.assertEqual(self.path(cli).read_bytes(), data)

    def test_uninstall_refuses_what_it_did_not_create(self):
        self.write('agy', {AGY_PRE: {'PreToolUse': [OTHERS]}})
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(('agy',), apply=True, uninstall=True)
        self.write('agy', {AGY_PRE: {'PreToolUse': [{'matcher': 'x', 'hooks': [OTHERS]}]}})
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
            self.assertEqual(hooks.run(self.home, 'all', True, False, self.repo), 1)  # agy out
            self.assertEqual(hooks.run(self.home, 'all', False, False, self.repo), 0)
        self.assertEqual(self.read('agy'), seeds['agy'])
        self.assertEqual(sorted(self.read('claude')['hooks']), ['PreToolUse', 'SessionEnd', 'Stop', 'WorktreeCreate', 'WorktreeRemove'])

    def test_run_follows_the_target_and_uninstall_ignores_the_switches(self):
        with patch.object(installer, 'REGISTRY', registry(self.home, agy=False)), redirect_stdout(io.StringIO()):
            self.assertEqual(hooks.run(self.home, 'all', True, False, self.repo), 2)  # agy is off: no file
            self.assertFalse(self.path('agy').exists())
            self.assertEqual(hooks.run(self.home, 'claude', True, True, self.repo), 1)
            self.assertEqual(self.read('claude'), {})
            self.assertIn('hooks', self.read('codex'))  # not selected
            self.assertEqual(hooks.run(self.home, 'agy', True, True, self.repo), 0)  # nothing of ours there
            with self.assertRaisesRegex(ValueError, 'unknown target'):
                hooks.run(self.home, 'gemini', False, False, self.repo)

    # --- the retired daily-log nudge --------------------------------------------------------

    def seed_retired(self):
        """The hook files as the daily-log install of October 2026 left them, plus its state folder."""
        self.write('claude', {'model': 'opus', 'hooks': {
            'PostToolUse': [{'matcher': 'Edit|Write|NotebookEdit', 'hooks': [old_handler('claude', 'tool')]}],
            'Stop': [{'hooks': [old_handler('claude', 'stop')]}, THEIRS]}})
        self.write('codex', {'hooks': {
            'PostToolUse': [{'matcher': 'Edit|Write', 'hooks': [old_handler('codex', 'tool'), OTHERS]}],
            'Stop': [{'hooks': [old_handler('codex', 'stop')]}]}})
        self.write('agy', {
            OLD_TOOL: {'PostToolUse': [{'matcher': 'write_to_file', 'hooks': [old_handler('agy', 'tool')]}]},
            OLD_STOP: {'enabled': False, 'Stop': [old_handler('agy', 'stop')]},
            'lint': {'Stop': [OTHERS]}})
        state = self.home / hooks.RETIRED_STATE[0]
        state.mkdir(parents=True)
        (state / 'session.json').write_text('{}')
        return state

    def test_install_retires_the_daily_log_nudge_and_its_state_folder(self):
        state = self.seed_retired()
        self.assertEqual(self.install(), 4)  # three files and the folder
        self.assertIn('Would remove folder', self.output)
        self.assertTrue(state.is_dir())  # a preview
        self.assertEqual(self.install(apply=True), 4)
        self.assertFalse(state.exists())
        claude = self.read('claude')
        self.assertEqual(claude['model'], 'opus')
        self.assertEqual(sorted(claude['hooks']), ['PreToolUse', 'SessionEnd', 'Stop', 'WorktreeCreate', 'WorktreeRemove'])
        self.assertEqual(claude['hooks']['Stop'], [THEIRS])  # the foreign group stays, ours is gone
        codex = self.read('codex')['hooks']
        self.assertEqual(codex['PostToolUse'], [{'matcher': 'Edit|Write', 'hooks': [OTHERS]}])  # theirs kept
        self.assertNotIn('Stop', codex)
        agy = self.read('agy')
        self.assertEqual(sorted(agy), [AGY_COMMITS, AGY_PRE, 'lint'])
        self.assertEqual(self.install(), 0)

    def test_uninstall_retires_the_daily_log_nudge_too(self):
        self.seed_retired()
        self.assertEqual(self.install(apply=True, uninstall=True), 4)
        for cli in ('claude', 'codex'):
            text = self.path(cli).read_text()
            self.assertNotIn(OLD_MARK, text, cli)
        self.assertEqual(self.read('claude'), {'model': 'opus', 'hooks': {'Stop': [THEIRS]}})
        self.assertEqual(sorted(self.read('agy')), ['lint'])

    def test_a_hand_made_entry_under_a_retired_name_stays(self):
        self.write('agy', {OLD_STOP: {'Stop': [OTHERS]}, OLD_TOOL: {'PostToolUse': [old_handler('agy', 'tool')]}})
        self.install(('agy',), apply=True)
        data = self.read('agy')
        self.assertEqual(data[OLD_STOP], {'Stop': [OTHERS]})
        self.assertNotIn(OLD_TOOL, data)
        self.assertIn(AGY_PRE, data)

    def test_retire_leaves_a_file_without_old_entries_alone(self):
        self.seed()
        self.assertEqual(self.install(), 3)  # the guard's own changes only, no folder
        self.assertNotIn('remove folder', self.output)


if __name__ == '__main__':
    unittest.main()
