"""agent_hooks: one interface over the four CLIs' hook formats.

Run: python3 -m unittest discover -s scripts/tests -p 'test_agent_hooks.py' -v
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from support import ROOT

sys.path.insert(0, str(ROOT / 'scripts'))
import agent_hooks  # noqa: E402  (imported, not loaded by path: its dataclasses need sys.modules)
Continue = agent_hooks.Continue


def raw(cli, session='s1', tool='', **extra):
    """A hook input in `cli`'s own shape."""
    if cli == 'agy':
        return {'conversationId': session, 'workspacePaths': ['/w'], 'toolCall': {'name': tool}, **extra}
    return {'session_id': session, 'cwd': '/w', 'tool_name': tool, **extra}


class ReadTest(unittest.TestCase):
    def test_each_cli_input_becomes_one_event(self):
        for cli, edit, other in (('claude', 'Edit', 'Read'), ('codex', 'apply_patch', 'Bash'),
                                 ('agy', 'write_to_file', 'view_file'), ('pi', 'edit', 'read')):
            event = agent_hooks.read(cli, 'tool', raw(cli, tool=edit))
            self.assertEqual((event.cli, event.kind, event.session, event.folder, event.tool, event.edit),
                             (cli, 'tool', 's1', '/w', edit, True), cli)
            self.assertFalse(agent_hooks.read(cli, 'tool', raw(cli, tool=other)).edit, cli)

    def test_turn_facts(self):
        self.assertTrue(agent_hooks.read('claude', 'stop', raw('claude', stop_hook_active=True)).continuation)
        self.assertFalse(agent_hooks.read('agy', 'stop', raw('agy', terminationReason='error')).model_stopped)
        self.assertTrue(agent_hooks.read('agy', 'stop', raw('agy')).model_stopped)

    def test_input_that_is_not_an_object_has_no_session(self):
        for data in ([], None, 'x', {'toolCall': []}):
            self.assertIsNone(agent_hooks.read('agy', 'tool', data).session)


class RenderTest(unittest.TestCase):
    def test_continue_in_each_cli_shape(self):
        self.assertEqual(agent_hooks.render('claude', 'stop', Continue('t')),
                         {'hookSpecificOutput': {'hookEventName': 'Stop', 'additionalContext': 't'}})
        self.assertEqual(agent_hooks.render('codex', 'stop', Continue('t')), {'decision': 'block', 'reason': 't'})
        self.assertEqual(agent_hooks.render('agy', 'stop', Continue('t')), {'decision': 'continue', 'reason': 't'})
        self.assertEqual(agent_hooks.render('pi', 'stop', Continue('t')), {'continue': 't'})

    def test_nothing_to_say_in_each_cli_shape(self):
        quiet = {(cli, kind): agent_hooks.render(cli, kind, None) for cli in agent_hooks.CLIS for kind in ('tool', 'stop')}
        self.assertEqual(quiet, {('claude', 'tool'): None, ('claude', 'stop'): None,
                                 ('codex', 'tool'): None, ('codex', 'stop'): {},
                                 ('agy', 'tool'): {}, ('agy', 'stop'): {'decision': 'stop'},
                                 ('pi', 'tool'): None, ('pi', 'stop'): None})


class CallTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='agent hooks 空間 ')
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name) / 'state'
        self.store = agent_hooks.Store('AGENT_HOOKS_TEST_STATE_UNSET', str(self.folder), keep=60)
        self.seen = []

    def nudge_once(self, event, state):
        self.seen.append(event)
        if event.kind == 'stop' and not event.continuation and not state.get('nudged'):
            state['nudged'] = True
            return Continue('go on')
        return None

    def call(self, cli, kind, data, now=1000.0):
        return agent_hooks.call(cli, kind, data, self.nudge_once, self.store, now)

    def test_no_session_is_quiet_and_never_reaches_the_feature(self):
        self.assertEqual(self.call('agy', 'stop', {}), {'decision': 'stop'})
        self.assertEqual(self.seen, [])
        self.assertFalse(self.folder.exists())

    def test_state_is_kept_per_session(self):
        self.assertEqual(self.call('claude', 'stop', raw('claude'))['hookSpecificOutput']['additionalContext'], 'go on')
        self.assertIsNone(self.call('claude', 'stop', raw('claude')))
        self.assertEqual(self.store.load('s1'), {'nudged': True})
        self.assertIsNotNone(self.call('claude', 'stop', raw('claude', session='s2')))

    def test_the_turn_a_continue_started_is_flagged_where_the_cli_does_not(self):
        for cli in ('agy', 'pi'):
            self.call(cli, 'stop', raw(cli, session=cli))
            self.call(cli, 'stop', raw(cli, session=cli))
            self.assertTrue(self.seen[-1].continuation, cli)
        self.call('claude', 'stop', raw('claude', session='c'))
        self.call('claude', 'stop', raw('claude', session='c'))
        self.assertFalse(self.seen[-1].continuation)  # Claude Code flags it itself: stop_hook_active

    def test_old_sessions_are_pruned(self):
        self.call('claude', 'tool', raw('claude', session='old'), now=0.0)
        os.utime(self.store.file('old'), (0, 0))
        self.call('claude', 'tool', raw('claude'), now=1000.0)
        self.assertFalse(self.store.file('old').exists())
        self.assertTrue(self.store.file('s1').exists())

    def test_session_names_cannot_leave_the_folder(self):
        self.assertEqual(self.store.file('../x/y').parent, self.folder)
        self.store.file('bad').parent.mkdir(parents=True)
        self.store.file('bad').write_text('[1]')
        self.assertEqual(self.store.load('bad'), {})


class ServeTest(unittest.TestCase):
    def serve(self, stdin, answer, cli='codex', kind='stop'):
        out = io.StringIO()
        status = agent_hooks.serve(cli, kind, answer, io.StringIO(stdin), out)
        return status, out.getvalue()

    def test_prints_one_json_line(self):
        self.assertEqual(self.serve('{"a": 1}', lambda data: {'got': data['a']}), (0, '{"got": 1}\n'))
        self.assertEqual(self.serve('{}', lambda data: None), (0, ''))

    def test_fails_open_with_the_quiet_reply(self):
        def broken(data):
            raise RuntimeError('bug')
        self.assertEqual(self.serve('{}', broken), (0, '{}\n'))
        self.assertEqual(self.serve('not json', lambda data: {'x': 1}), (0, '{}\n'))
        self.assertEqual(self.serve('{}', broken, cli='claude'), (0, ''))


class InstallTableTest(unittest.TestCase):
    def test_native_events_per_hook_file(self):
        wants = (('tool', 'edit'), ('stop', None))
        self.assertEqual(agent_hooks.native_events('claude', wants),
                         (('PostToolUse', 'tool', 'Edit|Write|NotebookEdit'), ('Stop', 'stop', None)))
        self.assertEqual(agent_hooks.native_events('codex', wants)[0], ('PostToolUse', 'tool', 'Edit|Write'))
        self.assertEqual(agent_hooks.native_events('pi', wants), ())

    def test_every_cli_with_a_matcher_knows_its_edit_tools(self):
        self.assertEqual(set(agent_hooks.EDIT_MATCHERS), set(agent_hooks.HOOK_FILE_CLIS))
        self.assertEqual(set(agent_hooks.EDIT_TOOLS), set(agent_hooks.CLIS))
        json.dumps(agent_hooks.EDIT_MATCHERS)


if __name__ == '__main__':
    unittest.main()
