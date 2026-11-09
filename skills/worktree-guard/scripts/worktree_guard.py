#!/usr/bin/env python3
"""worktree-guard: keep agent sessions that share a checkout out of each other's changes.

  worktree-guard hook (pre|end) --cli (claude|codex|agy|pi)   JSON in; JSON or nothing out
  worktree-guard hook (create|remove) --cli claude    Claude's WorktreeCreate/Remove: path out, no JSON
  worktree-guard list   [--repo DIR]                  linked worktrees: owner, branch, merged
  worktree-guard done   DESCRIPTION [--path DIR]      a linked worktree's one-line summary
  worktree-guard rm     NAME [--force] [--repo DIR]   archive tag, then remove worktree and branch
  worktree-guard prune  [--repo DIR]                  rm every merged, clean, unowned one
  worktree-guard on|off [--repo DIR]                  switch the repo's worktree flow (people only)
  worktree-guard new    <type>/<slug> [--repo DIR]    a detached worktree from origin's default branch
  worktree-guard shipped NAME [--repo DIR]            delete a pushed worktree whose PR is open (ship runs it)
  worktree-guard release [PATH]                       clear a worktree's owner (people only)
  worktree-guard share   [PATH]                       let any session edit it (people only)

A session owns a worktree from its first edit until it ends or its process is gone. When a
second live session's first edit lands in a worktree another session owns, the guard makes a
linked worktree for it at <main worktree>/.claude/worktrees/<name>, on a new branch from the
busy worktree's last commit, and points the session there: Claude Code is told to call
EnterWorktree; Codex, Pi and Antigravity have their tool calls rewritten. An edit is a
file-edit tool or a git command that changes the working tree or the index. Subagents share
their parent's ownership. A failure never blocks an edit; it says the edit was not protected.

A repo whose flow is on (git config --local worktree-guard.flow true, set by `on`) is stricter:
an edit of a file in its main checkout is stopped, and the agent is asked to name the work with
`ai-dotfiles worktree new <type>/<slug>`. That fetches origin and makes .claude/worktrees/
<type>-<slug> detached at origin's default branch, with no local branch. The hook notes which
session is about to run it (naming/<CLI pid>.json); the command finds the note by its own pid or
an ancestor's, claims the worktree for that CLI process and records it in the session's state,
so Claude is told to call EnterWorktree and Codex, Pi and Antigravity are steered. Another
session's worktree is refused. The edited file's repo decides, wherever the session started; a
file outside git is never gated.

Codex and Pi, which have no status line that follows a steered session, hear it on their next tool
call when the session's worktree was made or deleted: Codex as a line of its own (systemMessage), Pi
as the work name for its footer status (or none).

Claude Code's own worktrees (`claude -w`, EnterWorktree with a name, subagent isolation) go through
its WorktreeCreate and WorktreeRemove hooks. In a repo that is on they are made in the same shape
as `new` makes them; in any other repo exactly as Claude makes them (.claude/worktrees/<name> on
branch worktree-<name> from HEAD), so the global hook changes nothing there.

State: $WORKTREE_GUARD_STATE, else ~/.local/state/ai-dotfiles/worktree-guard/ (claims/ per
worktree, sessions/ per session). The CLIs' hook formats live in the repo's
scripts/agent_hooks.py. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import replace
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL.parents[1] / 'scripts'))
import agent_hooks  # noqa: E402  (the CLIs' hook formats, in the repo's scripts folder)
from agent_hooks import Deny, Note, Rewrite, Shown  # noqa: E402
sys.path.insert(0, str(SKILL.parent / 'git' / 'scripts'))
import git_run  # noqa: E402  (the git bundle's runner)
git_run.use('archive-tag')
import archive_tag  # noqa: E402  (the one archive format, shared with approve)

ENV = 'WORKTREE_GUARD_STATE'
DEFAULT_STATE = '~/.local/state/ai-dotfiles/worktree-guard'
KEEP_SECONDS = 30 * 24 * 3600
SESSIONS = agent_hooks.Store(ENV, DEFAULT_STATE, KEEP_SECONDS, 'sessions')
LINKED = Path('.claude/worktrees')
BRANCH_PREFIX = 'agent/'
FLOW_KEY = 'worktree-guard.flow'  # local git config: `true` when the repo works through worktrees
GIT_CHANGES = frozenset(
    'add am apply checkout cherry-pick clean commit merge mv pull rebase reset restore revert rm stash switch'.split())
GIT_OPTIONS_WITH_VALUE = frozenset(('-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env'))
WRAPPERS = frozenset(('sh', 'bash', 'zsh', 'dash', 'fish', 'ksh', 'env', 'timeout', 'gtimeout', 'nice', 'nohup'))
WORK_NAME = re.compile(r'[a-z][a-z0-9]*/[a-z0-9][a-z0-9-]*')  # <type>/<slug>
FETCH_SECONDS = 120
HOOK_FETCH_SECONDS = 40  # Claude's create hook has 60 s in all
CLAUDE_BRANCH = 'worktree-'  # the branch Claude's own default puts a worktree on: worktree-<name>
FOLDER_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
NAMING_SECONDS = 600  # how long the hook's note of a `worktree new` call stays good
PERSON_ONLY = frozenset(('release', 'share', 'on', 'off'))  # worktree commands a person runs
HEREDOC = re.compile(r'<<-?\s*([\'"]?)(\w+)\1[^\n]*\n.*?^[ \t]*\2[ \t]*$', re.M | re.S)
SEPARATORS = frozenset(';&|()\n')
COMMAND_PREFIXES = frozenset(('sudo', 'env', 'command', 'exec', 'time', 'nohup', 'nice', 'timeout', 'gtimeout'))
SHELLS = frozenset(('sh', 'bash', 'zsh', 'dash', 'ksh'))
GUARD_NAMES = frozenset(('worktree-guard', 'worktree_guard', 'worktree-guard.py', 'worktree_guard.py'))
PATH_KEYS = {  # tool-input fields that name a file or folder
    'claude': ('file_path', 'notebook_path'),
    'pi': ('path',),
    'agy': ('TargetFile', 'AbsolutePath', 'DirectoryPath', 'SearchPath', 'SearchDirectory'),
}
PATCH_HEADER = re.compile(r'^(\*\*\* (?:Add|Update|Delete) File: |\*\*\* Move to: )(.+)$', re.M)


def state_root():
    return Path(os.environ.get(ENV) or DEFAULT_STATE).expanduser()


# --- processes ---------------------------------------------------------------------------

def process_table():
    """{pid: (parent pid, command name)} for every process."""
    run = subprocess.run(['ps', '-A', '-o', 'pid=,ppid=,comm='], capture_output=True, text=True)
    table = {}
    for line in run.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), Path(parts[2]).name if len(parts) > 2 else '')
    return table


def lineage(table, pid):
    """pid's parent, grandparent, ... up to (not including) init."""
    found = []
    while pid in table and len(found) < 64:
        pid = table[pid][0]
        if pid <= 1:
            break
        found.append(pid)
    return found


