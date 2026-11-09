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

    def test_claudes_worktree_inputs_carry_the_name_and_the_path(self):
        made = agent_hooks.read('claude', 'create', {'session_id': 's1', 'cwd': '/w', 'name': 'bold-oak'})
        self.assertEqual((made.kind, made.session, made.folder, made.name, made.path), ('create', 's1', '/w', 'bold-oak', ''))
        gone = agent_hooks.read('claude', 'remove', {'session_id': 's1', 'cwd': '/w', 'worktree_path': '/w/x'})
        self.assertEqual((gone.name, gone.path), ('', '/w/x'))
        self.assertEqual(agent_hooks.read('claude', 'create', {'name': 7}).name, '')

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


class PreReplyTest(unittest.TestCase):
    def test_deny_note_and_rewrite_in_each_cli_shape(self):
        Deny, Note, Rewrite = agent_hooks.Deny, agent_hooks.Note, agent_hooks.Rewrite
        for cli in ('claude', 'codex'):
            self.assertEqual(agent_hooks.render(cli, 'pre', Deny('busy'))['hookSpecificOutput'],
                             {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                              'permissionDecisionReason': 'busy'})
            self.assertEqual(agent_hooks.render(cli, 'pre', Note('n'))['hookSpecificOutput'],
                             {'hookEventName': 'PreToolUse', 'additionalContext': 'n'})
            self.assertEqual(agent_hooks.render(cli, 'pre', Rewrite({'command': 'x'}, 'moved'))['hookSpecificOutput'],
                             {'hookEventName': 'PreToolUse', 'permissionDecision': 'allow',
                              'updatedInput': {'command': 'x'}, 'additionalContext': 'moved'})
            self.assertIsNone(agent_hooks.render(cli, 'pre', None))
        self.assertEqual(agent_hooks.render('agy', 'pre', None), {'decision': 'allow'})
        self.assertEqual(agent_hooks.render('agy', 'pre', Deny('busy')), {'decision': 'deny', 'reason': 'busy'})
        self.assertEqual(agent_hooks.render('agy', 'pre', Rewrite({'Cwd': '/l'}, 'moved')),
                         {'decision': 'allow', 'overwrite': {'Cwd': '/l'}, 'reason': 'moved'})
        self.assertEqual(agent_hooks.render('pi', 'pre', Deny('busy')), {'block': True, 'reason': 'busy'})
        self.assertEqual(agent_hooks.render('pi', 'pre', Rewrite({'path': '/l/a'})), {'input': {'path': '/l/a'}})
        self.assertEqual(agent_hooks.render('pi', 'pre', Note('n')), {'note': 'n'})
        self.assertIsNone(agent_hooks.render('codex', 'end', Note('ignored')))

    def test_a_pre_event_carries_the_action_input_and_pid(self):
        event = agent_hooks.read('claude', 'pre', {'session_id': 's', 'tool_name': 'Bash',
                                                    'tool_input': {'command': 'ls'}})
        self.assertEqual((event.action, event.tool_input, event.pid), ('shell', {'command': 'ls'}, None))
        event = agent_hooks.read('agy', 'pre', {'conversationId': 'a', 'toolCall': {'name': 'view_file',
                                                'args': {'AbsolutePath': '/w/x'}}})
        self.assertEqual((event.action, event.tool_input), ('read', {'AbsolutePath': '/w/x'}))
        self.assertEqual(agent_hooks.read('pi', 'pre', {'session_id': 'p', 'tool_name': 'write', 'pid': 42}).pid, 42)
        self.assertIsNone(agent_hooks.read('pi', 'pre', {'pid': True}).pid)


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

    def test_on_error_says_what_failed(self):
        def broken(data):
            raise RuntimeError('bug')
        status, out = self.serve('{}', broken, cli='claude', kind='pre')
        self.assertEqual(status, 0)
        self.assertEqual(out, '')
        out = io.StringIO()
        agent_hooks.serve('claude', 'pre', broken, io.StringIO('{}'), out,
                          on_error=lambda error: agent_hooks.Note(f'guard failed: {error}'))
        self.assertIn('guard failed: bug', json.loads(out.getvalue())['hookSpecificOutput']['additionalContext'])

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
        self.assertEqual(set(agent_hooks.MATCHERS), set(agent_hooks.HOOK_FILE_CLIS))
        self.assertEqual(set(agent_hooks.TOOLS), set(agent_hooks.CLIS))
        for cli, matchers in agent_hooks.MATCHERS.items():
            for action, matcher in matchers.items():
                named = agent_hooks.TOOLS[cli][action]
                self.assertTrue(set(matcher.split('|')) <= named | {'Edit', 'Write'}, (cli, action))
        json.dumps(agent_hooks.MATCHERS)

    def test_guard_events_and_a_cli_without_session_end(self):
        wants = (('pre', ('edit', 'shell', 'read')), ('end', None))
        self.assertEqual(agent_hooks.native_events('codex', wants),
                         (('PreToolUse', 'pre', 'Edit|Write|Bash'), ('SessionEnd', 'end', None)))
        self.assertEqual([e for e, _, _ in agent_hooks.native_events('agy', wants)], ['PreToolUse'])

    def test_worktree_events_exist_for_claude_only_and_take_no_matcher(self):
        wants = (('create', None), ('remove', None))
        self.assertEqual(agent_hooks.native_events('claude', wants),
                         (('WorktreeCreate', 'create', None), ('WorktreeRemove', 'remove', None)))
        for cli in ('codex', 'agy', 'pi'):
            self.assertEqual(agent_hooks.native_events(cli, wants), (), cli)


if __name__ == '__main__':
    unittest.main()
