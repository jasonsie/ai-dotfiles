"""Pi."""
from .base import Adapter


class Pi(Adapter):
    cli = 'pi'
    tools = {'edit': frozenset(('edit', 'write')), 'shell': frozenset(('bash',)),
             'read': frozenset(('read', 'grep', 'find', 'ls'))}
    path_keys = ('path',)
