"""Codex CLI: it edits through apply_patch, whose patch arrives in the command field, and reads through its shell."""
import re

from .base import PATCH_HEADER, Adapter
from .rows import args, items, obj, text, when


class Codex(Adapter):
    cli = 'codex'
    tools = {'edit': frozenset(('apply_patch', 'Edit', 'Write')), 'shell': frozenset(('Bash',)), 'read': frozenset()}
    patch_edits = True
    shows_worktree_move = False  # no status line follows a steered session
    prompt_starts_open = True
    session_store = '.codex/sessions'  # <store>/YYYY/MM/DD/rollout-<ts>-<id>.jsonl, a folder per local day
    rollout = re.compile(r'rollout-\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-(.+)')
    matchers = {'edit': 'Edit|Write', 'shell': 'Bash'}  # it matches apply_patch as Edit or Write
    # SessionStart runs only inside a session's first turn there, too late to report a resumed session.
    kinds = ('pre', 'tool', 'stop', 'end', 'prompt', 'permission', 'interrupt')
    timeouts = {'pre': 60, 'end': 3, 'interrupt': 3}  # it runs SessionEnd and Interrupt hooks 3 s at most
    settings_format = 'toml'  # config.toml holds its settings and its MCP servers
    mcp_key = 'mcp_servers'
    instructions_override = 'AGENTS.override.md'

    def mcp_add(self, server):
        return self.native_mcp_add(server)

    def transcripts(self, store):
        # Files sit under the day the session began and a session resumed days later keeps writing there.
        return sorted(store.glob('*/*/*/*.jsonl'))

    def session_id(self, stem):
        named = self.rollout.fullmatch(stem)
        return named.group(1) if named else stem

    def files_in_patch(self, patch):
        return [match.group(2).strip() for match in PATCH_HEADER.finditer(patch) if match.group(2).strip()]

    def read_row(self, reader, row):
        kind, payload = row.get('type'), obj(row.get('payload'))
        if kind == 'session_meta':
            if not reader.opened:  # a forked thread repeats its parent's meta after its own
                reader.opened = True
                reader.id = text(payload.get('id')) or reader.id
                reader.cwd = text(payload.get('cwd'))
                source = payload.get('source')
                reader.subagent = payload.get('thread_source') == 'subagent' or (
                    isinstance(source, dict) and 'subagent' in source)
            return
        at = when(row.get('timestamp'))
        if kind != 'response_item' or at is None:
            return
        item = payload.get('type')
        if item == 'message':
            texts = [part.get('text') for part in items(payload.get('content'))
                     if part.get('type') in ('input_text', 'output_text')]
            if payload.get('role') == 'user':  # the injected AGENTS.md starts with '#'
                reader.user(at, texts, hidden=('<', '#'))
            elif payload.get('role') == 'assistant':
                reader.assistant(at, texts)
        elif item in ('custom_tool_call', 'function_call'):
            body = payload.get('input' if item == 'custom_tool_call' else 'arguments')
            for path in self.patched(payload.get('name'), body):
                reader.edited(at, path)

    def patched(self, name, body):
        """The paths a Codex tool call edits, from the patch in its text, whatever the call is named.
        apply_patch carries the patch as its input, or as the `input` of JSON arguments. Any other
        call (exec runs JavaScript that calls apply_patch; a shell call may too) carries it inside a
        string, with the newlines escaped, so those are unescaped first. Only a line that starts with
        a directive counts, not a '+' line of a hunk that happens to quote one."""
        if not isinstance(body, str):
            return []
        if name == 'apply_patch':
            body = text(args(body).get('input')) or body
        return self.files_in_patch(body.replace('\\n', '\n'))
