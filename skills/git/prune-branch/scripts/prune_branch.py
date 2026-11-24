#!/usr/bin/env python3
"""prune-branch: after the merge, the base checked out and pulled, the branch gone, and the worktree.

  ai-dotfiles git prune [--dry-run]

Run on the merged branch: checks out the base, pulls it fast-forward, deletes the branch
locally and on origin. In a linked worktree whose base is checked out in another worktree,
HEAD is detached at origin/<base> instead (git lets one worktree hold a branch). Tag it first
(archive-tag): the deleted branch is kept nowhere else. A branch, here or on origin, whose tip is
neither in origin/<base> nor under an archive tag stops the run before anything is deleted.

Run in a linked worktree, it then fast-forwards the main checkout when git can without touching
uncommitted files, and deletes the worktree, last: only the archive tag is left. worktree-guard
deletes it (its record, owner and the session's binding go too) or keeps it, with why: in a repo
whose flow is off, one the guard did not make, one another live session owns, or one holding
uncommitted changes or a commit on no remote. Kept is a `skipped:` line, not a stop.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import git_run  # noqa: E402  (the bundle's runner, in skills/git/scripts)
from git_run import Stop  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'worktree-guard' / 'scripts'))
import worktree_guard as guard  # noqa: E402  (a worktree's record and its deletion)

BACK = ('Back in {}. Claude Code: call ExitWorktree (action keep) or cd there; the next first edit '
        'starts a new task.')


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


def remote_tip(branch):
    """The branch's commit on origin, asked of origin itself; '' when origin has no such branch."""
    code, listed, _ = git_run.sh(['git', 'ls-remote', '--exit-code', '--heads', 'origin', branch])
    return listed.split()[0] if code == 0 and listed else ''


def delete_remote(branch, dry):
    """Delete the branch on origin; False when it is gone already."""
    if git_run.sh(['git', 'ls-remote', '--exit-code', '--heads', 'origin', branch])[0] != 0:
        return False
    git_run.act(['git', 'push', '-q', 'origin', '--delete', branch], dry)
    return True


def kept(sha, base):
    """What still holds the commit once its branch is gone: 'origin/<base>' (merged), an archive
    tag's name, or '' for nothing. A commit this clone has not fetched is held by nothing it knows."""
    if git_run.sh(['git', 'merge-base', '--is-ancestor', sha, f'origin/{base}'])[0] == 0:
        return f'origin/{base}'
    code, tags, _ = git_run.sh(['git', 'tag', '--list', 'archive/*', '--contains', sha])
    return tags.split()[0] if code == 0 and tags else ''


def refuse_a_loss(repo, tips):
    """Stop before the first delete when a tip to be deleted is merged nowhere and tagged nowhere."""
    for what, sha, first in tips:
        if sha and not kept(sha, repo.base):
            raise Stop(f'prune: {what} is at {sha[:7]}, which is neither in origin/{repo.base} nor under an archive '
                       f'tag; deleting it would lose its commits. Nothing was deleted. {first}Tag the branch '
                       '(`ai-dotfiles git tag`, with --unmerged when it never merged), then rerun')


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
    git_run.act(['git', 'fetch', '-q', 'origin', base], dry)  # a dry run compares with the last fetch
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
    """Delete the branch here and on origin, after the base is checked out; Stop, with nothing
    changed, when a delete would lose commits. A dry run fetches nothing, so it cannot tell a
    merged branch from an unmerged one and does not check."""
    done = []
    git_run.act(['git', 'fetch', '-q', 'origin', repo.base], dry)  # the merge: origin/<base> vouches for the branch
    code, local, _ = git_run.sh(['git', 'rev-parse', '--verify', '-q', f'refs/heads/{repo.branch}'])
    local = local if code == 0 else ''
    if not dry:
        refuse_a_loss(repo, ((repo.branch, local, ''),
                             (f"origin's {repo.branch}", remote_tip(repo.branch), 'Pull it into the branch first. ')))
    if held_elsewhere(repo.base):
        if git_run.out(['git', 'branch', '--show-current']) == repo.branch:
            git_run.act(['git', 'checkout', '-q', '--detach', f'origin/{repo.base}'], dry)
            done.append(f'detached at origin/{repo.base} ({repo.base} is checked out in another worktree)')
    else:
        if git_run.out(['git', 'branch', '--show-current']) == repo.branch:
            git_run.act(['git', 'checkout', '-q', repo.base], dry)
            done.append(f'on {repo.base}')
        git_run.act(['git', 'pull', '-q', '--ff-only', 'origin', repo.base], dry)
    if local:
        git_run.act(['git', 'branch', '-q', '-D', repo.branch], dry)
        done.append('local branch deleted')
    if delete_remote(repo.branch, dry):
        done.append('remote branch deleted')
    return ', '.join(done) or 'nothing left'


