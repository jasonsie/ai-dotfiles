from datetime import timezone
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from support import ROOT, load

statusline = load('statusline.py')
sys.path.insert(0, str(ROOT / 'scripts'))
import agent_hooks  # noqa: E402  (imported, not loaded by path: its dataclasses need sys.modules)

HOME = '/Users/me'
NOW = 1794195900  # 2026-11-09 03:45 UTC, a Monday
UTC = timezone.utc
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
    'rate_limits': {'five_hour': {'used_percentage': 23.4, 'resets_at': 1794204000},    # 06:00 UTC the same day
                    'seven_day': {'used_percentage': 41.2, 'resets_at': 1794441600}},   # Thursday 00:00 UTC
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
    'quota': {'gemini-weekly': {'remaining_fraction': 0.9378, 'reset_time': '2026-11-12T07:50:32Z',
                                'reset_in_seconds': 260132}},
    'agent_state': 'idle', 'vcs': {'type': 'git'}, 'sandbox': {'enabled': False},
    'cost': {'total_usd': 0.4213, 'subagent_usd': 0, 'estimated': False},
}


def plain(text):
    """The text without its colors."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


class RenderTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = patch.dict(os.environ, {'HOME': HOME, 'WORKTREE_GUARD_STATE': temp.name})  # no guard state leaks in
        env.start()
        self.addCleanup(env.stop)

    def lines(self, data, facts=('main', '')):
        return [plain(line) for line in statusline.render(data, facts, NOW, UTC)]

    def test_claude_payload(self):
        self.assertEqual(self.lines(CLAUDE), [
            '📁 ~/Developer/repo  🌿 main  🤖 Fable 5.1 · max  📟 v2.1.318',
            '🧠 Context: 93% [=========-]',
            '⏳ 5h 23% → 06:00  7d 41% → Thu 00:00  💰 $0.12',
        ])

    def test_antigravity_payload(self):
        self.assertEqual(self.lines(ANTIGRAVITY), [
            '📁 ~/project  🌿 main  🤖 Gemini 4 Argon · medium  📟 v1.4.5',  # the effort is not repeated
            '🧠 Context: 85% [========--]',
            '⏳ gemini-weekly 6% → Thu 07:50  💰 $0.42',
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

    def test_a_window_whose_reset_has_passed_is_left_out(self):
        data = {'rate_limits': {'five_hour': {'used_percentage': 90, 'resets_at': NOW - 1},
                                'seven_day': {'used_percentage': 41.2, 'resets_at': 1794441600}}}
        self.assertEqual(self.lines(data)[-1], '⏳ 7d 41% → Thu 00:00')
        stale = {'quota': {'gemini-weekly': {'remaining_fraction': 0.5, 'reset_time': '2026-11-01T00:00:00Z'}}}
        self.assertEqual(len(self.lines(stale)), 2)
        self.assertEqual(len(self.lines({'rate_limits': {'five_hour': {'used_percentage': 90, 'resets_at': NOW}}})), 2)

    def test_reset_time_fallbacks(self):
        self.assertEqual(statusline.epoch(1794204000), 1794204000.0)
        self.assertEqual(statusline.epoch('2026-11-12T07:50:32Z'), 1794469832.0)
        self.assertEqual(statusline.epoch('2026-11-12T07:50:32+00:00'), 1794469832.0)
        for unreadable in (None, 'soon', True, [1]):
            self.assertIsNone(statusline.epoch(unreadable))
        seconds_only = {'quota': {'b': {'remaining_fraction': 0.25, 'reset_in_seconds': 3600}}}
        self.assertEqual(statusline.limits(seconds_only, NOW), [('b', 75.0, NOW + 3600)])
        unreadable = {'quota': {'b': {'remaining_fraction': 0.25, 'reset_time': 'soon'}}}
        self.assertEqual(statusline.limits(unreadable, NOW), [('b', 75.0, None)])
        self.assertEqual(self.lines(unreadable)[-1], '⏳ b 75%')

    def test_reset_times_are_shown_in_the_local_zone_by_default(self):
        self.addCleanup(time.tzset)  # back to the system zone once patch.dict has restored TZ
        with patch.dict(os.environ, {'TZ': 'Asia/Taipei'}):
            time.tzset()
            line = plain(statusline.usage_line(CLAUDE, NOW))
        self.assertEqual(line, '⏳ 5h 23% → 14:00  7d 41% → Thu 08:00  💰 $0.12')
        self.assertIn(str(statusline.COLORS['detail']), statusline.usage_line(CLAUDE, NOW, UTC))

    def test_tilde(self):
        self.assertEqual(statusline.tilde('/Users/me', '/Users/me/'), '~')
        self.assertEqual(statusline.tilde('/Users/me/a', '/Users/me'), '~/a')
        self.assertEqual(statusline.tilde('/Users/meow/a', '/Users/me'), '/Users/meow/a')


class WorkNameTest(unittest.TestCase):
    """The work name replaces the branch while a session has a worktree; the guard's state is the fixture."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.state = self.root / 'state'
        self.main = self.root / 'repo'
        self.linked = self.main / '.claude/worktrees/fix-x'
        self.linked.mkdir(parents=True)
        env = patch.dict(os.environ, {'HOME': HOME, 'WORKTREE_GUARD_STATE': str(self.state)})
        env.start()
        self.addCleanup(env.stop)

    def keep(self, session, moved):
        """The guard's record of a session, written by the guard's own store."""
        store = agent_hooks.Store('WORKTREE_GUARD_STATE', '', 60, 'sessions')
        store.save(session, {'moved': moved})

    def moved(self, **fields):
        return {'busy': str(self.main), 'linked': str(self.linked), 'name': 'fix-x', 'work': 'fix/x',
                'branch': None, **fields}

    def first(self, data, facts=('main', '')):
        return plain(statusline.render(data, facts, NOW, UTC)[0])

    def agy(self, **extra):
        return {**ANTIGRAVITY, 'cwd': str(self.main), 'workspace': {'current_dir': str(self.main)}, **extra}

    def test_antigravity_shows_the_work_the_guard_moved_its_session_to(self):
        self.keep('x', self.moved())
        self.assertEqual(self.first(self.agy()),
                         f'📁 {self.main}  🌿 fix/x  🤖 Gemini 4 Argon · medium  📟 v1.4.5')

    def test_the_conversation_id_finds_the_session_too(self):
        self.keep('conv-1', self.moved())
        data = self.agy(session_id=None, conversation_id='conv-1')
        self.assertIn('🌿 fix/x', self.first(data))

    def test_the_session_file_is_the_one_the_guard_writes(self):
        store = agent_hooks.Store('WORKTREE_GUARD_STATE', '', 60, 'sessions')
        self.assertEqual(statusline.session_file('we/ird id'), store.file('we/ird id'))
        self.assertEqual(statusline.session_file('a' * 200), store.file('a' * 200))

    def test_claude_shows_the_work_from_its_worktree_folder(self):
        (self.main / '.claude/worktrees/fix-x.json').write_text(json.dumps({'work': 'fix/x', 'branch': None}))
        data = {**CLAUDE, 'cwd': str(self.linked / 'src'), 'workspace': {'current_dir': str(self.linked / 'src')}}
        (self.linked / 'src').mkdir()
        self.assertIn('🌿 fix/x  🤖', self.first(data, ('abc1234', 'fix-x')))

    def test_a_worktree_without_a_work_name_keeps_the_branch_and_folder(self):
        (self.main / '.claude/worktrees/fix-x.json').write_text(json.dumps({'branch': 'agent/fix-x'}))
        data = {**CLAUDE, 'cwd': str(self.linked), 'workspace': {'current_dir': str(self.linked)}}
        self.assertIn('🌿 agent/fix-x ⎇ fix-x', self.first(data, ('agent/fix-x', 'fix-x')))

    def test_the_branch_shows_when_the_session_has_no_worktree(self):
        self.assertIn('🌿 main  🤖', self.first(self.agy()))
        self.keep('x', {})
        self.assertIn('🌿 main  🤖', self.first(self.agy()))
        self.keep('other', self.moved())
        self.assertIn('🌿 main  🤖', self.first(self.agy()))

    def test_a_worktree_that_is_gone_shows_the_branch(self):
        self.keep('x', self.moved(linked=str(self.main / '.claude/worktrees/deleted')))
        self.assertIn('🌿 main  🤖', self.first(self.agy()))

    def test_state_that_cannot_be_read_shows_the_branch(self):
        path = statusline.session_file('x')
        path.parent.mkdir(parents=True)
        for text in ('not json', '[1]', '{"moved": 3}', '{"moved": {"linked": 4}}', '{"moved": {"linked": "' + str(self.linked) + '", "work": 5}}'):
            path.write_text(text)
            self.assertIn('🌿 main  🤖', self.first(self.agy()), text)
        self.assertIn('🌿 main  🤖', self.first(self.agy(session_id=['x'], conversation_id=None)))

    def test_a_work_less_move_shows_its_branch(self):  # a record an older guard wrote (move on clash)
        self.keep('x', self.moved(work=None, branch='agent/codex-bbbb2222'))
        self.assertIn('🌿 agent/codex-bbbb2222  🤖', self.first(self.agy()))

    def test_runs_as_a_script_with_the_state_in_place(self):
        self.keep('x', self.moved())
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/statusline.py')], input=json.dumps(self.agy()),
                                capture_output=True, text=True, env=os.environ.copy())
        self.assertIn('🌿 fix/x', plain(result.stdout))


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
