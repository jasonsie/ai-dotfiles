"""Claude Code."""
from .base import Adapter


class Claude(Adapter):
    cli = 'claude'
    tools = {'edit': frozenset(('Edit', 'Write', 'NotebookEdit')), 'shell': frozenset(('Bash',)),
             'read': frozenset(('Read', 'Glob', 'Grep')), 'ask': frozenset(('AskUserQuestion', 'ExitPlanMode'))}
    path_keys = ('file_path', 'notebook_path')
