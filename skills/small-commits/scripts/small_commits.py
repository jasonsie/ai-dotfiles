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
