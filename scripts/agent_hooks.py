"""agent_hooks: one interface over the hook formats of Claude Code, Codex, Antigravity and Pi.

A feature (worktree-guard; daily-log's nudge before it) sees a plain Event and answers with a plain reply; this
module reads each CLI's hook input into that Event, writes the reply back in the CLI's own
shape, keeps the feature's state per session, and tells the installer which native events and
matchers a feature needs. Everything that differs between the CLIs lives here.

  call(cli, kind, data, handle, store)   one hook call: handle(event, state) -> a reply or None
  serve(cli, kind, answer)               a call on stdin/stdout; exits 0 and fails open
  Store(env, default, keep)              one JSON file per session, pruned after `keep` seconds
  native_events(cli, wants)              ((native event, kind, matcher), ...) for the installer

Kinds: 'pre' (before a tool call), 'tool' (after one), 'stop' (a turn ends), 'end' (the
session ends), 'prompt' (the user submits one; never answered, and Antigravity has no such
event). Kinds only some CLIs have (ONLY_IN), never answered: 'error' (a turn ends on an API
error), 'permission' (a permission dialog is about to open), 'form' (an MCP server asks for
input), 'start' (a session starts or resumes), 'interrupt' (the user stops a turn).
An Event names what the tool does (action: edit, shell, read, ask or other) and carries its
input; a 'prompt' Event carries the prompt and the transcript's path, a 'stop' Event the
agent's last message and its background work. Replies: Continue (a 'stop'), Note, Deny and
Rewrite (a 'pre').
Pi has no hook file: a feature's Pi extension sends {session_id, cwd, tool_name, tool_input,
pid} (a prompt: {session_id, cwd, prompt, source, transcript_path}; a stop: {...,
last_assistant_message, outcome}; an end: {..., reason}) and applies {continue}, {block,
reason}, {input, note} or {note}. Features import this file from the repo's scripts/ folder.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

CLIS = ('claude', 'codex', 'agy', 'pi')
HOOK_FILE_CLIS = ('claude', 'codex', 'agy')  # Pi loads an extension instead
TOOLS = {  # what each CLI's tools do; Codex reads through its shell; 'ask' tools open a dialog for the user
    'claude': {'edit': {'Edit', 'Write', 'NotebookEdit'}, 'shell': {'Bash'}, 'read': {'Read', 'Glob', 'Grep'},
               'ask': {'AskUserQuestion', 'ExitPlanMode'}},
    'codex': {'edit': {'apply_patch', 'Edit', 'Write'}, 'shell': {'Bash'}, 'read': set()},
    'agy': {'edit': {'write_to_file', 'replace_file_content', 'multi_replace_file_content'},
            'shell': {'run_command'}, 'read': {'view_file', 'list_dir', 'find_by_name', 'grep_search'}},
    'pi': {'edit': {'edit', 'write'}, 'shell': {'bash'}, 'read': {'read', 'grep', 'find', 'ls'}},
}
EDIT_TOOLS = {cli: tools['edit'] for cli, tools in TOOLS.items()}
# The installer's matchers per action; Codex matches apply_patch as Edit or Write.
MATCHERS = {
    'claude': {'edit': 'Edit|Write|NotebookEdit', 'shell': 'Bash', 'read': 'Read|Glob|Grep',
               'ask': 'AskUserQuestion|ExitPlanMode'},
    'codex': {'edit': 'Edit|Write', 'shell': 'Bash'},
    'agy': {'edit': 'write_to_file|replace_file_content|multi_replace_file_content', 'shell': 'run_command',
            'read': 'view_file|list_dir|find_by_name|grep_search'},
}
NATIVE = {'pre': 'PreToolUse', 'tool': 'PostToolUse', 'stop': 'Stop', 'end': 'SessionEnd',
          'prompt': 'UserPromptSubmit', 'create': 'WorktreeCreate', 'remove': 'WorktreeRemove',
          'error': 'StopFailure', 'permission': 'PermissionRequest', 'form': 'Elicitation',
          'start': 'SessionStart', 'interrupt': 'Interrupt'}
NO_SESSION_END = ('agy',)  # Antigravity's hooks have no end-of-session event
NO_PROMPT = ('agy',)  # nor one for a submitted prompt (PreInvocation carries no prompt text)
CLAUDE_ONLY = ('create', 'remove')  # worktree events: only Claude Code lets a hook make and remove worktrees
# Kinds only some hook-file CLIs have. Codex runs SessionStart only inside a session's first turn,
# too late to report a resumed session, so 'start' is Claude Code's here.
ONLY_IN = {'create': ('claude',), 'remove': ('claude',), 'error': ('claude',), 'form': ('claude',),
           'start': ('claude',), 'permission': ('claude', 'codex'), 'interrupt': ('codex',)}
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
    action: str = 'other'        # what the tool does: edit, shell, read or other
    tool_input: dict = field(default_factory=dict)  # the tool's arguments, in the CLI's own names
    pid: int | None = None       # the CLI's process, when its extension says (Pi)
    model: str = ''              # the model, when the CLI says
    name: str = ''               # the new worktree's name (Claude's 'create' event)
    path: str = ''               # the worktree being removed (Claude's 'remove' event)
    prompt: str = ''             # what the user submitted (a 'prompt' event)
    transcript: str = ''         # the session's transcript file, when the CLI says
    subagent: bool = False       # the hook fired inside a subagent or an in-process teammate (Claude Code)
    last_message: str = ''       # the agent's final message of the turn (a 'stop' event)
    tasks: tuple = ()            # the types of the background tasks still in flight at a stop (Claude Code)
    crons: int = 0               # the session's scheduled wake-ups at a stop (Claude Code)
    error: str = ''              # the API error that ended the turn (an 'error' event)
    source: str = ''             # where a prompt came from (Pi), or why a session started ('start')
    reason: str = ''             # why the session ends (an 'end' event)
    outcome: str = ''            # how the run ended: completed, aborted or error (Pi's 'stop')


@dataclass(frozen=True)
class Continue:
    """Keep the turn going, with `text` as the model's next instruction (a 'stop' reply)."""
    text: str


