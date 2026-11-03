#!/usr/bin/env python3
"""open-pr: the open pull request for the branch being landed, or a new one.

  ai-dotfiles git pr [--title T --body-file F] [--dry-run]

An open or merged PR for the branch is reused; otherwise one is opened against the base from
--title and --body-file (the body written per the pr skill). Prints the PR's URL.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import git_run  # noqa: E402  (the bundle's runner, in skills/git/scripts)
from git_run import Stop  # noqa: E402


def find_pr(repo):
    """The branch's open or merged PR as {number, url, state, title}; None when there is none."""
    text = git_run.out(['gh', 'pr', 'list', '--head', repo.branch, '--state', 'all', '--limit', '5',
                        '--json', 'number,url,state,title'], what='gh pr list')
    prs = [pr for pr in json.loads(text or '[]') if pr['state'] != 'CLOSED']
    return prs[0] if prs else None


def pull_request(repo, title, body_file, dry):
    """(the PR, what was done)."""
    pr = find_pr(repo)
    if pr:
        return pr, f'#{pr["number"]} exists ({pr["state"].lower()})'
    if not repo.ahead:
        raise Stop(f'pr: no commits ahead of origin/{repo.base} and no PR; nothing to land')
    if not title or not body_file:
        raise Stop('pr: no open PR for this branch; pass --title and --body-file (pr skill) to open one')
    if not os.path.isfile(body_file):
        raise Stop(f'pr: body file not found: {body_file}')
    create = ['gh', 'pr', 'create', '--base', repo.base, '--head', repo.branch, '--title', title, '--body-file', body_file]
    if dry:
        git_run.act(create, dry)
        return {'number': 0, 'url': '(dry run)', 'state': 'OPEN', 'title': title}, 'would open'
    url = git_run.out(create, what='gh pr create')
    pr = find_pr(repo) or {'number': int(url.rstrip('/').rsplit('/', 1)[-1]), 'url': url, 'state': 'OPEN', 'title': title}
    return pr, f'#{pr["number"]} opened'


def found(repo):
    """The branch's PR, or Stop: for the steps that need one to exist."""
    pr = find_pr(repo)
    if not pr:
        raise Stop(f'pr: no open PR for {repo.branch}; open one first (ai-dotfiles git pr)')
    return pr


def run(args):
    pr, said = pull_request(git_run.preflight(), args.title, args.body_file, args.dry_run)
    git_run.step('pr', said)
    print(pr['url'])


def configure(parser):
    parser.add_argument('--title', help='the PR title, when no PR is open for the branch')
    parser.add_argument('--body-file', help='the PR body (pr skill), when no PR is open for the branch')


def main(argv=None):
    return git_run.cli('pr', __doc__, run, configure, argv)


if __name__ == '__main__':
    sys.exit(main())
