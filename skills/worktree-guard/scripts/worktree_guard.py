#!/usr/bin/env python3
"""worktree-guard: keep agent sessions that share a checkout out of each other's changes.

  worktree-guard hook (pre|end) --cli (claude|codex|agy|pi)   JSON in; JSON or nothing out

A session owns a worktree from its first edit until it ends or its process is gone. When a
second live session's first edit lands in a worktree another session owns, the guard makes a
linked worktree for it at <main worktree>/.claude/worktrees/<name>, on a new branch from the
busy worktree's last commit, and points the session there: Claude Code is told to call
EnterWorktree; Codex, Pi and Antigravity have their tool calls rewritten. An edit is a
file-edit tool or a git command that changes the working tree or the index. Subagents share
their parent's ownership. A failure never blocks an edit; it says the edit was not protected.

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
from agent_hooks import Deny, Note, Rewrite  # noqa: E402

ENV = 'WORKTREE_GUARD_STATE'
DEFAULT_STATE = '~/.local/state/ai-dotfiles/worktree-guard'
KEEP_SECONDS = 30 * 24 * 3600
SESSIONS = agent_hooks.Store(ENV, DEFAULT_STATE, KEEP_SECONDS, 'sessions')
LINKED = Path('.claude/worktrees')
BRANCH_PREFIX = 'agent/'
GIT_CHANGES = frozenset(
    'add am apply checkout cherry-pick clean commit merge mv pull rebase reset restore revert rm stash switch'.split())
GIT_OPTIONS_WITH_VALUE = frozenset(('-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env'))
WRAPPERS = frozenset(('sh', 'bash', 'zsh', 'dash', 'fish', 'ksh', 'env', 'timeout', 'gtimeout', 'nice', 'nohup'))
OVERRIDE = re.compile(r'(ai-dotfiles\s+worktree|worktree[-_]guard(\.py)?)\s+(release|share)\b')
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
    change a working tree or the index."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    found, i = [], 0
    while i < len(tokens):
        if Path(tokens[i]).name != 'git':
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
            found.append(where)
        i = j + 1
    return found


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
    """`path` (absolute) inside the busy worktree, as the same path in the linked one; else None."""
    busy, linked = Path(moved['busy']), Path(moved['linked'])
    try:
        rest = Path(path).relative_to(busy)
    except ValueError:
        return None
    if rest.parts[:2] == LINKED.parts:
        return None
    return linked / rest


def steer_text(text, moved):
    """Absolute busy-worktree paths in a command line, pointed at the linked worktree."""
    busy, linked = re.escape(moved['busy']), moved['linked']
    return re.sub(busy + r'(?![\w.-])(?!/' + re.escape(LINKED.as_posix()) + r'/)', lambda _: linked, text)


def steer(event, moved):
    """The tool input with the busy worktree swapped for the linked one, or None if unchanged."""
    folder = event.folder or os.getcwd()
    data = dict(event.tool_input)
    if event.action == 'shell':
        key = 'CommandLine' if event.cli == 'agy' else 'command'
        command = command_of(event)
        steered = steer_text(command, moved)
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
    linked = main / LINKED / name
    git(main, 'worktree', 'add', '-q', '-b', BRANCH_PREFIX + name, str(linked), base)
    exclude(main)
    copy_included(busy, linked)
    moved = {'busy': str(busy), 'linked': str(linked), 'name': name, 'branch': BRANCH_PREFIX + name,
             'from': branch or base[:12], 'base': base, 'default': default_ref(busy),
             'owner': {k: claim.get(k) for k in ('cli', 'session')}}
    state['moved'] = moved
    take(linked, me, table)
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


def decide(event, state, table=None):
    """The reply to one hook call; `state` is the session's, saved by agent_hooks.call."""
    if event.kind == 'end':
        release(event.session)
        return None
    if event.kind != 'pre':
        return None
    if event.action == 'shell' and OVERRIDE.search(command_of(event)):
        return Deny('worktree-guard: release and share are for a person, run from a terminal; '
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
    if worktrees:
        table = table if table is not None else process_table()
        me = owner(event, table)
        for worktree in worktrees:
            verdict, claim, previous = take(worktree, me, table)
            if verdict == 'busy':
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
    return agent_hooks.serve(args.cli, args.kind, answer(args.cli, args.kind),
                             on_error=failed if args.kind == 'pre' else None)


# --- the command -------------------------------------------------------------------------

def parser():
    top = argparse.ArgumentParser(prog='worktree-guard', description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest='command', required=True)
    hook = sub.add_parser('hook', help='the CLI hook: JSON on stdin')
    hook.add_argument('kind', choices=('pre', 'end'))
    hook.add_argument('--cli', choices=agent_hooks.CLIS, required=True)
    hook.set_defaults(run=cmd_hook)
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
