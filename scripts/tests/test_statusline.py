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
        os.environ.pop(statusline.GATEWAY_ENV, None)  # nor a real gateway (patch.dict puts it back)

    def lines(self, data, facts=('main', '')):
        return [plain(line) for line in statusline.render(data, facts, NOW, UTC)]

    def test_claude_payload(self):
        self.assertEqual(self.lines(CLAUDE), [
            '📁 ~/Developer/repo  🌿 main  🤖 Fable 5.1 · max  📟 v2.1.318',
            '🧠 Context: 93% [=========-]',
            '⏳ 23% → 06:00  41% → Thu 00:00  💰 $0.12',
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

    def test_the_5h_and_7d_windows_show_no_label_the_spend_limit_keeps_its_name(self):
        data = {'rate_limits': {**CLAUDE['rate_limits'], 'spend_limit': {'used_percentage': 62.8, 'resets_at': 1794441600}}}
        self.assertEqual(self.lines(data)[-1], '⏳ 23% → 06:00  41% → Thu 00:00  spend 63% → Thu 00:00')

    def test_a_window_whose_reset_has_passed_is_left_out(self):
        data = {'rate_limits': {'five_hour': {'used_percentage': 90, 'resets_at': NOW - 1},
                                'seven_day': {'used_percentage': 41.2, 'resets_at': 1794441600}}}
        self.assertEqual(self.lines(data)[-1], '⏳ 41% → Thu 00:00')
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
        self.assertEqual(line, '⏳ 23% → 14:00  41% → Thu 08:00  💰 $0.12')
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
        os.environ.pop(statusline.GATEWAY_ENV, None)

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
                                capture_output=True, text=True, env=os.environ.copy())  # the gateway's variable dropped in setUp
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


# What Magpie's GET /v1/magpie/quotas answers (`magpie quota --help`), trimmed; the accounts are made up.
QUOTAS = {'object': 'list', 'data': [
    {'provider': 'claude', 'kind': 'subscription', 'plan': 'max', 'user': 'someone@example.com',
     'windows': [{'name': '5 hours', 'used': 63, 'remaining': 37, 'resetsAt': '2026-11-09T06:00:00+00:00'},
                 {'name': '7 days', 'used': 51, 'remaining': 49, 'resetsAt': '2026-11-12T00:00:00Z'},
                 {'name': '7 days · Fable', 'used': 45, 'remaining': 55, 'resetsAt': '2026-11-12T00:00:00Z'}],
     'readAt': '2026-11-09T03:44:00Z', 'lastServedAt': '2026-11-09T03:40:00Z', 'last': True},
    {'provider': 'codex', 'plan': 'free', 'user': 'someone@example.com',
     'windows': [{'name': '30 days', 'used': 24, 'resetsAt': '2026-12-02T04:40:16Z'}],
     'lastServedAt': '2026-11-08T10:00:00Z'},
    {'provider': 'copilot', 'user': 'someone@example.com', 'error': 'sign in again'},
]}
AGY = {'provider': 'agy-cli', 'lastServedAt': '2026-11-09T03:30:00Z',
       'windows': [{'name': 'Gemini · 5 hours', 'used': 45.6, 'resetsAt': '2026-11-09T12:14:00Z'}]}
WITHOUT_LIMITS = {key: value for key, value in CLAUDE.items() if key != 'rate_limits'}
FULL_LINE = '⏳ 63% → 06:00  51% → Thu 00:00  7 days · Fable 45% → Thu 00:00  💰 $0.12'


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Opener:
    """A urllib opener stand-in: records each URL and answers with `body` (bytes, or an exception it raises)."""

    def __init__(self, body):
        self.body, self.urls = body, []

    def open(self, url, timeout=None):
        self.urls.append((url, timeout))
        if isinstance(self.body, Exception):
            raise self.body
        return Reply(self.body)


class GatewayTest(unittest.TestCase):
    """Behind a gateway on this machine Claude Code sends no rate_limits; the windows are asked of the gateway."""

    def usage(self, data, entries=QUOTAS['data'], served=lambda session, model: None):
        return plain(statusline.usage_line(data, NOW, UTC, ask=lambda: entries, served=served))

    def entries(self, base, body=json.dumps(QUOTAS).encode()):
        opener = Opener(body)
        return statusline.gateway_entries({statusline.GATEWAY_ENV: base}, opener=opener), opener.urls

    def test_the_claude_account_s_windows_show_when_the_payload_has_none(self):
        self.assertEqual(self.usage(WITHOUT_LIMITS), FULL_LINE)

    def test_the_cli_s_own_figures_win_and_the_gateway_is_not_asked(self):
        def ask():
            raise AssertionError('asked the gateway')
        line = lambda data: plain(statusline.usage_line(data, NOW, UTC, ask=ask))  # noqa: E731
        self.assertEqual(line(CLAUDE), '⏳ 23% → 06:00  41% → Thu 00:00  💰 $0.12')
        self.assertEqual(line(ANTIGRAVITY), '⏳ gemini-weekly 6% → Thu 07:50  💰 $0.42')
        self.assertEqual(line({**WITHOUT_LIMITS, 'rate_limits': {}}), '💰 $0.12')  # every window reset: still claude.ai

    def test_the_model_s_provider_picks_the_account(self):
        codex = {**WITHOUT_LIMITS, 'model': {'id': 'codex/gpt-6-luna'}}
        self.assertEqual(self.usage(codex), '⏳ 30 days 24% → Wed 04:40  💰 $0.12')
        prefixed = {**WITHOUT_LIMITS, 'model': {'id': 'claude/claude-fable-5-2[1m]'}}
        self.assertEqual(self.usage(prefixed), FULL_LINE)
        self.assertEqual(self.usage({**WITHOUT_LIMITS, 'model': None}), FULL_LINE)  # no model: Claude's

    def test_a_group_takes_the_account_that_served_it_in_this_session(self):
        # Claude Code's background calls (Haiku) answer after the group's, so the account that answered
        # last is Claude's; the group's own figures are those of the account that served it.
        group = {**WITHOUT_LIMITS, 'model': {'id': 'auto/gemini-3.8-flash[1m]'}}
        asked = []
        served = lambda session, model: asked.append((session, model)) or 'agy-cli'  # noqa: E731
        self.assertEqual(self.usage(group, QUOTAS['data'] + [AGY], served), '⏳ Gemini · 5 hours 46% → 12:14  💰 $0.12')
        self.assertEqual(asked, [('abc', 'auto/gemini-3.8-flash[1m]')])

    def test_the_log_is_read_only_for_a_group(self):
        def served(session, model):
            raise AssertionError('read the log')
        for model in ('claude-opus-5-5', 'codex/gpt-6-luna', 'claude/claude-fable-5-2[1m]'):
            self.assertNotEqual(self.usage({**WITHOUT_LIMITS, 'model': {'id': model}}, served=served), '', model)
        self.assertEqual(self.usage({**WITHOUT_LIMITS, 'model': {'id': 'auto/x'}}, [], served), '💰 $0.12')  # no gateway

    def test_a_group_the_log_does_not_name_takes_the_account_that_answered_last(self):
        group = {**WITHOUT_LIMITS, 'model': {'id': 'group/auto-claude-opus-5-5'}}
        self.assertEqual(self.usage(group), FULL_LINE)
        self.assertEqual(self.usage(group, served=lambda session, model: 'gemini'), FULL_LINE)  # served by one with no account
        nobody_last = [{**entry, 'last': None} for entry in QUOTAS['data']]
        self.assertEqual(self.usage(group, nobody_last), '💰 $0.12')

    def test_of_several_accounts_the_one_that_answered_last(self):
        older = {'provider': 'claude', 'lastServedAt': '2026-11-01T00:00:00Z',
                 'windows': [{'name': '5 hours', 'used': 99, 'resetsAt': '2026-11-09T06:00:00Z'}]}
        newer = {'provider': 'claude', 'lastServedAt': '2026-11-09T03:00:00Z',
                 'windows': [{'name': '5 hours', 'used': 10, 'resetsAt': '2026-11-09T06:00:00Z'}]}
        self.assertEqual(self.usage(WITHOUT_LIMITS, [older, newer, {'provider': 'claude'}]), '⏳ 10% → 06:00  💰 $0.12')
        self.assertEqual(self.usage(WITHOUT_LIMITS, [{**older, 'last': True}, newer]), '⏳ 99% → 06:00  💰 $0.12')

    def test_no_account_no_windows_or_bad_entries_show_nothing(self):
        bad_windows = [1, {'name': 5, 'used': 1}, {'name': 'x', 'used': '9'}, {'name': 'x', 'used': True}]
        for entries in ([], [QUOTAS['data'][2]], [{'provider': 'claude', 'windows': 'x'}],
                        [{'provider': 'claude', 'windows': bad_windows}], [{'provider': 'claude', 'lastServedAt': 5}]):
            self.assertEqual(self.usage(WITHOUT_LIMITS, entries), '💰 $0.12', entries)

    def test_a_window_whose_reset_has_passed_is_left_out(self):
        windows = [{'name': '5 hours', 'used': 90, 'resetsAt': '2026-11-01T00:00:00Z'}, {'name': '7 days', 'used': 5}]
        self.assertEqual(self.usage(WITHOUT_LIMITS, [{'provider': 'claude', 'windows': windows}]), '⏳ 5%  💰 $0.12')

    def test_only_a_gateway_on_this_machine_is_asked_and_with_no_key(self):
        entries, urls = self.entries('http://127.0.0.1:3425')
        self.assertEqual([entry['provider'] for entry in entries], ['claude', 'codex', 'copilot'])
        self.assertEqual(urls, [('http://127.0.0.1:3425/v1/magpie/quotas', statusline.GATEWAY_TIMEOUT)])
        for base, url in (('http://localhost:3425/anthropic/', 'http://localhost:3425/v1/magpie/quotas'),
                          ('http://[::1]:8080', 'http://[::1]:8080/v1/magpie/quotas'),
                          ('https://127.0.0.1', 'https://127.0.0.1/v1/magpie/quotas'),
                          ('http://user:secret@127.0.0.1:1', 'http://127.0.0.1:1/v1/magpie/quotas')):
            self.assertEqual(self.entries(base)[1], [(url, statusline.GATEWAY_TIMEOUT)], base)
        for base in ('', 'https://gateway.example.com', 'http://10.0.0.5:3425', 'ftp://127.0.0.1', 'not a url',
                     'http://127.0.0.1.example.com', 'http://127.0.0.1:port'):
            self.assertEqual(self.entries(base), ([], []), base)
        self.assertEqual(statusline.gateway_entries({}, opener=Opener(b'{}')), [])

    def test_a_gateway_that_fails_or_answers_otherwise_gives_nothing(self):
        for body in (OSError('refused'), TimeoutError(), b'not json', b'[1]', b'{"data": 3}', b'{"error": "404"}'):
            self.assertEqual(self.entries('http://127.0.0.1:3425', body)[0], [], body)
        self.assertEqual(self.entries('http://127.0.0.1:3425', b'{"data": [1, {"provider": "x"}]}')[0], [{'provider': 'x'}])

    def test_render_asks_the_gateway_only_without_rate_limits(self):
        asked = []
        ask = lambda: asked.append(1) or QUOTAS['data']  # noqa: E731
        self.assertEqual(plain(statusline.render(WITHOUT_LIMITS, ('main', ''), NOW, UTC, ask=ask)[-1]), FULL_LINE)
        statusline.render(CLAUDE, ('main', ''), NOW, UTC, ask=ask)
        self.assertEqual(asked, [1])


def served_line(session, model, provider, status=200):
    """One line of Magpie's request log (~/.config/magpie/usage.jsonl), trimmed to the fields read."""
    return json.dumps({'t': '2026-11-09T03:40:00Z', 'native_session': session, 'model': model,
                       'provider': provider, 'providerAccount': 'someone@example.com', 'status': status})


class GatewayServedTest(unittest.TestCase):
    """The provider that served a group's model in this session, from the tail of Magpie's request log."""

    def served(self, lines, session='abc', model='auto/gemini-3.8-flash[1m]', head=b''):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'usage.jsonl'
            log.write_bytes(head + ''.join(line + '\n' for line in lines).encode())
            return statusline.gateway_served(session, model, str(log))

    def test_the_last_request_for_the_group_s_model_in_this_session(self):
        lines = [served_line('abc', 'gemini-3.8-flash', 'gemini'),
                 served_line('abc', 'gemini-3.8-flash', 'agy-cli'),
                 served_line('abc', 'claude-haiku-5-5', 'claude'),         # this session's background call
                 served_line('other', 'gemini-3.8-flash', 'gemini'),       # another session's
                 served_line('abc', 'gemini-3.8-flash', 'gemini', 429)]    # refused: it did not serve
        self.assertEqual(self.served(lines), 'agy-cli')
        self.assertEqual(self.served(lines, model='auto/gemini-3.8-flash'), 'agy-cli')
        self.assertEqual(self.served(lines, session='other'), 'gemini')

    def test_nothing_when_the_log_names_no_such_request(self):
        lines = [served_line('abc', 'claude-haiku-5-5', 'claude')]
        self.assertIsNone(self.served(lines))
        self.assertIsNone(self.served(lines, session='nobody'))
        for session, model in ((None, 'auto/x'), ('', 'auto/x'), ('abc', 'claude-haiku-5-5'), ('abc', 'auto/')):
            self.assertIsNone(self.served([served_line('abc', 'x', 'claude')], session, model), (session, model))

    def test_bad_lines_are_skipped_and_a_missing_log_gives_nothing(self):
        lines = ['not json', '[1]', '{"native_session": "abc", "model": "gemini-3.8-flash", "provider": 5, "status": 200}',
                 served_line('abc', 'gemini-3.8-flash', 'agy-cli'), '\xff', '']
        self.assertEqual(self.served(lines), 'agy-cli')
        self.assertIsNone(statusline.gateway_served('abc', 'auto/x', '/nonexistent/usage.jsonl'))

    def test_only_the_tail_is_read(self):
        old = served_line('abc', 'gemini-3.8-flash', 'gemini').encode() + b'\n'
        padding = b'x' * statusline.GATEWAY_LOG_TAIL + b'\n'
        self.assertIsNone(self.served([], head=old + padding))             # beyond the tail: not found
        self.assertEqual(self.served([served_line('abc', 'gemini-3.8-flash', 'agy-cli')], head=old + padding), 'agy-cli')


class MainTest(unittest.TestCase):
    def run_main(self, text):
        out = io.StringIO()
        with patch.dict(os.environ, {'HOME': HOME}):
            os.environ.pop(statusline.GATEWAY_ENV, None)
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
                                capture_output=True, text=True, env={**os.environ, 'HOME': HOME, statusline.GATEWAY_ENV: ''})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('🤖 Fable 5.1 · max  📟 v2.1.318', plain(result.stdout))


if __name__ == '__main__':
    unittest.main()
