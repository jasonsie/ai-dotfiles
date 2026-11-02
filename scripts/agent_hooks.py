"""agent_hooks: one interface over the hook formats of Claude Code, Codex, Antigravity and Pi.

A feature (daily-log, worktree-guard) sees a plain Event and answers with a plain reply; this
module reads each CLI's hook input into that Event, writes the reply back in the CLI's own
shape, keeps the feature's state per session, and tells the installer which native events and
matchers a feature needs. Everything that differs between the CLIs lives here.

  call(cli, kind, data, handle, store)   one hook call: handle(event, state) -> None | Continue
  serve(cli, kind, answer)               a call on stdin/stdout; exits 0, fails open, silently
  Store(env, default, keep)              one JSON file per session, pruned after `keep` seconds
  native_events(cli, wants)              ((native event, kind, matcher), ...) for the installer

Kinds: 'tool' (after a tool call) and 'stop' (a turn ends). Pi has no hook file: a feature's
Pi extension sends {session_id, cwd, tool_name} and reads {continue: text}. Features import
this file from the repo's scripts/ folder. Python 3.11+, stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

CLIS = ('claude', 'codex', 'agy', 'pi')
HOOK_FILE_CLIS = ('claude', 'codex', 'agy')  # Pi loads an extension instead
EDIT_TOOLS = {
    'claude': {'Edit', 'Write', 'NotebookEdit'},
    'codex': {'apply_patch', 'Edit', 'Write'},
    'agy': {'write_to_file', 'replace_file_content', 'multi_replace_file_content'},
    'pi': {'edit', 'write'},
}
# The installer's matcher for "an edit tool"; Codex matches apply_patch as Edit or Write.
EDIT_MATCHERS = {
    'claude': 'Edit|Write|NotebookEdit',
    'codex': 'Edit|Write',
    'agy': 'write_to_file|replace_file_content|multi_replace_file_content',
}
NATIVE = {'tool': 'PostToolUse', 'stop': 'Stop'}  # the same names in all three hook files
# CLIs that do not flag the turn a hook's own Continue started; the store remembers it for them.
UNFLAGGED_CONTINUATION = ('agy', 'pi')
CONTINUED = 'pending'


@dataclass(frozen=True)
class Event:
    cli: str
    kind: str
    session: str | None
    folder: str | None
    tool: str = ''               # the CLI's own tool name
    edit: bool = False           # the tool changes files
    continuation: bool = False   # this turn was started by a hook's own Continue
    model_stopped: bool = True   # the turn ended because the model finished, not on an error or cap


@dataclass(frozen=True)
class Continue:
    """Keep the turn going, with `text` as the model's next instruction (a 'stop' reply)."""
    text: str


def read(cli, kind, data):
    """The Event in one CLI's hook input."""
    data = data if isinstance(data, dict) else {}
    if cli == 'agy':
        paths = data.get('workspacePaths') or []
        call = data.get('toolCall') if isinstance(data.get('toolCall'), dict) else {}
        session, folder = data.get('conversationId'), (paths[0] if paths else None)
        tool = str(call.get('name') or '')
        model_stopped = data.get('terminationReason', 'model_stop') == 'model_stop'
    else:
        session, folder = data.get('session_id'), data.get('cwd')
        tool = str(data.get('tool_name') or '')
        model_stopped = True
    return Event(cli, kind, session, folder, tool, tool in EDIT_TOOLS.get(cli, ()),
                 bool(data.get('stop_hook_active')), model_stopped)


def render(cli, kind, reply):
    """The JSON a CLI expects for `reply`, or None to print nothing."""
    if isinstance(reply, Continue):
        if cli == 'claude':
            return {'hookSpecificOutput': {'hookEventName': 'Stop', 'additionalContext': reply.text}}
        if cli == 'codex':
            return {'decision': 'block', 'reason': reply.text}
        if cli == 'agy':
            return {'decision': 'continue', 'reason': reply.text}
        return {'continue': reply.text}
    # Nothing to say: Codex wants JSON from Stop, Antigravity a decision or an object.
    if cli == 'codex' and kind == 'stop':
        return {}
    if cli == 'agy':
        return {'decision': 'stop'} if kind == 'stop' else {}
    return None


class Store:
    """A feature's state: one JSON object per session under $<env>, else `default`."""

    def __init__(self, env, default, keep):
        self.env, self.default, self.keep = env, default, keep

    @property
    def folder(self):
        return Path(os.environ.get(self.env) or self.default).expanduser()

    def file(self, session):
        return self.folder / (re.sub(r'[^A-Za-z0-9_.-]', '_', str(session))[:128] + '.json')

    def load(self, session):
        try:
            state = json.loads(self.file(session).read_text())
        except (OSError, ValueError):
            return {}
        return state if isinstance(state, dict) else {}

    def save(self, session, state):
        path = self.file(session)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as handle:
            json.dump(state, handle, ensure_ascii=False, sort_keys=True)
        os.chmod(handle.name, 0o600)
        os.replace(handle.name, path)

    def prune(self, now):
        for path in self.folder.glob('*.json'):
            try:
                if now - path.stat().st_mtime > self.keep:
                    path.unlink()
            except OSError:
                pass


def call(cli, kind, data, handle, store, now=None):
    """The rendered reply to one hook call. handle(event, state) reads and changes the session's
    state, saved after it; a call without a session id gets the quiet reply."""
    event = read(cli, kind, data)
    if not event.session:
        return render(cli, kind, None)
    store.prune(time.time() if now is None else now)
    state = store.load(event.session)
    if kind == 'stop' and cli in UNFLAGGED_CONTINUATION and state.pop(CONTINUED, False):
        event = replace(event, continuation=True)
    reply = handle(event, state)
    if isinstance(reply, Continue) and cli in UNFLAGGED_CONTINUATION:
        state[CONTINUED] = True
    store.save(event.session, state)
    return render(cli, kind, reply)


def serve(cli, kind, answer, stdin=None, stdout=None):
    """Run answer(data) on the JSON from stdin and print its reply. Always returns 0, and any
    failure prints only the quiet reply: a broken hook must not block or steer a session."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        out = answer(json.loads(stdin.read() or '{}'))
    except Exception:  # fail open
        out = render(cli, kind, None)
    if out is not None:
        stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
    return 0


def native_events(cli, wants):
    """((native event, kind, matcher), ...) in `cli`'s hook file for a feature's wants, e.g.
    (('tool', 'edit'), ('stop', None)); () for a CLI without a hook file."""
    if cli not in HOOK_FILE_CLIS:
        return ()
    return tuple((NATIVE[kind], kind, EDIT_MATCHERS[cli] if tools == 'edit' else None) for kind, tools in wants)
