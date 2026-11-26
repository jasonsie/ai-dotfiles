"""Pi."""
from .base import Adapter


class Pi(Adapter):
    cli = 'pi'
    tools = {'edit': frozenset(('edit', 'write')), 'shell': frozenset(('bash',)),
             'read': frozenset(('read', 'grep', 'find', 'ls'))}
    path_keys = ('path',)
    shows_worktree_move = False  # its footer is set by the extension

    def session_survives_end(self, reason):
        return reason == 'reload'
    hook_file = False
    kinds = ('pre', 'stop', 'end', 'prompt', 'start')  # the events its extension (scripts/agent_hooks.ts) sends
    timeouts = {'pre': 60, 'end': 60}
    continuation_unflagged = True
