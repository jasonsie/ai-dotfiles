#!/usr/bin/env python3
"""small-commits: every commit an agent makes stays small, one concern, and says why.

  small-commits hook pre --cli (claude|codex|agy|pi)   JSON in; JSON or nothing out
  small-commits check [GIT COMMIT ARGS...]             what the hook would say to `git commit ARGS` here

The hook sees each `git commit` a session runs and measures what it would commit: the staged
diff; with -a, every tracked change; with pathspecs, those paths; with --amend, the result
against the parent. Added plus deleted lines count; binaries, lockfiles and files the repo
marks `linguist-generated` or `-diff` in .gitattributes do not. Over 300 lines the first
attempt is blocked with a split hint, and the same commit retried in that session goes
through; over 600 it is blocked unless the command sets ALLOW_LARGE_COMMIT="<reason>" and the
message carries the reason as a `Large-commit:` trailer. The message needs a subject
`type(scope): outcome` of at most 72 characters and the trailers Why:, Scope: and Verified:
(Part: n/m when split). A commit that finishes a merge, cherry-pick, revert or rebase is left
alone, as is the message of --fixup and --squash. A failure never blocks: it says the commit
was not checked.

State: $SMALL_COMMITS_STATE, else ~/.local/state/ai-dotfiles/small-commits/ (the commits a
session was warned about). The CLIs' hook formats live in the repo's scripts/agent_hooks.py.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass, field
from fnmatch import fnmatch
import hashlib
import io
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL.parents[1] / 'scripts'))
import agent_hooks  # noqa: E402  (the CLIs' hook formats, in the repo's scripts folder)
from agent_hooks import Deny, Note  # noqa: E402

ENV = 'SMALL_COMMITS_STATE'
DEFAULT_STATE = '~/.local/state/ai-dotfiles/small-commits'
KEEP_SECONDS = 7 * 24 * 3600
SESSIONS = agent_hooks.Store(ENV, DEFAULT_STATE, KEEP_SECONDS)
WARN, WALL = 300, 600
OVERRIDE = 'ALLOW_LARGE_COMMIT'
OVERRIDE_SET = re.compile(r'(?<![\w-])' + OVERRIDE + r'=')
REQUIRED = ('Why', 'Scope', 'Verified')
LARGE, PART = 'Large-commit', 'Part'
PART_VALUE = re.compile(r'^\d+/\d+$')
TYPES = ('feat', 'fix', 'docs', 'style', 'refactor', 'perf', 'test', 'build', 'ci', 'chore', 'revert')
SUBJECT = re.compile(r'^(?P<type>[a-z]+)(\([^()]+\))?!?: \S')
SUBJECT_MAX = 72
LOCKFILES = ('*.lock', '*-lock.json', '*-lock.yaml', '*-lock.yml', '*.lockb', 'go.sum')
EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
IN_PROGRESS = ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply')
WARNED, WARNED_KEPT = 'warned', 20
# `git commit -m "$(cat <<'EOF' ... EOF)"`: the message is the heredoc's body.
HEREDOC = re.compile(r'^\$\(\s*cat\s*<<-?\s*[\'"]?(\w+)[\'"]?\s*\n(.*?)\n\s*\1\s*\)$', re.S)

GIT_OPTIONS_WITH_VALUE = frozenset(('-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env'))
SEPARATORS = set('();<>|&')
SHORT_WITH_VALUE = {'m': 'messages', 'F': 'file', 'C': 'reuse', 'c': 'reuse', 't': 'template'}
SHORT_OPTIONAL_VALUE = ('S', 'u')  # -S[keyid], -u[mode]: the rest of the token is the value
LONG_WITH_VALUE = {'--message': 'messages', '--file': 'file', '--reuse-message': 'reuse', '--reedit-message': 'reuse',
                   '--fixup': 'fixup', '--squash': 'fixup', '--template': 'template', '--author': None,
                   '--date': None, '--cleanup': None, '--trailer': 'trailers', '--pathspec-from-file': None}
SHORT_FLAGS = {'a': 'all', 'o': 'only', 'i': 'include'}
LONG_FLAGS = {'--all': 'all', '--amend': 'amend', '--only': 'only', '--include': 'include'}


# --- what a shell command commits --------------------------------------------------------

@dataclass
class Commit:
    """One `git commit` in a command line: where it runs and what its options say."""
    where: str = ''                 # the folder, relative to the shell's
    all: bool = False               # -a
    amend: bool = False
    only: bool = False              # -o
    include: bool = False           # -i
    pathspecs: list = field(default_factory=list)
    messages: list = field(default_factory=list)   # -m, in order
    file: str | None = None         # -F
    reuse: str | None = None        # -C / -c <commit>
    fixup: str | None = None        # --fixup / --squash
    template: str | None = None
    trailers: list = field(default_factory=list)   # --trailer "Key: value"


def tokens_of(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return command.split()


def is_separator(token):
    return bool(token) and set(token) <= SEPARATORS


def take(commit, name, value):
    current = getattr(commit, name)
    if isinstance(current, list):
        current.append(value)
    else:
        setattr(commit, name, value)


def commit_options(commit, tokens, i):
    """Read `git commit`'s arguments from tokens[i:] into `commit`; the index after them."""
    pathspecs_only = False
    while i < len(tokens) and not is_separator(tokens[i]):
        token = tokens[i]
        i += 1
        if token.isdigit() and i < len(tokens) and tokens[i][:1] in '<>':
            continue  # a redirect's file descriptor, as in 2>&1
        if pathspecs_only or not token.startswith('-') or token == '-':
            commit.pathspecs.append(token)
        elif token == '--':
            pathspecs_only = True
        elif token.startswith('--'):
            name, has_value, inline = token.partition('=')
            if name in LONG_WITH_VALUE:
                if not has_value:
                    inline, i = (tokens[i], i + 1) if i < len(tokens) and not is_separator(tokens[i]) else ('', i)
                if LONG_WITH_VALUE[name]:
                    take(commit, LONG_WITH_VALUE[name], inline)
            elif name in LONG_FLAGS:
                setattr(commit, LONG_FLAGS[name], True)
        else:
            for k, letter in enumerate(token[1:]):
                if letter in SHORT_WITH_VALUE:
                    rest = token[k + 2:]
                    if not rest:
                        rest, i = (tokens[i], i + 1) if i < len(tokens) and not is_separator(tokens[i]) else ('', i)
                    take(commit, SHORT_WITH_VALUE[letter], rest)
                    break
                if letter in SHORT_OPTIONAL_VALUE:
                    break
                if letter in SHORT_FLAGS:
                    setattr(commit, SHORT_FLAGS[letter], True)
    return i