def cli_pid(table, given=None):
    """The CLI process this hook runs for: the extension says (Pi), or the first ancestor that
    is not a shell, a wrapper or Python."""
    if given:
        return given
    for pid in lineage(table, os.getpid()):
        name = table.get(pid, (0, ''))[1]
        if name not in WRAPPERS and not name.lower().startswith('python'):
            return pid
    return os.getppid()


def started(pid):
    run = subprocess.run(['ps', '-o', 'lstart=', '-p', str(pid)], capture_output=True, text=True)
    return run.stdout.strip() if run.returncode == 0 else ''


def alive(claim):
    pid = claim.get('pid')
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return not claim.get('started') or started(pid) == claim['started']


# --- git ---------------------------------------------------------------------------------

def git(cwd, *args, check=True):
    run = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True)
    if run.returncode:
        if check:
            raise RuntimeError(f'git {" ".join(args)}: {run.stderr.strip()}')
        return None
    return run.stdout.strip()


def worktree_of(path):
    """The worktree a path is in, or None outside git."""
    place = Path(path)
    while not place.exists():
        if place.parent == place:
            return None
        place = place.parent
    top = git(place if place.is_dir() else place.parent, 'rev-parse', '--show-toplevel', check=False)
    return Path(top).resolve() if top else None


def common_dir(worktree):
    return Path(git(worktree, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()


def main_of(worktree):
    common = common_dir(worktree)
    return common.parent if common.name == '.git' else worktree


def flow_on(worktree):
    """Whether the repo of `worktree` works through worktrees (`worktree on`)."""
    return git(worktree, 'config', '--local', '--bool', '--get', FLOW_KEY, check=False) == 'true'


def head_of(worktree):
    """(branch or None when detached, commit or None before the first commit)."""
    return git(worktree, 'symbolic-ref', '-q', '--short', 'HEAD', check=False) or None, \
        git(worktree, 'rev-parse', '-q', '--verify', 'HEAD', check=False) or None


def changes_in(worktree):
    out = git(worktree, 'status', '--porcelain', check=False)
    return len(out.splitlines()) if out else 0


def default_ref(worktree):
    ref = git(worktree, 'symbolic-ref', '-q', '--short', 'refs/remotes/origin/HEAD', check=False)
    if ref:
        return ref
    for name in ('main', 'master'):
        if git(worktree, 'rev-parse', '-q', '--verify', f'refs/heads/{name}', check=False):
            return name
    return None


def exclude(main):
    """Keep linked worktrees out of the main worktree's `git status` (local, never committed)."""
    path = common_dir(main) / 'info' / 'exclude'
    line = '/' + LINKED.as_posix() + '/'
    text = path.read_text() if path.exists() else ''
    if line not in text.splitlines():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + ('' if not text or text.endswith('\n') else '\n') + line + '\n')


def copy_included(source, target):
    """Copy the gitignored files `.worktreeinclude` lists (gitignore syntax), as Claude Code does."""
    patterns = source / '.worktreeinclude'
    if not patterns.is_file():
        return []
    listed = git(source, 'ls-files', '--others', '--ignored', f'--exclude-from={patterns}', check=False)
    if not listed:
        return []
    run = subprocess.run(['git', '-C', str(source), 'check-ignore', '--stdin'], input=listed,
                         capture_output=True, text=True)
    copied = []
    for name in run.stdout.splitlines():
        if (source / name).is_file() and not (target / name).exists():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target / name)
            copied.append(name)
    return copied


# --- what a tool call changes ------------------------------------------------------------

