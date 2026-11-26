"""Claude Code."""
import json

from .base import Adapter
from .rows import items, obj, text, when


class Claude(Adapter):
    cli = 'claude'
    tools = {'edit': frozenset(('Edit', 'Write', 'NotebookEdit')), 'shell': frozenset(('Bash',)),
             'read': frozenset(('Read', 'Glob', 'Grep')), 'ask': frozenset(('AskUserQuestion', 'ExitPlanMode'))}
    path_keys = ('file_path', 'notebook_path')
    enters_worktree = True  # EnterWorktree
    session_store = '.claude/projects'  # <store>/<cwd-slug>/<session-id>.jsonl
    # Lines that look like turns but are not: injected, a subagent's, a summary, an API error.
    not_a_turn = ('isMeta', 'isSidechain', 'isCompactSummary', 'isApiErrorMessage')

    def is_headless(self, environ):
        return environ.get('CLAUDE_CODE_ENTRYPOINT', '').startswith('sdk-')  # `claude -p` and the SDK
    matchers = {'edit': 'Edit|Write|NotebookEdit', 'shell': 'Bash', 'read': 'Read|Glob|Grep',
                'ask': 'AskUserQuestion|ExitPlanMode'}
    # Worktree events, API errors and MCP forms are Claude Code's own.
    kinds = ('pre', 'tool', 'stop', 'end', 'prompt', 'error', 'permission', 'form', 'start', 'create', 'remove')
    # Claude Code gives SessionEnd hooks 1.5 s unless an entry asks for more (up to 60); a worktree takes a while.
    timeouts = {'pre': 60, 'end': 60, 'create': 60, 'remove': 60}

    def transcripts(self, store):
        return sorted(store.glob('*/*.jsonl'))  # not deeper: Claude Code keeps subagent threads there

    def read_row(self, reader, row):
        kind = row.get('type')
        if kind == 'ai-title':  # no timestamp, and it may come again: the last one is the title
            reader.ai_title = text(row.get('aiTitle')).strip() or reader.ai_title
            return
        reader.cwd = reader.cwd or text(row.get('cwd'))
        at = when(row.get('timestamp'))
        if kind not in ('user', 'assistant') or at is None or any(row.get(flag) for flag in self.not_a_turn):
            return
        content = obj(row.get('message')).get('content')
        if kind == 'user':  # a list is tool results, not a prompt
            if isinstance(content, str):
                reader.user(at, [content])
            return
        blocks = items(content)
        reader.assistant(at, [block.get('text') for block in blocks if block.get('type') == 'text'])
        for block in blocks:
            if block.get('type') == 'tool_use' and block.get('name') in self.tools['edit']:
                edit = obj(block.get('input'))
                reader.edited(at, edit.get('file_path') or edit.get('notebook_path'))

    def note_since_prompt(self, lines, prefix):
        found = False
        for line in lines:
            try:
                row = obj(json.loads(line))
            except ValueError:
                continue
            if row.get('type') != 'user' or row.get('isSidechain'):
                continue
            content = obj(row.get('message')).get('content')
            if row.get('isMeta'):
                texts = [content] if isinstance(content, str) else [b.get('text') for b in map(obj, items(content))]
                found = found or any(text(each).startswith(prefix) for each in texts)
            elif isinstance(content, str) and content.strip():  # a new prompt: notes before it no longer count
                found = False
        return found
