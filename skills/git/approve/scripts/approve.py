#!/usr/bin/env python3
"""approve: land a reviewed branch: the six git step skills, in order, as one resumable run.

  ai-dotfiles approve [--title T --body-file F] [--reviewer LOGIN] [--dry-run]

The user has reviewed the branch and said "approve"; the commits and the PR body are already
written. Each step is its own skill, with its own command, and is skipped when already done,
so a run that stopped can be rerun:

  preflight   a branch other than the base, no tracked changes        (git_run)
  reviewer    this repo's reviewer, verified and cached               (approve-pr)
  push        the branch to origin                                    (push-branch, git push)
  pr          the open PR, or a new one from --title and --body-file  (open-pr, git pr)
  review      an approval as the reviewer                             (approve-pr, git review)
  tag         archive/<name> at the branch tip, pushed                (archive-tag, git tag)
  merge       a merge commit                                          (merge-pr, git merge)
  prune       base checked out and pulled; branch deleted everywhere  (prune-branch, git prune)

Nothing is undone on failure: the run stops, names the step, and exits 1. Exit 3 means no
reviewer is known for this repo: ask the user which login reviews here and rerun with
--reviewer. Python 3.11+, stdlib only; needs git and an authenticated gh.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import git_run  # noqa: E402  (the bundle's runner, in skills/git/scripts)

git_run.use('push-branch', 'open-pr', 'approve-pr', 'archive-tag', 'merge-pr', 'prune-branch')
import approve_pr  # noqa: E402
import archive_tag  # noqa: E402
import merge_pr  # noqa: E402
import open_pr  # noqa: E402
import prune_branch  # noqa: E402
import push_branch  # noqa: E402

NO_REVIEWER = approve_pr.NO_REVIEWER


def tag(repo, pr, dry):
    name = archive_tag.archive(repo.branch, pr.get('title') or repo.branch, True, f'origin/{repo.base}',
                               extra=(f'PR: {pr["url"]}',), dry=dry)
    if not name:
        return 'no commits of its own; no tag'
    return archive_tag.push_tag(name, dry=dry)


def run(args):
    dry = args.dry_run
    step = git_run.step
    repo = git_run.preflight()
    step('preflight', f'{repo.branch} -> {repo.base} in {repo.slug}, as {repo.author}')
    login, token = approve_pr.reviewer(repo, args.reviewer, dry)
    step('reviewer', login)
    step('push', push_branch.push(repo, dry))
    pr, said = open_pr.pull_request(repo, args.title, args.body_file, dry)
    step('pr', said)
    step('review', approve_pr.review(pr, login, token, dry))
    step('tag', tag(repo, pr, dry))
    step('merge', merge_pr.merge(pr, dry))
    step('prune', prune_branch.prune(repo, dry))
    print(('would land ' if dry else 'landed ') + pr['url'])


def configure(parser):
    parser.prog = 'ai-dotfiles approve'
    parser.add_argument('--title', help='the PR title, when no PR is open for the branch')
    parser.add_argument('--body-file', help='the PR body (pr skill), when no PR is open for the branch')
    parser.add_argument('--reviewer', metavar='LOGIN', help='the GitHub login that approves; verified, then cached')


def main(argv=None):
    return git_run.cli('approve', __doc__, run, configure, argv)


if __name__ == '__main__':
    sys.exit(main())