def commits_in(command):
    """Every `git commit` in a shell command line, with the folder each runs in (relative to
    the shell's, following `cd` and `git -C`)."""
    tokens, found, here, i = tokens_of(command), [], '', 0
    while i < len(tokens):
        token = tokens[i]
        if token in ('cd', 'pushd') and i + 1 < len(tokens) and not is_separator(tokens[i + 1]):
            here = os.path.join(here, tokens[i + 1])
            i += 2
            continue
        if Path(token).name != 'git':
            i += 1
            continue
        j, where = i + 1, here
        while j < len(tokens) and tokens[j].startswith('-') and not is_separator(tokens[j]):
            if tokens[j] in GIT_OPTIONS_WITH_VALUE:
                if tokens[j] == '-C' and j + 1 < len(tokens):
                    where = os.path.join(where, tokens[j + 1])
                j += 2
            else:
                j += 1
        if j < len(tokens) and tokens[j] == 'commit':
            commit = Commit(where=where)
            j = commit_options(commit, tokens, j + 1)
            found.append(commit)
        i = j + 1
    return found


def command_of(event):
    key = 'CommandLine' if event.cli == 'agy' else 'command'
    value = event.tool_input.get(key)
    return value if isinstance(value, str) else ''


def shell_folder(event):
    cwd = event.tool_input.get('Cwd') if event.cli == 'agy' else None
    return cwd if isinstance(cwd, str) and cwd else (event.folder or os.getcwd())


