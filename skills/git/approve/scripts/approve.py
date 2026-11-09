#!/usr/bin/env python3
"""approve: land a reviewed branch: the six git step skills, in order, as one resumable run.

  ai-dotfiles approve [--title T --body-file F] [--reviewer LOGIN] [--dry-run]   the branch checked out here
  ai-dotfiles approve <n> [--reviewer LOGIN] [--dry-run]                         PR #n, from any session

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

With a PR number nothing is local: no branch, no worktree, no preflight. The PR is read from
GitHub, then, each step skipped when done:

  reviewer    as above, checked against the PR's author               (approve-pr)
  review      an approval as the reviewer                             (approve-pr)
  tag         archive/<name> at the PR's head, pushed                 (archive-tag)
  merge       a merge commit                                          (merge-pr)
  branch      the branch deleted on origin                            (prune-branch)
  main        the main checkout fast-forwarded to origin/<base>, only when git can without
              touching uncommitted files (never a stash or reset); otherwise skipped, with why

Nothing is undone on failure: the run stops, names the step, and exits 1. Exit 3 means no
reviewer is known for this repo: ask the user which login reviews here and rerun with
--reviewer. Python 3.11+, stdlib only; needs git and an authenticated gh.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import git_run  # noqa: E402  (the bundle's runner, in skills/git/scripts)
from git_run import Stop  # noqa: E402

git_run.use('push-branch', 'open-pr', 'approve-pr', 'archive-tag', 'merge-pr', 'prune-branch')
import approve_pr  # noqa: E402
import archive_tag  # noqa: E402
import merge_pr  # noqa: E402
import open_pr  # noqa: E402
import prune_branch  # noqa: E402
import push_branch  # noqa: E402

NO_REVIEWER = approve_pr.NO_REVIEWER


def tag(repo, pr, dry, ref=None):
    name = archive_tag.archive(repo.branch, pr.get('title') or repo.branch, True, f'origin/{repo.base}',
                               extra=(f'PR: {pr["url"]}',), dry=dry, ref=ref)
    if not name:
        return 'no commits of its own; no tag'
    return archive_tag.push_tag(name, dry=dry)


def pull_request(number):
    """(Repo, pr) from GitHub's view of PR #number; the PR's head is fetched so it can be tagged."""
    fields = 'number,url,state,title,headRefName,baseRefName,headRefOid,author'
    pr = json.loads(git_run.out(['gh', 'pr', 'view', str(number), '--json', fields], what='gh pr view'))
    if pr['state'] == 'CLOSED':
        raise Stop(f'pr: PR #{number} is closed, not merged; reopen it or open another')
    base = pr['baseRefName']
    git_run.out(['git', 'fetch', '-q', 'origin', base, f'refs/pull/{number}/head'], what='git fetch')
    slug, _ = git_run.github()
    return git_run.Repo(base, pr['headRefName'], pr['headRefOid'], slug, pr['author']['login']), pr


def run_number(args):
    if args.title or args.body_file:
        raise Stop('approve: --title and --body-file belong to the one-run form (no PR number)')
    dry = args.dry_run
    step = git_run.step
    repo, pr = pull_request(args.pr)
    step('pr', f'#{pr["number"]} {pr["state"].lower()}: {repo.branch} -> {repo.base} in {repo.slug}, by {repo.author}')
    login, token = approve_pr.reviewer(repo, args.reviewer, dry)
    step('reviewer', login)
    step('review', approve_pr.review(pr, login, token, dry))
    step('tag', tag(repo, pr, dry, ref=repo.tip))
    step('merge', merge_pr.merge(pr, dry))
    step('branch', 'deleted on origin' if prune_branch.delete_remote(repo.branch, dry) else 'gone already')
    step('main', prune_branch.fast_forward(repo.base, dry))
    print(('would land ' if dry else 'landed ') + pr['url'])


def run(args):
    if args.pr:
        return run_number(args)
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
    parser.add_argument('pr', nargs='?', type=int, help='land this PR number, from any session; without it, the branch checked out here')
    parser.add_argument('--title', help='the PR title, when no PR is open for the branch')
    parser.add_argument('--body-file', help='the PR body (pr skill), when no PR is open for the branch')
    parser.add_argument('--reviewer', metavar='LOGIN', help='the GitHub login that approves; verified, then cached')


def main(argv=None):
    return git_run.cli('approve', __doc__, run, configure, argv)


if __name__ == '__main__':
    sys.exit(main())
