"""Adapter: what one CLI does differently on the hook side. The CLI's own file holds the data.

A feature never asks which CLI it runs in: it reads the command, its folder and the files a call
names from the Event (scripts/agent_hooks.py), which asks the CLI's adapter here, and it asks the
adapter what the CLI can do. Python 3.11+, stdlib only.
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

    @property
    def takes_folder(self):
        return self.folder_key is not None

    def action_of(self, tool):
        for action, names in self.tools.items():
            if tool in names:
                return action
        return 'other'

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
