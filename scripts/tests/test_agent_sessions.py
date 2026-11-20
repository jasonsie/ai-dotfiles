"""agent_sessions: the session stores of Claude Code, Codex and Pi behind one interface.

Run: python3 -m unittest discover -s scripts/tests -p 'test_agent_sessions.py' -v
"""
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from support import ROOT

sys.path.insert(0, str(ROOT / 'scripts'))
import agent_sessions  # noqa: E402  (imported, not loaded by path: its dataclasses need sys.modules)

try:
    NEW_YORK = ZoneInfo('America/New_York')
except ZoneInfoNotFoundError:  # no time zone database on this machine
    NEW_YORK = None

TZ = timezone(timedelta(hours=8))
DAY = date(2026, 11, 2)
START, END = agent_sessions.window(DAY, tz=TZ)  # 04:00 on the 2nd to 04:00 on the 3rd, local
CWD = '/w/proj'


def local(hour, minute=0, days=0):
    """The aware datetime at hour:minute on DAY (+ days), in the tests' zone."""
    return datetime(DAY.year, DAY.month, DAY.day, tzinfo=TZ) + timedelta(days=days, hours=hour, minutes=minute)


def stamp(hour, minute=0, days=0):
    """The same moment as the stores write it: ISO 8601 in UTC, ending in Z."""
    return local(hour, minute, days).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def claude_user(when, text, cwd=CWD, **flags):
    return {'type': 'user', 'timestamp': when, 'cwd': cwd, 'sessionId': 's',
            'message': {'role': 'user', 'content': text}, **flags}


def claude_assistant(when, *texts, edits=(), cwd=CWD, **flags):
    blocks = [{'type': 'text', 'text': text} for text in texts]
    blocks += [{'type': 'tool_use', 'id': 't', 'name': name, 'input': args} for name, args in edits]
    return {'type': 'assistant', 'timestamp': when, 'cwd': cwd, 'message': {'role': 'assistant', 'content': blocks},
            **flags}


def claude_title(title):  # the real ones carry no timestamp
    return {'type': 'ai-title', 'sessionId': 's', 'aiTitle': title}


def codex_meta(sid, cwd=CWD, extra=None):
    return {'timestamp': stamp(1), 'type': 'session_meta', 'payload': {'id': sid, 'cwd': cwd, **(extra or {})}}


def codex_message(when, role, *texts):
    kind = 'output_text' if role == 'assistant' else 'input_text'
    return {'timestamp': when, 'type': 'response_item',
            'payload': {'type': 'message', 'role': role, 'content': [{'type': kind, 'text': text} for text in texts]}}


def codex_call(when, name, text, kind='custom_tool_call'):
    return {'timestamp': when, 'type': 'response_item',
            'payload': {'type': kind, 'name': name, 'input' if kind == 'custom_tool_call' else 'arguments': text}}


def pi_header(sid, cwd=CWD):
    return {'type': 'session', 'version': 3, 'id': sid, 'timestamp': stamp(1), 'cwd': cwd}


def pi_message(when, role, content):
    return {'type': 'message', 'id': 'm', 'parentId': None, 'timestamp': when,
            'message': {'role': role, 'content': content}}


def pi_text(text):
    return {'type': 'text', 'text': text}


def pi_call(name, arguments):
    return {'type': 'toolCall', 'id': 'c', 'name': name, 'arguments': arguments}


PATCH = '\n'.join(['*** Begin Patch', '*** Update File: src/a.py', '@@', '-x', '+y', '*** Add File: /abs/new.py',
                   '+hello', '*** Delete File: old/b.py', '*** Update File: c.py', '*** Move to: moved/c.py',
                   '*** Update File: /w/My Docs/x y.md', '@@', '-1', '+2', '*** End Patch'])
PATCH_FILES = ('/abs/new.py', '/w/My Docs/x y.md', '/w/proj/c.py', '/w/proj/moved/c.py', '/w/proj/old/b.py',
               '/w/proj/src/a.py')
DECOY = '\n'.join(['*** Begin Patch', '*** Add File: /w/proj/doc.md', '+*** Update File: /w/proj/not-edited.py',
                   '+text', '*** End Patch'])


def exec_code(patch):
    """What Codex's exec tool receives when its code applies a patch: the patch inside a string, newlines escaped."""
    return 'const r = await tools.apply_patch("' + patch.replace('\n', '\\n') + '");\ntext(r);'


def use_zone(test, spec):
    """Make `spec` the system zone for `test`: a POSIX TZ string, so no zone database is needed
    ('TST-8' is UTC+8, 'TST+8' is UTC-8)."""
    if not hasattr(time, 'tzset'):
        test.skipTest('no tzset on this platform')
    saved = os.environ.get('TZ')

    def restore():
        if saved is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = saved
        time.tzset()
    test.addCleanup(restore)
    os.environ['TZ'] = spec
    time.tzset()