def git_changes(command):
    """The folders ('' for the current one) of the git commands in a shell command line that
    change a working tree or the index. A leading `cd <dir>` joined by && or ; moves the base
    for the commands after it, so `cd repo && git commit` names repo, not the current folder; a
    pipe or subshell boundary forgets it. `-C` and an absolute `cd` resolve on top of that base."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    found, i, cwd = [], 0, ''
    while i < len(tokens):
        token = tokens[i]
        if token in ('|', '|&', '(', ')'):  # a pipe or subshell runs elsewhere: forget the cd
            cwd, i = '', i + 1
            continue
        name = Path(token).name
        if name == 'cd' and i + 1 < len(tokens) and not tokens[i + 1].startswith('-'):
            arg = tokens[i + 1]
            cwd = arg if os.path.isabs(arg) else os.path.join(cwd, arg)
            i += 2
            continue
        if name != 'git':
            i += 1
            continue
        j, where = i + 1, ''
        while j < len(tokens) and tokens[j].startswith('-'):
            if tokens[j] in GIT_OPTIONS_WITH_VALUE:
                if tokens[j] == '-C' and j + 1 < len(tokens):
                    where = os.path.join(where, tokens[j + 1])
                j += 2
            else:
                j += 1
        sub = tokens[j] if j < len(tokens) else ''
        reading = sub == 'stash' and j + 1 < len(tokens) and tokens[j + 1] in ('list', 'show')
        if sub in GIT_CHANGES and not reading:
            base = where if os.path.isabs(where) else os.path.join(cwd, where)
            found.append(os.path.normpath(base) if base else '')
        i = j + 1
    return found


def guard_calls(command):
    """[(verb, arguments)] for each worktree command (`ai-dotfiles worktree <verb> ...`, or the
    guard script with a verb) a shell command line runs as a command: first on the line or after
    `&&`, `;`, `|`, a newline or a parenthesis, behind `VAR=x`, `sudo`, `env`..., or inside
    `sh -c '...'`. The same words in a quote, a heredoc, a comment or an argument do not count.
    The arguments run to the end of the line, separators included."""
    try:
        lexer = shlex.shlex(HEREDOC.sub('', command), posix=True, punctuation_chars=';()<>|&\n')
        lexer.whitespace_split, lexer.whitespace = True, ' \t\r'
        tokens = list(lexer)
    except ValueError:
        return []
    found, start = [], True
    for i, token in enumerate(tokens):
        if set(token) <= SEPARATORS:
            start = True
            continue
        if not start:
            continue
        name, rest = Path(token).name, tokens[i + 1:]
        if '=' in token.split('/')[0] or name in COMMAND_PREFIXES or name.startswith('python'):
            continue  # VAR=x, sudo, env ...: the command is the next word
        start = False
        if name == 'ai-dotfiles':
            if rest[:1] == ['worktree'] and rest[1:2]:
                found.append((rest[1], rest[2:]))
        elif name in GUARD_NAMES:
            if rest[:1]:
                found.append((rest[0], rest[1:]))
        elif name in SHELLS:
            flag = next((n for n, t in enumerate(rest) if re.fullmatch(r'-\w*c', t)), None)
            if flag is not None and flag + 1 < len(rest):
                found += guard_calls(rest[flag + 1])
    return found


def person_only(command):
    """Whether a shell command line runs a person-only worktree command (`on`, `off`, `release`,
    `share`)."""
    return any(verb in PERSON_ONLY for verb, _ in guard_calls(command))


def new_names(command):
    """The work names a shell command line passes to `worktree new`."""
    names = []
    for verb, args in guard_calls(command):
        skip = False
        for arg in args if verb == 'new' else ():
            if set(arg) <= SEPARATORS:
                break
            if skip or arg.startswith('-'):
                skip = arg == '--repo'
                continue
            names.append(arg)
            break
    return names


def command_of(event):
    key = 'CommandLine' if event.cli == 'agy' else 'command'
    value = event.tool_input.get(key)
    return value if isinstance(value, str) else ''


def shell_folder(event):
    cwd = event.tool_input.get('Cwd') if event.cli == 'agy' else None
    return cwd if isinstance(cwd, str) and cwd else (event.folder or os.getcwd())


def patch_paths(patch):
    return [match.group(2).strip() for match in PATCH_HEADER.finditer(patch)]


def targets(event):
    """Absolute paths whose worktrees this call changes."""
    folder = event.folder or os.getcwd()
    if event.action == 'edit':
        if event.cli == 'codex':
            names = patch_paths(command_of(event))
        else:
            names = [event.tool_input.get(key) for key in PATH_KEYS.get(event.cli, ())]
        return [Path(os.path.normpath(os.path.join(folder, name))) for name in names if isinstance(name, str) and name]
    if event.action == 'shell':
        here = shell_folder(event)
        return [Path(os.path.normpath(os.path.join(here, where))) for where in git_changes(command_of(event))]
    return []


# --- steering a moved session -----------------------------------------------------------

def into(path, moved):
    """`path` (absolute) inside the busy worktree, as the same path in the linked one; else None.
    Symlinks are resolved first: git names worktrees by their real paths (/private/var on macOS)."""
    busy, linked = Path(moved['busy']), Path(moved['linked'])
    try:
        rest = Path(os.path.realpath(path)).relative_to(busy)
    except ValueError:
        return None
    if rest.parts[:2] == LINKED.parts:
        return None
    return linked / rest


def aliases(moved, folder):
    """The busy worktree's path as git gives it, and as the session's folder spells it when a
    symlink stands in between."""
    busy, names = moved['busy'], [moved['busy']]
    real = os.path.realpath(folder) if folder else ''
    if folder and (real == busy or real.startswith(busy + '/')):
        rest = real[len(busy):]
        spelled = folder.rstrip('/')
        if spelled.endswith(rest) and spelled[:len(spelled) - len(rest)] not in names:
            names.append(spelled[:len(spelled) - len(rest)])
    return names


def steer_text(text, moved, folder=None):
    """Absolute busy-worktree paths in a command line, pointed at the linked worktree."""
    linked = moved['linked']
    for busy in aliases(moved, folder):
        text = re.sub(re.escape(busy) + r'(?![\w.-])(?!/' + re.escape(LINKED.as_posix()) + r'/)',
                      lambda _: linked, text)
    return text


def steer(event, moved):
    """The tool input with the busy worktree swapped for the linked one, or None if unchanged."""
    folder = event.folder or os.getcwd()
    data = dict(event.tool_input)
    if event.action == 'shell':
        key = 'CommandLine' if event.cli == 'agy' else 'command'
        command = command_of(event)
        steered = steer_text(command, moved, event.folder)
        here = into(os.path.normpath(shell_folder(event)), moved)
        if event.cli == 'agy':
            if here:
                data['Cwd'] = str(here)
            data[key] = steered
        elif here:
            data[key] = f'cd {shlex.quote(str(here))} && {steered}'
        else:
            data[key] = steered
    elif event.cli == 'codex' and event.action == 'edit':
        def header(match):
            target = into(os.path.normpath(os.path.join(folder, match.group(2).strip())), moved)
            return match.group(1) + (os.path.relpath(target, folder) if target else match.group(2))
        data['command'] = PATCH_HEADER.sub(header, command_of(event))
    else:
        for key in PATH_KEYS.get(event.cli, ()):
            if isinstance(data.get(key), str) and data[key]:
                target = into(os.path.normpath(os.path.join(folder, data[key])), moved)
                if target:
                    data[key] = str(target)
    return data if data != event.tool_input else None


# --- claims ------------------------------------------------------------------------------

def claim_file(worktree):
    return state_root() / 'claims' / (hashlib.sha1(str(worktree).encode()).hexdigest()[:20] + '.json')


def read_claim(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_claim(path, claim):
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as handle:
        json.dump(claim, handle, sort_keys=True)
    os.chmod(handle.name, 0o600)
    os.replace(handle.name, path)


@contextlib.contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path.with_suffix('.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def take(worktree, me, table):
    """(verdict, claim, previous owner): 'new' (now ours; previous is a dead owner, if any),
    'mine' (ours already, or our parent's), 'shared', or 'busy' (another live session's)."""
    path = claim_file(worktree)
    with locked(path):
        claim = read_claim(path)
        if claim is not None:
            if claim.get('session') == me['session']:
                return 'mine', claim, None
            if claim.get('shared'):
                return 'shared', claim, None
            if claim.get('pid') in lineage(table, os.getpid()):
                return 'mine', claim, None  # we run inside the owner: a subagent CLI it started
            if alive(claim):
                return 'busy', claim, None
        write_claim(path, {**me, 'worktree': str(worktree)})
        return 'new', me, claim


def release(session):
    folder = state_root() / 'claims'
    for path in folder.glob('*.json') if folder.is_dir() else ():
        with locked(path):
            claim = read_claim(path)
            if claim and claim.get('session') == str(session):
                path.unlink(missing_ok=True)


# --- the hook ----------------------------------------------------------------------------

def owner(event, table):
    pid = cli_pid(table, event.pid)
    return {'session': str(event.session), 'cli': event.cli, 'pid': pid, 'started': started(pid),
            'since': int(time.time())}


def who(claim):
    return f"{claim.get('cli', 'an agent')} session {str(claim.get('session', '?'))[:8]}"


def linked_name(main, event):
    base = f"{event.cli}-{re.sub(r'[^A-Za-z0-9]', '', str(event.session))[:8] or 'session'}"
    name, n = base, 1
    while (main / LINKED / name).exists() or git(main, 'rev-parse', '-q', '--verify',
                                                   f'refs/heads/{BRANCH_PREFIX}{name}', check=False):
        n += 1
        name = f'{base}-{n}'
    return name


def moved_text(event, moved, claim):
    first = (f"worktree-guard: {moved['busy']} is busy: {who(claim)} is editing it. To keep your changes "
             f"apart, this session works in a linked worktree: {moved['linked']} (branch {moved['branch']}, "
             f"from {moved['from']} at {moved['base'][:7]}).")
    how = (f" Call EnterWorktree with path \"{moved['linked']}\", then redo this change there."
           if event.cli == 'claude' else
           " Your tool calls are moved there automatically; name files by their paths there.")
    fresh = (" It starts from the last commit, without the other session's uncommitted changes: re-read "
             "files before you edit them.")
    unrelated = (f" If your task is unrelated to {moved['from']}, start from {moved['default']} before any "
                 f"edit: git -C {shlex.quote(moved['linked'])} reset --hard {moved['default']}."
                 if moved.get('default') else '')
    done = (f" When done: commit on {moved['branch']}, run ai-dotfiles worktree done \"<one-line description>\","
            f" and report: git merge {moved['branch']} (in {moved['busy']}), then ai-dotfiles worktree rm "
            f"{moved['name']}.")
    return first + how + fresh + unrelated + done


def make_worktree(main, name, base, branch, source, owner=None, table=None, meta=None):
    """The one path that makes a linked worktree: `main/.claude/worktrees/<name>` at commit `base`,
    on a new `branch` (None: detached), kept out of `git status`, with the gitignored files
    `.worktreeinclude` lists copied from `source`, its sidecar written and, given an `owner`
    (claim dict) and process `table`, claimed for that owner. Returns the worktree's path."""
    linked = main / LINKED / name
    git(main, 'worktree', 'add', '-q', *(('-b', branch) if branch else ('--detach',)), str(linked), base)
    exclude(main)
    copy_included(source, linked)
    write_meta(main, name, {'name': name, 'branch': branch, 'base': base, **(meta or {}),
                            'created': int(time.time())})
    if owner:
        take(linked, owner, table)
    return linked