# --- git ---------------------------------------------------------------------------------

def git(cwd, *args, check=True, stdin=None):
    run = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, input=stdin)
    if run.returncode:
        if check:
            raise RuntimeError(f'git {" ".join(args[:2])}: {run.stderr.strip()}')
        return None
    return run.stdout


def toplevel(cwd):
    out = git(cwd, 'rev-parse', '--show-toplevel', check=False)
    return out.strip() if out else None


def in_progress(cwd):
    """A merge, cherry-pick, revert or rebase waits for this commit: git writes it, not the agent."""
    git_dir = Path(cwd, git(cwd, 'rev-parse', '--git-dir').strip())
    return any((git_dir / name).exists() for name in IN_PROGRESS)


def numstat(cwd, *args):
    """[(path, added, deleted)] for `git diff --numstat ARGS`; binaries count None."""
    out = git(cwd, 'diff', '--numstat', '-z', '-M', *args) or ''
    parts, files, i = out.split('\0'), [], 0
    while i < len(parts):
        fields = parts[i].split('\t')
        i += 1
        if len(fields) < 3:
            continue
        added, deleted, path = fields[0], fields[1], '\t'.join(fields[2:])
        if path == '' and i + 1 < len(parts):  # a rename: old and new paths follow
            path, i = parts[i + 1], i + 2
        files.append((path, None if added == '-' else int(added), None if deleted == '-' else int(deleted)))
    return files


def base_of(commit, cwd):
    """The tree the commit is measured against: HEAD, or the parent on --amend; the empty tree
    in a repository without commits."""
    if commit.amend:
        parent = git(cwd, 'rev-parse', '-q', '--verify', 'HEAD^', check=False)
        return parent.strip() if parent else EMPTY_TREE
    head = git(cwd, 'rev-parse', '-q', '--verify', 'HEAD', check=False)
    return 'HEAD' if head else EMPTY_TREE


def changes(commit, cwd):
    """What `git commit` with these options would put in the commit, as numstat lines."""
    base = base_of(commit, cwd)
    if commit.pathspecs and not commit.include:  # -o, or paths alone: those paths as in the tree
        return numstat(cwd, base, '--', *commit.pathspecs)
    if commit.all:
        return numstat(cwd, base)
    staged = numstat(cwd, '--cached', base)
    if commit.include and commit.pathspecs:  # -i: the index, plus those paths as in the tree
        named = {path: line for path, *_ in (line for line in numstat(cwd, base, '--', *commit.pathspecs))
                 for line in [(path, *_)]}
        return [line for line in staged if line[0] not in named] + list(named.values())
    return staged


def skipped(top, paths):
    """The paths a reviewer does not read: lockfiles, and what .gitattributes marks
    `linguist-generated` or `-diff`."""
    skip = {p for p in paths if any(fnmatch(Path(p).name, pattern) for pattern in LOCKFILES)}
    rest = [p for p in paths if p not in skip]
    if rest:
        out = git(top, 'check-attr', '-z', '--stdin', 'linguist-generated', 'diff', stdin='\0'.join(rest) + '\0') or ''
        parts = out.split('\0')
        for k in range(0, len(parts) - 2, 3):
            path, attr, value = parts[k:k + 3]
            if (attr == 'linguist-generated' and value in ('set', 'true')) or (attr == 'diff' and value == 'unset'):
                skip.add(path)
    return skip


@dataclass(frozen=True)
class Size:
    files: tuple    # (path, added + deleted) for every counted file, largest first
    lines: int
    left_out: tuple  # the paths not counted: binaries, lockfiles, generated

    @property
    def fingerprint(self):
        return hashlib.sha1(repr(self.files).encode()).hexdigest()[:16]


