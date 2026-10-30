"""daily-log: the journal grammar as one command, and the hook behind it.

Run: python3 -m unittest discover -s scripts/tests -p 'test_daily_log.py' -v
"""
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT

SCRIPT = ROOT / 'skills/daily-log/scripts/daily_log.py'
SPEC = importlib.util.spec_from_file_location('daily_log', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
daily_log = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(daily_log)

FIXTURE = Path(__file__).parent / 'fixtures/daily-log/week-4'  # a real October week file
SEP = '-' * 84
RULE = '-' * 12


class JournalTest(unittest.TestCase):
    """The `add`, `show`, `path` and `tutor-daily` commands against a copy of a real week file."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='daily-log 空間 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'journal'
        (self.root / '2026/Oct').mkdir(parents=True)
        self.week4 = self.root / '2026/Oct/week-4'
        shutil.copy(FIXTURE, self.week4)
        self.state = Path(self.temp.name).resolve() / 'state'
        patcher = patch.dict(os.environ, {'DAILY_LOG_STATE': str(self.state), 'DAILY_LOGGER_ROOT': str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *args, stdin=''):
        """(exit status, stdout, stderr) of one daily-log call, stdin never a terminal."""
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, 'stdin', io.StringIO(stdin)), redirect_stdout(out), redirect_stderr(err):
            code = daily_log.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def add(self, *args, stdin=''):
        code, out, err = self.run_cli('add', *args, stdin=stdin)
        self.assertEqual(code, 0, err)
        return out

    def test_week_file_follows_the_days_own_month(self):
        self.assertEqual(daily_log.week_file('/r', date(2026, 10, 1)), Path('/r/2026/Oct/week-1'))
        self.assertEqual(daily_log.week_file('/r', date(2026, 9, 29)), Path('/r/2026/Sep/week-5'))
        self.assertEqual(daily_log.week_file('/r', date(2026, 10, 26)), Path('/r/2026/Oct/week-5'))
        self.assertEqual(daily_log.week_file('/r', date(2026, 11, 2)), Path('/r/2026/Nov/week-2'))  # Nov 1 is a Sunday

    def test_sub_bullets_get_one_tab_and_a_bullet(self):
        self.assertEqual(daily_log.normalize('tests green  '), '\t- tests green')
        self.assertEqual(daily_log.normalize('- tests green'), '\t- tests green')
        self.assertEqual(daily_log.normalize('\t- [ ] 1-Two Sum(new)'), '\t- [ ] 1-Two Sum(new)')
        self.assertEqual(daily_log.normalize('↳ O(n)/O(1)'), '\t\t↳ O(n)/O(1)')
        self.assertIsNone(daily_log.normalize('   '))

    def test_entry_after_content_is_set_off_by_a_blank_line(self):
        out = self.add('--date', '2026-10-23', '--done', 'ai-dotfiles: daily-log', 'skill + hook', 'tests green')
        text = self.week4.read_text()
        self.assertIn('- [] G-DOC extracter: Obsidian-web-clipper\n\n- [X] ai-dotfiles: daily-log\n'
                      '\t- skill + hook\n\t- tests green\n\n\n' + SEP + '\n', text)
        self.assertTrue(out.startswith('# 10/23 (Fri)\n' + RULE + '\n- [] leetcode\n'))
        self.assertTrue(out.endswith('\t- tests green\n'))  # the block, trailing blanks trimmed

    def test_entry_under_the_tutor_block_and_first_entry_flush_under_the_rule(self):
        self.add('--date', '2026-10-24', 'reading')
        self.assertIn('- [] leetcode\n\n- [] reading\n\n\n' + SEP, self.week4.read_text())
        empty = self.root / '2026/Nov/week-2'
        empty.parent.mkdir(parents=True)
        empty.write_text('# Week Goal\n' + RULE + '\n# Thought\n\n' + SEP + '\n\n# 11/2 (Mon)\n' + RULE + '\n\n\n' + SEP + '\n')
        self.add('--date', '2026-11-02', '--done', 'first')
        self.assertIn('# 11/2 (Mon)\n' + RULE + '\n- [X] first\n\n\n' + SEP + '\n', empty.read_text())

    def test_same_label_merges_drops_duplicates_and_flips_to_done(self):
        self.add('--date', '2026-10-23', 'ai-dotfiles: daily-log', 'skill + hook')
        self.add('--date', '2026-10-23', '--done', 'ai-dotfiles: daily-log', 'skill + hook', 'docs')
        text = self.week4.read_text()
        self.assertEqual(text.count('ai-dotfiles: daily-log'), 1)
        self.assertIn('- [X] ai-dotfiles: daily-log\n\t- skill + hook\n\t- docs\n', text)
        self.add('--date', '2026-10-23', '--open', '/obnoard skill', 'still done')  # --open never un-checks
        self.assertIn('- [X] /obnoard skill\n\t- still done\n', self.week4.read_text())

    def test_if_absent_leaves_the_file_byte_identical(self):
        before = self.week4.read_bytes()
        out = self.add('--date', '2026-10-23', '--open', '--if-absent', 'leetcode', stdin='\t- [ ] 1-Two Sum(new)\n')
        self.assertEqual(self.week4.read_bytes(), before)
        self.assertIn('\t- [ ] 72-Edit Distance(new)\n', out)

    def test_stdin_lines_keep_their_tabs(self):
        self.add('--date', '2026-10-24', '--open', 'leetcode', stdin='\t- [ ] 72-Edit Distance(new)\n\t- [ ] 981-Time(weak)\n')
        text = self.week4.read_text()
        self.assertIn('- [] leetcode\n\t- [ ] 72-Edit Distance(new)\n\t- [ ] 981-Time(weak)\n', text)
        self.assertNotIn('    - [ ]', text)

    def test_missing_day_is_appended_after_the_last_separator(self):
        self.add('--date', '2026-10-25', '--done', 'sunday thing')
        self.assertTrue(self.week4.read_text().endswith(
            SEP + '\n\n# 10/25 (Sun)\n' + RULE + '\n- [X] sunday thing\n\n\n' + SEP + '\n'))

    def test_new_week_file_gets_the_skeleton(self):
        out = self.add('--date', '2026-11-02', '--open', '--show', 'file', 'leetcode', '\t- [ ] 1-Two Sum(new)')
        expected = ('# Week Goal\n' + RULE + '\n# Thought\n\n' + SEP + '\n\n\n# 11/2 (Mon)\n' + RULE +
                    '\n- [] leetcode\n\t- [ ] 1-Two Sum(new)\n\n\n' + SEP + '\n')
        self.assertEqual(out, expected)
        self.assertEqual((self.root / '2026/Nov/week-2').read_text(), expected)
        self.assertEqual((self.root / '2026/Nov/week-2').stat().st_mode & 0o777, 0o644)

    def test_dry_run_prints_the_block_and_writes_nothing(self):
        before = self.week4.read_bytes()
        out = self.add('--date', '2026-10-23', '--dry-run', '--done', 'nope')
        self.assertIn('- [X] nope', out)
        self.assertEqual(self.week4.read_bytes(), before)
        self.assertFalse((self.root / '2026/Nov').exists())

    def test_show_and_path(self):
        code, out, _ = self.run_cli('show', '--date', '2026-10-24')
        self.assertEqual((code, out), (0, '# 10/24 (Sat)\n' + RULE + '\n- [] leetcode\n'))
        code, out, err = self.run_cli('show', '--date', '2026-10-25')
        self.assertEqual(code, 1)
        self.assertIn('no block for 2026-10-25', err)
        code, out, _ = self.run_cli('path', '--date', '2026-10-01')
        self.assertEqual((code, out), (0, f'{self.root}/2026/Oct/week-1\n'))

    def test_missing_root_is_refused(self):
        code, _, err = self.run_cli('add', '--root', str(self.root / 'nowhere'), 'x')
        self.assertEqual(code, 1)
        self.assertIn('journal root not found', err)

    def test_session_marks_the_hook_state_logged(self):
        self.add('--date', '2026-10-23', '--done', '--session', 'abc/1', 'logged')
        self.assertEqual(json.loads((self.state / 'abc_1.json').read_text()), {'logged': True})
        self.add('--date', '2026-10-23', '--dry-run', '--session', 'dry', 'x')
        self.assertFalse((self.state / 'dry.json').exists())

    def test_tutor_daily_renders_one_key(self):
        code, out, _ = self.run_cli('tutor-daily', '--key', 'dsa', '--subject', 'DSA', '--item', 'problem',
                                    '--tutor', 'leetcode-tutor', '--paste-hint', 'a TypeScript solution',
                                    '--note', 'Hards are parked.')
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('---\nname: dsa-tutor-daily\n'))
        self.assertIn('run --key dsa', out)
        self.assertIn('one new problem (the floor), one weak problem due', out)
        self.assertIn("He can still paste a TypeScript solution here anytime for a leetcode-tutor-style review.", out)
        self.assertTrue(out.endswith('- Keep the report concise.\n- Hards are parked.\n'))
        self.assertNotIn('{', out.replace('{notes-blank}', ''))
        code, out, _ = self.run_cli('tutor-daily', '--key', 'system-design', '--subject', 'System Design',
                                    '--item', 'concept', '--tutor', 'socratic', '--paste-hint', 'an explanation')
        self.assertTrue(out.endswith('- Keep the report concise.\n'))
        self.assertIn('Sat: weekend concluding session — no new concepts; 2 unlabeled', out)


class HookTest(unittest.TestCase):
    """One nudge per session once files changed, at most two, never on the hook's own continuation."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='daily-log hook 空間 ')
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name).resolve() / 'state'
        patcher = patch.dict(os.environ, {'DAILY_LOG_STATE': str(self.state)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tool(self, cli, name, session='s1'):
        data = ({'conversationId': session, 'workspacePaths': ['/w'], 'toolCall': {'name': name}} if cli == 'agy'
                else {'session_id': session, 'cwd': '/w', 'tool_name': name})
        return daily_log.hook('tool', cli, data)

    def stop(self, cli, session='s1', **extra):
        data = {'conversationId': session, 'workspacePaths': ['/w']} if cli == 'agy' else {'session_id': session, 'cwd': '/w'}
        return daily_log.hook('stop', cli, {**data, **extra})

    def test_claude_nudges_after_an_edit_then_once_more_at_most(self):
        self.assertIsNone(self.tool('claude', 'Read'))
        self.assertIsNone(self.stop('claude'))  # no edits yet
        self.tool('claude', 'Edit')
        reply = self.stop('claude')
        context = reply['hookSpecificOutput']['additionalContext']
        self.assertEqual(reply['hookSpecificOutput']['hookEventName'], 'Stop')
        self.assertIn('daily-log add --done --session s1', context)
        self.assertIn('(1 edits)', context)
        self.assertIsNone(self.stop('claude'))  # nothing new since the nudge
        self.tool('claude', 'Write')
        self.assertIsNone(self.stop('claude', stop_hook_active=True))  # our own continuation
        self.assertIn('(2 edits)', self.stop('claude')['hookSpecificOutput']['additionalContext'])
        self.tool('claude', 'NotebookEdit')
        self.assertIsNone(self.stop('claude'))  # the cap
        self.assertEqual(json.loads((self.state / 's1.json').read_text()), {'edits': 3, 'edits_at_nudge': 2, 'nudges': 2})

    def test_a_logged_session_is_left_alone(self):
        self.tool('claude', 'Edit')
        daily_log.mark_logged('s1')
        self.assertIsNone(self.stop('claude'))
        self.tool('claude', 'Edit')
        self.assertIsNone(self.stop('claude'))

    def test_each_cli_counts_its_own_edit_tools_and_answers_in_its_own_shape(self):
        self.assertEqual(self.stop('codex'), {})
        self.assertIsNone(self.tool('codex', 'Bash'))
        self.tool('codex', 'apply_patch')
        self.assertEqual(self.stop('codex')['decision'], 'block')
        self.assertEqual(self.tool('agy', 'view_file', 'a1'), {})
        self.tool('agy', 'write_to_file', 'a1')
        self.assertEqual(self.stop('agy', 'a1')['decision'], 'continue')
        self.assertEqual(self.stop('agy', 'a1'), {'decision': 'stop'})  # the turn our continuation started
        self.assertEqual(self.stop('agy', 'a1'), {'decision': 'stop'})  # nothing new since
        self.tool('pi', 'edit', 'p1')
        self.assertIn('--session p1', self.stop('pi', 'p1')['continue'])
        self.assertIsNone(self.stop('pi', 'p1'))  # pending, then quiet

    def test_agy_nudges_only_when_the_model_stopped(self):
        self.tool('agy', 'replace_file_content', 'a2')
        for reason in ('error', 'max_steps_exceeded'):
            self.assertEqual(self.stop('agy', 'a2', terminationReason=reason), {'decision': 'stop'}, reason)
        self.assertEqual(self.stop('agy', 'a2', terminationReason='model_stop')['decision'], 'continue')

    def test_no_session_is_quiet_and_old_state_is_pruned(self):
        self.assertIsNone(daily_log.hook('stop', 'claude', {}))
        self.assertEqual(daily_log.hook('stop', 'agy', {}), {'decision': 'stop'})
        self.state.mkdir(parents=True)
        old = self.state / 'old.json'
        old.write_text('{}')
        os.utime(old, (0, 0))
        self.tool('claude', 'Read')
        self.assertFalse(old.exists())
        self.assertTrue((self.state / 's1.json').exists())

    def test_the_command_never_fails_or_speaks_outside_json(self):
        for stdin, args in (('not json', ['hook', 'stop', '--cli', 'codex']), ('[]', ['hook', 'tool', '--cli', 'claude']),
                            ('{}', ['hook', 'bogus', '--cli', 'claude']), ('{}', ['hook', 'stop'])):
            run = subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True,
                                 env={**os.environ, 'DAILY_LOG_STATE': str(self.state)})
            self.assertEqual((run.returncode, run.stderr), (0, ''), args)
            if run.stdout.strip():
                json.loads(run.stdout)


if __name__ == '__main__':
    unittest.main()
