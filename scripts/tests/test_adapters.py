"""adapters: what differs between the CLIs on the hook side, one adapter per CLI (lib/adapters).

Run: python3 -m unittest discover -s scripts/tests -p 'test_adapters.py' -v
"""
import json
import sys
import unittest

from support import ROOT

sys.path.insert(0, str(ROOT / 'lib'))
sys.path.insert(0, str(ROOT / 'scripts'))
import adapters  # noqa: E402
import agent_hooks  # noqa: E402

PATCH = '*** Begin Patch\n*** Update File: a/b.py\n@@\n-x\n+y\n*** Add File: c.py\n+z\n*** Move to: d.py\n*** End Patch'


class RegistryTest(unittest.TestCase):
    def test_one_adapter_per_cli_in_the_config_and_no_other(self):
        listed = set(json.loads((ROOT / 'config/ai-clis.json').read_text())['clis'])
        self.assertEqual(set(adapters.CLIS), listed)
        for cli in adapters.CLIS:
            self.assertEqual(adapters.get(cli).cli, cli)

    def test_an_unknown_cli_gets_an_adapter_with_no_tools_and_the_plain_command_field(self):
        stranger = adapters.get('nova')
        self.assertEqual((stranger.action_of('Bash'), stranger.command({'command': 'ls'}), stranger.files({}, 'edit')),
                         ('other', 'ls', ()))


class ToolsTest(unittest.TestCase):
    def test_each_cli_names_its_tools_by_what_they_do(self):
        for cli, tool, action in (('claude', 'Write', 'edit'), ('claude', 'Bash', 'shell'), ('claude', 'Grep', 'read'),
                                  ('claude', 'ExitPlanMode', 'ask'), ('codex', 'apply_patch', 'edit'),
                                  ('codex', 'Bash', 'shell'), ('agy', 'run_command', 'shell'),
                                  ('agy', 'view_file', 'read'), ('pi', 'bash', 'shell'), ('pi', 'write', 'edit'),
                                  ('pi', 'Bash', 'other'), ('claude', 'bash', 'other')):
            self.assertEqual(adapters.get(cli).action_of(tool), action, (cli, tool))


class CommandTest(unittest.TestCase):
    def test_the_command_and_its_folder_sit_where_the_cli_puts_them(self):
        self.assertEqual(adapters.get('claude').command({'command': 'git status'}), 'git status')
        self.assertEqual(adapters.get('agy').command({'CommandLine': 'git status', 'Cwd': '/w'}), 'git status')
        self.assertEqual(adapters.get('agy').folder({'CommandLine': 'ls', 'Cwd': '/w'}), '/w')
        self.assertEqual(adapters.get('claude').folder({'command': 'ls', 'Cwd': '/w'}), '')
        self.assertEqual(adapters.get('pi').command({'command': 7}), '')

    def test_a_new_folder_goes_into_the_input_or_in_front_of_the_command(self):
        self.assertEqual(adapters.get('agy').with_command({'CommandLine': 'ls', 'Other': 1}, 'ls -a', '/n'),
                         {'CommandLine': 'ls -a', 'Cwd': '/n', 'Other': 1})
        self.assertEqual(adapters.get('claude').with_command({'command': 'ls', 'description': 'd'}, 'ls -a', '/n x'),
                         {'command': "cd '/n x' && ls -a", 'description': 'd'})
        self.assertEqual(adapters.get('pi').with_command({'command': 'ls'}, 'ls -a'), {'command': 'ls -a'})
        self.assertTrue(adapters.get('agy').takes_folder)
        self.assertFalse(adapters.get('codex').takes_folder)


class FilesTest(unittest.TestCase):
    def test_a_call_names_its_files_in_the_cli_s_fields(self):
        self.assertEqual(adapters.get('claude').files({'file_path': '/a.py'}, 'edit'), ('/a.py',))
        self.assertEqual(adapters.get('claude').files({'notebook_path': '/a.ipynb'}, 'edit'), ('/a.ipynb',))
        self.assertEqual(adapters.get('pi').files({'path': 'a.py', 'content': 'x'}, 'edit'), ('a.py',))
        self.assertEqual(adapters.get('agy').files({'TargetFile': '/t', 'SearchPath': '/s'}, 'read'), ('/t', '/s'))
        self.assertEqual(adapters.get('claude').files({'file_path': 7}, 'edit'), ())

    def test_codex_names_them_in_the_headers_of_its_patch(self):
        self.assertEqual(adapters.get('codex').files({'command': PATCH}, 'edit'), ('a/b.py', 'c.py', 'd.py'))
        self.assertEqual(adapters.get('codex').files({'command': PATCH}, 'shell'), ())

    def test_a_move_rewrites_the_names_a_call_holds(self):
        def move(path):
            return '/new' + path if path.startswith('/old') else None
        self.assertEqual(adapters.get('claude').retarget({'file_path': '/old/a', 'x': 1}, 'edit', '/old', move),
                         {'file_path': '/new/old/a', 'x': 1})
        self.assertEqual(adapters.get('claude').retarget({'file_path': '/else/a'}, 'edit', '/old', move), None)

    def test_a_moved_patch_header_is_relative_to_the_folder(self):
        def move(path):
            return path.replace('/old', '/new') if path.startswith('/old') else None
        patch = '*** Update File: a.py\n*** Add File: /elsewhere/b.py'
        out = adapters.get('codex').retarget({'command': patch}, 'edit', '/old', move)
        self.assertEqual(out, {'command': '*** Update File: ../new/a.py\n*** Add File: /elsewhere/b.py'})


