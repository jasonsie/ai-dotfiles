"""herdr-title: an agent's row in Herdr says what its current prompt is for.

Each hook call goes through the door as the CLIs make it (`ai-dotfiles hook`, lib/door.py), with a
`herdr` and a `claude` on PATH that only write down how they were called.

Run: python3 -m unittest discover -s scripts/tests -p 'test_herdr_title.py' -v
"""
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from support import ROOT, load

sys.path.insert(0, str(ROOT / 'lib'))
import door  # noqa: E402
import features  # noqa: E402

SCRIPT = ROOT / 'skills/herdr-title/scripts/herdr_title.py'
DOOR = ROOT / 'scripts/ai-dotfiles'
TITLE = next(feature for feature in features.find() if feature.name == 'herdr-title')
FAKE = f'''#!{sys.executable}
import json, os, sys, time
name = os.path.basename(sys.argv[0])
if name == 'claude':
    time.sleep(float(os.environ.get('FAKE_CLAUDE_SLEEP', 0)))
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps({{'tool': name, 'argv': sys.argv[1:], 'cwd': os.getcwd(),
                          'herdr_env': sorted(key for key in os.environ if key.startswith('HERDR_'))}}) + '\\n')
if name == 'herdr':
    time.sleep(float(os.environ.get('FAKE_HERDR_SLEEP', 0)))
if name == 'claude':
    sys.stdout.write(os.environ.get('FAKE_CLAUDE_SAYS', ''))
    sys.exit(int(os.environ.get('FAKE_CLAUDE_EXIT', 0)))
'''
GRILL = {'working': 'grill › run', 'blocked': 'grill › wait', 'done': 'grill › wait › done', 'idle': 'idle',
         'unknown': 'idle'}


