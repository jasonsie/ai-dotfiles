#!/usr/bin/env python3
"""prune-branch: after the merge, the base checked out and pulled, the branch gone.

  ai-dotfiles git prune [--dry-run]

Run on the merged branch: checks out the base, pulls it fast-forward, deletes the branch
locally and on origin. In a linked worktree whose base is checked out in another worktree,
HEAD is detached at origin/<base> instead (git lets one worktree hold a branch). Tag it first (archive-tag): the deleted branch is kept nowhere else.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import git_run  # noqa: E402  (the bundle's runner, in skills/git/scripts)
from git_run import Stop  # noqa: E402


def held_elsewhere(base):
    """True when another worktree has the base checked out."""
    here = git_run.out(['git', 'rev-parse', '--show-toplevel'])
    path = None
    for line in git_run.out(['git', 'worktree', 'list', '--porcelain']).splitlines():
        if line.startswith('worktree '):
            path = line.split(' ', 1)[1]
        elif line == f'branch refs/heads/{base}' and path != here:
            return True
    return False


def prune(repo, dry):
    done = []
    if held_elsewhere(repo.base):
        git_run.act(['git', 'fetch', '-q', 'origin', repo.base], dry)
        if git_run.out(['git', 'branch', '--show-current']) == repo.branch:
            git_run.act(['git', 'checkout', '-q', '--detach', f'origin/{repo.base}'], dry)
            done.append(f'detached at origin/{repo.base} ({repo.base} is checked out in another worktree)')
    else:
        if git_run.out(['git', 'branch', '--show-current']) == repo.branch:
            git_run.act(['git', 'checkout', '-q', repo.base], dry)
            done.append(f'on {repo.base}')
        git_run.act(['git', 'pull', '-q', '--ff-only', 'origin', repo.base], dry)
    if git_run.sh(['git', 'rev-parse', '--verify', '-q', f'refs/heads/{repo.branch}'])[0] == 0:
        git_run.act(['git', 'branch', '-q', '-D', repo.branch], dry)
        done.append('local branch deleted')
    if git_run.sh(['git', 'ls-remote', '--exit-code', '--heads', 'origin', repo.branch])[0] == 0:
        git_run.act(['git', 'push', '-q', 'origin', '--delete', repo.branch], dry)
        done.append('remote branch deleted')
    return ', '.join(done) or 'nothing left'


def main(argv=None):
    return git_run.cli('prune', __doc__, lambda args: git_run.step('prune', prune(git_run.preflight(), args.dry_run)),
                       argv=argv)


if __name__ == '__main__':
    sys.exit(main())
