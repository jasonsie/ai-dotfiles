"""Adapter: what one CLI does differently, on the hook side and the install side. The CLI's own file holds the data.

A feature never asks which CLI it runs in: it reads the command, its folder and the files a call
names from the Event (scripts/agent_hooks.py), which asks the CLI's adapter here, and it asks the
adapter what the CLI can do. An install step (lib/install) does the same: it asks the adapter how
the CLI's files are edited. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import os
import re
import shlex

# The lines of an apply_patch patch that name a file; the second group is the name.
PATCH_HEADER = re.compile(r'^(\*\*\* (?:Add|Update|Delete) File: |\*\*\* Move to: )(.+)$', re.M)


class Adapter:
    cli = ''
    tools: dict[str, frozenset[str]] = {}  # what each tool does: edit, shell, read or ask; the rest is 'other'
    command_key = 'command'                # the tool-input field that holds a shell call's command
    folder_key: str | None = None          # the field that holds the folder it runs in, if the CLI has one
    path_keys: tuple[str, ...] = ()        # the fields that name a file or folder
    patch_edits = False                    # an edit is a patch in the command field, not a file field
    hook_file = True                       # its hooks sit in a hook file (Pi loads an extension instead)
    matchers: dict[str, str] = {}          # the hook file's tool matcher per action, where it differs from the tools
    kinds: tuple[str, ...] = ()            # the hook events it hands over (scripts/agent_hooks.py NATIVE names them)
    timeouts: dict[str, int] = {}          # the door's time in seconds per kind, where it is not the default
    continuation_unflagged = False         # it does not flag the turn a hook's own Continue started
    enters_worktree = False                # it has its own tool to enter a worktree, so a session needs no steering
    shows_worktree_move = True             # its own status line follows a session steered to another worktree
    prompt_starts_open = False             # a typed prompt opens a turn nothing has judged, until its Stop hook answers

    # The install side (lib/install): how the installer edits this CLI's files.
    settings_format = 'json'               # its settings and MCP files: 'json' or 'toml'
    mcp_key = 'mcpServers'                 # the key of those files that holds the MCP servers
    mcp_lists = True                       # `<cli> mcp list` names its servers (else its file is read)
    instructions_override = None           # a file next to its instructions that it reads first and would shadow ours

    def check_settings(self, data, keys):
        """Refuse managed `keys` that, merged into the settings `data`, this CLI would not honour."""

    def mcp_add(self, server):
        """The argv that adds the server (a dict of config/mcp-servers.json) in user scope, or None when the
        CLI has no such command and its file is edited."""
        return None

    def native_mcp_add(self, server, before=(), after=()):
        """`<cli> mcp add`, with `before` and `after` the options that go either side of the server's name."""
        return [self.cli, 'mcp', 'add', *before, server['name'], *after, '--', server['command'], *server.get('args', [])]

    @property
    def takes_folder(self):
        return self.folder_key is not None

    def action_of(self, tool):
        for action, names in self.tools.items():
            if tool in names:
                return action
        return 'other'

    # Its session store, read by scripts/agent_sessions.py: transcripts under `session_store` (relative to home),
    # each line told to read_row, which says what it holds to the reader (user, assistant, edited, id, cwd, ...).
    session_store: str | None = None
    leaves_notes = False  # its harness writes notes into the transcript (note_since_prompt)

    def transcripts(self, store):
        """The transcript files under `store`: every one (a file's age rules the old ones out, not its folder's)."""
        return []

    def session_id(self, stem):
        """A session's id from its transcript's file name, until the transcript says it itself."""
        return stem

    def read_row(self, reader, row):
        """Tell `reader` what one line of a transcript (a dict) says."""

    def note_since_prompt(self, lines, prefix):
        """Whether the harness left a note starting with `prefix` after the last prompt in these transcript lines."""
        return False

    def session_survives_end(self, reason):
        """Whether a session that ends for `reason` goes on (the CLI reloads it in place)."""
        return False

    def is_headless(self, environ):
        """Whether `environ` is that of a run started by a program, not typed at by a person."""
        return False

    def command(self, tool_input):
        value = tool_input.get(self.command_key)
        return value if isinstance(value, str) else ''

    def folder(self, tool_input):
        """The folder the call says it runs in, or ''."""
        value = tool_input.get(self.folder_key) if self.folder_key else None
        return value if isinstance(value, str) else ''

    def files(self, tool_input, action):
        """The names the call gives its files, as written (a relative one is relative to the session's folder)."""
        if self.patch_edits and action == 'edit':
            return tuple(match.group(2).strip() for match in PATCH_HEADER.finditer(self.command(tool_input)))
        return tuple(name for name in (tool_input.get(key) for key in self.path_keys) if isinstance(name, str) and name)

    def with_command(self, tool_input, command, folder=None):
        """The input running `command` in `folder`: in its folder field when the CLI has one, else after a `cd`."""
        data = dict(tool_input)
        if folder and self.folder_key:
            data[self.folder_key] = folder
        elif folder:
            command = f'cd {shlex.quote(folder)} && {command}'
        data[self.command_key] = command
        return data

    def retarget(self, tool_input, action, folder, move):
        """The input with each file `move` gives a new place (`move(absolute path)`: the new absolute path,
        or None to leave it), or None when nothing changes. `folder` is what a relative name is relative to."""
        data = dict(tool_input)
        if self.patch_edits and action == 'edit':
            def header(match):
                target = move(os.path.normpath(os.path.join(folder, match.group(2).strip())))
                return match.group(1) + (os.path.relpath(target, folder) if target else match.group(2))
            data[self.command_key] = PATCH_HEADER.sub(header, self.command(tool_input))
        else:
            for key in self.path_keys:
                if isinstance(data.get(key), str) and data[key]:
                    target = move(os.path.normpath(os.path.join(folder, data[key])))
                    if target:
                        data[key] = str(target)
        return data if data != tool_input else None