class Sandbox(unittest.TestCase):
    """A Herdr pane with nothing real in it: fake commands, a state folder, a log of their calls."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin, self.log = self.home / 'bin', self.home / 'calls.jsonl'
        self.bin.mkdir()
        for name in ('herdr', 'claude'):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        self.env = {'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.home), 'FAKE_LOG': str(self.log),
                    'HERDR_TITLE_STATE': str(self.home / 'state'), 'PYTHON': sys.executable,
                    'HERDR_ENV': '1', 'HERDR_PANE_ID': 'w1:p1', 'HERDR_SOCKET_PATH': '/tmp/herdr.sock'}

    def run_script(self, *args, data=None, **env):
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=json.dumps(data or {}), text=True,
                              capture_output=True, env={**self.env, **env}, timeout=30)

    def hook(self, kind, cli='claude', session='s1', env=None, **fields):
        """One hook call as the CLI makes it: the door, the event on stdin."""
        return subprocess.run([str(DOOR), 'hook', kind, '--cli', cli], text=True, capture_output=True, timeout=30,
                              input=json.dumps({'session_id': session, 'cwd': '/w', **fields}),
                              env={**self.env, **(env or {})})

    def calls(self, tool, wait=0):
        """The calls `tool` got so far; with `wait`, as soon as there are that many (5 s at most)."""
        deadline = time.time() + 5
        while True:
            lines = self.log.read_text().splitlines() if self.log.exists() else []
            found = [call for call in map(json.loads, lines) if call['tool'] == tool]
            if len(found) >= wait or time.time() > deadline:
                return found
            time.sleep(0.05)

    def state(self, session='s1'):
        return json.loads((self.home / 'state' / f'{session}.json').read_text())

    def seed(self, session='s1', where='w1:p1', **state):
        """A session that owns `where`, in the state given."""
        (self.home / 'state' / 'panes').mkdir(parents=True, exist_ok=True)
        (self.home / 'state' / f'{session}.json').write_text(json.dumps({'pane': where, 'cli': 'claude', **state}))
        (self.home / 'state' / 'panes' / f'{where.replace(":", "_")}.json').write_text(json.dumps({'session': session}))

    @staticmethod
    def labels(call):
        argv = call['argv']
        return dict(argv[i + 1].split('=', 1) for i, arg in enumerate(argv) if arg == '--state-label')


class CertainTest(Sandbox):
    def test_a_skill_named_in_the_prompt_tags_the_pane_at_once(self):
        done = self.hook('prompt', prompt='Show the status in the title. /grilling to align ahead of execution')
        self.assertEqual((done.returncode, done.stdout), (0, ''))
        (call,) = self.calls('herdr')
        self.assertEqual(call['argv'][:7], ['pane', 'report-metadata', 'w1:p1', '--source', 'user:ai-dotfiles-title',
                                            '--agent', 'claude'])  # Herdr drops the labels when this agent exits
        self.assertEqual(self.labels(call), GRILL)
        self.assertEqual(self.calls('claude'), [])

    def test_approve_alone_or_with_a_pr_number_is_a_command(self):
        for session, prompt in enumerate(('approve', 'Approve 57', 'approve #57.', ' ship it ')):
            self.hook('prompt', session=f's{session}', prompt=prompt)
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')], ['git › run'] * 4)

    def test_a_sentence_that_only_contains_a_command_word_is_not_one(self):
        self.hook('prompt', prompt='all approve and do them all for me')
        (call,) = self.calls('herdr')
        self.assertEqual(self.labels(call)['working'], 'run')  # reported at once, before the model names a type
        self.assertEqual(len(self.calls('claude', wait=1)), 1)

    def test_a_plugins_skill_and_a_dollar_skill_count_and_the_first_one_wins(self):
        prompts = ('take /zkfy:zk-note on each page', '$tutor based on this session',
                   '/web-clipper:web-clipper, https://example.com/llm', '"/grill-me" first, then /plan.')
        for session, prompt in enumerate(prompts):
            self.hook('prompt', cli='codex', session=f's{session}', prompt=prompt)
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')],
                         ['note › run', 'explain › run', 'note › run', 'grill › run'])

    def test_a_path_or_an_unknown_name_is_not_a_skill(self):
        for session, prompt in enumerate(('read /Users/me/research/x.md and docs/grilling.md',
                                          'see https://example.com/plan and ~/onboard/notes',
                                          '/model then /clear', 'costs $5 and $HOME/tdd.txt')):
            self.hook('prompt', session=f's{session}', prompt=prompt)
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')], ['run'] * 4)

    def test_a_prompt_the_user_did_not_type_keeps_the_tag(self):
        for prompt in ('Another Claude session sent a message:\n<agent-message from="a1">/grilling done</agent-message>',
                       '[SYSTEM NOTIFICATION - NOT USER INPUT]\n<task-notification>approve</task-notification>',
                       '<teammate-message teammate_id="discover">/research finished</teammate-message>',
                       '<local-command-stdout>Set model to /plan</local-command-stdout>',
                       '<bash-stdout>ran /tdd</bash-stdout>', '<system-reminder>\n/grilling</system-reminder>', '   '):
            self.hook('prompt', prompt=prompt)
        self.assertEqual(self.calls('herdr'), [])
        self.assertEqual(self.calls('claude'), [])

    def test_a_subagent_or_teammate_shares_the_pane_and_leaves_its_tag_alone(self):
        self.hook('prompt', prompt='/grilling')
        self.hook('prompt', prompt='/implement the reader', agent_id='agent-abc', agent_type='general-purpose')
        self.hook('prompt', prompt='then explain it to me', agent_id='agent-abc', env={'FAKE_CLAUDE_SAYS': 'EXPLAIN'})
        self.hook('end', agent_id='agent-abc')
        self.assertEqual([self.labels(call) for call in self.calls('herdr')], [GRILL])
        self.assertEqual({key: self.state()[key] for key in ('event', 'type', 'ended')},
                         {'event': 1, 'type': 'grill', 'ended': False})  # TurnTest: no model's turn either


class EndTest(Sandbox):
    def test_session_end_takes_the_labels_off_and_keeps_the_type_for_a_resume(self):
        self.hook('prompt', prompt='/grilling')
        done = self.hook('end')
        self.assertEqual((done.returncode, done.stdout), (0, ''))
        tagged, cleared = (call['argv'] for call in self.calls('herdr'))
        self.assertEqual(cleared[:8], ['pane', 'report-metadata', 'w1:p1', '--source', 'user:ai-dotfiles-title',
                                       '--agent', 'claude', '--clear-state-labels'])
        # Herdr drops a report whose --seq is not above the source's last one.
        self.assertGreater(int(cleared[cleared.index('--seq') + 1]), int(tagged[tagged.index('--seq') + 1]))
        self.assertEqual((self.state()['type'], self.state()['ended']), ('grill', True))
        self.assertFalse((self.home / 'state' / 'panes' / 'w1_p1.json').exists())

    def test_a_session_that_ends_waiting_for_the_user_takes_its_need_token_off_too(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('stop', last_assistant_message='Which one, A or B?')
        self.hook('end')  # /clear or Pi's /new: the CLI runs on in the pane, and Herdr keeps a token until cleared
        asked, cleared = (call['argv'] for call in self.calls('herdr')[1:])
        self.assertIn('need=1', asked)
        self.assertEqual(cleared[cleared.index('--clear-token') + 1], 'need')

    def test_the_end_of_a_session_the_pane_no_longer_belongs_to_changes_nothing(self):
        self.hook('prompt', session='old', prompt='/grilling')
        self.hook('prompt', session='new', prompt='/tdd')  # typed into the same pane: it is the new session's now
        self.hook('end', session='old', cli='claude')
        self.assertEqual(len(self.calls('herdr')), 2)  # no clear
        self.assertFalse(self.state('old')['ended'])

    def test_pis_reload_keeps_the_session_and_its_labels(self):
        self.hook('prompt', cli='pi', prompt='/grilling')
        self.hook('end', cli='pi', reason='reload')
        self.assertEqual(len(self.calls('herdr')), 1)
        self.hook('end', cli='pi', reason='quit')
        self.assertIn('--clear-state-labels', self.calls('herdr')[-1]['argv'])


class ModelTest(Sandbox):
    """A prompt that names no purpose goes to a small model, in a process the hook does not wait for."""

    def transcript(self, last):
        """A Claude Code transcript whose last reply is `last`."""
        rows = [{'type': 'user', 'timestamp': '2026-11-19T04:00:00Z', 'cwd': '/w', 'message': {'content': 'grill me'}},
                {'type': 'assistant', 'timestamp': '2026-11-19T04:00:09Z',
                 'message': {'content': [{'type': 'text', 'text': last}]}}]
        path = self.home / 'session.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return str(path)

    def test_the_model_sees_the_agents_last_message_and_its_answer_tags_the_pane(self):
        self.hook('prompt', prompt='/grilling')
        path = self.transcript('That is every decision. Confirm and I will build it.')
        self.hook('prompt', prompt='y', transcript_path=path, env={'FAKE_CLAUDE_SAYS': 'EXECUTE'})
        tagged = self.calls('herdr', wait=3)  # /grilling, y at once with the type it has, the model's answer
        self.assertEqual(self.labels(tagged[1])['working'], 'grill › run')
        self.assertEqual(self.labels(tagged[2]), {'working': 'execute › run', 'blocked': 'execute › wait',
                                                  'done': 'execute › wait › done', 'idle': 'idle', 'unknown': 'idle'})
        (asked,) = self.calls('claude')
        flag, question, *options = asked['argv']
        self.assertEqual(flag, '-p')
        self.assertIn('Current label: grill', question)
        self.assertIn('Confirm and I will build it.', question)
        self.assertTrue(question.endswith('\ny'), question)
        for name, value in (('--model', 'haiku'), ('--tools', ''), ('--setting-sources', 'project')):
            self.assertEqual(options[options.index(name) + 1], value, name)
        self.assertIn('--no-session-persistence', options)
        self.assertIn('--strict-mcp-config', options)
        system = options[options.index('--system-prompt') + 1]
        self.assertIn('execute: make the change, build it, do the task', system)
        self.assertIn('keep:', system)
        # The model's CLI must not know the pane: its own hooks would report to it.
        self.assertEqual(asked['herdr_env'], [])
        self.assertTrue(asked['cwd'].startswith(os.path.realpath(self.home / 'state')), asked['cwd'])
        self.assertEqual(self.state()['type'], 'execute')

    def test_the_hook_returns_before_the_model_answers(self):
        self.hook('prompt', prompt='how does this work', env={'FAKE_CLAUDE_SAYS': 'EXPLAIN', 'FAKE_CLAUDE_SLEEP': '1.5'})
        self.assertEqual(self.calls('claude'), [])  # the fake model writes its line only once it answers
        (first,) = self.calls('herdr')
        self.assertEqual(self.labels(first)['working'], 'run')  # no type yet
        self.assertEqual(self.labels(self.calls('herdr', wait=2)[1])['working'], 'explain › run')

    def classify(self, says='EXECUTE', code=0, **request):
        """The model's turn by itself, as the hook starts it, with the model saying `says`."""
        asked = {'job': 'type', 'cli': 'claude', 'session': 's1', 'prompt': 'y', 'transcript': '', 'trigger': 5, **request}
        return self.run_script('classify', data=asked, FAKE_CLAUDE_SAYS=says, FAKE_CLAUDE_EXIT=str(code))

    def test_keep_a_word_that_is_no_tag_or_a_failed_call_leaves_the_tag(self):
        self.seed(type='grill', typed=5)  # each answer below is for this session's latest prompt
        for says, code in (('KEEP', 0), ('banana', 0), ('', 0), ('EXECUTE', 1)):
            done = self.classify(says, code)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, '', ''), says)
        self.assertEqual(len(self.calls('claude')), 4)
        (self.bin / 'claude').unlink()  # no claude on this machine
        self.assertEqual(self.classify().returncode, 0)
        self.assertEqual(self.calls('herdr'), [])
        self.assertEqual(self.state()['type'], 'grill')

    def test_a_late_answer_for_a_session_that_lost_the_pane_reports_nothing(self):
        self.hook('prompt', prompt='how does it work', env={'FAKE_CLAUDE_SAYS': 'EXPLAIN', 'FAKE_CLAUDE_SLEEP': '1'})
        self.hook('prompt', session='s2', prompt='/tdd')  # typed into the same pane while the model thinks
        deadline = time.time() + 10
        while self.state().get('type') != 'explain' and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.state()['type'], 'explain')  # s1's answer still lands in s1's state
        time.sleep(0.5)  # its report would follow at once
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')], ['run', 'execute › run'])

    def test_an_answer_that_comes_after_a_newer_tag_is_dropped(self):
        self.hook('prompt', prompt='/grilling')  # typed now; the answer below is for a prompt before it
        self.classify('EXECUTE', trigger=0)
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')], ['grill › run'])
        self.assertEqual(self.state()['type'], 'grill')

    def test_a_long_reply_is_cut_to_its_end_and_a_long_prompt_to_its_start_and_end(self):
        path = self.transcript('Opening words. ' + 'r' * 3000 + ' Shall I build it?')
        self.classify(transcript=path, prompt='First line. ' + 'p' * 3000 + ' why does it fail?')
        question = self.calls('claude')[0]['argv'][1]
        self.assertLess(len(question), 2000)
        self.assertIn('Shall I build it?', question)  # a reply ends with what it asks
        self.assertNotIn('Opening words.', question)
        self.assertIn('First line.', question)
        self.assertIn('why does it fail?', question)  # a pasted log comes before the question about it

    def test_the_answer_may_come_in_lower_case_or_inside_a_sentence(self):
        for session, says in enumerate(('execute\n', 'The label is DEBUG.', '**Review**', 'I would keep it: KEEP, not PLAN')):
            self.seed(f's{session}', where=f'w1:p{session}', typed=5)
            self.classify(says, session=f's{session}')
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')],
                         ['execute › run', 'debug › run', 'review › run'])


