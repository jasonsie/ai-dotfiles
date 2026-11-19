"""herdr-title: an agent's row in Herdr says what its current prompt is for.

The script runs as the CLIs run it, with a `herdr` and a `claude` on PATH that only write down
how they were called.

Run: python3 -m unittest discover -s scripts/tests -p 'test_herdr_title.py' -v
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from support import ROOT, load

SCRIPT = ROOT / 'skills/herdr-title/scripts/herdr_title.py'
FAKE = f'''#!{sys.executable}
import json, os, sys, time
name = os.path.basename(sys.argv[0])
if name == 'claude':
    time.sleep(float(os.environ.get('FAKE_CLAUDE_SLEEP', 0)))
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps({{'tool': name, 'argv': sys.argv[1:], 'cwd': os.getcwd(),
                          'herdr_env': sorted(key for key in os.environ if key.startswith('HERDR_'))}}) + '\\n')
if name == 'claude':
    sys.stdout.write(os.environ.get('FAKE_CLAUDE_SAYS', ''))
    sys.exit(int(os.environ.get('FAKE_CLAUDE_EXIT', 0)))
'''
GRILLING = {'working': '[GRILLING]', 'idle': '[GRILLED]', 'done': '[GRILLED]', 'blocked': '[BLOCKED]'}


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
                    'HERDR_TITLE_STATE': str(self.home / 'state'),
                    'HERDR_ENV': '1', 'HERDR_PANE_ID': 'w1:p1', 'HERDR_SOCKET_PATH': '/tmp/herdr.sock'}

    def run_script(self, *args, data=None, **env):
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=json.dumps(data or {}), text=True,
                              capture_output=True, env={**self.env, **env}, timeout=30)

    def hook(self, kind, cli='claude', session='s1', env=None, **fields):
        return self.run_script('hook', kind, '--cli', cli, data={'session_id': session, 'cwd': '/w', **fields},
                               **(env or {}))

    def calls(self, tool, wait=0):
        """The calls `tool` got so far; with `wait`, as soon as there are that many (5 s at most)."""
        deadline = time.time() + 5
        while True:
            lines = self.log.read_text().splitlines() if self.log.exists() else []
            found = [call for call in map(json.loads, lines) if call['tool'] == tool]
            if len(found) >= wait or time.time() > deadline:
                return found
            time.sleep(0.05)

    @staticmethod
    def labels(call):
        argv = call['argv']
        return dict(argv[i + 1].split('=', 1) for i, arg in enumerate(argv) if arg == '--state-label')


class CertainTest(Sandbox):
    def test_a_skill_named_in_the_prompt_tags_the_pane_at_once(self):
        done = self.hook('prompt', prompt='Show the status in the title. /grilling to align ahead of execution')
        self.assertEqual((done.returncode, done.stdout), (0, ''))
        (call,) = self.calls('herdr')
        self.assertEqual(call['argv'][:5], ['pane', 'report-metadata', 'w1:p1', '--source', 'user:ai-dotfiles-title'])
        self.assertEqual(self.labels(call), GRILLING)
        self.assertEqual(self.calls('claude'), [])

    def test_approve_alone_or_with_a_pr_number_is_a_command(self):
        for session, prompt in enumerate(('approve', 'Approve 57', 'approve #57.', ' ship it ')):
            self.hook('prompt', session=f's{session}', prompt=prompt)
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')], ['[LANDING]'] * 4)

    def test_a_sentence_that_only_contains_a_command_word_is_not_one(self):
        self.hook('prompt', prompt='all approve and do them all for me')
        self.assertEqual(self.calls('herdr'), [])

    def test_a_plugins_skill_and_a_dollar_skill_count_and_the_first_one_wins(self):
        prompts = ('take /zkfy:zk-note on each page', '$tutor based on this session',
                   '/web-clipper:web-clipper, https://example.com/llm', '"/grill-me" first, then /plan.')
        for session, prompt in enumerate(prompts):
            self.hook('prompt', cli='codex', session=f's{session}', prompt=prompt)
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')],
                         ['[NOTING]', '[EXPLAINING]', '[NOTING]', '[GRILLING]'])

    def test_a_path_or_an_unknown_name_is_not_a_skill(self):
        for session, prompt in enumerate(('read /Users/me/research/x.md and docs/grilling.md',
                                          'see https://example.com/plan and ~/onboard/notes',
                                          '/model then /clear', 'costs $5 and $HOME/tdd.txt')):
            self.hook('prompt', session=f's{session}', prompt=prompt)
        self.assertEqual(self.calls('herdr'), [])

    def test_a_prompt_the_user_did_not_type_keeps_the_tag(self):
        for prompt in ('Another Claude session sent a message:\n<agent-message from="a1">/grilling done</agent-message>',
                       '[SYSTEM NOTIFICATION - NOT USER INPUT]\n<task-notification>approve</task-notification>',
                       '<teammate-message teammate_id="discover">/research finished</teammate-message>', '   '):
            self.hook('prompt', prompt=prompt)
        self.assertEqual(self.calls('herdr'), [])


class EndTest(Sandbox):
    def test_session_end_takes_the_tag_off_and_forgets_the_session(self):
        self.hook('prompt', prompt='/grilling')
        kept = self.home / 'state' / 's1.json'
        self.assertEqual(json.loads(kept.read_text())['tag'], 'GRILL')
        done = self.hook('end')
        self.assertEqual((done.returncode, done.stdout), (0, ''))
        tagged, cleared = (call['argv'] for call in self.calls('herdr'))
        self.assertEqual(cleared[:6], ['pane', 'report-metadata', 'w1:p1', '--source', 'user:ai-dotfiles-title',
                                       '--clear-state-labels'])
        # Herdr drops a report whose --seq is not above the source's last one.
        self.assertGreater(int(cleared[cleared.index('--seq') + 1]), int(tagged[tagged.index('--seq') + 1]))
        self.assertFalse(kept.exists())


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
        tagged = self.calls('herdr', wait=2)
        self.assertEqual(self.labels(tagged[1]), {'working': '[EXECUTING]', 'idle': '[EXECUTED]',
                                                  'done': '[EXECUTED]', 'blocked': '[BLOCKED]'})
        (asked,) = self.calls('claude')
        flag, question, *options = asked['argv']
        self.assertEqual(flag, '-p')
        self.assertIn('Current label: GRILL', question)
        self.assertIn('Confirm and I will build it.', question)
        self.assertTrue(question.endswith('\ny'), question)
        for name, value in (('--model', 'haiku'), ('--tools', ''), ('--setting-sources', 'project')):
            self.assertEqual(options[options.index(name) + 1], value, name)
        self.assertIn('--no-session-persistence', options)
        self.assertIn('--strict-mcp-config', options)
        system = options[options.index('--system-prompt') + 1]
        self.assertIn('EXECUTE: make the change, build it, do the task', system)
        self.assertIn('KEEP', system)
        # The model's CLI must not know the pane: its own hooks would report to it.
        self.assertEqual(asked['herdr_env'], [])
        self.assertTrue(asked['cwd'].startswith(os.path.realpath(self.home / 'state')), asked['cwd'])
        self.assertEqual(json.loads((self.home / 'state' / 's1.json').read_text())['tag'], 'EXECUTE')

    def test_the_hook_returns_before_the_model_answers(self):
        started = time.time()
        self.hook('prompt', prompt='how does this work', env={'FAKE_CLAUDE_SAYS': 'EXPLAIN', 'FAKE_CLAUDE_SLEEP': '1.5'})
        self.assertLess(time.time() - started, 1.0)
        self.assertEqual(self.calls('herdr'), [])
        (call,) = self.calls('herdr', wait=1)
        self.assertEqual(self.labels(call)['working'], '[EXPLAINING]')

    def classify(self, says='EXECUTE', code=0, **request):
        """The model's turn by itself, as the hook starts it, with the model saying `says`."""
        asked = {'cli': 'claude', 'session': 's1', 'pane': 'w1:p1', 'prompt': 'y', 'transcript': '', 'seq': 5, **request}
        return self.run_script('classify', data=asked, FAKE_CLAUDE_SAYS=says, FAKE_CLAUDE_EXIT=str(code))

    def test_keep_a_word_that_is_no_tag_or_a_failed_call_leaves_the_tag(self):
        for says, code in (('KEEP', 0), ('banana', 0), ('', 0), ('EXECUTE', 1)):
            done = self.classify(says, code)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, '', ''), says)
        self.assertEqual(len(self.calls('claude')), 4)
        (self.bin / 'claude').unlink()  # no claude on this machine
        self.assertEqual(self.classify().returncode, 0)
        self.assertEqual(self.calls('herdr'), [])

    def test_an_answer_that_comes_after_a_newer_tag_is_dropped(self):
        self.hook('prompt', prompt='/grilling')  # tagged now; the answer below is for a prompt before it
        self.classify('EXECUTE', seq=5)
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')], ['[GRILLING]'])
        self.assertEqual(json.loads((self.home / 'state' / 's1.json').read_text())['tag'], 'GRILL')

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
            self.classify(says, session=f's{session}')
        self.assertEqual([self.labels(call)['working'] for call in self.calls('herdr')],
                         ['[EXECUTING]', '[DEBUGGING]', '[REVIEWING]'])


