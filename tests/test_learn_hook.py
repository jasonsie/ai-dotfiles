import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/learn/hooks/learn_hook.py'
spec = importlib.util.spec_from_file_location('learn_hook', SCRIPT)
learn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(learn)

PHRASES = learn.load_keywords()


class LearnHookTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='learn 空間 ')
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        (self.repo / '.git').mkdir(parents=True)
        (self.repo / 'docs/plans').mkdir(parents=True)
        (self.repo / 'src').mkdir()
        self.state = self.root / 'state'

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, name, status):
        (self.repo / 'docs/plans' / name).write_text(f'# {name}\n\n{status}\n\n## Goal\n')

    def payload(self, cli, **extra):
        if cli == 'agy':
            return {'conversationId': 'c1', 'workspacePaths': [str(self.repo / 'src')], **extra}
        return {'session_id': 's1', 'cwd': str(self.repo / 'src'), **extra}

    def call(self, mode, cli, **extra):
        return learn.run(mode, cli, self.payload(cli, **extra), self.state, PHRASES)

    def test_keywords_match_phrases_not_parts_of_words(self):
        self.assertEqual(learn.find_cue('OK, Remember this for later', PHRASES), 'remember this')
        self.assertEqual(learn.find_cue('you’re right, I told you', PHRASES), 'i told you')
        self.assertEqual(learn.find_cue('這個要記住', PHRASES), '記住')
        self.assertEqual(learn.find_cue('又错了吧', PHRASES), '又错了')
        self.assertIsNone(learn.find_cue('remember thistle seeds', PHRASES))
        self.assertIsNone(learn.find_cue('please refactor the parser', PHRASES))
        pasted = '<pasted_content id="x">\nremember this\n</pasted_content id="x">\nsummarize the log'
        self.assertIsNone(learn.find_cue(pasted, PHRASES))

    def test_status_lines_are_read_loosely(self):
        self.plan('a.md', 'Status: active')
        self.plan('b.md', 'Status: **done** (2026-10-18). The redesign is implemented.')
        self.plan('c.md', 'status: Done.')
        (self.repo / 'docs/plans/d.md').write_text('# no status\n')
        self.assertEqual(learn.plan_statuses(self.repo), {'a.md': 'active', 'b.md': 'done', 'c.md': 'done', 'd.md': ''})

    def test_prompt_context_per_cli(self):
        claude = self.call('prompt', 'claude', prompt='you forgot the tests')
        self.assertEqual(claude['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')
        self.assertIn('"you forgot"', claude['hookSpecificOutput']['additionalContext'])
        self.assertIn('additionalContext', self.call('prompt', 'codex', prompt='not what I asked')['hookSpecificOutput'])
        self.assertIn('context', self.call('prompt', 'pi', prompt='記住這個'))
        self.assertIsNone(self.call('prompt', 'claude', prompt='add a test'))

    def test_plan_done_asks_once_with_the_right_shape(self):
        self.plan('a.md', 'Status: active')
        self.plan('old.md', 'Status: done')
        self.call('prompt', 'claude', prompt='finish plan a')
        self.assertIsNone(self.call('stop', 'claude'))
        self.plan('a.md', 'Status: done')
        reply = self.call('stop', 'claude')
        self.assertEqual(reply['hookSpecificOutput']['hookEventName'], 'Stop')
        self.assertIn('docs/plans/a.md', reply['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('old.md', reply['hookSpecificOutput']['additionalContext'])
        self.assertIsNone(self.call('stop', 'claude', stop_hook_active=True))
        self.assertIsNone(self.call('stop', 'claude'))

    def test_new_plan_finished_in_session_counts(self):
        self.call('prompt', 'codex', prompt='start')
        self.plan('new.md', 'Status: done')
        reply = self.call('stop', 'codex')
        self.assertEqual(reply['decision'], 'block')
        self.assertIn('docs/plans/new.md', reply['reason'])

    def test_codex_and_agy_get_an_explicit_no_op(self):
        self.call('prompt', 'codex', prompt='start')
        self.assertEqual(self.call('stop', 'codex'), {})
        self.assertEqual(self.call('stop', 'agy'), {'decision': 'stop'})
        self.assertIsNone(self.call('stop', 'claude'))

    def test_own_marker_guards_agy_and_pi(self):
        for cli in ('agy', 'pi'):
            self.plan('a.md', 'Status: active')
            self.call('prompt', cli, prompt='go')
            self.plan('a.md', 'Status: done')
            reply = self.call('stop', cli)
            self.assertIn('docs/plans/a.md', reply['reason'] if cli == 'agy' else reply['continue'])
            self.plan('b.md', 'Status: done')  # finished during the continuation itself
            self.assertEqual(self.call('stop', cli), learn.quiet(cli, 'stop'))
            (self.repo / 'docs/plans/b.md').unlink()

    def test_cap_of_three_asks_per_session(self):
        for i in range(4):
            self.plan(f'p{i}.md', 'Status: active')
        self.call('prompt', 'claude', prompt='go')
        replies = []
        for i in range(4):
            self.plan(f'p{i}.md', 'Status: done')
            replies.append(self.call('stop', 'claude'))
        self.assertEqual([r is not None for r in replies], [True, True, True, False])

    def test_continue_text_holds_no_keyword(self):
        for note in (learn.STOP_NOTE.format(plans='docs/plans/x.md'), learn.PROMPT_NOTE.format(cue='')):
            self.assertIsNone(learn.find_cue(note, PHRASES), note)

    def test_agy_reads_the_transcript_once_per_turn(self):
        transcript = self.root / 'transcript.jsonl'
        steps = [
            {'step_index': 0, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT',
             'content': '<USER_REQUEST>\nremember this rule\n</USER_REQUEST>\n<ADDITIONAL_METADATA>x</ADDITIONAL_METADATA>'},
            {'step_index': 1, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'content': 'remember this'},
        ]
        transcript.write_text('\n'.join(json.dumps(s) for s in steps) + '\nnot json\n')
        first = self.call('prompt', 'agy', transcriptPath=str(transcript))
        self.assertIn('remember this', first['injectSteps'][0]['ephemeralMessage'])
        self.assertIsNone(self.call('prompt', 'agy', transcriptPath=str(transcript)))

    def test_old_state_is_pruned(self):
        self.call('prompt', 'claude', prompt='go')
        old = self.state / 'claude-old.json'
        old.write_text('{}')
        os.utime(old, (0, 0))
        self.call('prompt', 'claude', prompt='go')
        self.assertFalse(old.exists())
        self.assertTrue((self.state / 'claude-s1.json').exists())

    def test_broken_input_exits_zero_quietly(self):
        cases = ((['prompt', '--cli', 'claude'], ''), (['stop', '--cli', 'codex'], '{}'), (['stop', '--cli', 'nope'], ''))
        for args, expected in cases:
            run = subprocess.run([sys.executable, str(SCRIPT), *args], input='not json',
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0)
            self.assertEqual(run.stdout.strip(), expected)


if __name__ == '__main__':
    unittest.main()