class StopTest(Sandbox):
    """A turn ends: the label says what the agent waits for, at once when it can, else after a model's turn."""

    def stopped(self, last, cli='claude', says='', session='s1', **fields):
        """A prompt typed as /tdd, then a stop whose reply ends with `last`; the model says `says`."""
        self.hook('prompt', cli=cli, session=session, prompt='/tdd')
        return self.hook('stop', cli=cli, session=session, last_assistant_message=last, env={'FAKE_CLAUDE_SAYS': says},
                         **fields)

    def after(self, wait):
        """The done and idle labels of the reports so far, once there are `wait` of them."""
        return [(self.labels(call)['done'], self.labels(call)['idle']) for call in self.calls('herdr', wait=wait)]

    def test_a_reply_that_ends_by_asking_is_ask_at_once(self):
        done = self.stopped('Built both.\n\nWhich name do you want, A or B?**')
        self.assertEqual((done.returncode, done.stdout), (0, ''))
        self.assertEqual(self.after(2)[1], ('execute › wait › ask', 'execute › wait › ask'))  # TurnTest: no model

    def test_a_codex_reply_that_ends_with_its_plan_is_ask_at_once(self):
        done = self.stopped('<proposed_plan>\n1. Add the reader.\n</proposed_plan>\n', cli='codex')
        self.assertEqual(done.stdout, '{}\n')  # Codex wants JSON from a Stop hook
        self.assertEqual(self.after(2)[1][0], 'execute › wait › ask')

    def test_any_other_reply_keeps_run_until_the_model_says_what_it_waits_for(self):
        self.stopped('All tests pass and the reader is in.', says='DONE')
        rows = self.after(3)
        self.assertEqual(rows[1], ('execute › run', 'execute › run'))  # at once: still the agent's move
        self.assertEqual(rows[2], ('execute › wait › done', 'idle'))
        (asked,) = self.calls('claude')
        self.assertEqual(asked['argv'][1], "The agent's last message ended:\nAll tests pass and the reader is in.")
        system = asked['argv'][asked['argv'].index('--system-prompt') + 1]
        self.assertIn('ASK:', system)
        self.assertEqual(asked['herdr_env'], [])
        self.assertEqual(self.state()['mode'], 'normal')

    def test_wait_counts_only_while_claude_lists_background_work_that_reports_back(self):
        self.stopped('Three reviewers are running; I will report when they finish.', says='WAIT',
                     background_tasks=[{'type': 'subagent', 'id': 'a1'}])
        self.assertEqual(self.after(3)[2], ('execute › run', 'execute › run'))
        self.stopped('I will report when the dev server is up.', says='WAIT', session='s2',
                     background_tasks=[{'type': 'shell', 'id': 'b1'}])  # it may be a server that never ends
        self.calls('herdr', wait=6)  # s2's prompt, its stop, the model's verdict
        self.assertEqual(self.state('s2')['mode'], 'normal')

    def test_a_scheduled_wake_up_makes_wait_count_and_the_turn_it_wakes_starts_normal(self):
        self.stopped('I will check the build again in five minutes.', says='WAIT',
                     session_crons=[{'id': 'c1', 'schedule': '*/5 * * * *', 'recurring': True, 'prompt': 'check the build'}])
        self.assertEqual(self.after(3)[2], ('execute › run', 'execute › run'))
        self.hook('prompt', prompt='check the build')  # it fires: not typed, and its stop says what comes next
        self.assertEqual(self.state()['mode'], 'normal')

    def test_no_answer_from_the_model_reads_wait_with_no_result_and_needs_the_user(self):
        self.stopped('Here is where things stand.', says='banana')
        self.assertEqual(self.after(3)[2], ('execute › wait', 'execute › wait'))
        self.assertIn('need=1', self.calls('herdr')[2]['argv'])  # a look costs less than a missed ask

    def test_an_api_error_or_claudes_usage_limit_note_is_fail_at_once(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('error', error='rate_limit')
        self.assertEqual(self.after(2)[1], ('execute › wait › fail', 'execute › wait › fail'))
        rows = [{'type': 'user', 'timestamp': '2026-11-19T04:00:00Z', 'message': {'content': 'build it'}},
                {'type': 'user', 'isMeta': True, 'timestamp': '2026-11-19T04:00:05Z',
                 'message': {'content': '[Usage limit reached; a short grace allowance remains.]'}}]
        path = self.home / 'limit.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.stopped('Stopping here until the limit resets.', session='s2', transcript_path=str(path))
        self.assertEqual(self.state('s2')['mode'], 'fail')

    def test_a_report_after_a_failure_starts_its_turn_in_normal_mode(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('error', error='overloaded')
        self.hook('prompt', prompt='<task-notification>a reviewer finished</task-notification>')
        self.assertEqual(self.state()['mode'], 'normal')  # that turn's end says what comes next
        self.assertIn('--clear-token', self.calls('herdr', wait=3)[2]['argv'])  # a working row sorts as no one's move

    def test_pis_error_and_abort_are_known_at_once(self):
        self.stopped('Request failed.', cli='pi', outcome='error')
        self.assertEqual(self.state()['mode'], 'fail')
        self.stopped('Partial answer', cli='pi', outcome='aborted', session='s2')
        self.assertEqual(self.state('s2')['mode'], 'normal')

    def test_an_open_ask_stays_through_a_turn_the_user_did_not_start(self):
        self.stopped('Shall I build it?')
        self.hook('prompt', prompt='<task-notification>a reviewer finished</task-notification>')
        self.assertEqual(self.labels(self.calls('herdr', wait=3)[2])['working'], 'execute › wait › ask')
        self.hook('stop', last_assistant_message='One of three reviewers is back.')
        self.assertEqual(self.state()['mode'], 'ask')

    def test_a_scheduled_prompt_firing_is_not_typed_and_keeps_an_open_ask(self):
        long = 'Summarize the night. ' + 'x' * 1100
        self.stopped('Which name do you want, A or B?', session_crons=[
            {'id': 'c1', 'schedule': '*/5 * * * *', 'recurring': True, 'prompt': 'check the build'},
            {'id': 'c2', 'schedule': '0 9 * * *', 'recurring': True, 'prompt': long[:1000] + '… [+121 chars]'}])
        for prompt in ('check the build', long):  # a /loop tick, a cron, a wake-up: no mark of its own
            self.hook('prompt', prompt=prompt)
            self.assertEqual({key: self.state()[key] for key in ('mode', 'typed_turn', 'typed', 'type')},
                             {'mode': 'ask', 'typed_turn': False, 'typed': 1, 'type': 'execute'}, prompt[:20])
        self.hook('prompt', prompt='check the build twice')  # typed: no scheduled prompt says exactly this
        self.assertEqual((self.state()['mode'], self.state()['typed']), ('normal', 5))  # the fifth event

    def test_a_late_verdict_after_a_newer_prompt_is_dropped(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('stop', last_assistant_message='That is everything.',
                  env={'FAKE_CLAUDE_SAYS': 'ASK', 'FAKE_CLAUDE_SLEEP': '1'})
        self.hook('prompt', prompt='/grilling')  # the user moved on before the model answered
        self.calls('claude', wait=1)  # the fake model writes its line once it answers
        time.sleep(0.5)  # a verdict it applied would be saved and reported at once
        self.assertEqual((self.state()['type'], self.state()['mode']), ('grill', 'normal'))
        self.assertEqual(self.labels(self.calls('herdr')[-1])['working'], 'grill › run')

    def test_a_codex_interrupt_ends_the_turn_in_normal_mode(self):
        self.hook('prompt', cli='codex', prompt='/tdd')
        self.assertEqual(self.after(1)[0], ('execute › wait', 'execute › wait'))  # until its stop hook answers
        self.hook('interrupt', cli='codex')
        self.assertEqual(self.after(2)[1], ('execute › wait › done', 'idle'))

    def test_codexs_interrupt_and_end_give_up_on_a_hung_herdr_within_codexs_3_s_cap(self):
        self.hook('prompt', cli='codex', prompt='/tdd')
        for kind in ('interrupt', 'end'):
            started = time.time()
            self.hook(kind, cli='codex', env={'FAKE_HERDR_SLEEP': '30'})
            self.assertLess(time.time() - started, 3.0, kind)

    def test_the_stop_of_a_session_the_pane_does_not_belong_to_changes_nothing(self):
        self.hook('prompt', session='before', prompt='/grilling')
        self.hook('prompt', prompt='/tdd')  # s1 takes the pane over
        kept = self.state('before')
        for last in ('Which file?', 'All done.'):
            self.hook('stop', session='before', last_assistant_message=last)
        self.assertEqual(self.state('before'), kept)
        self.assertEqual(len(self.calls('herdr')), 2)


class DialogTest(Sandbox):
    """A dialog says what it waits for: allow for a permission, ask for a question, a plan or a form."""

    def blocked(self, wait):
        return self.labels(self.calls('herdr', wait=wait)[wait - 1])['blocked']

    def test_each_dialog_reads_allow_or_ask_and_prints_nothing(self):
        self.hook('prompt', prompt='/tdd')
        for number, (kind, tool, said) in enumerate((('permission', 'Bash', 'execute › wait › allow'),
                                                     ('permission', 'AskUserQuestion', 'execute › wait › ask'),
                                                     ('pre', 'ExitPlanMode', 'execute › wait › ask'),
                                                     ('form', '', 'execute › wait › ask')), start=2):
            done = self.hook(kind, tool_name=tool)
            self.assertEqual((done.returncode, done.stdout), (0, ''), kind)  # a reply here would decide the dialog
            self.assertEqual(self.blocked(number), said, (kind, tool))

    def test_a_subagents_permission_dialog_and_codexs_count_too(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('permission', tool_name='Bash', agent_id='agent-1')
        self.assertEqual(self.blocked(2), 'execute › wait › allow')
        self.hook('prompt', cli='codex', session='c1', prompt='/tdd')
        self.assertEqual(self.hook('permission', cli='codex', session='c1', tool_name='Bash').stdout, '')
        self.assertEqual(self.blocked(4), 'execute › wait › allow')

    def test_the_next_turn_end_or_prompt_forgets_the_dialog(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('permission', tool_name='Bash')
        self.hook('stop', last_assistant_message='Which one?')
        self.assertEqual(self.blocked(3), 'execute › wait')
        for number, prompt in enumerate(('/tdd', '<task-notification>a reviewer finished</task-notification>'), start=4):
            self.hook('permission', tool_name='Bash')
            self.hook('prompt', prompt=prompt)  # typed, then not
            self.assertEqual(self.blocked(2 * number - 3), 'execute › wait', prompt)


class StartTest(Sandbox):
    """A resumed Claude Code session (Pi's start is in PiExtensionTest): the kept state comes back."""

    def test_a_resumed_session_labels_its_pane_again_with_its_kept_state(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('stop', last_assistant_message='Which one, A or B?')
        self.hook('end')
        self.assertEqual(self.hook('start', source='resume').stdout, '')  # SessionStart's stdout would be context
        back = self.labels(self.calls('herdr', wait=4)[3])
        self.assertEqual((back['done'], back['idle']), ('execute › wait › ask', 'execute › wait › ask'))

    def test_a_verdict_that_died_with_its_process_reads_a_bare_wait_at_a_resume_or_an_end(self):
        self.seed(type='execute', mode='pending', event=3)
        self.hook('start', source='resume')
        self.assertEqual(self.state()['mode'], 'unknown')
        self.assertEqual(self.labels(self.calls('herdr', wait=1)[0])['done'], 'execute › wait')
        self.seed(type='execute', mode='pending', event=5)
        self.hook('end')
        self.assertEqual(self.state()['mode'], 'unknown')  # what a resume will show

    def test_a_new_or_cleared_session_and_a_pane_another_session_owns_change_nothing(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('end')
        for source in ('startup', 'clear', 'compact'):
            self.hook('start', source=source)
        self.hook('prompt', session='other', prompt='/grilling')
        self.hook('start', source='resume')  # s1 comes back where the other session now works
        self.assertEqual(len(self.calls('herdr')), 3)


class ViewTest(Sandbox):
    """Rows that need the user carry a token, and Herdr's agent list sorts them first."""

    def setUp(self):
        super().setUp()
        self.requests = []
        path = Path(tempfile.mkdtemp(prefix='h', dir='/tmp')) / 's'  # a socket path stays short
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        server.listen()
        self.addCleanup(server.close)
        self.env['HERDR_SOCKET_PATH'] = str(path)

        def serve():
            while True:
                try:
                    conn, _ = server.accept()
                except OSError:
                    return
                with conn:
                    line = conn.makefile().readline()
                    self.requests.append(json.loads(line))
                    conn.sendall(b'{"id":"herdr-title-view","result":{"type":"agent_view","active":true}}\n')
        threading.Thread(target=serve, daemon=True).start()

    def need(self, call):
        argv = call['argv']
        if '--token' in argv:
            return argv[argv.index('--token') + 1]
        return 'cleared' if argv[argv.index('--clear-token') + 1] == 'need' else None

    def test_a_typed_prompt_and_a_stop_set_the_view_with_the_rows_that_need_the_user_first(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('stop', last_assistant_message='Which one?')
        self.assertEqual(len(self.requests), 2)
        request = self.requests[0]
        self.assertEqual((request['method'], request['params']['source']), ('agent.view.set', 'user:ai-dotfiles-title'))
        self.assertEqual(request['params']['sort'][0], {'field': {'token': 'need'}, 'order': 'desc'})

    def test_a_resume_sets_the_view_again(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('end')
        self.hook('start', source='resume')  # after a restart of Herdr's server, which drops the view
        self.assertEqual(len(self.requests), 2)

    def test_the_need_token_follows_the_mode(self):
        self.hook('prompt', prompt='/tdd')
        self.hook('stop', last_assistant_message='Which one?')
        self.hook('prompt', prompt='/tdd')
        self.hook('error', error='overloaded')
        self.assertEqual([self.need(call) for call in self.calls('herdr', wait=4)],
                         ['cleared', 'need=1', 'cleared', 'need=1'])


DRIVER = """
import extension from %s;
const on = {};
extension({ on: (name, handler) => { on[name] = handler; } });
const ctx = { cwd: "/w", isIdle: () => true, model: { id: "m" },
              sessionManager: { getSessionId: () => "p1", getSessionFile: () => "" } };
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
on.input({ text: "/tdd", source: "interactive" }, ctx);
await pause(800);
on.turn_end({ message: { role: "assistant", content: [{ type: "text", text: "Which name, A or B?" }] },
              outcome: "completed" }, ctx);
on.agent_settled({}, ctx);
await pause(800);
on.session_shutdown({ reason: "reload" }, ctx);
on.input({ text: "an extension's prompt", source: "extension" }, ctx);
await pause(800);
on.session_shutdown({ reason: "quit" }, ctx);
on.session_start({ reason: "startup" }, ctx);
await pause(800);
"""


@unittest.skipUnless(shutil.which('node'), 'Node runs Pi\'s extension here')
class PiExtensionTest(Sandbox):
    """scripts/agent_hooks.ts as Pi loads it: input, a settled run, a reload, a quit and a start."""

    def test_pis_input_and_settled_run_label_the_pane_a_reload_keeps_it_and_a_restart_brings_it_back(self):
        driver = self.home / 'driver.mjs'
        driver.write_text(DRIVER % json.dumps(str(ROOT / 'scripts/agent_hooks.ts')))
        done = subprocess.run(['node', '--experimental-strip-types', '--no-warnings', str(driver)],
                              capture_output=True, text=True, env={**self.env, 'PATH': f'{self.bin}:{os.environ["PATH"]}'},
                              timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.calls('herdr', wait=5)
        # Typed input, the settled run that asked, then the extension's prompt: not typed, so the ask stays.
        self.assertEqual([self.labels(call)['working'] for call in calls[:3]],
                         ['execute › run', 'execute › wait › ask', 'execute › wait › ask'])
        self.assertEqual(self.labels(calls[1])['done'], 'execute › wait › ask')
        self.assertEqual(calls[1]['argv'][5:7], ['--agent', 'pi'])
        self.assertFalse(any('--clear-state-labels' in call['argv'] for call in calls[:3]))  # the reload kept them
        # Pi starts every launch with reason startup, `pi -c` and Herdr's restore too: the kept state is back.
        self.assertIn('--clear-state-labels', calls[3]['argv'])
        self.assertEqual(self.labels(calls[4])['done'], 'execute › wait › ask')


class OwnerTest(Sandbox):
    """A pane's labels belong to the session the user last typed into there."""

    def test_a_teammate_in_claudes_tmux_server_or_a_headless_run_changes_nothing(self):
        for env in ({'TMUX': '/private/tmp/tmux-501/claude-swarm-4242,77,0'}, {'CLAUDE_CODE_ENTRYPOINT': 'sdk-cli'}):
            self.hook('prompt', prompt='/grilling', env=env)
            self.hook('end', env=env)
        self.assertEqual(self.calls('herdr'), [])
        self.assertFalse((self.home / 'state' / 's1.json').exists())

    def test_the_users_own_tmux_and_an_interactive_run_still_count(self):
        self.hook('prompt', prompt='/grilling', env={'TMUX': '/private/tmp/tmux-501/default,1,0',
                                                     'CLAUDE_CODE_ENTRYPOINT': 'cli'})
        self.assertEqual(len(self.calls('herdr')), 1)

    def test_a_prompt_the_user_did_not_type_relabels_only_the_panes_own_session(self):
        self.hook('prompt', session='before', prompt='/grilling')
        self.hook('prompt', prompt='/tdd')  # s1 takes the pane over
        kept = self.state('before')
        report = '<task-notification>a background agent finished</task-notification>'
        self.hook('prompt', session='before', prompt=report)  # no longer the pane's session
        self.assertEqual(self.state('before'), kept)
        self.hook('prompt', prompt=report)  # the pane's own session: the turn it starts keeps the type
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')],
                         ['grill › run', 'execute › run', 'execute › run'])

    def test_a_pi_prompt_an_extension_sent_is_not_typed(self):
        self.hook('prompt', cli='pi', prompt='/tdd', source='extension')
        self.assertEqual(self.calls('herdr'), [])
        self.hook('prompt', cli='pi', prompt='/tdd', source='interactive')
        self.assertEqual(self.labels(self.calls('herdr')[0])['working'], 'execute › run')


class LabelTest(unittest.TestCase):
    """The matrix: the label each mode shows under each state Herdr detects."""

    def setUp(self):
        self.module = load('../skills/herdr-title/scripts/herdr_title.py')
        self.settings = self.module.config()

    def labels(self, **state):
        return self.module.labels(state, self.settings)

    def test_each_mode_under_each_herdr_state(self):
        rows = {mode: self.labels(type='execute', mode=mode) for mode in self.module.AFTER}
        self.assertEqual({mode: (row['done'], row['idle']) for mode, row in rows.items()}, {
            'normal': ('execute › wait › done', 'idle'), 'open': ('execute › wait', 'execute › wait'),
            'pending': ('execute › run', 'execute › run'), 'ask': ('execute › wait › ask', 'execute › wait › ask'),
            'wait': ('execute › run', 'execute › run'), 'fail': ('execute › wait › fail', 'execute › wait › fail'),
            'unknown': ('execute › wait', 'execute › wait')})
        self.assertEqual({row['working'] for mode, row in rows.items() if mode != 'ask'}, {'execute › run'})
        self.assertEqual(rows['ask']['working'], 'execute › wait › ask')  # its background agents keep Herdr working
        self.assertTrue(all(row['unknown'] == row['idle'] for row in rows.values()))

    def test_a_dialog_says_what_it_waits_for_when_a_hook_knows(self):
        self.assertEqual(self.labels(type='git')['blocked'], 'git › wait')
        self.assertEqual(self.labels(type='git', blocked='allow')['blocked'], 'git › wait › allow')
        self.assertEqual(self.labels(type='git', blocked='ask')['blocked'], 'git › wait › ask')

    def test_without_a_type_the_type_layer_is_left_out(self):
        self.assertEqual(self.labels(mode='ask'), {'working': 'wait › ask', 'blocked': 'wait', 'done': 'wait › ask',
                                                    'idle': 'wait › ask', 'unknown': 'wait › ask'})
        self.assertEqual(self.labels()['working'], 'run')


class TurnTest(Sandbox):
    """Which hook calls start a model's turn, in this process with the detached start replaced: a
    turn that must not start shows at once, with no waiting for a process that should not exist."""

    def setUp(self):
        super().setUp()
        self.module = door.module_of(TITLE)  # the module the door runs
        self.asked = []
        for patcher in (mock.patch.object(self.module, 'ask_later', self.asked.append),
                        mock.patch.dict(os.environ, self.env, clear=True)):  # no TMUX or entrypoint of the runner's
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, kind, cli='claude', session='s1', **fields):
        data = json.dumps({'session_id': session, 'cwd': '/w', **fields})
        with mock.patch('sys.stdin', io.StringIO(data)), mock.patch('sys.stdout', io.StringIO()):
            self.assertEqual(door.main(['hook', kind, '--cli', cli]), 0)

    def test_a_prompt_starts_one_only_when_typed_and_naming_no_type(self):
        self.call('prompt', prompt='/tdd')
        self.call('prompt', prompt='<task-notification>a reviewer finished</task-notification>')
        self.call('prompt', prompt='how does it work', agent_id='agent-1')  # a subagent's
        self.assertEqual((self.asked, self.state()['event']), ([], 2))  # both of the session's prompts ran
        self.call('prompt', prompt='how does it work')
        self.assertEqual([(job['job'], job['trigger']) for job in self.asked], [('type', 3)])

    def test_a_stop_starts_one_only_when_no_rule_decides_it(self):
        self.call('prompt', prompt='/tdd')
        self.call('stop', last_assistant_message='Which name do you want, A or B?')
        self.call('prompt', prompt='<task-notification>a reviewer finished</task-notification>')
        self.call('stop', last_assistant_message='One of three reviewers is back.')  # the ask stays open
        self.assertEqual(self.state()['mode'], 'ask')
        rows = [{'type': 'user', 'timestamp': '2026-11-19T04:00:00Z', 'message': {'content': 'build it'}},
                {'type': 'user', 'isMeta': True, 'timestamp': '2026-11-19T04:00:05Z',
                 'message': {'content': '[Usage limit reached; a short grace allowance remains.]'}}]
        path = self.home / 'limit.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.call('prompt', prompt='/tdd')
        self.call('stop', last_assistant_message='Stopping here.', transcript_path=str(path))
        self.call('prompt', prompt='/tdd')
        self.call('error', error='overloaded')
        self.assertEqual((self.asked, self.state()['mode']), ([], 'fail'))
        self.call('prompt', prompt='/tdd')
        self.call('stop', last_assistant_message='All tests pass.')
        self.assertEqual([job['job'] for job in self.asked], ['stop'])

    def test_pis_error_and_abort_start_none(self):
        for outcome, mode in (('error', 'fail'), ('aborted', 'normal')):
            self.call('prompt', cli='pi', prompt='/tdd')
            self.call('stop', cli='pi', last_assistant_message='Partial answer', outcome=outcome)
            self.assertEqual((self.asked, self.state()['mode']), ([], mode), outcome)

    def test_the_model_reads_the_replys_last_800_characters_and_learns_of_work_that_wakes_the_agent(self):
        reply = 'Opening words. ' + 'r' * 3000 + ' I will report back.'
        for work in ({'background_tasks': [{'type': 'shell', 'id': 'b1'}]},  # it may be a server that never ends
                     {'background_tasks': [{'type': 'subagent', 'id': 'a1'}]},
                     {'background_tasks': [{'type': 'monitor', 'id': 'm1'}]},  # each event it sees wakes the agent
                     {'session_crons': [{'id': 'c1', 'prompt': 'check the build'}]}):
            self.call('prompt', prompt='/tdd')
            self.call('stop', last_assistant_message=reply, **work)
        self.assertEqual([job['text'] for job in self.asked], [reply[-800:]] * 4)
        self.assertEqual([job['background'] for job in self.asked], [False, True, True, True])


class QuietTest(Sandbox):
    def test_outside_herdr_nothing_runs_and_nothing_is_kept(self):
        for missing in ('HERDR_ENV', 'HERDR_PANE_ID'):
            env = {key: value for key, value in self.env.items() if key != missing}
            done = subprocess.run([str(DOOR), 'hook', 'prompt', '--cli', 'claude'], text=True,
                                  input=json.dumps({'session_id': 's1', 'prompt': '/grilling'}),
                                  capture_output=True, env=env, timeout=30)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, '', ''), missing)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.home / 'state').exists())

    def test_codex_still_gets_json_from_its_stop_hook_outside_herdr(self):
        env = {key: value for key, value in self.env.items() if key != 'HERDR_ENV'}
        for cli, said in (('codex', '{}\n'), ('claude', ''), ('pi', '')):
            done = subprocess.run([str(DOOR), 'hook', 'stop', '--cli', cli], text=True,
                                  input=json.dumps({'session_id': 's1'}), capture_output=True, env=env, timeout=30)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, said, ''), cli)
        self.assertFalse(self.log.exists())

    def test_input_it_cannot_read_is_met_with_silence(self):
        for args, text in ((('hook', 'prompt', '--cli', 'claude'), 'not json'),
                           (('hook', 'prompt', '--cli', 'agy'), '{}'), (('hook', 'nonsense'), '{}')):
            done = subprocess.run([str(DOOR), *args], input=text, text=True,
                                  capture_output=True, env=self.env, timeout=30)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, '', ''), args)
        self.assertEqual(self.calls('herdr'), [])


