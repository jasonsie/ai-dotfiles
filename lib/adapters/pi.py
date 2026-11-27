"""Pi."""
import fnmatch

from .base import Adapter
from .rows import args, items, obj, text, when


class Pi(Adapter):
    cli = 'pi'
    tools = {'edit': frozenset(('edit', 'write')), 'shell': frozenset(('bash',)),
             'read': frozenset(('read', 'grep', 'find', 'ls'))}
    path_keys = ('path',)
    session_store = '.pi/agent/sessions'  # <store>/<cwd-slug>/<ts>_<id>.jsonl
    shows_worktree_move = False  # its footer is set by the extension
    hook_file = False
    kinds = ('pre', 'stop', 'end', 'prompt', 'start')  # the events its extension (scripts/agent_hooks.ts) sends
    timeouts = {'pre': 60, 'end': 60}
    continuation_unflagged = True
    instructions_override = 'AGENTS.override.md'

    def check_settings(self, data, keys):
        if not keys.keys() & {'defaultProvider', 'defaultModel'}:
            return
        patterns = data.get('enabledModels') or []
        full = f"{data.get('defaultProvider', '')}/{data.get('defaultModel', '')}"
        if patterns and not any(fnmatch.fnmatch(full, pattern) for pattern in patterns):
            raise ValueError(f'Pi default {full} is not in enabledModels; add it there first')  # its scope would hide it

    def mcp_add(self, server):
        described = ('--description', server['description']) if server.get('description') else ()
        return self.native_mcp_add(server, after=described)

    def session_survives_end(self, reason):
        return reason == 'reload'

    def transcripts(self, store):
        return sorted(store.glob('*/*.jsonl'))

    def session_id(self, stem):
        return stem.split('_', 1)[-1]

    def read_row(self, reader, row):
        kind = row.get('type')
        if kind == 'session':
            reader.id = text(row.get('id')) or reader.id
            reader.cwd = text(row.get('cwd'))
            return
        at = when(row.get('timestamp'))
        if kind != 'message' or at is None:
            return
        message = obj(row.get('message'))
        content = message.get('content')
        parts = items(content)
        texts = [content] if isinstance(content, str) else [part.get('text') for part in parts
                                                            if part.get('type') == 'text']
        if message.get('role') == 'user':
            reader.user(at, texts)
        elif message.get('role') == 'assistant':
            reader.assistant(at, texts)
            for part in parts:
                if part.get('type') == 'toolCall' and part.get('name') in self.tools['edit']:
                    reader.edited(at, args(part.get('arguments')).get('path'))
