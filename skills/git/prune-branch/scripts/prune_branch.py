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


def delete_remote(branch, dry):
    """Delete the branch on origin; False when it is gone already."""
    if git_run.sh(['git', 'ls-remote', '--exit-code', '--heads', 'origin', branch])[0] != 0:
        return False
    git_run.act(['git', 'push', '-q', 'origin', '--delete', branch], dry)
    return True


def main_checkout():
    """(path, branch ref or None) of the main checkout: the first worktree git lists."""
    path = ref = None
    for line in git_run.out(['git', 'worktree', 'list', '--porcelain']).splitlines() + ['']:
        if line.startswith('worktree ') and path is None:
            path = line.split(' ', 1)[1]
        elif line.startswith('branch ') and path:
            ref = line.split(' ', 1)[1]
        elif not line and path:
            break
    return path, ref


def paths(args, where):
    code, text, _ = git_run.sh(['git', '-C', where, *args])
    return set(text.split('\0')) - {''} if code == 0 else set()


def fast_forward(base, dry):
    """Move the main checkout to origin/<base> when git can without touching uncommitted files.

    Never a stash, reset or forced checkout: a checkout that is not on the base, is not behind it,
    or has uncommitted work in a file the move would change is left as it is, with the reason."""
    path, ref = main_checkout()
    if ref != f'refs/heads/{base}':
        on = ref.removeprefix('refs/heads/') if ref else 'a detached HEAD'
        return f'skipped: the main checkout is on {on}, not {base}'
    git_run.out(['git', 'fetch', '-q', 'origin', base], what='git fetch')
    head = git_run.out(['git', '-C', path, 'rev-parse', 'HEAD'])
    target = git_run.out(['git', '-C', path, 'rev-parse', f'origin/{base}'])
    if head == target:
        return 'up to date already'
    if git_run.sh(['git', '-C', path, 'merge-base', '--is-ancestor', head, target])[0] != 0:
        return f'skipped: {base} has commits origin/{base} lacks'
    incoming = paths(['diff', '--name-only', '-z', '--no-renames', head, target], path)
    dirty = (paths(['diff', '--name-only', '-z', '--no-renames'], path)
             | paths(['diff', '--name-only', '-z', '--no-renames', '--cached'], path)
             | paths(['ls-files', '-z', '--others', '--exclude-standard'], path))
    clash = sorted(incoming & dirty)
    if clash:
        more = f' and {len(clash) - 3} more' if len(clash) > 3 else ''
        return f'skipped: uncommitted changes in {", ".join(clash[:3])}{more}'
    merge = ['git', '-C', path, 'merge', '--ff-only', f'origin/{base}']
    if dry:
        git_run.act(merge, dry)
        return 'would fast-forward'
    code, stdout, stderr = git_run.sh(merge)
    if code != 0:
        why = (stderr or stdout).splitlines()
        return f'skipped: git refused: {why[0] if why else f"exit {code}"}'
    return f'fast-forwarded to {target[:7]}'


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
    if delete_remote(repo.branch, dry):
        done.append('remote branch deleted')
    return ', '.join(done) or 'nothing left'


def main(argv=None):
    return git_run.cli('prune', __doc__, lambda args: git_run.step('prune', prune(git_run.preflight(), args.dry_run)),
                       argv=argv)


if __name__ == '__main__':
    sys.exit(main())