class ConfigTest(unittest.TestCase):
    """config/herdr-title.json: the types, the label's words, and what decides a type at once."""

    def setUp(self):
        self.config = json.loads((ROOT / 'config/herdr-title.json').read_text())

    def test_ten_lower_case_types_each_with_a_meaning_and_every_label_fits_its_row(self):
        types, words = self.config['types'], self.config['words']
        self.assertEqual(len(types), 10)
        for kind, means in types.items():
            self.assertTrue(kind.isalpha() and kind.islower(), kind)
            self.assertTrue(means.strip(), kind)
        longest = max(len(kind) for kind in types) + max(len(words[r]) for r in ('ask', 'allow', 'fail', 'done'))
        longest += len(words['wait']) + 2 * len(words['separator'])
        self.assertLessEqual(longest, 22)  # the label's own row in a sidebar of 26 columns

    def test_the_words_are_distinct_and_no_type_is_a_word(self):
        words = {key: value for key, value in self.config['words'].items() if key != 'separator'}
        self.assertEqual(len(set(words.values())), len(words))
        self.assertEqual(set(words.values()) & set(self.config['types']), set())

    def test_a_prompt_from_claudes_usage_limit_resume_is_not_typed(self):
        machine = tuple(self.config['machine'])
        for prompt in ('Your claude.ai usage limit has reset. Continue the task you were working on.',
                       'Your claude.ai usage is available again. Continue the task.'):
            self.assertTrue(prompt.startswith(machine), prompt)

    def test_the_stop_instruction_names_the_three_answers(self):
        system = '\n'.join(self.config['model']['stop'])
        for word in ('ASK:', 'WAIT:', 'DONE:'):
            self.assertIn(word, system)

    def test_every_skill_and_command_leads_to_a_type(self):
        for table in ('skills', 'outside', 'commands'):
            self.assertEqual(sorted(set(self.config[table].values()) - set(self.config['types'])), [], table)

    def test_skills_are_this_repos_and_outside_holds_the_rest(self):
        ours = set(load('install/skills.py').repo_skills(ROOT))  # bundles (skills/git/) flattened
        self.assertEqual(sorted(set(self.config['skills']) - ours), [], 'named under skills, not in skills/')
        self.assertEqual(sorted(set(self.config['outside']) & ours), [], 'a skill of this repo under outside')


if __name__ == '__main__':
    unittest.main()