@dataclass(frozen=True)
class Note:
    """Let the tool call run and tell the model `text` (a 'pre' reply)."""
    text: str


@dataclass(frozen=True)
class Deny:
    """Block the tool call; the model sees `reason` (a 'pre' reply)."""
    reason: str


@dataclass(frozen=True)
class Rewrite:
    """Run the tool call with `tool_input` instead, and tell the model `note` (a 'pre' reply)."""
    tool_input: dict
    note: str = ''


@dataclass(frozen=True)
class Shown:
    """A 'pre' reply that also tells the person something: `reply` (None for nothing else) is rendered
    as usual. Claude Code and Codex show `text` as a warning; Pi's extension sets its footer status to
    `status` (None clears it); Antigravity has no such channel and gets `reply` only."""
    reply: object
    text: str
    status: str | None = None


def action_of(cli, tool):
    for action, names in TOOLS.get(cli, {}).items():
        if tool in names:
            return action
    return 'other'


def text(value):
    return value if isinstance(value, str) else ''


def read(cli, kind, data):
    """The Event in one CLI's hook input."""
    data = data if isinstance(data, dict) else {}
    if cli == 'agy':
        paths = data.get('workspacePaths') or []
        call = data.get('toolCall') if isinstance(data.get('toolCall'), dict) else {}
        session, folder = data.get('conversationId'), (paths[0] if paths else None)
        tool, tool_input = str(call.get('name') or ''), call.get('args')
        model_stopped = data.get('terminationReason', 'model_stop') == 'model_stop'
    else:
        session, folder = data.get('session_id'), data.get('cwd')
        tool, tool_input = str(data.get('tool_name') or ''), data.get('tool_input')
        model_stopped = True
    pid, model = data.get('pid'), data.get('model') or data.get('modelName')
    action = action_of(cli, tool)
    tasks, crons = data.get('background_tasks'), data.get('session_crons')
    return Event(cli, kind, session, folder, tool=tool, edit=action == 'edit',
                 continuation=bool(data.get('stop_hook_active')), model_stopped=model_stopped, action=action,
                 tool_input=tool_input if isinstance(tool_input, dict) else {},
                 pid=pid if isinstance(pid, int) and not isinstance(pid, bool) else None,
                 model=model if isinstance(model, str) else '', name=text(data.get('name')),
                 path=text(data.get('worktree_path')), prompt=text(data.get('prompt')),
                 transcript=text(data.get('transcript_path')), subagent=bool(data.get('agent_id')),
                 last_message=text(data.get('last_assistant_message')),
                 tasks=tuple(text(task.get('type')) for task in tasks if isinstance(task, dict))
                 if isinstance(tasks, list) else (),
                 crons=len(crons) if isinstance(crons, list) else 0, error=text(data.get('error')),
                 source=text(data.get('source')), reason=text(data.get('reason')), outcome=text(data.get('outcome')))


