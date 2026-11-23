"""lib/door.py: one hook call serves every feature that wants the event, in order, in one process.

Fixture features in a temporary folder prove the door's own rules: the order, the chaining, a
block ending the chain, joined notes, and a skip on error and on overrun. The three real features'
replies through the door are in their own tests (test_worktree_guard, test_small_commits,
test_herdr_title).

Run: python3 -m unittest discover -s scripts/tests -p 'test_door.py' -v
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from support import ROOT

sys.path.insert(0, str(ROOT / 'lib'))
import door  # noqa: E402
import features  # noqa: E402

HOOK = '''\
"""A fixture feature: does what behavior.json beside it says, and logs what it saw."""
import json
from pathlib import Path
import time

import agent_hooks

HERE = Path(__file__).parent


def hook(event):
    said = json.loads((HERE / 'behavior.json').read_text())
    with open(said['log'], 'a') as log:
        log.write(json.dumps({'name': HERE.name, 'kind': event.kind, 'input': event.tool_input}) + '\\n')
    time.sleep(said.get('sleep', 0))
    if 'raise' in said:
        raise RuntimeError(said['raise'])
    reply = None
    if 'rewrite' in said:
        reply = agent_hooks.Rewrite({**event.tool_input, **said['rewrite']}, said.get('note', ''))
    elif 'deny' in said:
        reply = agent_hooks.Deny(said['deny'])
    elif 'note' in said:
        reply = agent_hooks.Note(said['note'])
    elif 'path' in said:
        reply = said['path']
    if 'shown' in said:
        reply = agent_hooks.Shown(reply, *said['shown'])
    return reply


def failed(error):
    return agent_hooks.Note(f'{HERE.name} failed ({error})')
'''
EVERY_TOOL = {**{cli: {'pre': True, 'end': True, 'stop': True} for cli in ('claude', 'codex', 'pi')},
              'agy': {'pre': True, 'stop': True}}


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='door 空間 ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.log = self.root / 'seen.jsonl'

    def feature(self, name, order, wants=None, budget=None, cloud=False, **behavior):
        folder = self.root / 'features' / name
        folder.mkdir(parents=True)
        wants = wants or EVERY_TOOL
        kinds = {kind for each in wants.values() for kind in each}
        (folder / 'feature.json').write_text(json.dumps({'version': 1, 'cloud': cloud, 'hooks': {
            'module': 'hook.py', 'order': order, 'wants': wants,
            'budget': {kind: (budget or 10) for kind in kinds}}}))
        (folder / 'hook.py').write_text(HOOK)
        (folder / 'behavior.json').write_text(json.dumps({'log': str(self.log), **behavior}))

    def call(self, cli='claude', kind='pre', command='git status', tool='Bash', **data):
        payload = {'session_id': 's1', 'cwd': '/w', 'tool_name': tool, 'tool_input': {'command': command}, **data}
        return door.call(cli, kind, payload, features.find(self.root), stderr=io.StringIO())

    def main(self, *argv, data=None, env=None):
        """(status, stdout, stderr) of the door's command line on this folder's features."""
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env or {}):
            status = door.main(['hook', *argv], root=self.root, stdin=io.StringIO(json.dumps(data or {})),
                               stdout=out, stderr=err)
        return status, out.getvalue(), err.getvalue()

    def seen(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []


class ChainTest(Fixture):
    def test_features_run_in_order_and_each_sees_the_input_as_the_one_before_left_it(self):
        self.feature('a-steers', 2, rewrite={'command': 'cd /x && git status'}, note='a moved it')
        self.feature('z-first', 1, note='z first')
        self.feature('b-last', 3, note='b saw it')
        out, status = self.call()
        self.assertEqual(status, 0)
        self.assertEqual([row['name'] for row in self.seen()], ['z-first', 'a-steers', 'b-last'])  # order, not name
        self.assertEqual([row['input']['command'] for row in self.seen()],
                         ['git status', 'git status', 'cd /x && git status'])
        self.assertEqual(out['hookSpecificOutput'], {
            'hookEventName': 'PreToolUse', 'permissionDecision': 'allow',
            'updatedInput': {'command': 'cd /x && git status'}, 'additionalContext': 'z first\na moved it\nb saw it'})
        pi, _ = self.call('pi', tool='bash')
        self.assertEqual(pi, {'input': {'command': 'cd /x && git status'}, 'note': 'z first\na moved it\nb saw it'})

    def test_the_first_block_ends_the_chain_and_carries_the_notes_said_before_it(self):
        self.feature('a', 1, note='a noted')
        self.feature('b', 2, deny='b says no')
        self.feature('c', 3, note='never asked')
        out, _ = self.call()
        self.assertEqual(out['hookSpecificOutput'], {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                     'permissionDecisionReason': 'b says no',
                                                     'additionalContext': 'a noted'})
        self.assertEqual([row['name'] for row in self.seen()], ['a', 'b'])
        self.assertEqual(self.call('pi', tool='bash')[0], {'block': True, 'reason': 'b says no\na noted'})
        self.assertEqual(self.call('agy')[0], {'decision': 'deny', 'reason': 'b says no\na noted'})

    def test_lines_for_the_person_are_joined_and_the_last_status_stands(self):
        self.feature('a', 1, shown=['made fix/x', 'fix/x'])
        self.feature('b', 2, note='b noted', shown=['also this', None])
        out, _ = self.call('codex')
        self.assertEqual(out['systemMessage'], 'made fix/x\nalso this')
        self.assertEqual(out['hookSpecificOutput']['additionalContext'], 'b noted')
        self.assertEqual(self.call('pi', tool='bash')[0], {'note': 'b noted', 'status': None})

    def test_only_the_features_that_want_the_event_and_the_tool_run(self):
        self.feature('edits', 1, wants={'claude': {'pre': ['edit']}}, note='edits')
        self.feature('every', 2, wants={'claude': {'pre': True}}, note='every')
        self.feature('codex-only', 3, wants={'codex': {'pre': ['shell']}}, note='codex')
        self.feature('ends', 4, wants={'claude': {'end': True}}, note='ends')
        self.call()
        self.assertEqual([row['name'] for row in self.seen()], ['every'])
        self.call(tool='Write')
        self.assertEqual([row['name'] for row in self.seen()][1:], ['edits', 'every'])

    def test_nothing_to_say_is_each_clis_quiet_reply(self):
        self.feature('quiet', 1)
        self.assertEqual(self.call()[0], None)
        self.assertEqual(self.call('codex', 'stop')[0], {})
        self.assertEqual(self.call('agy')[0], {'decision': 'allow'})
        self.assertEqual(self.call('claude', 'end')[0], None)


class SkipTest(Fixture):
    def test_a_feature_that_fails_is_skipped_and_before_a_tool_call_says_so(self):
        self.feature('a', 1, **{'raise': 'boom'})
        self.feature('b', 2, note='b answered')
        out, status = self.call()
        self.assertEqual(status, 0)
        self.assertEqual(out['hookSpecificOutput'], {'hookEventName': 'PreToolUse',
                                                     'additionalContext': 'a failed (boom)\nb answered'})
        self.assertEqual(self.call('codex', 'stop')[0], {})  # after the tool call: skipped, nothing said

    def test_a_feature_past_its_budget_is_skipped_and_the_rest_still_answer(self):
        self.feature('slow', 1, budget=0.3, sleep=5)
        self.feature('b', 2, note='b answered')
        started = time.monotonic()
        out, _ = self.call()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(out['hookSpecificOutput']['additionalContext'],
                         'slow failed (took more than 0.3 s)\nb answered')

    def test_codexs_session_end_and_interrupt_are_answered_within_its_3_s_cap_whatever_the_budgets(self):
        wants = {'codex': {'end': True, 'interrupt': True}}
        self.feature('hangs', 1, wants=wants, budget=60, sleep=60)
        self.feature('after', 2, wants=wants, budget=60)
        for kind in ('end', 'interrupt'):
            started = time.monotonic()
            self.assertEqual(self.call('codex', kind), (None, 0))
            self.assertLess(time.monotonic() - started, 3 - door.MARGIN / 2, kind)
        self.assertEqual([row['name'] for row in self.seen()], ['hangs', 'hangs'])  # no time was left for `after`

    def test_a_feature_that_cannot_load_is_skipped(self):
        self.feature('broken', 1, note='x')
        (self.root / 'features/broken/hook.py').write_text('def hook(event:\n')
        self.feature('b', 2, note='b answered')
        out, _ = self.call()
        self.assertEqual(out['hookSpecificOutput']['additionalContext'], 'b answered')


class CommandTest(Fixture):
    def test_a_cloud_session_runs_only_the_features_that_say_cloud(self):
        self.feature('mac', 1, note='mac only')
        self.feature('both', 2, cloud=True, note='cloud too')
        status, out, _ = self.main('pre', '--cli', 'claude', data={'session_id': 's', 'tool_name': 'Bash'},
                                   env={'CLAUDE_CODE_REMOTE': 'true'})
        self.assertEqual(json.loads(out)['hookSpecificOutput']['additionalContext'], 'cloud too')
        status, out, _ = self.main('pre', '--cli', 'claude', data={'session_id': 's', 'tool_name': 'Bash'},
                                   env={'CLAUDE_CODE_REMOTE': ''})
        self.assertEqual(json.loads(out)['hookSpecificOutput']['additionalContext'], 'mac only\ncloud too')

    def test_a_worktree_is_answered_with_its_path_and_a_failure_with_its_reason(self):
        self.feature('refuses', 1, wants={'claude': {'create': True, 'remove': True}}, **{'raise': 'taken'})
        self.feature('makes', 2, wants={'claude': {'create': True}}, path='/w/.claude/worktrees/x')
        self.assertEqual(self.main('create', '--cli', 'claude', data={'name': 'x'}),
                         (0, '/w/.claude/worktrees/x\n', 'refuses: taken\n'))
        self.assertEqual(self.main('remove', '--cli', 'claude'), (1, '', 'refuses: taken\n'))

    def test_a_bad_call_stays_silent_and_exits_zero(self):
        self.feature('a', 1, note='x')
        for argv in (('bogus', '--cli', 'claude'), ('pre',), ('pre', '--cli', 'gemini')):
            self.assertEqual(self.main(*argv), (0, '', ''), argv)
        out, err = io.StringIO(), io.StringIO()
        status = door.main(['hook', 'stop', '--cli', 'codex'], root=self.root, stdin=io.StringIO('not json'),
                           stdout=out, stderr=err)
        self.assertEqual((status, out.getvalue(), err.getvalue()), (0, '{}\n', ''))

    def test_a_declaration_that_does_not_check_gives_the_quiet_reply_and_says_why(self):
        self.feature('a', 1, note='x')
        (self.root / 'features/a/feature.json').write_text('{"version": 2}')
        status, out, err = self.main('stop', '--cli', 'codex', data={'session_id': 's'})
        self.assertEqual((status, out), (0, '{}\n'))
        self.assertIn('features/a/feature.json', err)


if __name__ == '__main__':
    unittest.main()
