"""Codex CLI: it edits through apply_patch, whose patch arrives in the command field, and reads through its shell."""
from .base import Adapter


class Codex(Adapter):
    cli = 'codex'
    tools = {'edit': frozenset(('apply_patch', 'Edit', 'Write')), 'shell': frozenset(('Bash',)), 'read': frozenset()}
    patch_edits = True
    shows_worktree_move = False  # no status line follows a steered session
    prompt_starts_open = True
    matchers = {'edit': 'Edit|Write', 'shell': 'Bash'}  # it matches apply_patch as Edit or Write
    # SessionStart runs only inside a session's first turn there, too late to report a resumed session.
    kinds = ('pre', 'tool', 'stop', 'end', 'prompt', 'permission', 'interrupt')
    timeouts = {'pre': 60, 'end': 3, 'interrupt': 3}  # it runs SessionEnd and Interrupt hooks 3 s at most
