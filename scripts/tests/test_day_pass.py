"""day_pass: the evidence the daily pass reads, from synthetic sessions, a small repository and a journal.

Run: python3 -m unittest discover -s scripts/tests -p 'test_day_pass.py' -v
"""
from contextlib import redirect_stdout
from datetime import date, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT

SCRIPT = ROOT / 'skills/daily-log/scripts/day_pass.py'
SPEC = importlib.util.spec_from_file_location('day_pass', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
day_pass = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(day_pass)
agent_sessions = day_pass.agent_sessions

DAY = date(2026, 11, 2)
RULE = '-' * 12
SEP = '-' * 84


def stamp(moment):
    """A store timestamp: ISO 8601 in UTC with a Z."""
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


class DayPassTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='day-pass 空間 ')
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.home, self.root, self.repo = base / 'home', base / 'journal', base / 'work/ai_dotfiles'
        self.start, self.end = agent_sessions.window(DAY)
        # The fixtures live under the system temp folder, which the readers drop as a probe's cwd.
        patcher = patch.object(agent_sessions, 'TEMP_PREFIXES', ())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.make_repo()
        self.make_sessions()
        self.make_journal()

    def git(self, *args, at=None):
        env = dict(os.environ)
        if at is not None:
            env['GIT_AUTHOR_DATE'] = env['GIT_COMMITTER_DATE'] = at.isoformat()
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True, text=True,
                              env={**env, 'GIT_CONFIG_GLOBAL': '/dev/null'}).stdout

    def make_repo(self):
        self.repo.mkdir(parents=True)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 't@t')
        self.git('config', 'user.name', 't')
        self.git('remote', 'add', 'origin', 'https://github.com/jason/ai-dotfiles.git')
        (self.repo / 'README.md').write_text('hi\n')
        self.git('add', 'README.md')
        self.git('commit', '-q', '-m', 'before the window', at=self.start - timedelta(days=2))
        (self.repo / 'guard.py').write_text('x\n')
        self.git('add', 'guard.py')
        self.git('commit', '-q', '-m', 'feat: the guard moves a session', at=self.start + timedelta(hours=3))
        (self.repo / 'notes.md').write_text('uncommitted\n')

    def make_sessions(self):
        folder = self.home / '.claude/projects/-work-ai-dotfiles'
        folder.mkdir(parents=True)
        at = self.start + timedelta(hours=2)
        lines = [
            {'type': 'user', 'timestamp': stamp(at), 'cwd': str(self.repo), 'sessionId': 's1',
             'message': {'role': 'user', 'content': 'Please build the guard\nwith tests'}},
            {'type': 'assistant', 'timestamp': stamp(at + timedelta(minutes=5)), 'cwd': str(self.repo), 'sessionId': 's1',
             'message': {'role': 'assistant', 'content': [
                 {'type': 'text', 'text': 'Guard built and tested.'},
                 {'type': 'tool_use', 'name': 'Write', 'input': {'file_path': str(self.repo / 'guard.py'), 'content': 'x'}}]}},
            {'type': 'ai-title', 'aiTitle': 'Guard build', 'sessionId': 's1'},
        ]
        (folder / 's1.jsonl').write_text('\n'.join(json.dumps(line) for line in lines) + '\n')
        gone = self.home / '.claude/projects/-gone'
        gone.mkdir(parents=True)
        (gone / 's2.jsonl').write_text(json.dumps({
            'type': 'user', 'timestamp': stamp(at), 'cwd': str(self.home / 'gone'), 'sessionId': 's2',
            'message': {'role': 'user', 'content': 'a folder that no longer exists'}}) + '\n')

    def make_journal(self):
        (self.root / '2026/Oct').mkdir(parents=True)
        (self.root / '2026/Nov').mkdir(parents=True)
        (self.root / '2026/Oct/week-5').write_text(
            '# Week Goal\n' + RULE + '\n# Thought\n\n' + SEP + '\n\n\n# 10/30 (Fri)\n' + RULE +
            '\n- [X] ai-dotfiles: tutor skill\n\t- keyword: skills, docs\n\t- description: done\n\n\n' + SEP + '\n')
        (self.root / '2026/Nov/week-2').write_text(
            '# Week Goal\n' + RULE + '\n# Thought\n\n' + SEP + '\n\n\n# 11/2 (Mon)\n' + RULE +
            '\n- [] leetcode\n\t- [ ] 72-Edit Distance(new)\n\n- [X] CS vault: study plan\n\t- keyword: docs, planning\n'
            '\t- description: plan written\n\n\n' + SEP + '\n')

    def run_pass(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = day_pass.main(['--home', str(self.home), '--root', str(self.root), *args])
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_a_day_with_sessions_is_rendered_in_full(self):
        out = self.run_pass('--date', '2026-11-02', '--back', '1')
        self.assertTrue(out.startswith('# Day pass 2026-11-01 to 2026-11-02; days with sessions: 2026-11-02\n'))
        self.assertNotIn('## 2026-11-01', out)  # no sessions that day
        self.assertIn(f'## 2026-11-02 (Mon), {self.start:%Y-%m-%d %H:%M} to {self.end:%Y-%m-%d %H:%M}', out)
        self.assertIn('rewrite: off, skip work the block already covers', out)
        self.assertIn('### Existing block\n# 11/2 (Mon)\n' + RULE + '\n- [] leetcode', out)
        self.assertIn('- [X] CS vault: study plan', out)
        self.assertIn('### Keywords in use, reuse before coining\nskills, docs, planning\n', out)  # last month first, deduped
        self.assertIn(f'### {self.repo}\n  repo: {self.repo}\n  origin: ai-dotfiles\n  branch: main\n  commits in window: 1\n'
                      '    feat: the guard moves a session\n', out)
        self.assertNotIn('before the window', out)
        self.assertIn('  uncommitted now: 1\n', out)
        at = (self.start + timedelta(hours=2)).astimezone()
        self.assertIn(f'- claude {at:%H:%M}-{at + timedelta(minutes=5):%H:%M} Guard build\n', out)
        self.assertIn('    asked: Please build the guard\n', out)  # the first line only
        self.assertIn('    said: Guard built and tested.\n', out)
        self.assertIn('    edited: guard.py\n', out)  # relative to the repository
        self.assertIn(f'### {self.home / "gone"}\n  folder gone\n', out)
        self.assertIn('### Write\ndaily-log add --date 2026-11-02 --done "<project>: <what the day was about>" '
                      '"keyword: <tags>" "description: <one line>"\n', out)

    def test_rewrite_is_passed_through_to_the_model(self):
        out = self.run_pass('--date', '2026-11-02', '--back', '0', '--rewrite')
        self.assertIn('rewrite: on, pass --rewrite to daily-log add', out)
        self.assertIn('daily-log add --date 2026-11-02 --done --rewrite "<project>', out)

    def test_no_sessions_anywhere_is_said_in_one_line(self):
        out = self.run_pass('--date', '2026-10-01', '--back', '2')
        self.assertEqual(out, '# Day pass 2026-09-29 to 2026-10-01; days with sessions: none\n')

    def test_dates(self):
        self.assertEqual(day_pass.parse_date('yesterday'), date.today() - timedelta(days=1))
        self.assertEqual(day_pass.parse_date(None), date.today() - timedelta(days=1))
        self.assertEqual(day_pass.parse_date('today'), date.today())
        self.assertEqual(day_pass.parse_date('2026-11-02'), DAY)

    def test_repo_name_from_any_remote_shape(self):
        for url in ('https://github.com/jason/ai-dotfiles.git', 'git@github.com:jason/ai-dotfiles.git',
                    'ssh://git@host/x/ai-dotfiles', '/srv/git/ai-dotfiles/'):
            self.assertEqual(day_pass.repo_name(url), 'ai-dotfiles', url)

    def test_keywords_come_from_this_and_last_month_in_order(self):
        self.assertEqual(day_pass.keywords(self.root, DAY), ['skills', 'docs', 'planning'])
        self.assertEqual(day_pass.keywords(self.root, date(2026, 12, 15)), ['docs', 'planning'])
        self.assertEqual(day_pass.keywords(self.root / 'nowhere', DAY), [])

    def test_first_line_is_clipped(self):
        self.assertEqual(day_pass.first_line('\n\n  two words \nmore'), 'two words')
        self.assertEqual(len(day_pass.first_line('x' * 500)), day_pass.WIDTH)
        self.assertTrue(day_pass.first_line('x' * 500).endswith('…'))

    def test_repo_facts_outside_a_repository(self):
        plain = self.home / 'plain'
        plain.mkdir()
        self.assertEqual(day_pass.repo_facts(plain, self.start, self.end), (None, ['not a git repository']))
        self.assertEqual(day_pass.repo_facts(self.home / 'missing', self.start, self.end), (None, ['folder gone']))
        self.assertEqual(day_pass.repo_facts('', self.start, self.end), (None, ['no working folder recorded']))


if __name__ == '__main__':
    unittest.main()