def call(cli, tool, args, folder='/w'):
    """The Event of a 'pre' hook call in `cli`'s own input shape."""
    if cli == 'agy':
        data = {'conversationId': 's', 'workspacePaths': [folder], 'toolCall': {'name': tool, 'args': args}}
    else:
        data = {'session_id': 's', 'cwd': folder, 'tool_name': tool, 'tool_input': args}
    return agent_hooks.read(cli, 'pre', data)


class EventTest(unittest.TestCase):
    def test_a_shell_event_gives_the_command_and_the_folder_it_runs_in(self):
        agy = call('agy', 'run_command', {'CommandLine': 'git status', 'Cwd': '/w/x'})
        self.assertEqual((agy.command, agy.command_folder, agy.files), ('git status', '/w/x', ()))
        claude = call('claude', 'Bash', {'command': 'git status'})
        self.assertEqual((claude.command, claude.command_folder), ('git status', '/w'))

    def test_an_edit_event_gives_the_files_the_call_names(self):
        self.assertEqual(call('claude', 'Write', {'file_path': '/w/a.py'}).files, ('/w/a.py',))
        self.assertEqual(call('codex', 'apply_patch', {'command': PATCH}).files, ('a/b.py', 'c.py', 'd.py'))
        self.assertEqual(call('pi', 'edit', {'path': 'a.py'}).command, '')

    def test_the_properties_follow_a_rewritten_input(self):
        from dataclasses import replace
        event = replace(call('agy', 'run_command', {'CommandLine': 'ls'}), tool_input={'CommandLine': 'pwd', 'Cwd': '/n'})
        self.assertEqual((event.command, event.command_folder), ('pwd', '/n'))
        self.assertIs(event.adapter, adapters.get('agy'))


class HookFileTest(unittest.TestCase):
    """What the installer writes into each CLI's hook file: a change here is a new Codex /hooks approval."""

    def test_the_matchers_the_kinds_and_the_times_are_the_ones_the_hook_files_hold(self):
        self.assertEqual(agent_hooks.MATCHERS, {
            'claude': {'edit': 'Edit|Write|NotebookEdit', 'shell': 'Bash', 'read': 'Read|Glob|Grep',
                       'ask': 'AskUserQuestion|ExitPlanMode'},
            'codex': {'edit': 'Edit|Write', 'shell': 'Bash'},
            'agy': {'edit': 'write_to_file|replace_file_content|multi_replace_file_content', 'shell': 'run_command',
                    'read': 'view_file|list_dir|find_by_name|grep_search'}})
        self.assertEqual(agent_hooks.KINDS, {
            'claude': ('pre', 'tool', 'stop', 'end', 'prompt', 'error', 'permission', 'form', 'start', 'create',
                       'remove'),
            'codex': ('pre', 'tool', 'stop', 'end', 'prompt', 'permission', 'interrupt'),
            'agy': ('pre', 'tool', 'stop'), 'pi': ('pre', 'stop', 'end', 'prompt', 'start')})
        self.assertEqual(agent_hooks.TIMEOUTS, {
            'claude': {'pre': 60, 'end': 60, 'create': 60, 'remove': 60}, 'codex': {'pre': 60, 'end': 3, 'interrupt': 3},
            'agy': {'pre': 60}, 'pi': {'pre': 60, 'end': 60}})
        self.assertEqual((agent_hooks.CLIS, agent_hooks.HOOK_FILE_CLIS, agent_hooks.UNFLAGGED_CONTINUATION),
                         (('claude', 'codex', 'agy', 'pi'), ('claude', 'codex', 'agy'), ('agy', 'pi')))

    def test_each_adapter_holds_its_own(self):
        codex = adapters.get('codex')
        self.assertEqual((codex.kinds, codex.timeouts['end'], codex.matchers['edit'], codex.hook_file),
                         (agent_hooks.KINDS['codex'], 3, 'Edit|Write', True))
        self.assertEqual((adapters.get('pi').hook_file, adapters.get('pi').matchers, adapters.get('pi').continuation_unflagged),
                         (False, {}, True))
        self.assertFalse(adapters.get('claude').continuation_unflagged)


class CapabilityTest(unittest.TestCase):
    def test_what_a_cli_can_do_is_named_not_looked_up_by_its_id(self):
        self.assertEqual({cli: adapters.get(cli).enters_worktree for cli in adapters.CLIS},
                         {'claude': True, 'codex': False, 'agy': False, 'pi': False})
        self.assertEqual({cli: adapters.get(cli).shows_worktree_move for cli in adapters.CLIS},
                         {'claude': True, 'codex': False, 'agy': True, 'pi': False})


if __name__ == '__main__':
    unittest.main()