def clash(event, state, busy, claim, me, table):
    if state.get('moved'):
        return Deny(f"worktree-guard: {busy} is busy: {who(claim)} is editing it. This session works in "
                    f"{state['moved']['linked']}; make this change there.")
    main = main_of(busy)
    branch, base = head_of(busy)
    if not base:
        return Note(f'worktree-guard: {busy} is busy ({who(claim)}) but has no commit to start a linked '
                    'worktree from; this edit was not protected.')
    name = linked_name(main, event)
    linked = make_worktree(main, name, base, BRANCH_PREFIX + name, source=busy, owner=me, table=table,
                           meta={'from': branch or base[:12], 'busy': str(busy), 'cli': event.cli,
                                 'session': str(event.session), 'model': event.model})
    moved = {'busy': str(busy), 'linked': str(linked), 'name': name, 'branch': BRANCH_PREFIX + name,
             'from': branch or base[:12], 'base': base, 'default': default_ref(busy),
             'owner': {k: claim.get(k) for k in ('cli', 'session')}}
    state['moved'] = moved
    text = moved_text(event, moved, claim)
    if event.cli == 'claude':
        return Deny(text)
    steered = steer(event, moved)
    return Rewrite(steered, text) if steered is not None else Deny(text)


def leftovers(worktree, previous, state):
    warned = state.setdefault('warned', [])
    count = changes_in(worktree)
    if not count or str(worktree) in warned:
        return ''
    warned.append(str(worktree))
    last = f' (last owner: {who(previous)}, no longer running)' if previous else ''
    return (f'worktree-guard: {worktree} already had {count} uncommitted change(s) when this session '
            f'started editing it{last}. Check git status; keep them out of your commits unless your task '
            'is to finish them.')


def naming_dir():
    return state_root() / 'naming'


def note_naming(event, table):
    """The hook saw a shell command that runs `worktree new <name>`. The command has no hook input
    of its own, so keep who is running it, by the CLI process, for the command to find. A note
    changes nothing for the call: it keeps its own permissions."""
    names = new_names(command_of(event)) if event.action == 'shell' else []
    if not names:
        return
    me = owner(event, table if table is not None else process_table())
    folder = naming_dir()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for old in folder.glob('*.json'):
        if time.time() - old.stat().st_mtime > 3600:
            old.unlink(missing_ok=True)
    write_claim(folder / f"{me['pid']}.json", {'owner': me, 'names': names, 'at': int(time.time())})


def naming_for(name):
    """(file, owner) of the session whose hook just saw `worktree new <name>` in the CLI process
    this command runs under, else (None, None)."""
    table = process_table()
    for pid in (os.getpid(), *lineage(table, os.getpid())):
        path = naming_dir() / f'{pid}.json'
        note = read_claim(path)
        if (note and name in note.get('names', ()) and time.time() - note.get('at', 0) <= NAMING_SECONDS
                and isinstance(note.get('owner'), dict) and alive(note['owner'])):
            return path, note['owner']
    return None, None


def stop_text(state, worktree):
    """The refusal for an edit in a main checkout of a repo that is on: name the work, or, for a
    session that already did, go where its work is."""
    moved = state.get('moved') or {}
    if moved.get('busy') == str(worktree) and Path(moved.get('linked', '')).is_dir():
        return (f"worktree-guard: {worktree} is not edited by agents; this session works in {moved['linked']}. "
                f"Make this change there (Claude Code: call EnterWorktree with path \"{moved['linked']}\" first).")
    return STOP


STOP = ('worktree-guard: this repo works through worktrees, and its main checkout is not edited by '
        'agents. Name this work: run `ai-dotfiles worktree new <type>/<slug>` (for example '
        'fix/prune-worktrees), then make this change there.')