class QuietTest(Sandbox):
    def test_outside_herdr_nothing_runs_and_nothing_is_kept(self):
        for missing in ('HERDR_ENV', 'HERDR_PANE_ID'):
            env = {key: value for key, value in self.env.items() if key != missing}
            done = subprocess.run([sys.executable, str(SCRIPT), 'hook', 'prompt', '--cli', 'claude'], text=True,
                                  input=json.dumps({'session_id': 's1', 'prompt': '/grilling'}),
                                  capture_output=True, env=env, timeout=30)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, '', ''), missing)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.home / 'state').exists())

    def test_input_it_cannot_read_is_met_with_silence(self):
        for args, text in ((('hook', 'prompt', '--cli', 'claude'), 'not json'),
                           (('hook', 'prompt', '--cli', 'agy'), '{}'), (('hook', 'nonsense'), '{}')):
            done = subprocess.run([sys.executable, str(SCRIPT), *args], input=text, text=True,
                                  capture_output=True, env=self.env, timeout=30)
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, '', ''), args)
        self.assertEqual(self.calls('herdr'), [])


class ConfigTest(unittest.TestCase):
    """config/herdr-title.json: the tags, and what decides one at once."""

    def setUp(self):
        self.config = json.loads((ROOT / 'config/herdr-title.json').read_text())

    def test_every_tag_has_a_form_for_working_and_one_for_done_that_fit_the_sidebar(self):
        self.assertEqual(len(self.config['tags']), 10)
        for tag, forms in self.config['tags'].items():
            self.assertTrue(forms['working'].endswith('ING') and forms['done'].endswith('ED'), tag)
            self.assertTrue(forms['working'].startswith(tag[:3]) and forms['done'].startswith(tag[:3]), tag)
            self.assertLessEqual(max(len(forms['working']), len(forms['done'])), 11, tag)  # 26 columns in all
            self.assertTrue(forms['means'].strip(), tag)

    def test_every_skill_and_command_leads_to_a_tag(self):
        for table in ('skills', 'outside', 'commands'):
            self.assertEqual(sorted(set(self.config[table].values()) - set(self.config['tags'])), [], table)

    def test_skills_are_this_repos_and_outside_holds_the_rest(self):
        ours = set(load('install/skills.py').skills(ROOT / 'skills'))  # bundles (skills/git/) flattened
        self.assertEqual(sorted(set(self.config['skills']) - ours), [], 'named under skills, not in skills/')
        self.assertEqual(sorted(set(self.config['outside']) & ours), [], 'a skill of this repo under outside')


if __name__ == '__main__':
    unittest.main()
