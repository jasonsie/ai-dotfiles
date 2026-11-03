#!/usr/bin/env python3
"""merge-pr: merge the branch's PR by merge commit.

  ai-dotfiles git merge [--dry-run]

Skipped when merged already; a PR GitHub reports dirty (conflicts), blocked (checks or
required reviews) or behind stops the run with that state.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import git_run  # noqa: E402  (the bundle's runner, in skills/git/scripts)
from git_run import Stop  # noqa: E402

git_run.use('open-pr')
import open_pr  # noqa: E402

NOT_MERGEABLE = ('DIRTY', 'BLOCKED', 'BEHIND')


def merge(pr, dry):
    if pr['state'] == 'MERGED':
        return 'merged already'
    if pr['number']:
        state = git_run.out(['gh', 'pr', 'view', str(pr['number']), '--json', 'mergeStateStatus', '-q', '.mergeStateStatus'])
        if state in NOT_MERGEABLE:
            raise Stop(f'merge: PR #{pr["number"]} is {state.lower()}; resolve that, then rerun')
    git_run.act(['gh', 'pr', 'merge', str(pr['number']), '--merge'], dry)
    return f'#{pr["number"]} merged'


def main(argv=None):
    return git_run.cli('merge', __doc__,
                       lambda args: git_run.step('merge', merge(open_pr.found(git_run.preflight()), args.dry_run)),
                       argv=argv)


if __name__ == '__main__':
    sys.exit(main())
