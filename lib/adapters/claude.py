"""Claude Code."""
from .base import Adapter


class Claude(Adapter):
    cli = 'claude'
    tools = {'edit': frozenset(('Edit', 'Write', 'NotebookEdit')), 'shell': frozenset(('Bash',)),
             'read': frozenset(('Read', 'Glob', 'Grep')), 'ask': frozenset(('AskUserQuestion', 'ExitPlanMode'))}
    path_keys = ('file_path', 'notebook_path')
    matchers = {'edit': 'Edit|Write|NotebookEdit', 'shell': 'Bash', 'read': 'Read|Glob|Grep',
                'ask': 'AskUserQuestion|ExitPlanMode'}
    # Worktree events, API errors and MCP forms are Claude Code's own.
    kinds = ('pre', 'tool', 'stop', 'end', 'prompt', 'error', 'permission', 'form', 'start', 'create', 'remove')
    # Claude Code gives SessionEnd hooks 1.5 s unless an entry asks for more (up to 60); a worktree takes a while to make.
    timeouts = {'pre': 60, 'end': 60, 'create': 60, 'remove': 60}