def render_pre(cli, reply):
    """A 'pre' reply: Claude Code and Codex share hookSpecificOutput; Antigravity always wants
    a decision; Pi's extension applies block, input, note and status itself."""
    if isinstance(reply, Shown):
        out = render_pre(cli, reply.reply)
        if cli in ('claude', 'codex'):  # only systemMessage: PreToolUse rejects continue, stopReason, suppressOutput
            return {**(out or {}), 'systemMessage': reply.text}
        return {**(out or {}), 'status': reply.status} if cli == 'pi' else out
    if cli in ('claude', 'codex'):
        if reply is None:
            return None
        out = {'hookEventName': 'PreToolUse'}
        if isinstance(reply, Deny):
            out.update(permissionDecision='deny', permissionDecisionReason=reply.reason)
        elif isinstance(reply, Rewrite):
            out.update(permissionDecision='allow', updatedInput=reply.tool_input)
        text = reply.text if isinstance(reply, Note) else getattr(reply, 'note', '')
        if text:
            out['additionalContext'] = text
        return {'hookSpecificOutput': out}
    if cli == 'agy':
        if isinstance(reply, Deny):
            return {'decision': 'deny', 'reason': reply.reason}
        out = {'decision': 'allow'}
        if isinstance(reply, Rewrite):
            out['overwrite'] = reply.tool_input
        text = reply.text if isinstance(reply, Note) else getattr(reply, 'note', '')
        return {**out, 'reason': text} if text else out
    if isinstance(reply, Deny):
        return {'block': True, 'reason': reply.reason}
    if isinstance(reply, Rewrite):
        return {'input': reply.tool_input, **({'note': reply.note} if reply.note else {})}
    if isinstance(reply, Note):
        return {'note': reply.text}
    return None


def render(cli, kind, reply):
    """The JSON a CLI expects for `reply`, or None to print nothing."""
    if kind == 'pre':
        return render_pre(cli, reply)
    if kind in ('end', 'prompt'):  # a prompt hook's stdout would reach the model as context
        return None
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

    def __init__(self, env, default, keep, sub=''):
        self.env, self.default, self.keep, self.sub = env, default, keep, sub

    @property
    def folder(self):
        return Path(os.environ.get(self.env) or self.default).expanduser() / self.sub

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


def serve(cli, kind, answer, stdin=None, stdout=None, on_error=None):
    """Run answer(data) on the JSON from stdin and print its reply. Always returns 0, and a
    failure never blocks: it prints the quiet reply, or the reply on_error(error) gives (a
    Note that says protection lapsed, say)."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        out = answer(json.loads(stdin.read() or '{}'))
    except Exception as error:  # fail open
        out = render(cli, kind, on_error(error) if on_error else None)
    if out is not None:
        stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
    return 0


def native_events(cli, wants):
    """((native event, kind, matcher), ...) in `cli`'s hook file for a feature's wants, e.g.
    (('tool', 'edit'), ('stop', None)) or (('pre', ('edit', 'shell')), ('end', None)); () for a
    CLI without a hook file. An event the CLI lacks is left out."""
    if cli not in HOOK_FILE_CLIS:
        return ()
    found = []
    for kind, actions in wants:
        if ((kind == 'end' and cli in NO_SESSION_END) or (kind == 'prompt' and cli in NO_PROMPT)
                or cli not in ONLY_IN.get(kind, (cli,))):
            continue
        actions = (actions,) if isinstance(actions, str) else actions or ()
        matcher = '|'.join(MATCHERS[cli][a] for a in actions if a in MATCHERS[cli]) or None
        if actions and matcher is None:
            continue  # none of these tools in this CLI: no entry, not one for every tool
        found.append((NATIVE[kind], kind, matcher))
    return tuple(found)
