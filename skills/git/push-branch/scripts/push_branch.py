#!/usr/bin/env python3
"""push-branch: push the branch being landed to origin.

  ai-dotfiles git push [--dry-run]

Skipped when origin already has this commit or the branch has nothing ahead of the base; a
remote branch at a commit HEAD does not contain stops the run (reconcile it by hand).
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import git_run  # noqa: E402  (the bundle's runner, in skills/git/scripts)
from git_run import Stop  # noqa: E402


def push(repo, dry):
    remote = git_run.on_origin(repo.branch)
    if remote == repo.tip:
        return 'already pushed'
    if not repo.ahead:
        return f'nothing ahead of origin/{repo.base}; not pushed'
    # A commit this clone has not fetched is no ancestor of HEAD either: git answers non-zero.
    if remote and git_run.sh(['git', 'merge-base', '--is-ancestor', remote, repo.tip])[0] != 0:
        raise Stop(f'push: origin/{repo.branch} is at {remote[:7]}, not behind HEAD; reconcile first')
    git_run.act(['git', 'push', '-q', '-u', 'origin', repo.branch], dry)
    return 'pushed'


def main(argv=None):
    return git_run.cli('push', __doc__, lambda args: git_run.step('push', push(git_run.preflight(), args.dry_run)),
                       argv=argv)


if __name__ == '__main__':
    sys.exit(main())