class StoreTest(unittest.TestCase):
    """A temporary home folder to put the three stores in."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='agent sessions 空間 ')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)

    def put(self, relative, rows, mtime=None):
        """Write `rows` (dicts, or raw lines) as a file in the home, last written at `mtime` (the window's end)."""
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = (row if isinstance(row, str) else json.dumps(row, ensure_ascii=False) for row in rows)
        path.write_text(''.join(line + '\n' for line in lines), encoding='utf-8')
        when = (END if mtime is None else mtime).timestamp()
        os.utime(path, (when, when))
        return path

    def claude(self, name, rows, slug='-w-proj', **kwargs):
        return self.put(f'.claude/projects/{slug}/{name}.jsonl', rows, **kwargs)

    def codex(self, name, rows, folder='2026/11/02', **kwargs):
        return self.put(f'.codex/sessions/{folder}/rollout-2026-11-02T10-00-00-{name}.jsonl', rows, **kwargs)

    def pi(self, name, rows, slug='--w-proj--', **kwargs):
        return self.put(f'.pi/agent/sessions/{slug}/2026-11-02T02-00-00-000Z_{name}.jsonl', rows, **kwargs)

    def read(self, cli, path):
        return agent_sessions.read(cli, path, START, END)

    def sessions(self):
        return agent_sessions.sessions(START, END, self.home)


class WindowTest(unittest.TestCase):
    def test_runs_from_the_cutoff_hour_to_the_same_hour_next_day(self):
        self.assertEqual(agent_sessions.window(DAY, tz=TZ),
                         (datetime(2026, 11, 2, 4, tzinfo=TZ), datetime(2026, 11, 3, 4, tzinfo=TZ)))

    def test_a_custom_cutoff_hour(self):
        self.assertEqual(agent_sessions.window(DAY, 6, TZ),
                         (datetime(2026, 11, 2, 6, tzinfo=TZ), datetime(2026, 11, 3, 6, tzinfo=TZ)))
        self.assertEqual(agent_sessions.window(DAY, cutoff_hour=0, tz=TZ)[0], datetime(2026, 11, 2, tzinfo=TZ))

    def test_the_next_day_starts_where_this_one_ends(self):
        self.assertEqual(agent_sessions.window(DAY, tz=TZ)[1], agent_sessions.window(DAY + timedelta(days=1), tz=TZ)[0])

    def test_the_default_zone_is_aware_and_local(self):
        start, end = agent_sessions.window(DAY)
        self.assertIsNotNone(start.utcoffset())
        self.assertIsNotNone(end.utcoffset())
        self.assertEqual((start.replace(tzinfo=None), end.replace(tzinfo=None)),
                         (datetime(2026, 11, 2, 4), datetime(2026, 11, 3, 4)))
        self.assertEqual(start.utcoffset(), datetime(2026, 11, 2, 4).astimezone().utcoffset())

    @unittest.skipIf(NEW_YORK is None, 'no time zone database')
    def test_a_zone_with_daylight_saving_keeps_the_local_hour(self):
        start, end = agent_sessions.window(date(2026, 10, 31), tz=NEW_YORK)  # clocks go back on 1 November
        self.assertEqual((start.hour, end.hour), (4, 4))
        self.assertEqual(end.astimezone(timezone.utc) - start.astimezone(timezone.utc), timedelta(hours=25))

    def test_the_system_zone_is_the_one_each_morning_had(self):
        use_zone(self, 'EST5EDT,M3.2.0,M11.1.0')  # New York: the clocks go back on the first Sunday of November
        if datetime(2026, 7, 1).astimezone().utcoffset() != timedelta(hours=-4):
            self.skipTest('this platform does not read POSIX zone rules')
        start, end = agent_sessions.window(date(2026, 10, 31))
        self.assertEqual((start.utcoffset(), end.utcoffset()), (timedelta(hours=-4), timedelta(hours=-5)))
        self.assertEqual(end.astimezone(timezone.utc) - start.astimezone(timezone.utc), timedelta(hours=25))

    def test_the_default_zone_follows_the_system_zone(self):
        use_zone(self, 'TST-8')
        self.assertEqual(agent_sessions.window(DAY), (START, END))
        use_zone(self, 'TST+8')
        start, end = agent_sessions.window(DAY)
        self.assertEqual((start, end), (datetime(2026, 11, 2, 4, tzinfo=timezone(timedelta(hours=-8))),
                                        datetime(2026, 11, 3, 4, tzinfo=timezone(timedelta(hours=-8)))))


class IsTempTest(unittest.TestCase):
    def test_scratch_folders(self):
        for cwd in ('/tmp/x', '/private/tmp/claude-501/x/scratchpad', '/var/folders/ab/T/x',
                    '/private/var/folders/ab/cd/T/x', '/tmp', '/tmp/', '/private/tmp', '/var/folders',
                    '/private/var/folders/', '/tmp//x', '/tmp/x/'):
            self.assertTrue(agent_sessions.is_temp(cwd), cwd)

    def test_everything_else(self):
        for cwd in ('/w/proj', '/tmpfiles', '/var/log', '/var/foldersx', '/home/me/tmp/x', '/private', 'tmp/x', '', None):
            self.assertFalse(agent_sessions.is_temp(cwd), cwd)


class ClaudeTest(StoreTest):
    def test_the_prompts_replies_and_edits_of_the_window(self):
        path = self.claude('c1', [
            {'type': 'mode', 'mode': 'default', 'sessionId': 's'},  # no timestamp, no cwd
            claude_user(stamp(3), 'before the window'),
            claude_assistant(stamp(3, 30), 'early reply', edits=[('Edit', {'file_path': '/w/proj/early.py'})]),
            claude_user(stamp(9), 'fix the bug'),
            claude_assistant(stamp(9, 5), 'looking', '', '  ', 'at it', edits=[
                ('Edit', {'file_path': '/w/proj/a.py', 'old_string': 'x', 'new_string': 'y'}),
                ('Edit', {'file_path': '/w/proj/a.py'}),
                ('Write', {'file_path': '/w/proj/sub/../b.py', 'content': 'x'}),
                ('NotebookEdit', {'notebook_path': '/w/proj/n.ipynb'}),
                ('Edit', {'file_path': 'rel/c.py'}),
                ('Bash', {'command': 'rm /w/proj/gone.py'}),
                ('Read', {'file_path': '/w/proj/read.py'})]),
            {'type': 'user', 'timestamp': stamp(9, 6), 'cwd': CWD,
             'message': {'role': 'user', 'content': [{'type': 'tool_result', 'content': 'ok'}]}},
            claude_user(stamp(1, days=1), 'late night'),
            claude_user(stamp(5, days=1), 'after the window'),
            claude_assistant(stamp(5, days=1), 'late reply', edits=[('Edit', {'file_path': '/w/proj/late.py'})]),
        ])
        session = self.read('claude', path)
        self.assertEqual([(turn.role, turn.text) for turn in session.turns],
                         [('user', 'fix the bug'), ('assistant', 'looking\nat it'), ('user', 'late night')])
        self.assertEqual((session.started, session.ended), (local(9), local(1, days=1)))
        self.assertEqual(session.files, ('/w/proj/a.py', '/w/proj/b.py', '/w/proj/n.ipynb', '/w/proj/rel/c.py'))
        self.assertEqual((session.cli, session.id, session.cwd, session.path), ('claude', 'c1', CWD, path))
        self.assertTrue(all(turn.at.utcoffset() is not None for turn in session.turns))

    def test_the_title_is_the_last_ai_title_which_has_no_timestamp(self):
        self.assertNotIn('timestamp', claude_title('x'))  # like the real ones: type, aiTitle, sessionId
        path = self.claude('t1', [claude_title('Early title'), claude_user(stamp(9), 'a prompt'),
                                  claude_title('First title'), claude_assistant(stamp(9, 1), 'ok'),
                                  claude_title('Final title')])
        self.assertEqual(self.read('claude', path).title, 'Final title')

    def test_a_title_does_not_make_a_session_of_a_window_without_turns(self):
        path = self.claude('t7', [claude_user(stamp(9), 'a prompt'), claude_title('Titled')])
        self.assertEqual(self.read('claude', path).title, 'Titled')
        self.assertIsNone(agent_sessions.read('claude', path, START - timedelta(days=2), START - timedelta(days=1)))

    def test_without_an_ai_title_it_is_the_first_prompts_first_line_cut_to_80(self):
        short = self.claude('t2', [claude_user(stamp(9), 'first line\nsecond line'), claude_assistant(stamp(9, 1), 'ok')])
        self.assertEqual(self.read('claude', short).title, 'first line')
        long = self.claude('t3', [claude_user(stamp(9), 'x' * 200 + '\nmore')])
        self.assertEqual(self.read('claude', long).title, 'x' * 80)
        unicode = self.claude('t4', [claude_user(stamp(9), '  修正 the bug  \nmore')])
        self.assertEqual(self.read('claude', unicode).title, '修正 the bug')

    def test_the_title_comes_from_the_whole_transcript(self):
        path = self.claude('t5', [claude_user(stamp(2, days=-1), 'started yesterday'), claude_user(stamp(9), 'continue')])
        session = self.read('claude', path)
        self.assertEqual(session.title, 'started yesterday')
        self.assertEqual([turn.text for turn in session.turns], ['continue'])

    def test_the_title_skips_prompts_that_are_not_the_users(self):
        path = self.claude('t6', [claude_user(stamp(8), '<command-name>/clear</command-name>'),
                                  claude_user(stamp(8, 1), 'caveat', isMeta=True), claude_user(stamp(9), 'the real one')])
        self.assertEqual(self.read('claude', path).title, 'the real one')

    def test_the_cwd_is_the_first_one_any_line_gives_inside_the_window_or_not(self):
        timeless = self.claude('w1', [{'type': 'attachment', 'timestamp': stamp(8)},
                                      {'type': 'worktree-state', 'cwd': '/w/first'},  # no timestamp
                                      claude_user(stamp(3), 'before the window', cwd='/w/second'),
                                      claude_user(stamp(9), 'inside', cwd='/w/third')])
        self.assertEqual(self.read('claude', timeless).cwd, '/w/first')
        early = self.claude('w2', [claude_user(stamp(3), 'before the window', cwd='/w/early'),
                                   claude_user(stamp(9), 'inside', cwd='/w/inside')])
        self.assertEqual(self.read('claude', early).cwd, '/w/early')

    def test_lines_that_only_look_like_turns_are_skipped(self):
        path = self.claude('s1', [
            claude_user(stamp(9), 'real prompt'),
            claude_user(stamp(9, 1), 'caveat', isMeta=True),
            claude_user(stamp(9, 2), 'a subagent prompt', isSidechain=True),
            claude_user(stamp(9, 3), 'This session is being continued from a previous conversation', isCompactSummary=True),
            claude_user(stamp(9, 4), '<command-name>/clear</command-name>'),
            claude_user(stamp(9, 5), '<local-command-caveat>Caveat</local-command-caveat>'),
            claude_assistant(stamp(9, 6), 'a subagent reply', isSidechain=True,
                             edits=[('Edit', {'file_path': '/w/proj/side.py'})]),
            claude_assistant(stamp(9, 7), 'API Error: 529', isApiErrorMessage=True),
            claude_assistant(stamp(9, 8), 'real reply'),
            {'type': 'user', 'timestamp': stamp(9, 9), 'cwd': CWD,
             'message': {'role': 'user', 'content': [{'type': 'text', 'text': '[Request interrupted by user]'}]}},
            {'type': 'system', 'timestamp': stamp(9, 10), 'cwd': CWD, 'content': 'system text'},
            {'type': 'queue-operation', 'timestamp': stamp(9, 11), 'content': 'queued text'},
        ])
        session = self.read('claude', path)
        self.assertEqual([turn.text for turn in session.turns], ['real prompt', 'real reply'])
        self.assertEqual(session.files, ())


class CodexTest(StoreTest):
    def test_the_messages_of_the_window_and_the_meta(self):
        path = self.codex('0194-abc', [
            codex_meta('sid-1'),
            codex_message(stamp(3, 59), 'user', 'too early'),
            codex_message(stamp(8), 'developer', 'system rules'),
            codex_message(stamp(8, 1), 'user', '# AGENTS.md instructions for /w/proj', '<INSTRUCTIONS>x</INSTRUCTIONS>'),
            codex_message(stamp(8, 2), 'user', '<environment_context>cwd</environment_context>'),
            codex_message(stamp(9), 'user', 'add a flag'),
            codex_message(stamp(9, 1), 'assistant', 'adding', '', 'it'),
            codex_message(stamp(9, 2), 'user', '<image>', 'look at this'),
            {'timestamp': stamp(9, 3), 'type': 'event_msg', 'payload': {'type': 'task_complete'}},
            {'timestamp': stamp(9, 4), 'type': 'turn_context', 'payload': {'cwd': '/elsewhere'}},
            {'timestamp': stamp(9, 5), 'type': 'response_item', 'payload': {'type': 'reasoning', 'summary': []}},
            codex_call(stamp(9, 6), 'exec', 'text(await tools.shell("ls"))'),
            codex_message(stamp(5, days=1), 'assistant', 'too late'),
        ])
        session = self.read('codex', path)
        self.assertEqual([(turn.role, turn.text) for turn in session.turns],
                         [('user', 'add a flag'), ('assistant', 'adding\nit'), ('user', 'look at this')])
        self.assertEqual((session.cli, session.id, session.cwd, session.path), ('codex', 'sid-1', CWD, path))
        self.assertEqual((session.title, session.started, session.ended), ('too early', local(9), local(9, 2)))
        self.assertEqual(session.files, ())

    def test_the_id_comes_from_the_file_name_when_there_is_no_meta(self):
        path = self.codex('0194-abc-def', [codex_message(stamp(9), 'user', 'hi')])
        self.assertEqual(self.read('codex', path).id, '0194-abc-def')

    def test_a_forked_thread_is_the_first_meta_not_its_parents(self):
        path = self.codex('fork', [codex_meta('child', cwd='/w/child'), codex_meta('parent', cwd='/w/parent'),
                                   codex_message(stamp(9), 'user', 'go')])
        session = self.read('codex', path)
        self.assertEqual((session.id, session.cwd), ('child', '/w/child'))

    def test_a_subagent_thread_is_not_a_session(self):
        # session_meta.payload on a real machine: thread_source 'subagent' with a source dict that has the key
        # 'subagent' (and forked_from_id), against thread_source 'user' with source 'cli', 'vscode' or 'exec'.
        for n, extra in enumerate(({'thread_source': 'subagent', 'source': {'subagent': {'depth': 1}},
                                    'forked_from_id': 'parent'},
                                   {'thread_source': 'subagent'}, {'source': {'subagent': {}}})):
            path = self.codex(f'sub{n}', [codex_meta(f'sub{n}', extra=extra),
                                          codex_message(stamp(9), 'user', 'task from a parent')])
            self.assertIsNone(self.read('codex', path), extra)
        for n, source in enumerate(('cli', 'vscode', 'exec')):
            extra = {'source': source, 'thread_source': 'user'}
            path = self.codex(f'own{n}', [codex_meta(f'own{n}', extra=extra), codex_message(stamp(9), 'user', 'hello')])
            self.assertIsNotNone(self.read('codex', path), extra)

    def test_apply_patch_paths_are_made_absolute_against_the_cwd(self):
        path = self.codex('p1', [
            codex_meta('p1'), codex_message(stamp(9), 'user', 'patch it'),
            codex_call(stamp(3), 'apply_patch', '*** Begin Patch\n*** Update File: early.py\n*** End Patch'),
            codex_call(stamp(9, 1), 'apply_patch', PATCH),
        ])
        self.assertEqual(self.read('codex', path).files, PATCH_FILES)

    def test_apply_patch_as_a_function_call_carries_the_patch_in_json_arguments(self):
        path = self.codex('p2', [codex_meta('p2'), codex_message(stamp(9), 'user', 'patch it'),
                                 codex_call(stamp(9, 1), 'apply_patch', json.dumps({'input': PATCH}), kind='function_call'),
                                 codex_call(stamp(9, 2), 'apply_patch', 'not json {', kind='function_call')])
        self.assertEqual(self.read('codex', path).files, PATCH_FILES)

    def test_a_patch_applied_by_code_in_exec_has_its_newlines_escaped(self):
        code = exec_code(PATCH)
        self.assertIn('\\n*** Update File: src/a.py', code)
        self.assertNotIn('\n*** Update File', code)
        path = self.codex('p3', [codex_meta('p3'), codex_message(stamp(9), 'user', 'patch it'),
                                 codex_call(stamp(9, 1), 'exec', code)])
        self.assertEqual(self.read('codex', path).files, PATCH_FILES)

    def test_any_call_that_embeds_a_directive_edits_that_file_relative_to_the_cwd(self):
        escaped = ('text(await tools.apply_patch("*** Begin Patch\\n*** Update File: src/x.py\\n@@\\n-a\\n+b\\n'
                   '*** End Patch"));')
        template = ('const patch = `*** Begin Patch\n*** Add File: src/y.py\n+hi\n*** End Patch`;\n'
                    'await tools.apply_patch(patch);')
        headerless = ('await tools.exec_command({cmd: "apply_patch <<\'EOF\'\\n*** Update File: src/z.py\\n@@\\n-a\\n+b\\n'
                      'EOF"});')
        calls = (('exec', 'custom_tool_call', escaped, '/w/proj/src/x.py'),
                 ('exec', 'custom_tool_call', template, '/w/proj/src/y.py'),
                 ('anything', 'function_call', escaped, '/w/proj/src/x.py'),
                 ('exec', 'custom_tool_call', headerless, '/w/proj/src/z.py'))  # the Begin Patch line is not required
        for n, (name, kind, text, expected) in enumerate(calls):
            path = self.codex(f'q{n}', [codex_meta(f'q{n}'), codex_message(stamp(9), 'user', 'edit'),
                                        codex_call(stamp(9, 1), name, text, kind=kind)])
            self.assertEqual(self.read('codex', path).files, (expected,), (name, kind))

    def test_a_shell_call_that_runs_apply_patch_is_read_too(self):
        arguments = json.dumps({'command': ['apply_patch', PATCH]})
        path = self.codex('p4', [codex_meta('p4'), codex_message(stamp(9), 'user', 'patch it'),
                                 codex_call(stamp(9, 1), 'shell', arguments, kind='function_call')])
        self.assertEqual(self.read('codex', path).files, PATCH_FILES)

    def test_a_line_of_a_hunk_that_quotes_a_directive_is_not_an_edit(self):
        for call in (codex_call(stamp(9, 1), 'apply_patch', DECOY), codex_call(stamp(9, 1), 'exec', exec_code(DECOY))):
            path = self.codex('p5', [codex_meta('p5'), codex_message(stamp(9), 'user', 'patch it'), call])
            self.assertEqual(self.read('codex', path).files, ('/w/proj/doc.md',))

    def test_calls_without_a_patch_edit_nothing(self):
        path = self.codex('p6', [
            codex_meta('p6'), codex_message(stamp(9), 'user', 'look around'),
            codex_call(stamp(9, 1), 'exec', 'text(await tools.shell("cat notes.md"))'),
            codex_call(stamp(9, 2), 'exec', 'text("*** Update File: notes.md")'),  # mid-line: not a patch line
            codex_call(stamp(9, 3), 'shell', json.dumps({'command': ['ls']}), kind='function_call'),
            codex_call(stamp(9, 4), 'exec', None),
        ])
        self.assertEqual(self.read('codex', path).files, ())


class PiTest(StoreTest):
    def test_the_messages_of_the_window_and_the_header(self):
        path = self.pi('p1', [
            pi_header('pi-1'),
            {'type': 'model_change', 'id': 'a', 'parentId': None, 'timestamp': stamp(8), 'modelId': 'x'},
            {'type': 'thinking_level_change', 'id': 'b', 'parentId': 'a', 'timestamp': stamp(8), 'thinkingLevel': 'low'},
            pi_message(stamp(8, 1), 'system', 'system prompt'),
            pi_message(stamp(3, 59), 'user', [pi_text('too early')]),
            pi_message(stamp(9), 'user', [pi_text('add a test'), pi_text('please')]),
            pi_message(stamp(9, 1), 'assistant', [
                {'type': 'thinking', 'thinking': 'hmm'}, pi_text('sure'), pi_text('here'),
                pi_call('edit', {'path': 'src/a.py', 'edits': []}),
                pi_call('write', json.dumps({'path': '/abs/b.py', 'content': 'x'})),
                pi_call('edit', '{not json'),
                pi_call('bash', {'command': 'rm gone.py'}),
                pi_call('read', {'path': 'read.py'})]),
            pi_message(stamp(9, 2), 'toolResult', [pi_text('ok')]),
            pi_message(stamp(9, 3), 'user', '<skill>x</skill>'),
            pi_message(stamp(9, 4), 'user', 'a plain string prompt'),
            {'type': 'custom_message', 'id': 'z', 'parentId': None, 'timestamp': stamp(9, 5), 'content': 'x'},
            pi_message(stamp(5, days=1), 'assistant', [pi_text('too late'), pi_call('write', {'path': 'late.py'})]),
        ])
        session = self.read('pi', path)
        self.assertEqual([(turn.role, turn.text) for turn in session.turns],
                         [('user', 'add a test\nplease'), ('assistant', 'sure\nhere'), ('user', 'a plain string prompt')])
        self.assertEqual(session.files, ('/abs/b.py', '/w/proj/src/a.py'))
        self.assertEqual((session.cli, session.id, session.cwd, session.path), ('pi', 'pi-1', CWD, path))
        self.assertEqual((session.title, session.started, session.ended), ('too early', local(9), local(9, 4)))

    def test_the_id_comes_from_the_file_name_when_there_is_no_header(self):
        path = self.pi('01a1-b2c3', [pi_message(stamp(9), 'user', [pi_text('hi')])])
        self.assertEqual(self.read('pi', path).id, '01a1-b2c3')


class SessionsTest(StoreTest):
    def test_every_cli_is_read_and_the_oldest_session_comes_first(self):
        self.pi('p', [pi_header('p'), pi_message(stamp(11), 'user', [pi_text('pi work')])])
        self.claude('c', [claude_user(stamp(10), 'claude work')])
        self.codex('x', [codex_meta('x'), codex_message(stamp(9), 'user', 'codex work')])
        found = self.sessions()
        self.assertEqual([(s.cli, s.id, s.title) for s in found],
                         [('codex', 'x', 'codex work'), ('claude', 'c', 'claude work'), ('pi', 'p', 'pi work')])
        self.assertEqual([s.started for s in found], [local(9), local(10), local(11)])

    def test_sessions_that_start_together_come_in_a_fixed_order(self):
        self.pi('b', [pi_header('b'), pi_message(stamp(9), 'user', [pi_text('x')])])
        self.claude('b', [claude_user(stamp(9), 'x')])
        self.claude('a', [claude_user(stamp(9), 'x')])
        self.assertEqual([(s.cli, s.id) for s in self.sessions()], [('claude', 'a'), ('claude', 'b'), ('pi', 'b')])

    def test_turns_outside_the_window_are_dropped_and_a_session_without_any_is_absent(self):
        self.claude('some', [claude_user(stamp(3), 'before'), claude_user(stamp(9), 'inside'),
                             claude_user(stamp(5, days=1), 'after')])
        self.claude('none', [claude_user(stamp(3), 'before'), claude_user(stamp(5, days=1), 'after'),
                             claude_assistant(stamp(5, days=1), 'edit', edits=[('Edit', {'file_path': '/w/proj/x.py'})])])
        found = self.sessions()
        self.assertEqual([s.id for s in found], ['some'])
        self.assertEqual([turn.text for turn in found[0].turns], ['inside'])

    def test_the_window_includes_its_start_and_excludes_its_end(self):
        self.claude('edges', [claude_user(stamp(3, 59), 'previous day'), claude_user(stamp(4), 'first moment'),
                              claude_user(stamp(3, 59, days=1), 'last moment'), claude_user(stamp(4, days=1), 'next day')])
        self.assertEqual([turn.text for turn in self.sessions()[0].turns], ['first moment', 'last moment'])

    def test_a_turn_at_0359_belongs_to_the_previous_days_window_and_0400_to_the_days(self):
        self.claude('night', [claude_user(stamp(3, 59), 'late night'), claude_user(stamp(4), 'early morning')])
        today = agent_sessions.sessions(*agent_sessions.window(DAY, tz=TZ), home=self.home)
        yesterday = agent_sessions.sessions(*agent_sessions.window(DAY - timedelta(days=1), tz=TZ), home=self.home)
        self.assertEqual([turn.text for turn in today[0].turns], ['early morning'])
        self.assertEqual([turn.text for turn in yesterday[0].turns], ['late night'])

    def test_files_come_only_from_edits_inside_the_window(self):
        self.claude('f', [claude_user(stamp(9), 'go'),
                          claude_assistant(stamp(3), 'early', edits=[('Edit', {'file_path': '/w/proj/early.py'})]),
                          claude_assistant(stamp(9, 1), 'now', edits=[('Edit', {'file_path': '/w/proj/now.py'})]),
                          claude_assistant(stamp(5, days=1), 'late', edits=[('Edit', {'file_path': '/w/proj/late.py'})])])
        self.assertEqual(self.sessions()[0].files, ('/w/proj/now.py',))

    def test_sessions_in_scratch_folders_are_dropped(self):
        scratch = '/private/var/folders/ab/cd/T/exp'
        self.claude('keep', [claude_user(stamp(9), 'real')])
        self.claude('drop', [claude_user(stamp(9), 'scratch', cwd=scratch)], slug='-private-var-folders')
        self.codex('drop', [codex_meta('drop', cwd='/tmp/exp'), codex_message(stamp(9), 'user', 'scratch')])
        self.pi('drop', [pi_header('drop', cwd='/private/tmp/claude-501/x'),
                         pi_message(stamp(9), 'user', [pi_text('scratch')])])
        self.assertEqual([(s.cli, s.id) for s in self.sessions()], [('claude', 'keep')])

    def test_a_file_last_written_before_the_window_is_not_opened(self):
        rows = [claude_user(stamp(9), 'inside the window')]  # the lines are in the window; the file's time says otherwise
        old = self.claude('old', rows, mtime=START - timedelta(seconds=1))
        self.claude('edge', rows, mtime=START)
        self.assertEqual([s.id for s in self.sessions()], ['edge'])
        self.assertIsNotNone(self.read('claude', old))  # read() does not look at the file's time

    def test_a_line_that_cannot_be_read_is_skipped(self):
        self.claude('bad', [
            'not json at all', '', '[1, 2]', 'null', '{"truncated": ',
            json.dumps({'type': 'user', 'timestamp': 'yesterday-ish', 'message': {'content': 'bad time'}}),
            json.dumps({'type': 'user', 'timestamp': 5, 'message': {'content': 'number time'}}),
            json.dumps({'type': 'user', 'message': {'content': 'no time'}}),
            json.dumps({'type': 'user', 'timestamp': stamp(9), 'message': 'not an object'}),
            json.dumps({'type': 'user', 'timestamp': stamp(9), 'message': {'content': None}}),
            json.dumps({'type': 'assistant', 'timestamp': stamp(9), 'message': {'content': 5}}),
            json.dumps({'type': 'assistant', 'timestamp': stamp(9), 'message': {'content': [None, 'x', {'type': 'text'}]}}),
            json.dumps({'type': 'assistant', 'timestamp': stamp(9), 'message': {'content': [
                {'type': 'tool_use', 'name': 'Edit', 'input': 'not an object'}]}}),
            json.dumps({'type': 'ai-title', 'aiTitle': 5}),
            json.dumps({'type': 'user', 'timestamp': stamp(9, 1).rstrip('Z'), 'cwd': CWD,
                        'message': {'content': 'a time without a zone is UTC'}}),
            json.dumps(claude_user(stamp(9, 2), 'good')),
        ])
        self.codex('bad', ['{"type": "response_item", "timestamp": "' + stamp(9) + '", "payload": "x"}',
                           '{"type": "session_meta", "payload": []}',
                           json.dumps({'timestamp': stamp(9), 'type': 'response_item',
                                       'payload': {'type': 'message', 'role': 'user', 'content': 'not a list'}}),
                           json.dumps(codex_message(stamp(9, 1), 'user', 'good'))])
        self.pi('bad', ['{"type": "message", "timestamp": "' + stamp(9) + '", "message": "x"}',
                        json.dumps(pi_message(stamp(9), 'assistant', [pi_call('write', {'path': 5})])),
                        json.dumps(pi_message(stamp(9, 1), 'user', [pi_text('good')]))])
        found = {s.cli: s for s in self.sessions()}
        self.assertEqual([turn.text for turn in found['claude'].turns], ['a time without a zone is UTC', 'good'])
        self.assertEqual(found['claude'].files, ())
        self.assertEqual([turn.text for turn in found['codex'].turns], ['good'])
        self.assertEqual([turn.text for turn in found['pi'].turns], ['good'])

    def test_a_missing_store_is_skipped(self):
        self.assertEqual(self.sessions(), [])
        self.pi('only', [pi_header('only'), pi_message(stamp(9), 'user', [pi_text('hi')])])
        self.assertEqual([(s.cli, s.id) for s in self.sessions()], [('pi', 'only')])

    def test_the_home_folder_defaults_to_the_users(self):
        self.claude('h', [claude_user(stamp(9), 'hi')])
        with mock.patch.object(Path, 'home', return_value=self.home):
            self.assertEqual([s.id for s in agent_sessions.sessions(START, END)], ['h'])

    def test_a_window_without_a_zone_is_taken_as_local_time(self):
        self.assertEqual(agent_sessions.sessions(datetime(2026, 11, 2, 4), datetime(2026, 11, 3, 4), self.home), [])

    def test_only_the_top_folder_of_a_store_is_scanned_for_claude_and_pi(self):
        self.claude('top', [claude_user(stamp(9), 'user session')])
        self.put('.claude/projects/-w-proj/top/subagents/agent-1.jsonl', [claude_user(stamp(9), 'a subagent thread')])
        self.put('.claude/projects/-w-proj/notes.json', ['{}'])
        self.put('.pi/agent/sessions/--w-proj--/deeper/2026-11-02T02-00-00-000Z_x.jsonl', [pi_header('x')])
        self.put('.codex/sessions/2026/11/02/readme.txt', ['x'])
        self.assertEqual([(s.cli, s.id) for s in self.sessions()], [('claude', 'top')])

    def test_codex_reads_every_day_folder_since_a_resumed_session_writes_under_its_first_day(self):
        folders = {'d0830': '2026/08/30', 'd1030': '2026/10/30', 'd1031': '2026/10/31', 'd1101': '2026/11/01',
                   'd1102': '2026/11/02', 'd1103': '2026/11/03', 'd1104': '2026/11/04'}
        for n, (name, folder) in enumerate(folders.items()):
            self.codex(name, [codex_meta(name), codex_message(stamp(9, n), 'user', 'in the window')], folder=folder)
        self.assertEqual({s.id for s in self.sessions()}, set(folders))
        # A folder is never skipped for its date; a file last written before the window is, whatever its folder.
        (old,) = (self.home / '.codex/sessions/2026/08/30').glob('*.jsonl')
        os.utime(old, (0, 0))
        self.assertEqual({s.id for s in self.sessions()}, set(folders) - {'d0830'})


class ReadTest(StoreTest):
    def test_garbage_is_none(self):
        garbage = self.put('garbage.jsonl', ['\x00\x01 binary', '{{{', 'null', '42', '"text"', '[]'])
        binary = self.home / 'binary.jsonl'
        binary.write_bytes(b'\xff\xfe\x00{"type": "user"\n\x80\x81\n')
        for cli in agent_sessions.CLIS:
            self.assertIsNone(self.read(cli, garbage), cli)
            self.assertIsNone(self.read(cli, binary), cli)
            self.assertIsNone(self.read(cli, self.put('empty.jsonl', [])), cli)

    def test_a_missing_file_and_a_folder_are_none(self):
        for cli in agent_sessions.CLIS:
            self.assertIsNone(self.read(cli, self.home / 'missing.jsonl'), cli)
            self.assertIsNone(self.read(cli, self.home), cli)
            self.assertIsNone(self.read(cli, 'not\x00a path'), cli)

    def test_an_unknown_cli_is_none(self):
        path = self.claude('c', [claude_user(stamp(9), 'hi')])
        self.assertIsNone(self.read('agy', path))
        self.assertIsNotNone(self.read('claude', path))

    def test_the_path_may_be_a_string(self):
        path = self.claude('c', [claude_user(stamp(9), 'hi')])
        self.assertEqual(self.read('claude', str(path)).path, path)

    def test_a_transcript_with_no_turn_in_the_window_is_none(self):
        path = self.claude('c', [claude_user(stamp(3), 'before'), claude_title('A title')])
        self.assertIsNone(self.read('claude', path))


class LastReplyTest(StoreTest):
    """The agent's last message to the user, whatever the day, read from the file's tail."""

    def test_each_store_gives_its_last_assistant_text_and_a_later_prompt_does_not_hide_it(self):
        files = {
            'claude': self.claude('c', [claude_user(stamp(9), 'grill me'), claude_assistant(stamp(9, 1), 'Q1. Which?'),
                                        claude_user(stamp(9, 2), '1'),
                                        claude_assistant(stamp(9, 3), 'Noted.', 'Confirm and I will build it.'),
                                        claude_user(stamp(9, 4), 'y')]),
            'codex': self.codex('x', [codex_meta('x'), codex_message(stamp(9), 'user', 'review it'),
                                      codex_message(stamp(9, 1), 'assistant', 'Two findings.'),
                                      codex_message(stamp(9, 2), 'user', 'fix both')]),
            'pi': self.pi('p', [pi_header('p'), pi_message(stamp(9), 'user', 'why?'),
                                pi_message(stamp(9, 1), 'assistant', [pi_text('Because of the cache.')]),
                                pi_message(stamp(9, 2), 'user', [pi_text('ok')])]),
        }
        self.assertEqual({cli: agent_sessions.last_reply(cli, path) for cli, path in files.items()},
                         {'claude': 'Noted.\nConfirm and I will build it.', 'codex': 'Two findings.',
                          'pi': 'Because of the cache.'})

    def test_a_subagents_reply_inside_the_transcript_is_not_the_agents(self):
        path = self.claude('c', [claude_assistant(stamp(9), 'Shall I ship it?'),
                                 claude_assistant(stamp(9, 5), 'Subagent: 3 files read.', isSidechain=True)])
        self.assertEqual(agent_sessions.last_reply('claude', path), 'Shall I ship it?')

    def test_only_the_tail_is_read_and_a_line_cut_in_half_is_skipped(self):
        path = self.claude('c', [claude_assistant(stamp(9), 'Old reply.'), claude_user(stamp(9, 1), 'x' * 500),
                                 claude_assistant(stamp(9, 2), 'Last reply.'), claude_user(stamp(9, 3), 'y')])
        *_, reply, prompt = path.read_bytes().splitlines(keepends=True)
        # The tail starts 10 bytes into the 500-character prompt: that half line is dropped, the rest read.
        self.assertEqual(agent_sessions.last_reply('claude', path, tail=len(reply) + len(prompt) + 10), 'Last reply.')
        # The tail starts inside the last reply's own line: nothing older is looked for.
        self.assertEqual(agent_sessions.last_reply('claude', path, tail=len(prompt) + len(reply) // 2), '')

    def test_a_file_that_cannot_be_read_or_holds_no_reply_is_empty(self):
        prompts = self.claude('c', [claude_user(stamp(9), 'hi'), '{{{'])
        for path in (prompts, self.home / 'missing.jsonl', self.home, 'not\x00a path'):
            self.assertEqual(agent_sessions.last_reply('claude', path), '', path)
        self.assertEqual(agent_sessions.last_reply('agy', prompts), '')


class NoteTest(StoreTest):
    """A harness note (Claude Code's meta rows) since the last prompt: the usage-limit note, say."""
    NOTE = '[Usage limit reached'

    def test_a_note_after_the_prompt_counts_and_a_newer_prompt_clears_it(self):
        note = claude_user(stamp(9, 1), '[Usage limit reached; a short grace allowance remains.]', isMeta=True)
        reply = claude_assistant(stamp(9, 2), 'Stopping here.')
        noted = self.claude('a', [claude_user(stamp(9), 'build it'), note, reply])
        self.assertTrue(agent_sessions.note_since_prompt('claude', noted, self.NOTE))
        later = self.claude('b', [claude_user(stamp(9), 'build it'), note, reply, claude_user(stamp(9, 3), 'go on')])
        self.assertFalse(agent_sessions.note_since_prompt('claude', later, self.NOTE))

    def test_another_note_a_typed_look_alike_a_subagent_and_other_stores_do_not_count(self):
        rows = [claude_user(stamp(9), 'build it'),
                claude_user(stamp(9, 1), '<system-reminder>Usage limit reached</system-reminder>', isMeta=True),
                claude_user(stamp(9, 2), '[Usage limit reached', isSidechain=True, isMeta=True)]
        path = self.claude('c', rows)
        self.assertFalse(agent_sessions.note_since_prompt('claude', path, self.NOTE))
        typed = self.claude('d', [claude_user(stamp(9), '[Usage limit reached? what does that mean')])
        self.assertFalse(agent_sessions.note_since_prompt('claude', typed, self.NOTE))
        for cli, missing in (('codex', path), ('claude', self.home / 'missing.jsonl')):
            self.assertFalse(agent_sessions.note_since_prompt(cli, missing, self.NOTE), cli)


if __name__ == '__main__':
    unittest.main()
