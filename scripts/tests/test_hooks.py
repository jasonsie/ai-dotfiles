import copy
import io
import json
from contextlib import redirect_stdout
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT, load, registry
import installer

hooks = load('install/hooks.py')
agent_hooks = load('agent_hooks.py')

OTHERS = {'type': 'command', 'command': 'echo mine'}  # a handler this script did not write
THEIRS = {'hooks': [OTHERS]}  # and a group holding only it
AGY_PRE = 'ai-dotfiles-hook-pre'
OLD_GUARD, OLD_COMMITS = 'ai-dotfiles-worktree-guard-pre', 'ai-dotfiles-small-commits-pre'  # per feature, before the door
OLD_MARK = 'skills/daily-log/scripts/daily_log.py'  # the retired Stop nudge
GUARD, COMMITS, TITLE = (f'skills/{name}/scripts/{name.replace("-", "_")}.py'
                         for name in ('worktree-guard', 'small-commits', 'herdr-title'))
OLD_TOOL, OLD_STOP = 'ai-dotfiles-daily-log-tool', 'ai-dotfiles-daily-log-stop'
CLAUDE_EVENTS = ['Elicitation', 'PermissionRequest', 'PreToolUse', 'SessionEnd', 'SessionStart', 'Stop', 'StopFailure',
                 'UserPromptSubmit', 'WorktreeCreate', 'WorktreeRemove']  # every event the three features use


def old_handler(cli, mode, repo='/elsewhere/repo', script=OLD_MARK, timeout=10):
    """A handler as an earlier hooks.py wrote it: python3 and a script in the checkout."""
    command = shlex.join(['python3', f'{repo}/{script}', 'hook', mode, '--cli', cli]) + ' || true'
    return {'type': 'command', 'command': command, 'timeout': timeout}


def door(kind, cli='claude', timeout=10):
    return {'type': 'command', 'command': f'~/.local/bin/ai-dotfiles hook {kind} --cli {cli} || true', 'timeout': timeout}


class InstallHooksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hooks 空間 ')
        self.home = Path(self.temp.name).resolve()
        for folder in ('.claude', '.codex', '.gemini/config'):
            (self.home / folder).mkdir(parents=True)
        self.chosen = hooks.declared.find()
        self.output = ''

    def tearDown(self):
        self.temp.cleanup()

    def install(self, clis=agent_hooks.HOOK_FILE_CLIS, apply=False, uninstall=False):
        out = io.StringIO()
        with redirect_stdout(out):
            count = hooks.install(self.home, () if uninstall else clis, clis if uninstall else (), apply,
                                  self.chosen, python=None)
        self.output = out.getvalue()
        return count

    def path(self, cli):
        return installer.path(self.home, cli, 'hooks')

    def read(self, cli):
        return json.loads(self.path(cli).read_text())

    def write(self, cli, data):
        self.path(cli).write_text(json.dumps(data))

    def test_each_entry_runs_the_door_and_names_no_file_in_the_repo(self):
        self.install(apply=True)
        text = ''.join(self.path(cli).read_text() for cli in agent_hooks.HOOK_FILE_CLIS)
        self.assertNotIn(str(ROOT), text)
        self.assertNotIn('skills/', text)
        commands = [h['command'] for cli in ('claude', 'codex') for groups in self.read(cli)['hooks'].values()
                    for group in groups for h in group['hooks']]
        self.assertTrue(all(command.startswith('~/.local/bin/ai-dotfiles hook ') for command in commands))

    def test_a_cloud_install_takes_the_commit_gate_and_leaves_the_guard_out(self):
        """A cloud session already works alone on its own branch, so worktree-guard stays off its VM."""
        with redirect_stdout(io.StringIO()):
            hooks.run(self.home, 'claude', True, False, cloud=True)
        data = json.loads((self.home / '.claude/settings.json').read_text())
        self.assertEqual(data['hooks'], {'PreToolUse': [{'matcher': 'Bash', 'hooks': [door('pre', timeout=60)]}]})

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

        def at(kind, cli='claude', timeout=10):
            return [{'hooks': [door(kind, cli, timeout)]}]

        self.assertEqual(self.read('claude')['hooks'], {  # one entry per event, the union of the features' tools
            'PreToolUse': [{'matcher': 'Edit|Write|NotebookEdit|Bash|AskUserQuestion|ExitPlanMode',
                            'hooks': [door('pre', timeout=60)]}],
            'SessionEnd': at('end', timeout=60), 'UserPromptSubmit': at('prompt'), 'Stop': at('stop'),
            'StopFailure': at('error'), 'PermissionRequest': at('permission'), 'Elicitation': at('form'),
            'SessionStart': at('start'), 'WorktreeCreate': at('create', timeout=60), 'WorktreeRemove': at('remove', timeout=60),
        })
        self.assertEqual(self.read('codex')['hooks'], {  # worktree, error, form and start events are Claude's alone
            'PreToolUse': [{'matcher': 'Edit|Write|Bash', 'hooks': [door('pre', 'codex', 60)]}],
            'SessionEnd': at('end', 'codex', 3), 'Interrupt': at('interrupt', 'codex', 3),  # Codex allows 1 to 3 s
            'UserPromptSubmit': at('prompt', 'codex'), 'Stop': at('stop', 'codex'), 'PermissionRequest': at('permission', 'codex'),
        })

    def test_antigravity_gets_one_named_entry_with_a_matcher_group_and_no_session_end(self):
        self.install(('agy',), apply=True)
        data = self.read('agy')
        self.assertEqual(list(data), [AGY_PRE])
        (pre,) = data[AGY_PRE]['PreToolUse']
        for tool in ('write_to_file', 'run_command', 'view_file'):
            self.assertIn(tool, pre['matcher'])
        self.assertEqual(pre['hooks'], [door('pre', 'agy', 60)])

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
        self.assertEqual(data['hooks']['Stop'][0], THEIRS)  # theirs first, herdr-title's appended
        self.assertEqual(len(data['hooks']['Stop']), 2)
        self.assertEqual(data['hooks']['SessionEnd'][0], THEIRS)  # theirs first, ours appended
        self.assertEqual(len(data['hooks']['SessionEnd']), 2)  # theirs, then the door's
        self.assertEqual(data['hooks']['PreToolUse'][0], bash)
        self.assertEqual(len(data['hooks']['PreToolUse']), 2)  # theirs, then one group for every feature
        self.assertEqual(self.read('agy')['lint'], {'Stop': [OTHERS]})

    def test_a_feature_that_moves_or_changes_its_budget_changes_no_entry(self):
        """Codex trusts a hook by the hash of its entry: an unchanged entry needs no new approval."""
        self.install(apply=True)
        before = {cli: self.path(cli).read_bytes() for cli in agent_hooks.HOOK_FILE_CLIS}
        self.chosen = [hooks.declared.Feature(f.name, Path('/moved') / f.name, f.cloud, Path('/moved/x.py'), f.order,
                                              {kind: seconds + 7 for kind, seconds in f.budget.items()}, f.wants)
                       for f in self.chosen]
        self.assertEqual(self.install(apply=True), 0)
        self.assertEqual({cli: self.path(cli).read_bytes() for cli in agent_hooks.HOOK_FILE_CLIS}, before)

    def test_an_event_no_feature_wants_any_more_loses_its_entry(self):
        self.install(('claude', 'codex'), apply=True)
        self.chosen = [f for f in self.chosen if f.name != 'herdr-title']
        self.assertEqual(self.install(('claude', 'codex'), apply=True), 2)
        self.assertEqual(sorted(self.read('claude')['hooks']), ['PreToolUse', 'SessionEnd', 'WorktreeCreate', 'WorktreeRemove'])
        self.assertEqual(self.read('claude')['hooks']['PreToolUse'][0]['matcher'], 'Edit|Write|NotebookEdit|Bash')
        self.assertEqual(sorted(self.read('codex')['hooks']), ['PreToolUse', 'SessionEnd'])

    def test_a_foreign_handler_in_our_group_survives_a_reinstall_and_stays_put(self):
        self.install(('claude',), apply=True)
        data = self.read('claude')
        data['hooks']['SessionEnd'][0]['hooks'].append(OTHERS)  # added by hand beside ours
        data['hooks']['PreToolUse'].insert(0, THEIRS)
        data['hooks']['SessionEnd'][0]['hooks'][0]['timeout'] = 5  # and ours changed by hand
        self.write('claude', data)
        self.assertEqual(self.install(('claude',), apply=True), 1)
        events = self.read('claude')['hooks']
        self.assertEqual(events['SessionEnd'], [{'hooks': [door('end', timeout=60)]}, THEIRS])  # ours where it stood
        self.assertEqual(events['PreToolUse'][0], THEIRS)
        self.assertEqual(events['PreToolUse'][1]['hooks'], [door('pre', timeout=60)])
        self.assertEqual(self.install(('claude',)), 0)

    def test_a_repeated_group_of_ours_collapses_to_one(self):
        self.install(('codex',), apply=True)
        data = self.read('codex')
        ours = data['hooks']['SessionEnd'][0]
        data['hooks']['SessionEnd'] = [copy.deepcopy(ours), THEIRS, ours]
        self.write('codex', data)
        self.assertEqual(self.install(('codex',), apply=True), 1)
        end = self.read('codex')['hooks']['SessionEnd']
        self.assertEqual([hooks.holds_ours(group) for group in end], [True, False])
        self.assertEqual(end[1], THEIRS)
        self.assertEqual(self.install(('codex',)), 0)

    def test_refuses_what_it_did_not_create(self):
        ours = hooks.handler('agy', 'pre', 60)
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
        ours = hooks.handler('agy', 'pre', 60)
        for entry in ({'PreToolUse': [ours]}, {'PreToolUse': [{'matcher': 'x', 'hooks': [ours]}]},
                      {'enabled': False, 'PreToolUse': [{'hooks': [ours]}]}):
            hooks.check_agy_entry({AGY_PRE: entry}, AGY_PRE)
        hooks.check_agy_entry({}, AGY_PRE)  # nothing there yet

    def test_antigravity_keeps_the_enabled_switch_on_its_entry(self):
        self.install(('agy',), apply=True)
        data = self.read('agy')
        data[AGY_PRE] = {'enabled': False, **data[AGY_PRE]}
        self.write('agy', data)
        self.assertEqual(self.install(('agy',)), 0)
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

    def test_a_missing_door_still_exits_zero(self):
        for kind in ('pre', 'end'):
            command = hooks.handler('claude', kind, 60)['command']
            run = subprocess.run(['sh', '-c', command], input='{}', capture_output=True, text=True,
                                 env={**os.environ, 'HOME': str(self.home)})
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
            'PreToolUse': [{'matcher': 'Edit|Write|NotebookEdit|Bash|AskUserQuestion|ExitPlanMode', 'hooks': [OTHERS]}],
            'SessionEnd': [THEIRS]}})

    def test_the_worktree_entries_are_claudes_alone_and_uninstall_takes_back_only_ours(self):
        self.write('claude', {'hooks': {'WorktreeCreate': [THEIRS]}})
        self.install(apply=True)
        data = self.read('claude')['hooks']
        self.assertEqual(data['WorktreeCreate'][0], THEIRS)  # theirs first, ours appended
        self.assertEqual(data['WorktreeCreate'][1:], [{'hooks': [door('create', timeout=60)]}])
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
            self.assertEqual(hooks.run(self.home, 'all', True, False), 2)  # agy out; the door's Python linked
            self.assertEqual(hooks.run(self.home, 'all', False, False), 0)
        self.assertEqual(self.read('agy'), seeds['agy'])
        self.assertEqual(sorted(self.read('claude')['hooks']), CLAUDE_EVENTS)

    def test_run_follows_the_target_and_uninstall_ignores_the_switches(self):
        with patch.object(installer, 'REGISTRY', registry(self.home, agy=False)), redirect_stdout(io.StringIO()):
            self.assertEqual(hooks.run(self.home, 'all', True, False), 3)  # agy is off: no file; the Python link
            self.assertFalse(self.path('agy').exists())
            self.assertEqual(hooks.run(self.home, 'claude', True, True), 1)
            self.assertEqual(self.read('claude'), {})
            self.assertIn('hooks', self.read('codex'))  # not selected
            self.assertEqual(hooks.run(self.home, 'agy', True, True), 0)  # nothing of ours there
            with self.assertRaisesRegex(ValueError, 'unknown target'):
                hooks.run(self.home, 'gemini', False, False)

    def test_antigravity_gets_no_prompt_entry_and_nothing_is_left_to_do(self):
        self.install(('agy',), apply=True)
        self.assertEqual(list(self.read('agy')), [AGY_PRE])  # no prompt event: herdr-title has nothing there
        self.assertEqual(self.install(('agy',)), 0)
        self.assertEqual(self.install(('agy',), apply=True, uninstall=True), 1)
        self.assertEqual(self.read('agy'), {})
        self.assertEqual(self.install(('agy',), uninstall=True), 0)

    def test_a_hand_made_prompt_hook_stays_on_install_and_on_uninstall(self):
        for cli in ('claude', 'codex'):
            self.write(cli, {'hooks': {'UserPromptSubmit': [THEIRS]}})
        self.install(('claude', 'codex'), apply=True)
        for cli in ('claude', 'codex'):
            groups = self.read(cli)['hooks']['UserPromptSubmit']
            self.assertEqual(groups[0], THEIRS, cli)  # theirs first, ours appended
            self.assertEqual(len(groups), 2, cli)
        self.install(('claude', 'codex'), apply=True, uninstall=True)
        for cli in ('claude', 'codex'):
            self.assertEqual(self.read(cli), {'hooks': {'UserPromptSubmit': [THEIRS]}}, cli)

    def test_uninstall_takes_the_herdr_title_entries_out_and_leaves_no_empty_prompt_event(self):
        self.install(('claude', 'codex'), apply=True)
        self.install(('claude', 'codex'), apply=True, uninstall=True)
        for cli in ('claude', 'codex'):
            self.assertNotIn('herdr_title', self.path(cli).read_text(), cli)
            self.assertNotIn('UserPromptSubmit', self.read(cli), cli)
            self.assertEqual(self.read(cli), {}, cli)

    # --- the Python the door starts -----------------------------------------------------------

    def test_the_door_starts_the_python_the_install_ran_with_until_every_cli_is_uninstalled(self):
        link = self.home / hooks.PYTHON
        with redirect_stdout(io.StringIO()):
            hooks.run(self.home, 'all', True, False)
            self.assertEqual(os.readlink(link), sys.executable)
            self.assertEqual(hooks.run(self.home, 'all', False, False), 0)
            self.assertEqual(hooks.run(self.home, 'claude', False, True), 1)  # a preview: its entries alone
            hooks.run(self.home, 'claude', True, True)
            self.assertTrue(link.is_symlink())  # the other CLIs still run the door
            hooks.run(self.home, 'all', True, True)
            self.assertFalse(link.is_symlink())
            link.write_text('someone else\'s\n')
            with self.assertRaisesRegex(ValueError, 'refusing'):
                hooks.run(self.home, 'all', True, False)

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
        self.assertEqual(sorted(claude['hooks']), CLAUDE_EVENTS)
        self.assertEqual(claude['hooks']['Stop'], [{'hooks': [door('stop')]}, THEIRS])  # the door's where the nudge stood
        self.assertNotIn(OLD_MARK, json.dumps(claude))
        codex = self.read('codex')['hooks']
        self.assertEqual(codex['PostToolUse'], [{'matcher': 'Edit|Write', 'hooks': [OTHERS]}])  # theirs kept
        self.assertEqual(codex['Stop'], [{'hooks': [door('stop', 'codex')]}])
        self.assertEqual(sorted(self.read('agy')), [AGY_PRE, 'lint'])
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
        self.assertEqual(self.install(), 3)  # the door's own changes only, no folder
        self.assertNotIn('remove folder', self.output)

    # --- each feature's own entries, from before the door -------------------------------------

    def seed_per_feature(self):
        """Hook files as the per-feature install left them: one entry per feature and event."""
        def old(cli, kind, script, timeout):
            return old_handler(cli, kind, script=script, timeout=timeout)
        self.write('claude', {'model': 'opus', 'hooks': {
            'PreToolUse': [{'matcher': 'Edit|Write|NotebookEdit|Bash', 'hooks': [old('claude', 'pre', GUARD, 60)]},
                           {'matcher': 'Bash', 'hooks': [old('claude', 'pre', COMMITS, 30)]}, THEIRS,
                           {'matcher': 'AskUserQuestion|ExitPlanMode', 'hooks': [old('claude', 'pre', TITLE, 10)]}],
            'SessionEnd': [THEIRS, {'hooks': [old('claude', 'end', GUARD, 60)]}, {'hooks': [old('claude', 'end', TITLE, 10)]}]}})
        self.write('codex', {'hooks': {'Interrupt': [{'hooks': [old('codex', 'interrupt', TITLE, 3)]}]}})
        self.write('agy', {OLD_COMMITS: {'PreToolUse': [{'matcher': 'run_command', 'hooks': [old('agy', 'pre', COMMITS, 30)]}]},
                           OLD_GUARD: {'PreToolUse': [{'matcher': 'x', 'hooks': [old('agy', 'pre', GUARD, 60)]}]},
                           'lint': {'Stop': [OTHERS]}})

    def test_the_door_takes_the_place_of_each_features_own_entries(self):
        self.seed_per_feature()
        self.assertEqual(self.install(apply=True), 3)
        claude = self.read('claude')['hooks']
        self.assertEqual(claude['PreToolUse'], [{'matcher': 'Edit|Write|NotebookEdit|Bash|AskUserQuestion|ExitPlanMode',
                                                 'hooks': [door('pre', timeout=60)]}, THEIRS])  # where the first stood
        self.assertEqual(claude['SessionEnd'], [THEIRS, {'hooks': [door('end', timeout=60)]}])
        self.assertEqual(self.read('codex')['hooks']['Interrupt'], [{'hooks': [door('interrupt', 'codex', 3)]}])
        self.assertEqual(sorted(self.read('agy')), [AGY_PRE, 'lint'])
        self.assertNotIn('/elsewhere/repo', ''.join(self.path(cli).read_text() for cli in agent_hooks.HOOK_FILE_CLIS))
        self.assertEqual(self.install(), 0)

    def test_uninstall_takes_the_door_out_and_each_features_own_entries_with_it(self):
        self.seed_per_feature()
        self.assertEqual(self.install(apply=True, uninstall=True), 3)
        self.assertEqual(self.read('claude'), {'model': 'opus', 'hooks': {'PreToolUse': [THEIRS], 'SessionEnd': [THEIRS]}})
        self.assertEqual(self.read('codex'), {})
        self.assertEqual(self.read('agy'), {'lint': {'Stop': [OTHERS]}})


if __name__ == '__main__':
    unittest.main()