def measure(commit, cwd):
    lines = changes(commit, cwd)
    out = skipped(toplevel(cwd), [path for path, *_ in lines])
    counted = sorted(((path, added + deleted) for path, added, deleted in lines
                      if path not in out and added is not None and deleted is not None),
                     key=lambda item: (-item[1], item[0]))
    binaries = [path for path, added, deleted in lines if (added is None or deleted is None) and path not in out]
    return Size(tuple(counted), sum(n for _, n in counted), tuple(sorted(out) + binaries))


# --- the message -------------------------------------------------------------------------

def unwrap(text):
    """The message in one -m value, or None when the shell computes it (`$(...)`) and it is not
    a heredoc we can read."""
    match = HEREDOC.match(text.strip())
    if match:
        return match.group(2)
    return None if text.lstrip().startswith(('$(', '`')) else text


def message_of(commit, cwd):
    """The commit message these options give, or None when it is not known before the commit
    (an editor, stdin, a file not yet written)."""
    if commit.messages:
        parts = [part for part in map(unwrap, commit.messages) if part is not None]
        return '\n\n'.join(parts) if len(parts) == len(commit.messages) else None
    if commit.file is not None:
        try:
            return Path(cwd, commit.file).read_text()
        except (OSError, ValueError):
            return None
    if commit.reuse or commit.amend:
        out = git(cwd, 'log', '-1', '--format=%B', commit.reuse or 'HEAD', check=False)
        return out if out is not None else None
    return None


def trailers_of(message, given=()):
    """{key (lower): value} of the message's trailer block and any --trailer options."""
    out = git('.', 'interpret-trailers', '--parse', stdin=message) or ''
    found = {}
    for line in [*out.splitlines(), *given]:
        key, sep, value = line.partition(':')
        if not sep:
            key, sep, value = line.partition('=')
        if sep and key.strip():
            found[key.strip().lower()] = value.strip()
    return found


def message_problems(message, given, large):
    """What a reviewer would send back: the subject's shape, the missing trailers."""
    subject = message.strip().split('\n', 1)[0].strip() if message.strip() else ''
    problems = []
    match = SUBJECT.match(subject)
    if not match or match.group('type') not in TYPES:
        problems.append(f'the subject is not `type(scope): outcome` (types: {", ".join(TYPES)})')
    if len(subject) > SUBJECT_MAX:
        problems.append(f'the subject has {len(subject)} characters; {SUBJECT_MAX} at most')
    trailers = trailers_of(message, given)
    missing = [key for key in REQUIRED + ((LARGE,) if large else ()) if not trailers.get(key.lower())]
    if missing:
        problems.append('missing trailer' + ('s ' if len(missing) > 1 else ' ') + ', '.join(f'{k}:' for k in missing))
    if trailers.get(PART.lower()) and not PART_VALUE.match(trailers[PART.lower()]):
        problems.append(f'{PART}: is n/m, as in 2/4')
    return problems


# --- the verdict -------------------------------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    size: Size | None
    denied: tuple = ()   # reasons to block, in prose
    note: str = ''       # a word to the model when the commit runs


def listing(size, limit=5):
    rows = [f'  {n:>5}  {path}' for path, n in size.files[:limit]]
    if len(size.files) > limit:
        rows.append(f'         ... {len(size.files) - limit} more')
    return '\n'.join(rows)