def seen_work(state):
    """(work name, main checkout) of the worktree `worktree new` bound the session to, while it is
    there; None otherwise, and for a session a clash moved aside (it has no work name)."""
    moved = state.get('moved')
    if isinstance(moved, dict) and moved.get('work') and Path(str(moved.get('linked'))).is_dir():
        return moved['work'], moved.get('busy', '')
    return None


def tell(event, state, reply):
    """`reply` with a line for the person when the session's worktree was made or deleted since it
    was last told. Codex has no status line that follows a steered session and Pi's footer is set by
    its extension, so both hear it on their next tool call; the others show it themselves."""
    if event.kind != 'pre' or event.cli not in ('codex', 'pi'):
        return reply
    now, before = seen_work(state), state.get('shown')
    if now == (tuple(before) if before else None):
        return reply
    if now is None:
        state.pop('shown')
        text = f'worktree-guard: {before[0]} is deleted; the session is back in {before[1]}'
    else:
        state['shown'] = list(now)
        text = (f"worktree-guard: {now[0]} works in {state['moved']['linked']}; "
                'the footer may still show the main checkout')
    return Shown(reply, text, now[0] if now else None)


def decide(event, state, table=None):
    """The reply to one hook call; `state` is the session's, saved by agent_hooks.call."""
    return tell(event, state, route(event, state, table))


def route(event, state, table=None):
    """What the guard does with one hook call, before telling the person anything."""
    if event.kind == 'end':
        release(event.session)
        return None
    if event.kind != 'pre':
        return None
    if event.action == 'shell' and person_only(command_of(event)):
        return Deny('worktree-guard: release, share, on and off are for a person, run from a terminal; '
                    'ask the user to run it.')
    moved, steered = state.get('moved'), None
    if moved and event.cli != 'claude':
        steered = steer(event, moved)
        if steered is not None:
            folder = event.folder
            if event.action == 'shell' and event.cli != 'agy':  # it now starts with `cd <linked>`
                here = into(os.path.normpath(shell_folder(event)), moved)
                folder = str(here) if here else folder
            event = replace(event, tool_input=steered, folder=folder)
    paths = targets(event)
    worktrees = list(dict.fromkeys(w for w in map(worktree_of, paths) if w))
    notes = []
    note_naming(event, table)
    if worktrees:
        table = table if table is not None else process_table()
        me = owner(event, table)
        for worktree in worktrees:
            if worktree == main_of(worktree) and flow_on(worktree):
                return Deny(stop_text(state, worktree))
            verdict, claim, previous = take(worktree, me, table)
            if verdict == 'busy':
                if flow_on(worktree):  # in a repo that is on, every session has a worktree of its own
                    return Deny(f'worktree-guard: {worktree} belongs to {who(claim)}. Do not edit it; work in '
                                'your own worktree: `ai-dotfiles worktree new <type>/<slug>`.')
                return clash(event, state, worktree, claim, me, table)
            if verdict == 'new':
                notes.append(leftovers(worktree, previous, state))
    text = ' '.join(n for n in notes if n)
    if steered is not None:
        return Rewrite(steered, text)
    return Note(text) if text else None


def answer(cli, kind):
    return lambda data: agent_hooks.call(cli, kind, data, decide, SESSIONS)


def failed(error):
    return Note(f'worktree-guard failed ({error}); this edit was not protected from other sessions.')


def cmd_hook(args):
    if args.kind in agent_hooks.CLAUDE_ONLY:
        return cmd_native(args)
    return agent_hooks.serve(args.cli, args.kind, answer(args.cli, args.kind),
                             on_error=failed if args.kind == 'pre' else None)


# --- linked worktrees: metadata, listing, removal --------------------------------------

def meta_file(main, name):
    return main / LINKED / f'{name}.json'


def write_meta(main, name, meta):
    path = meta_file(main, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + '\n')


def read_meta(main, name):
    try:
        meta = json.loads(meta_file(main, name).read_text())
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def repo_main(where):
    worktree = worktree_of(Path(where or os.getcwd()).resolve())
    if not worktree:
        raise SystemExit(f'worktree-guard: not in a git repository: {where or os.getcwd()}')
    return main_of(worktree)


def linked_worktrees(main):
    """{name: metadata} of the linked worktrees this guard made in the repo."""
    folder = main / LINKED
    found = {}
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else ():
        meta = read_meta(main, path.stem)
        if meta:
            found[path.stem] = meta
    return found


def branch_of(main, name, meta):
    linked = main / LINKED / name
    current = git(linked, 'symbolic-ref', '-q', '--short', 'HEAD', check=False) if linked.is_dir() else None
    return current or meta.get('branch')


def ref_of(main, name, branch):
    """What to read the work's commits from: its branch, else (no branch) the worktree's HEAD
    commit; None when neither is there."""
    if branch:
        return branch
    linked = main / LINKED / name
    return git(linked, 'rev-parse', '-q', '--verify', 'HEAD', check=False) if linked.is_dir() else None


def label_of(meta, branch):
    return branch or f"{meta.get('work') or '?'} (no branch)"


def branch_exists(main, branch):
    return bool(branch) and git(main, 'rev-parse', '-q', '--verify', f'refs/heads/{branch}', check=False) is not None


def target_of(main, meta):
    source = meta.get('from')
    if source and git(main, 'rev-parse', '-q', '--verify', f'refs/heads/{source}', check=False):
        return source
    return default_ref(main)


def merged(main, ref, meta):
    target = target_of(main, meta)
    return bool(target) and bool(ref) and git(main, 'merge-base', '--is-ancestor', ref, target, check=False) is not None


def pushed(main, ref, branch):
    """Whether every commit of the work is on a remote: the branch's upstream has them, or (no
    branch) some remote-tracking ref does."""
    if not branch:
        return git(main, 'rev-list', '--count', ref, '--not', '--remotes', check=False) == '0'
    ahead = git(main, 'rev-list', '--count', f'{branch}@{{upstream}}..{branch}', check=False)
    return ahead == '0'


def owner_of(worktree):
    claim = read_claim(claim_file(worktree))
    return claim if claim and alive(claim) else None


def span(main, base, ref):
    """The work's commit dates, in archive-tag's words; '' for no commits of its own."""
    return archive_tag.span(base, ref, cwd=main) if ref else ''


