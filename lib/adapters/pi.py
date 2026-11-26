"""Pi."""
from .base import Adapter


class Pi(Adapter):
    cli = 'pi'
    tools = {'edit': frozenset(('edit', 'write')), 'shell': frozenset(('bash',)),
             'read': frozenset(('read', 'grep', 'find', 'ls'))}
    path_keys = ('path',)
    hook_file = False
    kinds = ('pre', 'stop', 'end', 'prompt', 'start')  # the events its extension (scripts/agent_hooks.ts) sends
    timeouts = {'pre': 60, 'end': 60}
    continuation_unflagged = True