def judge(commit, cwd, allowed, state):
    """The verdict on one commit: what blocks it and what to say. `allowed`: the command sets
    ALLOW_LARGE_COMMIT. The session's state remembers the sizes it was warned about."""
    if toplevel(cwd) is None or in_progress(cwd):
        return Verdict(None)
    size = measure(commit, cwd)
    message = message_of(commit, cwd)
    problems = [] if message is None or commit.fixup else message_problems(message, commit.trailers, size.lines > WALL)
    denied, note = [], ''
    count = f'{size.lines} lines across {len(size.files)} file{"s" if len(size.files) != 1 else ""}'
    if size.lines > WALL:
        if allowed:
            note = f'small-commits: {count}, over {WALL}, let through on {OVERRIDE}.'
        else:
            denied.append(f'{count}: over {WALL}, the wall. Split it (load the small-commits skill); if it cannot '
                          f'be split, ask the user and, with their go, rerun with {OVERRIDE}="<reason>" and a '
                          f'{LARGE}: <reason> trailer.\n{listing(size)}')
    elif size.lines > WARN:
        warned = state.get(WARNED) if isinstance(state.get(WARNED), list) else []
        if size.fingerprint in warned:
            note = f'small-commits: {count}, over {WARN}, let through on retry.'
        else:
            state[WARNED] = (warned + [size.fingerprint])[-WARNED_KEPT:]
            denied.append(f'{count}: over {WARN}. Split it into commits of one concern each (load the '
                          f'small-commits skill), or rerun the same command to commit as is.\n{listing(size)}')
    if problems:
        denied.append('the message needs work: ' + '; '.join(problems) + '.')
    return Verdict(size, tuple(denied), note)


def decide(event, state):
    if event.action != 'shell':
        return None
    command = command_of(event)
    if 'commit' not in command:
        return None
    commits = commits_in(command)
    if not commits:
        return None
    folder, allowed = shell_folder(event), bool(OVERRIDE_SET.search(command))
    denied, notes = [], []
    for commit in commits:
        verdict = judge(commit, os.path.normpath(os.path.join(folder, commit.where)), allowed, state)
        denied.extend(verdict.denied)
        if verdict.note:
            notes.append(verdict.note)
    if denied:
        return Deny('small-commits blocked this commit. ' + ' Also, '.join(denied))
    return Note(' '.join(notes)) if notes else None


def hook(event):
    """The door's call (lib/door.py) before a tool call: decide() with the session's state."""
    return agent_hooks.handle(event, decide, SESSIONS)


def answer(cli, kind):
    return lambda data: agent_hooks.call(cli, kind, data, decide, SESSIONS)


def failed(error):
    """What the door says in the gate's place when it fails: never a block."""
    return Note(f'small-commits failed ({error}); this commit was not checked.')


def cmd_hook(args):
    return agent_hooks.serve(args.cli, args.kind, answer(args.cli, args.kind), on_error=failed)


def cmd_check(args):
    """What the hook would say to `git commit ARGS` run here, with the size by file."""
    commit = Commit()
    commit_options(commit, list(args), 0)
    cwd = os.getcwd()
    if toplevel(cwd) is None:
        print('not in a git repository')
        return 1
    if in_progress(cwd):
        print('a merge, cherry-pick, revert or rebase is in progress: git writes this commit; nothing to check')
        return 0
    verdict = judge(commit, cwd, bool(os.environ.get(OVERRIDE)), {})
    size = verdict.size
    assert size is not None
    print(f'{size.lines} lines across {len(size.files)} file{"s" if len(size.files) != 1 else ""}'
          f' (limit {WARN}, wall {WALL})')
    if size.files:
        print(listing(size, limit=len(size.files)))
    for path in size.left_out:
        print(f'   skip  {path}')
    for reason in verdict.denied:
        print(f'BLOCKED: {reason.splitlines()[0]}')
    if message_of(commit, cwd) is None:
        print('message: not given (-m or -F), not checked')
    if not verdict.denied:
        print('ok')
    return 1 if verdict.denied else 0


def parser():
    top = argparse.ArgumentParser(prog='small-commits', description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest='command', required=True)
    hook = sub.add_parser('hook', help='the CLI hook: JSON on stdin')
    hook.add_argument('kind', choices=('pre',))
    hook.add_argument('--cli', choices=agent_hooks.CLIS, required=True)
    hook.set_defaults(run=cmd_hook)
    check = sub.add_parser('check', help="what the hook would say to `git commit ARGS` run here; ARGS are git "
                                         "commit's own (-a, --amend, paths, -m MSG), passed through untouched")
    check.set_defaults(run=None)
    return top


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ['check'] and argv[1:2] not in (['-h'], ['--help']):
        return cmd_check(argv[1:])  # git commit's options are not ours to parse
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