def archive(main, name, meta, branch, ref, was_merged):
    """Tag the work's tip with archive-tag; None when it has no commits of its own. A worktree
    with no branch is tagged by its work name (`fix/x` -> `archive/x`)."""
    if not ref or (branch and not branch_exists(main, branch)):
        return None
    description = meta.get('description') or git(main, 'log', '-1', '--format=%s', ref)
    agent = ' '.join(x for x in (meta.get('cli', 'agent'), meta.get('model', '')) if x)
    extra = (f"Agent: {agent}, session {meta.get('session', '?')}; redirected from branch {meta.get('from', '?')}.",)
    return archive_tag.archive(branch or meta.get('work') or name, description, was_merged, meta.get('base', ''),
                               cwd=main, extra=extra, ref=ref)


def remove(main, name, force=False, quiet_refusal=False):
    """Archive and remove one linked worktree; (done, lines to print)."""
    meta = read_meta(main, name)
    if meta is None:
        return False, [f'worktree-guard: no linked worktree named {name} in {main}']
    linked = main / LINKED / name
    branch = branch_of(main, name, meta)
    if not linked.is_dir() and not branch_exists(main, branch):
        # A stale record: both the worktree and its branch are already gone. Nothing to archive
        # or refuse; just drop the leftover files. --force is not needed.
        meta_file(main, name).unlink(missing_ok=True)
        claim_file(linked).unlink(missing_ok=True)
        return True, [f'worktree-guard: removed {name}: worktree and branch {branch} already gone (stale record)']
    ref = ref_of(main, name, branch)
    was_merged = merged(main, ref, meta)
    problems = []
    claim = owner_of(linked) if linked.is_dir() else None
    if claim:
        problems.append(f'{who(claim)} still works there')
    count = changes_in(linked) if linked.is_dir() else 0
    if count:
        problems.append(f'{count} uncommitted change(s)')
    if not was_merged and not pushed(main, ref, branch):
        problems.append(f"{branch or meta.get('work')} is neither merged into {target_of(main, meta)} nor pushed")
    if problems and not force:
        return False, [] if quiet_refusal else [f"worktree-guard: kept {name}: {'; '.join(problems)}. "
                                               f"--force removes it anyway."]
    tag = archive(main, name, meta, branch, ref, was_merged)
    if linked.is_dir():
        git(main, 'worktree', 'remove', *(['--force'] if force else []), str(linked))
    if branch:
        git(main, 'branch', '-D', branch, check=False)
    meta_file(main, name).unlink(missing_ok=True)
    claim_file(linked).unlink(missing_ok=True)
    lines = [f"worktree-guard: removed {name}{f' and branch {branch}' if branch else ''}"
             + (f'; archived as {tag}' if tag else '; no commits of its own, no tag')]
    if tag and git(main, 'remote', 'get-url', 'origin', check=False):
        try:
            lines.append(archive_tag.push_tag(tag, cwd=main).replace(' pushed', ' pushed to origin', 1))
        except git_run.Stop as error:
            lines.append(f'could not push {tag}: {error}; run: git push origin {tag}')
    return True, lines


def shipped(main, name):
    """Delete a worktree whose work is shipped (ship has pushed it and opened the PR): (done, lines
    to print). Refused while it has uncommitted changes or a commit on no remote. The owner's
    claim goes, and the session's `moved` with it, so its next first edit starts a new task. No
    archive tag: the branch is on origin, and approve tags it at the PR's head."""
    meta = read_meta(main, name)
    if meta is None:
        return False, [f'worktree-guard: no linked worktree named {name} in {main}']
    linked = main / LINKED / name
    if linked.is_dir():
        count = changes_in(linked)
        if count:
            return False, [f'worktree-guard: kept {name}: {count} uncommitted change(s)']
        head = git(linked, 'rev-parse', '-q', '--verify', 'HEAD', check=False)
        if head and not pushed(main, head, None):
            return False, [f'worktree-guard: kept {name}: a commit of it is on no remote']
    claim = read_claim(claim_file(linked)) or {}
    if linked.is_dir():
        try:
            git(main, 'worktree', 'remove', str(linked))
        except RuntimeError as error:
            return False, [f'worktree-guard: kept {name}: {error}']
    for session in {str(s) for s in (claim.get('session'), meta.get('session')) if s}:
        state = SESSIONS.load(session)
        if (state.get('moved') or {}).get('linked') == str(linked):
            state.pop('moved')
            SESSIONS.save(session, state)
    meta_file(main, name).unlink(missing_ok=True)
    claim_file(linked).unlink(missing_ok=True)
    return True, [f"worktree-guard: removed {name} ({meta.get('work') or 'no work name'}); "
                  f'its session is back in {main}']


def cmd_list(args):
    main = repo_main(args.repo)
    found = linked_worktrees(main)
    print(f"worktree-guard: flow: {'on' if flow_on(main) else 'off'} in {main}")
    if not found:
        print(f'worktree-guard: no linked worktrees in {main}')
    for name, meta in found.items():
        linked = main / LINKED / name
        branch = branch_of(main, name, meta)
        ref = ref_of(main, name, branch)
        claim = owner_of(linked) if linked.is_dir() else None
        state = ('no commits yet' if not span(main, meta.get('base', ''), ref) else
                 'merged' if merged(main, ref, meta) else 'not merged')
        count = changes_in(linked) if linked.is_dir() else 0
        print(f"{name}  {label_of(meta, branch)}  from {meta.get('from')}  {state}"
              f"{f', {count} uncommitted' if count else ''}  owner: {who(claim) if claim else 'none'}"
              f"{'  - ' + meta['description'] if meta.get('description') else ''}")
    return 0


def cmd_done(args):
    worktree = worktree_of(Path(args.path or os.getcwd()).resolve())
    main = main_of(worktree) if worktree else None
    if not worktree or worktree.parent != main / LINKED or read_meta(main, worktree.name) is None:
        print('worktree-guard: run this inside a linked worktree that worktree-guard made', file=sys.stderr)
        return 1
    meta = read_meta(main, worktree.name)
    meta['description'] = ' '.join(args.description.split())
    write_meta(main, worktree.name, meta)
    print(f'worktree-guard: noted for {worktree.name}: {meta["description"]}')
    return 0


def cmd_rm(args):
    done, lines = remove(repo_main(args.repo), args.name, args.force)
    print('\n'.join(lines), file=sys.stdout if done else sys.stderr)
    return 0 if done else 1


def cmd_prune(args):
    main = repo_main(args.repo)
    removed = 0
    for name in linked_worktrees(main):
        done, lines = remove(main, name, quiet_refusal=True)
        removed += done
        if lines:
            print('\n'.join(lines))
    if not removed:
        print('worktree-guard: nothing to prune (every linked worktree is owned, changed or unmerged)')
    return 0