def here():
    """(the worktree this run is in, the main checkout, the branch checked out here or None), from
    git's list of worktrees, which names the main checkout first."""
    top = Path(git_run.out(['git', 'rev-parse', '--show-toplevel']))
    trees = []
    for line in git_run.out(['git', 'worktree', 'list', '--porcelain']).splitlines():
        if line.startswith('worktree '):
            trees.append([Path(line.split(' ', 1)[1]), None])
        elif line.startswith('branch ') and trees:
            trees[-1][1] = line.split(' ', 1)[1].removeprefix('refs/heads/')
    return top, trees[0][0], next((branch for path, branch in trees if path == top), None)


def holds(top, main, checked_out, branch, number):
    """Whether the linked worktree `top` holds PR `number`'s work: its `branch` is checked out
    there, or worktree-guard's record of it names that branch (the work shipped as it) or that PR
    (a fix `worktree pr <n>` made)."""
    if checked_out == branch:
        return True
    meta = guard.read_meta(main, top.name) if top.parent == main / guard.LINKED else None
    return bool(meta) and (meta.get('work') == branch or meta.get('pr') == number)


def unlanded(tip, dry):
    """What this worktree holds that the landed commit `tip` lacks: 'uncommitted files', 'commits',
    or '' for nothing. A dry run that has not fetched `tip` cannot tell, and says nothing."""
    if git_run.out(['git', 'status', '--porcelain']):
        return 'uncommitted files'
    known = git_run.sh(['git', 'rev-parse', '--verify', '-q', f'{tip}^{{commit}}'])[0] == 0
    if (known or not dry) and git_run.sh(['git', 'merge-base', '--is-ancestor', 'HEAD', tip])[0] != 0:
        return 'commits'
    return ''


def leave(top, base, dry):
    """(step line, deleted): the linked worktree this run is in, deleted now that its work is merged
    and tagged; worktree-guard keeps it, with why, when it is not safe to. Origin's base is fetched
    first: with the branch deleted, the merge is what puts the worktree's commits on a remote."""
    git_run.act(['git', 'fetch', '-q', 'origin', base], dry)
    done, lines = guard.landed(top, dry)
    said = ' '.join(lines).replace('worktree-guard: ', '')
    return (said, not dry) if done else (f'skipped: {said}', False)


def finish(repo, dry, number=None):
    """The local end of a landing, after the merge, one step line each; returns where the session is
    when its worktree was deleted (BACK), else None.

    Plain (`approve`, `git prune`): prune; run in a linked worktree, then the main checkout
    fast-forwarded and the worktree deleted. By number (`approve <n>`): the main checkout
    fast-forwarded, and, run in the linked worktree holding PR <n>'s work, that worktree pruned
    before it and deleted after, unless it holds work the PR lacks: then its branch and folder
    stay. (The plain form needs no such check: its push made the branch's tip the PR's head.)
    The deletion is last: nothing can run in its folder after it."""
    top, main, checked_out = here()
    linked = top != main
    own = linked and (number is None or holds(top, main, checked_out, repo.branch, number))
    held = unlanded(repo.tip, dry) if own and number is not None else ''
    if number is None or (own and not held):
        git_run.step('prune', prune(repo, dry))
    if number is not None or linked:
        git_run.step('main', fast_forward(repo.base, dry))
    if held:
        git_run.step('worktree', f'skipped: {top.name} holds {held} that PR #{number} does not have; its '
                                 'branch and folder stay')
    if not own or held:
        return None
    said, gone = leave(top, repo.base, dry)
    git_run.step('worktree', said)
    return BACK.format(main) if gone else None


def run(args):
    back = finish(git_run.preflight(), args.dry_run)
    if back:
        print(back)


def main(argv=None):
    return git_run.cli('prune', __doc__, run, argv=argv)


if __name__ == '__main__':
    sys.exit(main())
