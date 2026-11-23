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
import unittest.mock

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

    def test_a_prompt_event_carries_the_text_and_the_transcript(self):
        for cli in ('claude', 'codex', 'pi'):
            event = agent_hooks.read(cli, 'prompt', raw(cli, prompt='approve 57', transcript_path='/t/s.jsonl'))
            self.assertEqual((event.kind, event.session, event.prompt, event.transcript),
                             ('prompt', 's1', 'approve 57', '/t/s.jsonl'), cli)
        bare = agent_hooks.read('codex', 'prompt', raw('codex', prompt=7, transcript_path=None))
        self.assertEqual((bare.prompt, bare.transcript), ('', ''))

    def test_a_stop_event_carries_the_last_message_and_the_work_still_in_flight(self):
        event = agent_hooks.read('claude', 'stop', raw('claude', last_assistant_message='Shall I?',
                                                       background_tasks=[{'type': 'subagent'}, {'type': 'shell'}, 'x'],
                                                       session_crons=[{'id': 'c1', 'prompt': 'check the build'}, 'x']))
        self.assertEqual((event.last_message, event.tasks, event.crons),
                         ('Shall I?', ('subagent', 'shell'), ('check the build',)))
        bare = agent_hooks.read('codex', 'stop', raw('codex', last_assistant_message=None, background_tasks={}))
        self.assertEqual((bare.last_message, bare.tasks, bare.crons), ('', (), ()))
        pi = agent_hooks.read('pi', 'stop', raw('pi', last_assistant_message='Done.', outcome='aborted'))
        self.assertEqual((pi.last_message, pi.outcome), ('Done.', 'aborted'))

    def test_the_other_kinds_carry_their_one_fact(self):
        self.assertEqual(agent_hooks.read('claude', 'error', raw('claude', error='rate_limit')).error, 'rate_limit')
        self.assertEqual(agent_hooks.read('claude', 'start', raw('claude', source='resume')).source, 'resume')
        self.assertEqual(agent_hooks.read('pi', 'end', raw('pi', reason='reload')).reason, 'reload')
        self.assertEqual(agent_hooks.read('pi', 'prompt', raw('pi', prompt='go', source='extension')).source, 'extension')
        self.assertEqual(agent_hooks.read('claude', 'permission', raw('claude', tool='AskUserQuestion')).action, 'ask')

    def test_a_hook_fired_inside_a_subagent_or_teammate_says_so(self):
        self.assertTrue(agent_hooks.read('claude', 'prompt', raw('claude', agent_id='agent-abc', agent_type='Explore')).subagent)
        self.assertFalse(agent_hooks.read('claude', 'prompt', raw('claude', agent_type='reviewer')).subagent)  # --agent
        self.assertFalse(agent_hooks.read('claude', 'pre', raw('claude', tool='Edit', agent_id='')).subagent)

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

    def test_a_prompt_hook_prints_nothing_where_stdout_would_reach_the_model(self):
        for cli in ('claude', 'codex', 'pi'):
            self.assertIsNone(agent_hooks.render(cli, 'prompt', None), cli)

    def test_the_kinds_never_answered_print_nothing(self):
        # SessionStart's stdout becomes context, and a PermissionRequest reply would decide the dialog.
        for cli in ('claude', 'codex', 'pi'):
            for kind in ('error', 'permission', 'form', 'start', 'interrupt'):
                self.assertIsNone(agent_hooks.render(cli, kind, None), (cli, kind))


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

    def test_a_shown_reply_adds_what_the_person_sees_to_the_reply_it_wraps(self):
        Deny, Note, Rewrite, Shown = agent_hooks.Deny, agent_hooks.Note, agent_hooks.Rewrite, agent_hooks.Shown
        for cli in ('claude', 'codex'):  # a top-level systemMessage, and nothing Codex's PreToolUse rejects
            alone = agent_hooks.render(cli, 'pre', Shown(None, 'made fix/x'))
            self.assertEqual(alone, {'systemMessage': 'made fix/x'})
            both = agent_hooks.render(cli, 'pre', Shown(Deny('busy'), 'made fix/x'))
            self.assertEqual(both['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertEqual(both['systemMessage'], 'made fix/x')
            self.assertEqual(set(both), {'hookSpecificOutput', 'systemMessage'})
        self.assertEqual(agent_hooks.render('pi', 'pre', Shown(None, 'made', 'fix/x')), {'status': 'fix/x'})
        self.assertEqual(agent_hooks.render('pi', 'pre', Shown(Note('n'), 'gone', None)), {'note': 'n', 'status': None})
        self.assertEqual(agent_hooks.render('pi', 'pre', Shown(Rewrite({'path': '/l'}), '', 'fix/x')),
                         {'input': {'path': '/l'}, 'status': 'fix/x'})
        self.assertEqual(agent_hooks.render('agy', 'pre', Shown(None, 'made')), {'decision': 'allow'})
        self.assertEqual(agent_hooks.render('agy', 'pre', Shown(Deny('busy'), 'made')),
                         {'decision': 'deny', 'reason': 'busy'})
        self.assertIsNone(agent_hooks.render('codex', 'end', Shown(None, 'ignored')))

    def test_a_deny_carries_its_note_in_each_cli_shape(self):
        deny = agent_hooks.Deny('blocked', 'earlier note')
        for cli in ('claude', 'codex'):
            out = agent_hooks.render(cli, 'pre', deny)['hookSpecificOutput']
            self.assertEqual((out['permissionDecision'], out['permissionDecisionReason'], out['additionalContext']),
                             ('deny', 'blocked', 'earlier note'))
        self.assertEqual(agent_hooks.render('agy', 'pre', deny), {'decision': 'deny', 'reason': 'blocked\nearlier note'})
        self.assertEqual(agent_hooks.render('pi', 'pre', deny), {'block': True, 'reason': 'blocked\nearlier note'})
        self.assertNotIn('additionalContext', agent_hooks.render('claude', 'pre', agent_hooks.Deny('x'))['hookSpecificOutput'])

    def test_a_worktree_is_answered_with_its_path_as_text(self):
        self.assertEqual(agent_hooks.render('claude', 'create', Path('/w/.claude/worktrees/x')), '/w/.claude/worktrees/x')
        self.assertIsNone(agent_hooks.render('claude', 'create', None))
        self.assertIsNone(agent_hooks.render('claude', 'remove', None))

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

    def test_handle_keeps_the_state_and_skips_an_event_without_a_session(self):
        event = agent_hooks.read('claude', 'stop', raw('claude'))
        self.assertEqual(agent_hooks.handle(event, self.nudge_once, self.store, 1000.0), Continue('go on'))
        self.assertIsNone(agent_hooks.handle(event, self.nudge_once, self.store, 1000.0))
        self.assertEqual(self.store.load('s1'), {'nudged': True})
        self.assertIsNone(agent_hooks.handle(agent_hooks.read('claude', 'stop', {}), self.nudge_once, self.store))
        self.assertEqual(len(self.seen), 2)

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


class KindsTest(unittest.TestCase):
    def test_every_kind_a_cli_hands_over_has_a_native_name_and_a_time_within_its_cap(self):
        self.assertEqual(set(agent_hooks.KINDS), set(agent_hooks.CLIS))
        caps = {('codex', 'end'): 3, ('codex', 'interrupt'): 3, ('claude', 'end'): 60}  # the CLIs' own limits
        for cli, kinds in agent_hooks.KINDS.items():
            for kind in kinds:
                self.assertIn(kind, agent_hooks.NATIVE, (cli, kind))
                self.assertGreater(agent_hooks.timeout(cli, kind), 0, (cli, kind))
                self.assertLessEqual(agent_hooks.timeout(cli, kind), caps.get((cli, kind), 600), (cli, kind))
        for cli, times in agent_hooks.TIMEOUTS.items():
            self.assertLessEqual(set(times), set(agent_hooks.KINDS[cli]), cli)
        self.assertLessEqual(set(agent_hooks.TOOL_KINDS) | set(agent_hooks.RAW), set(agent_hooks.NATIVE))

    def test_a_cloud_session_is_claude_codes_remote_flag(self):
        with unittest.mock.patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': 'true'}):
            self.assertTrue(agent_hooks.in_cloud())
        with unittest.mock.patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': ''}):
            self.assertFalse(agent_hooks.in_cloud())


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

    def test_the_prompt_event_is_left_out_where_the_cli_has_none(self):
        wants = (('prompt', None), ('end', None))
        for cli in ('claude', 'codex'):
            self.assertEqual(agent_hooks.native_events(cli, wants),
                             (('UserPromptSubmit', 'prompt', None), ('SessionEnd', 'end', None)), cli)
        self.assertEqual(agent_hooks.native_events('agy', wants), ())

    def test_kinds_a_cli_lacks_are_left_out(self):
        wants = (('error', None), ('permission', None), ('form', None), ('start', None), ('interrupt', None))
        self.assertEqual([event for event, _, _ in agent_hooks.native_events('claude', wants)],
                         ['StopFailure', 'PermissionRequest', 'Elicitation', 'SessionStart'])
        self.assertEqual([event for event, _, _ in agent_hooks.native_events('codex', wants)],
                         ['PermissionRequest', 'Interrupt'])
        self.assertEqual(agent_hooks.native_events('agy', wants), ())

    def test_dialog_tools_are_matched_by_name_and_never_widen_to_every_tool(self):
        wants = (('pre', ('ask',)),)
        self.assertEqual(agent_hooks.native_events('claude', wants),
                         (('PreToolUse', 'pre', 'AskUserQuestion|ExitPlanMode'),))
        for cli in ('codex', 'agy'):  # no such tools: no entry at all, not a PreToolUse for every tool
            self.assertEqual(agent_hooks.native_events(cli, wants), (), cli)

    def test_worktree_events_exist_for_claude_only_and_take_no_matcher(self):
        wants = (('create', None), ('remove', None))
        self.assertEqual(agent_hooks.native_events('claude', wants),
                         (('WorktreeCreate', 'create', None), ('WorktreeRemove', 'remove', None)))
        for cli in ('codex', 'agy', 'pi'):
            self.assertEqual(agent_hooks.native_events(cli, wants), (), cli)


if __name__ == '__main__':
    unittest.main()