def cmd_flow(args):
    main = repo_main(args.repo)
    if args.command == 'on':
        git(main, 'config', '--local', FLOW_KEY, 'true')
    else:
        git(main, 'config', '--local', '--unset', FLOW_KEY, check=False)  # exit 5 when it was never set
    print(f"worktree-guard: flow: {args.command} in {main}")
    return 0


def fetch(main, seconds=FETCH_SECONDS):
    """(fetched, why not): `git fetch origin`, never asking for a password."""
    try:
        run = subprocess.run(['git', '-C', str(main), 'fetch', '--prune', '--quiet', 'origin'], capture_output=True,
                             text=True, timeout=seconds, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    except subprocess.TimeoutExpired:
        return False, 'timed out'
    return run.returncode == 0, run.stderr.strip().splitlines()[-1] if run.stderr.strip() else 'failed'


def start_point(main, seconds=FETCH_SECONDS):
    """(ref, notes): where new work starts: origin's default branch after a fetch, else the last
    one known here, else the local default branch; None when the repo has no default at all."""
    notes = []
    if git(main, 'remote', 'get-url', 'origin', check=False):
        fetched, why = fetch(main, seconds)
        if not fetched:
            notes.append(f'could not fetch origin ({why}); starting from the last origin state known here')
        head = git(main, 'symbolic-ref', '-q', '--short', 'refs/remotes/origin/HEAD', check=False)
        for ref in (head, 'origin/main', 'origin/master'):
            if ref and git(main, 'rev-parse', '-q', '--verify', f'refs/remotes/{ref}', check=False):
                return ref, notes
    ref = default_ref(main)
    if ref:
        notes.append(f'no origin default branch here; starting from the local {ref}')
    return ref, notes


def taken(main, name, folder):
    """Why `name` cannot be used, or ''. Run after the fetch: origin's branches are then current."""
    if (main / LINKED / folder).exists() or meta_file(main, folder).exists():
        return f'{LINKED.as_posix()}/{folder} is taken'
    if git(main, 'rev-parse', '-q', '--verify', f'refs/heads/{name}', check=False):
        return 'a local branch of that name exists'
    if git(main, 'rev-parse', '-q', '--verify', f'refs/remotes/origin/{name}', check=False):
        return 'origin already has a branch of that name'
    return ''


def cmd_new(args):
    name = args.name
    if not WORK_NAME.fullmatch(name):
        print(f'worktree-guard: a work name looks like <type>/<slug> (lowercase letters, digits and hyphens), '
              f'for example fix/prune-worktrees; got {name!r}', file=sys.stderr)
        return 1
    main, folder = repo_main(args.repo), name.replace('/', '-')
    ref, notes = start_point(main)
    why = taken(main, name, folder) if ref else 'the repo has no default branch to start from'
    if why:
        print(f'worktree-guard: cannot start {name}: {why}.' + ('' if not ref else ' Pick another name.'),
              file=sys.stderr)
        return 1
    base = git(main, 'rev-parse', f'{ref}^{{commit}}')
    note, me = naming_for(name)
    try:
        linked = make_worktree(main, folder, base, None, source=main, owner=me, table=process_table() if me else None,
                               meta={'work': name, 'from': ref, 'busy': str(main),
                                     **({'cli': me['cli'], 'session': me['session']} if me else {})})
    except RuntimeError as error:
        print(f'worktree-guard: cannot start {name}: {error}', file=sys.stderr)
        return 1
    for line in notes:
        print(f'worktree-guard: {line}')
    head = f'worktree-guard: {name} starts in {linked} (from {ref} at {base[:7]}, no branch).'
    if not me:
        print(f'{head} Make every change there. Claude Code: call EnterWorktree with path "{linked}"; other CLIs: '
              f'name files by their paths under {linked}.')
        return 0
    moved = {'busy': str(main), 'linked': str(linked), 'name': folder, 'work': name, 'branch': None,
             'from': ref, 'base': base, 'default': ref, 'owner': None}
    state = SESSIONS.load(me['session'])
    SESSIONS.save(me['session'], {**state, 'moved': moved})
    note.unlink(missing_ok=True)
    how = (f'Call EnterWorktree with path "{linked}", then make every change there.' if me['cli'] == 'claude' else
           f'Your tool calls that name files in {main} are moved there automatically; name files by their paths '
           'there.')
    print(f'{head} This session owns it. {how}')
    return 0


def cmd_shipped(args):
    done, lines = shipped(repo_main(args.repo), args.name)
    print('\n'.join(lines), file=sys.stdout if done else sys.stderr)
    return 0 if done else 1


# --- Claude's own worktrees: the WorktreeCreate and WorktreeRemove hooks ---------------------

def folder_of(name):
    """The folder Claude's worktree `name` becomes under .claude/worktrees/, or '' when it is not
    a plain name (nothing that climbs out of the folder or reads as an option)."""
    folder = name.replace('/', '-')
    return folder if FOLDER_NAME.fullmatch(folder) and '..' not in folder else ''


def registered(main, folder):
    """Whether `folder` is a worktree of the repo."""
    listed = git(main, 'worktree', 'list', '--porcelain', check=False) or ''
    return any(line.startswith('worktree ') and Path(line[9:]).resolve() == folder.resolve()
               for line in listed.splitlines())


def native_create(event):
    """The path of the worktree Claude asked for. In a repo whose flow is on, our shape: no branch,
    from freshly fetched origin's default branch, claimed for the session. In any other repo,
    Claude's own default, so the hook changes nothing there: a new branch worktree-<name> from the
    session's HEAD. Both under .claude/worktrees/, with `.worktreeinclude` copied in."""
    folder = folder_of(event.name)
    if not folder:
        raise ValueError(f'{event.name!r} is not a name to make a worktree folder from')
    where = worktree_of(event.folder or os.getcwd())
    if not where:
        raise ValueError(f'{event.folder or os.getcwd()} is not in a git repository')
    main = main_of(where)
    linked = main / LINKED / folder
    if linked.exists():
        if registered(main, linked):
            return linked  # asked for again: the same worktree, as it is
        raise ValueError(f'{LINKED.as_posix()}/{folder} is taken')
    if not flow_on(main):
        base = git(where, 'rev-parse', '-q', '--verify', 'HEAD', check=False)
        if not base:
            raise ValueError(f'{where} has no commit to start a worktree from')
        git(main, 'worktree', 'add', '-q', '-b', CLAUDE_BRANCH + folder, str(linked), base)
        copy_included(main, linked)
        return linked
    ref, notes = start_point(main, HOOK_FETCH_SECONDS)
    why = taken(main, folder, folder) if ref else 'the repo has no default branch to start from'
    if why:
        raise ValueError(f'cannot start {event.name}: {why}')
    for line in notes:
        print(f'worktree-guard: {line}', file=sys.stderr)
    table = process_table() if event.session else None
    return make_worktree(main, folder, git(main, 'rev-parse', f'{ref}^{{commit}}'), None, source=main,
                         owner=owner(event, table) if table else None, table=table,
                         meta={'work': event.name, 'from': ref, 'busy': str(main), 'cli': event.cli,
                               'session': str(event.session)})


def native_remove(event):
    """Delete the worktree Claude is removing: ours with its record and claim (commits it made are
    kept under an archive tag), else one of Claude's default shape with its worktree-<name> branch.
    Claude has asked or checked already, so uncommitted changes go. Anything else is left alone."""
    path = Path(event.path) if event.path else None
    where = worktree_of(path) if path and path.is_dir() else None
    if not where or where != path.resolve():
        return  # gone already, or not a worktree's top folder
    main = main_of(where)
    if where == main:
        raise ValueError(f'{where} is the main checkout, not a worktree to remove')
    if where.parent != main / LINKED:
        return  # some other hook made it
    if read_meta(main, where.name) is not None:
        done, lines = remove(main, where.name, force=True)
        if not done:
            raise RuntimeError('\n'.join(lines))
        return
    branch = head_of(where)[0]
    git(main, 'worktree', 'remove', '--force', str(where))
    if branch == CLAUDE_BRANCH + where.name:
        git(main, 'branch', '-D', branch, check=False)


def cmd_native(args):
    """`hook create|remove --cli claude`: Claude reads the new worktree's path from our stdout, so
    nothing else goes there; a failure says why on stderr and exits 1 (a missing path fails the
    creation, which is right: there is no worktree to enter)."""
    if args.cli != 'claude':
        return 0
    try:
        event = agent_hooks.read(args.cli, args.kind, json.loads(sys.stdin.read() or '{}'))
    except ValueError:
        event = agent_hooks.read(args.cli, args.kind, {})
    try:
        if args.kind == 'create':
            print(native_create(event))
        else:
            native_remove(event)
    except Exception as error:  # the message is all Claude shows
        print(f'worktree-guard: {error}', file=sys.stderr)
        return 1
    return 0


def cmd_release(args):
    worktree = worktree_of(Path(args.path or os.getcwd()).resolve())
    path = claim_file(worktree) if worktree else None
    with locked(path) if path else contextlib.nullcontext():
        claim = read_claim(path) if path else None
        if not claim:
            print(f'worktree-guard: nobody owns {worktree or args.path}')
            return 0
        path.unlink(missing_ok=True)
    print(f'worktree-guard: released {worktree} from {who(claim)}')
    return 0


def cmd_share(args):
    worktree = worktree_of(Path(args.path or os.getcwd()).resolve())
    path = claim_file(worktree) if worktree else None
    with locked(path) if path else contextlib.nullcontext():
        claim = read_claim(path) if path else None
        if not claim:
            print(f'worktree-guard: nobody owns {worktree or args.path}; nothing to share')
            return 0
        write_claim(path, {**claim, 'shared': True})
    print(f'worktree-guard: any session may edit {worktree} until {who(claim)} ends')
    return 0


# --- the command -------------------------------------------------------------------------

def parser():
    top = argparse.ArgumentParser(prog='worktree-guard', description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest='command', required=True)
    hook = sub.add_parser('hook', help='the CLI hook: JSON on stdin')
    hook.add_argument('kind', choices=('pre', 'end', *agent_hooks.CLAUDE_ONLY))
    hook.add_argument('--cli', choices=agent_hooks.CLIS, required=True)
    hook.set_defaults(run=cmd_hook)
    for name, run, help_text in (('list', cmd_list, 'linked worktrees: owner, branch, merged'),
                                 ('prune', cmd_prune, 'rm every merged, clean, unowned linked worktree')):
        command = sub.add_parser(name, help=help_text)
        command.add_argument('--repo', help='a folder in the repository (default: here)')
        command.set_defaults(run=run)
    done = sub.add_parser('done', help="note a linked worktree's one-line description, for its archive tag")
    done.add_argument('description')
    done.add_argument('--path', help='a folder in the linked worktree (default: here)')
    done.set_defaults(run=cmd_done)
    rm = sub.add_parser('rm', help='archive tag, then remove a linked worktree and its branch')
    rm.add_argument('name')
    rm.add_argument('--force', action='store_true', help='also when owned, changed or unmerged')
    rm.add_argument('--repo', help='a folder in the repository (default: here)')
    rm.set_defaults(run=cmd_rm)
    for name in ('on', 'off'):
        command = sub.add_parser(name, help=f'switch the worktree flow {name} for the repo (for people)')
        command.add_argument('--repo', help='a folder in the repository (default: here)')
        command.set_defaults(run=cmd_flow)
    new = sub.add_parser('new', help='start work in its own worktree, from origin\'s default branch, with no branch')
    new.add_argument('name', help='<type>/<slug>, for example fix/prune-worktrees')
    new.add_argument('--repo', help='a folder in the repository (default: here)')
    new.set_defaults(run=cmd_new)
    done_ = sub.add_parser('shipped', help='delete a worktree whose work is pushed and has its PR (what ship runs)')
    done_.add_argument('name', help="the worktree's folder name, e.g. fix-prune-worktrees")
    done_.add_argument('--repo', help='a folder in the repository (default: here)')
    done_.set_defaults(run=cmd_shipped)
    for name, run, help_text in (('release', cmd_release, "clear a worktree's owner (for people)"),
                                 ('share', cmd_share, 'let any session edit a worktree until its owner ends')):
        command = sub.add_parser(name, help=help_text)
        command.add_argument('path', nargs='?', help='a folder in the worktree (default: here)')
        command.set_defaults(run=run)
    return top


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    is_hook = argv[:1] == ['hook']
    try:
        # A bad hook call must stay silent and exit 0: status 2 and stderr would steer the CLI.
        with contextlib.redirect_stderr(io.StringIO() if is_hook else sys.stderr):
            args = parser().parse_args(argv)
    except SystemExit as error:
        return 0 if is_hook else int(error.code or 0)
    return args.run(args)


if __name__ == '__main__':
    sys.exit(main())
