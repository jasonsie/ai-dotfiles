"""Antigravity."""
from .base import Adapter


class Antigravity(Adapter):
    cli = 'agy'
    tools = {'edit': frozenset(('write_to_file', 'replace_file_content', 'multi_replace_file_content')),
             'shell': frozenset(('run_command',)),
             'read': frozenset(('view_file', 'list_dir', 'find_by_name', 'grep_search'))}
    command_key = 'CommandLine'
    folder_key = 'Cwd'
    path_keys = ('TargetFile', 'AbsolutePath', 'DirectoryPath', 'SearchPath', 'SearchDirectory')
    matchers = {'edit': 'write_to_file|replace_file_content|multi_replace_file_content', 'shell': 'run_command',
                'read': 'view_file|list_dir|find_by_name|grep_search'}
    kinds = ('pre', 'tool', 'stop')  # no session end, and no prompt event (PreInvocation carries no prompt text)
    timeouts = {'pre': 60}
    continuation_unflagged = True
