"""daily-log: the journal grammar as one command.

Run: python3 -m unittest discover -s scripts/tests -p 'test_daily_log.py' -v
"""
import ast
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
import importlib.util
import io
import os
from pathlib import Path
import shutil
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
    """The `add`, `show`, `path`, `day` and `tutor-daily` commands against a copy of a real week file."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='daily-log 空間 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'journal'
        (self.root / '2026/Oct').mkdir(parents=True)
        self.week4 = self.root / '2026/Oct/week-4'
        shutil.copy(FIXTURE, self.week4)
        patcher = patch.dict(os.environ, {'DAILY_LOGGER_ROOT': str(self.root)})
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

    def test_the_writer_is_one_file_of_stdlib_imports(self):
        """A copy of the script is a complete writer (the learning-tutor vendors one)."""
        tree = ast.parse(SCRIPT.read_text())
        names = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for alias in node.names}
        names |= {node.module.split('.')[0] for node in ast.walk(tree)
                  if isinstance(node, ast.ImportFrom) and node.module}
        self.assertTrue(names <= sys.stdlib_module_names, names - sys.stdlib_module_names)

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

    def test_the_project_is_the_text_before_the_colon(self):
        self.assertEqual(daily_log.project('ai-dotfiles: daily-log'), 'ai-dotfiles')
        self.assertEqual(daily_log.project('leetcode'), 'leetcode')
        self.assertEqual(daily_log.project('/onboard skill'), '/onboard skill')
        self.assertEqual(daily_log.key('AI_dotfiles: x'), daily_log.key('ai-dotfiles: y'))
        self.assertEqual(daily_log.key('CS vault: x'), 'csvault')
        self.assertNotEqual(daily_log.key('CS: x'), daily_log.key('CS vault: y'))

    def test_another_label_for_the_same_project_is_refused_and_names_the_entry(self):
        self.add('--date', '2026-10-23', '--done', 'ai-dotfiles: daily-log', 'keyword: hooks', 'description: nudge')
        before = self.week4.read_bytes()
        code, out, err = self.run_cli('add', '--date', '2026-10-23', '--done', 'ai_dotfiles: verify flow', 'keyword: tests')
        self.assertEqual(code, 1)
        self.assertIn('2026-10-23 already has an entry for this project: - [X] ai-dotfiles: daily-log', err)
        self.assertIn('--rewrite', err)
        self.assertEqual((out, self.week4.read_bytes()), ('', before))

    def test_rewrite_replaces_the_projects_entry_whatever_its_label(self):
        self.add('--date', '2026-10-23', '--done', 'ai-dotfiles: daily-log', 'keyword: hooks', 'description: old')
        self.add('--date', '2026-10-23', '--done', '--rewrite', 'ai-dotfiles: daily-log and verify flow',
                 'keyword: hooks, tests', 'description: new')
        text = self.week4.read_text()
        self.assertNotIn('description: old', text)
        self.assertEqual(text.count('ai-dotfiles: daily-log'), 1)
        self.assertIn('- [X] ai-dotfiles: daily-log and verify flow\n\t- keyword: hooks, tests\n\t- description: new\n\n', text)
        self.add('--date', '2026-10-23', '--done', '--rewrite', 'ai-dotfiles: daily-log and verify flow',
                 'keyword: hooks', 'description: newer')  # the same label: replaced too, no duplicate lines
        text = self.week4.read_text()
        self.assertEqual(text.count('keyword:'), 1)
        self.assertIn('description: newer', text)
        before = self.week4.read_bytes()
        self.add('--date', '2026-10-23', '--done', '--rewrite', 'ai-dotfiles: daily-log and verify flow',
                 'keyword: hooks', 'description: newer')  # identical: nothing written
        self.assertEqual(self.week4.read_bytes(), before)
        self.assertIn('- [] G-DOC extracter: Obsidian-web-clipper\n', text)  # the other entries stay

    def test_other_projects_and_the_study_block_are_untouched_by_the_guard(self):
        self.add('--date', '2026-10-24', '--open', 'leetcode', stdin='\t- [ ] 1-Two Sum(new)\n')
        self.add('--date', '2026-10-24', '--done', 'reading: a book')
        self.add('--date', '2026-10-24', '--done', 'ai-dotfiles: x')
        self.assertIn('- [] leetcode\n\t- [ ] 1-Two Sum(new)\n\n- [X] reading: a book\n\n- [X] ai-dotfiles: x\n',
                      self.week4.read_text())

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

    def test_day_runs_the_pass_script_beside_the_writer(self):
        self.assertTrue(daily_log.DAY_PASS.is_file())
        with patch.object(daily_log.subprocess, 'call', return_value=0) as call:
            self.assertEqual(daily_log.main(['day', '--date', '2026-11-02', '--back', '0']), 0)
        self.assertEqual(call.call_args[0][0][1:], [str(daily_log.DAY_PASS), '--date', '2026-11-02', '--back', '0'])
        with patch.object(daily_log, 'DAY_PASS', self.root / 'missing.py'):
            code, _, err = self.run_cli('day')
        self.assertEqual(code, 1)
        self.assertIn('this copy lacks', err)

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


if __name__ == '__main__':
    unittest.main()
