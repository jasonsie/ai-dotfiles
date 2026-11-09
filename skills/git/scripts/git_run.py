"""git_run: what every skill in the git bundle shares: the command runner, the stop, the branch.

Each step skill (push-branch, open-pr, approve-pr, archive-tag, merge-pr, prune-branch) owns its
code in its own scripts/ folder and imports this module; approve imports the six. Every git and
gh call goes through `sh`, so a test fakes them all in one place. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys

BUNDLE = Path(__file__).resolve().parents[1]   # skills/git


class Stop(Exception):
    """The run stops here; the message names the step and the fix."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def use(*skills):
    """Make the named skills of this bundle importable, e.g. use('archive-tag')."""
    for skill in skills:
        folder = str(BUNDLE / skill / 'scripts')
        if folder not in sys.path:
            sys.path.insert(0, folder)


def sh(args, env=None, cwd=None):
    """Run a command; (exit code, stdout, stderr), never raising."""
    full = dict(os.environ, **env) if env else None
    try:
        done = subprocess.run(args, env=full, cwd=cwd, capture_output=True, text=True)
    except OSError as error:
        return 127, '', str(error)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def out(args, env=None, what=None, cwd=None):
    """stdout of a read-only command; Stop when it fails."""
    code, stdout, stderr = sh(args, env, cwd)
    if code != 0:
        raise Stop(f'{what or " ".join(args[:2])}: {stderr or stdout or f"exit {code}"}')
    return stdout


def act(args, dry, env=None, cwd=None):
    """A command that changes something: printed in a dry run, otherwise run and checked."""
    if dry:
        print('   would  ' + ' '.join(a if ' ' not in a else repr(a) for a in args))
        return
    code, stdout, stderr = sh(args, env, cwd)
    if code != 0:
        raise Stop(f'{" ".join(args[:2])}: {stderr or stdout or f"exit {code}"}')


@dataclass
class Repo:
    base: str          # the default branch, e.g. main
    branch: str        # the branch to land
    tip: str           # its commit
    slug: str          # owner/name on GitHub
    author: str        # the gh login that opens the PR
    ahead: int = 1     # its commits not on origin/<base>


def github():
    """(owner/name, the active gh login)."""
    slug = out(['gh', 'repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'], what='gh repo view')
    author = out(['gh', 'api', 'user', '-q', '.login'], what='gh api user')
    return slug, author


def preflight(work=None):
    """The branch to land: checked out, not the base, no tracked changes. A worktree with no
    branch is landed under its `work` name (<type>/<slug>), the branch it will be pushed as."""
    if sh(['git', 'rev-parse', '--is-inside-work-tree'])[0] != 0:
        raise Stop('preflight: not in a git repository')
    branch = work or out(['git', 'branch', '--show-current'])
    if not branch:
        raise Stop('preflight: detached HEAD; check out the branch to land')
    code, head, _ = sh(['git', 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD'])
    base = head.split('/', 1)[1] if code == 0 and '/' in head else 'main'
    if branch == base:
        raise Stop(f'preflight: on {base}; the work to land must be on its own branch')
    if out(['git', 'status', '--porcelain', '--untracked-files=no']):
        raise Stop('preflight: tracked changes are not committed; commit them first (small-commits)')
    out(['git', 'fetch', '-q', 'origin', base], what='git fetch')
    ahead = len(out(['git', 'rev-list', f'origin/{base}..HEAD']).split())
    slug, author = github()
    return Repo(base, branch, out(['git', 'rev-parse', 'HEAD']), slug, author, ahead)


def step(name, result):
    print(f'{name:<10} {result}')


def cli(name, doc, run, configure=None, argv=None):
    """`ai-dotfiles git <name>`: parse, run(args), and turn a Stop into its message and exit code."""
    parser = argparse.ArgumentParser(prog=f'ai-dotfiles git {name}', description=doc,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='print what would change; read-only commands still run')
    if configure:
        configure(parser)
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        return run(args) or 0
    except Stop as stop:
        print(f'{name} stopped at {stop}', file=sys.stderr)
        return stop.code
