"""Codex CLI: it edits through apply_patch, whose patch arrives in the command field, and reads through its shell."""
from .base import Adapter


class Codex(Adapter):
    cli = 'codex'
    tools = {'edit': frozenset(('apply_patch', 'Edit', 'Write')), 'shell': frozenset(('Bash',)), 'read': frozenset()}
    patch_edits = True
