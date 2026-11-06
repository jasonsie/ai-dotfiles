import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT, load

statusline = load('statusline.py')

HOME = '/Users/me'
# The payloads each CLI documents (code.claude.com/docs/en/statusline, antigravity.google/docs/cli/statusline).
CLAUDE = {
    'cwd': f'{HOME}/Developer/repo', 'session_id': 'abc',
    'model': {'id': 'claude-fable-5-1', 'display_name': 'Fable 5.1'},
    'workspace': {'current_dir': f'{HOME}/Developer/repo', 'project_dir': f'{HOME}/Developer/repo'},
    'version': '2.1.318', 'output_style': {'name': 'default'},
    'cost': {'total_cost_usd': 0.12345, 'total_duration_ms': 45000},
    'context_window': {'total_input_tokens': 15500, 'total_output_tokens': 1200, 'context_window_size': 200000,
                       'used_percentage': 7, 'remaining_percentage': 93,
                       'current_usage': {'input_tokens': 8500, 'output_tokens': 1200,
                                         'cache_creation_input_tokens': 5000, 'cache_read_input_tokens': 2000}},
    'exceeds_200k_tokens': False, 'fast_mode': False, 'effort': {'level': 'max'}, 'thinking': {'enabled': True},
    'rate_limits': {'five_hour': {'used_percentage': 23.4, 'resets_at': 1},
                    'seven_day': {'used_percentage': 41.2, 'resets_at': 2}},
}
ANTIGRAVITY = {
    'cwd': f'{HOME}/project', 'session_id': 'x', 'conversation_id': 'x',
    'model': {'id': 'Gemini 4 Argon (Medium)', 'display_name': 'Gemini 4 Argon (Medium)', 'effort': 'medium'},
    'workspace': {'current_dir': f'{HOME}/project', 'project_dir': f'{HOME}/project'},
    'version': '1.4.5',
    'context_window': {'total_input_tokens': 88244, 'total_output_tokens': 61074, 'context_window_size': 1048576,
                       'used_percentage': 14.24, 'remaining_percentage': 85.76,
                       'current_usage': {'input_tokens': 63382, 'output_tokens': 346,
                                         'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 20857}},
    'exceeds_200k_tokens': False, 'product': 'antigravity',
    'quota': {'gemini-weekly': {'remaining_fraction': 0.9378, 'reset_time': '2026-07-06T07:50:32Z'}},
    'agent_state': 'idle', 'vcs': {'type': 'git'}, 'sandbox': {'enabled': False},
    'cost': {'total_usd': 0.4213, 'subagent_usd': 0, 'estimated': False},
}


def plain(text):
    """The text without its colors."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


class RenderTest(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'HOME': HOME})
        env.start()
        self.addCleanup(env.stop)

    def lines(self, data, facts=('main', '')):
        return [plain(line) for line in statusline.render(data, facts)]

    def test_claude_payload(self):
        self.assertEqual(self.lines(CLAUDE), [
            '📁 ~/Developer/repo  🌿 main  🤖 Fable 5.1 · max  📟 v2.1.318',
            '🧠 Context: 93% [=========-]',
            '⏳ 5h 23%  7d 41%  💰 $0.12',
        ])

    def test_antigravity_payload(self):
        self.assertEqual(self.lines(ANTIGRAVITY), [
            '📁 ~/project  🌿 main  🤖 Gemini 4 Argon · medium  📟 v1.4.5',  # the effort is not repeated
            '🧠 Context: 85% [========--]',
            '⏳ gemini-weekly 6%  💰 $0.42',
        ])

    def test_worktree_thinking_off_and_fast_mode(self):
        data = {**CLAUDE, 'thinking': {'enabled': False}, 'fast_mode': True}
        self.assertEqual(self.lines(data, ('feat/x', 'agent-2'))[0],
                         '📁 ~/Developer/repo  🌿 feat/x ⎇ agent-2  🤖 Fable 5.1 · max · thinking off · ⚡fast  📟 v2.1.318')

    def test_model_without_effort_and_a_detached_head(self):
        self.assertEqual(self.lines({'model': {'display_name': 'Opus'}, 'cwd': HOME}, ('abc1234', ''))[0],
                         '📁 ~  🌿 abc1234  🤖 Opus')

    def test_no_repo_no_model_no_version(self):
        self.assertEqual(self.lines({'cwd': '/srv/x'}, ('', ''))[0], '📁 /srv/x  🤖 ?')

    def test_context_fallbacks_and_colors(self):
        unknown = {'context_window': {'remaining_percentage': None, 'current_usage': None}}
        self.assertEqual(plain(statusline.context_line(unknown)), '🧠 Context: ? [----------]')
        computed = {'context_window': {'context_window_size': 1000000,
                                       'current_usage': {'input_tokens': 700000, 'cache_read_input_tokens': 100000}}}
        self.assertEqual(plain(statusline.context_line(computed)), '🧠 Context: 20% [==--------]')
        self.assertIn(str(statusline.COLORS['ctx_crit']), statusline.context_line(computed))
        warn = statusline.context_line({'context_window': {'remaining_percentage': 35.9}})
        self.assertIn(str(statusline.COLORS['ctx_warn']), warn)
        self.assertIn(str(statusline.COLORS['ctx']), statusline.context_line(CLAUDE))

    def test_third_line_only_when_there_is_something_to_show(self):
        self.assertEqual(len(self.lines({'cost': {'total_cost_usd': 0}})), 2)
        self.assertEqual(self.lines({'cost': {'total_usd': 1.5}})[-1], '💰 $1.50')
        self.assertEqual(self.lines({'rate_limits': {'spend_limit': {'used_percentage': 62.8}}})[-1], '⏳ spend 63%')

    def test_tilde(self):
        self.assertEqual(statusline.tilde('/Users/me', '/Users/me/'), '~')
        self.assertEqual(statusline.tilde('/Users/me/a', '/Users/me'), '~/a')
        self.assertEqual(statusline.tilde('/Users/meow/a', '/Users/me'), '/Users/meow/a')


class GitFactsTest(unittest.TestCase):
    def fake(self, outputs):
        """A subprocess.run stand-in answering each call with the next (status, stdout)."""
        calls = []

        def run(args, **_):
            calls.append(args)
            status, out = outputs.pop(0)
            return subprocess.CompletedProcess(args, status, out, '')
        return run, calls

    def test_main_worktree(self):
        run, calls = self.fake([(0, 'main\n.git\n.git\n/r\n')])
        self.assertEqual(statusline.git_facts('/r', run), ('main', ''))
        self.assertEqual(calls[0][:3], ['git', '-C', '/r'])

    def test_linked_worktree_is_named(self):
        run, _ = self.fake([(0, 'feat/x\n/r/.git/worktrees/agent-2\n/r/.git\n/r/.claude/worktrees/agent-2\n')])
        self.assertEqual(statusline.git_facts('/r/.claude/worktrees/agent-2', run), ('feat/x', 'agent-2'))

    def test_detached_head_shows_the_commit(self):
        run, calls = self.fake([(0, 'HEAD\n.git\n.git\n/r\n'), (0, 'abc1234\n')])
        self.assertEqual(statusline.git_facts('/r', run), ('abc1234', ''))
        self.assertEqual(len(calls), 2)

    def test_no_repo_or_no_git(self):
        run, _ = self.fake([(128, '')])
        self.assertEqual(statusline.git_facts('/tmp', run), ('', ''))

        def missing(*_args, **_kwargs):
            raise OSError('no git')
        self.assertEqual(statusline.git_facts('/tmp', missing), ('', ''))

    def test_real_repo_and_linked_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / 'repo'
            repo.mkdir()
            env = {**os.environ, 'HOME': temp, 'GIT_CONFIG_GLOBAL': '/dev/null',
                   'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@x'}
            for args in (['init', '-q', '-b', 'main'], ['commit', '-q', '--allow-empty', '-m', 'root'],
                         ['worktree', 'add', '-q', '-b', 'feat/x', '.claude/worktrees/agent-2']):
                subprocess.run(['git', '-C', str(repo), *args], check=True, env=env, capture_output=True)
            self.assertEqual(statusline.git_facts(str(repo)), ('main', ''))
            self.assertEqual(statusline.git_facts(str(repo / '.claude/worktrees/agent-2')), ('feat/x', 'agent-2'))


class MainTest(unittest.TestCase):
    def run_main(self, text):
        out = io.StringIO()
        with patch.dict(os.environ, {'HOME': HOME}):
            status = statusline.main(io.StringIO(text), out)
        return status, plain(out.getvalue())

    def test_empty_or_broken_input_still_prints_a_line(self):
        for text in ('', 'not json', '[1, 2]'):
            status, out = self.run_main(text)
            self.assertEqual(status, 0)
            self.assertTrue(out.startswith('📁 '), out)

    def test_an_error_is_shown_not_raised(self):
        with patch.object(statusline, 'render', side_effect=RuntimeError('boom')):
            status, out = self.run_main('{}')
        self.assertEqual((status, out.strip()), (0, 'statusline: boom'))

    def test_runs_as_a_script(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/statusline.py')], input=json.dumps(CLAUDE),
                                capture_output=True, text=True, env={**os.environ, 'HOME': HOME})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('🤖 Fable 5.1 · max  📟 v2.1.318', plain(result.stdout))


if __name__ == '__main__':
    unittest.main()
