#!/usr/bin/env python3
"""approve-pr: approve the branch's PR as this repo's reviewer account.

  ai-dotfiles git review [--reviewer LOGIN] [--dry-run]   approve the open PR
  ai-dotfiles git reviewer [LOGIN | --unset]              show, set or clear this repo's reviewer

GitHub refuses self-approval, so each repo names its own reviewer: a second gh login, cached
in `git config --local approve.reviewer`. A login is cached only once it has a `gh auth`
token, is not the PR's author, and can read the repo. Exit 3: none cached; ask the user which
login reviews here and rerun with --reviewer. This script never invites an account.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import git_run  # noqa: E402  (the bundle's runner, in skills/git/scripts)
from git_run import Stop  # noqa: E402

git_run.use('open-pr')
import open_pr  # noqa: E402

KEY = 'approve.reviewer'
NO_REVIEWER = 3
APPROVAL = 'Approved: the owner reviewed this branch locally and said so.'


def cached_reviewer():
    code, login, _ = git_run.sh(['git', 'config', '--local', KEY])
    return login if code == 0 and login else None


def verify_reviewer(login, repo):
    """The reviewer's token, once the account is not the author and can read the repo."""
    if login == repo.author:
        raise Stop(f'reviewer: {login} opens the PR; GitHub refuses self-approval. Name another account')
    code, token, stderr = git_run.sh(['gh', 'auth', 'token', '--user', login])
    if code != 0 or not token:
        raise Stop(f'reviewer: no gh token for {login} ({stderr}); `gh auth login` as that account first')
    env = {'GH_TOKEN': token}
    whoami = git_run.out(['gh', 'api', 'user', '-q', '.login'], env, what=f'gh api user as {login}')
    if whoami != login:
        raise Stop(f'reviewer: the token for {login} belongs to {whoami}')
    code, _, stderr = git_run.sh(['gh', 'api', f'repos/{repo.slug}', '-q', '.id'], env)
    if code != 0:
        why = stderr.splitlines()[0] if stderr else f'exit {code}'
        raise Stop(f'reviewer: {login} cannot read {repo.slug} ({why}). Invite that account as a '
                   f'collaborator (triage is enough), accept the invite, then rerun')
    return token


def reviewer(repo, wanted, dry):
    """(login, token) of the repo's reviewer: --reviewer, else the cache; verified, then cached."""
    login = wanted or cached_reviewer()
    if not login:
        raise Stop(f'reviewer: none cached for {repo.slug}. Ask the user which GitHub login reviews here, '
                   f'then rerun with --reviewer <login>', NO_REVIEWER)
    token = verify_reviewer(login, repo)
    if login != cached_reviewer():
        git_run.act(['git', 'config', '--local', KEY, login], dry)
    return login, token


def review(pr, login, token, dry):
    if pr['state'] == 'MERGED':
        return 'merged already'
    if pr['number']:
        approvers = git_run.out(['gh', 'pr', 'view', str(pr['number']), '--json', 'reviews', '-q',
                                 '[.reviews[] | select(.state == "APPROVED") | .author.login] | join(" ")'],
                                what='gh pr view')
        if login in approvers.split():
            return f'approved by {login} already'
    git_run.act(['gh', 'pr', 'review', str(pr['number']), '--approve', '--body', APPROVAL], dry, env={'GH_TOKEN': token})
    return f'approved as {login}'


def run_review(args):
    repo = git_run.preflight()
    login, token = reviewer(repo, args.reviewer, args.dry_run)
    git_run.step('reviewer', login)
    git_run.step('review', review(open_pr.found(repo), login, token, args.dry_run))


def run_reviewer(args):
    if args.unset:
        git_run.act(['git', 'config', '--local', '--unset', KEY], args.dry_run)
        print('reviewer cleared')
        return 0
    if args.login:
        slug, author = git_run.github()
        verify_reviewer(args.login, git_run.Repo('', '', '', slug, author))
        git_run.act(['git', 'config', '--local', KEY, args.login], args.dry_run)
    login = cached_reviewer()
    print(login or 'no reviewer cached for this repo')
    return 0 if login else NO_REVIEWER


def main(argv=None):
    return git_run.cli('review', __doc__, run_review,
                       lambda p: p.add_argument('--reviewer', metavar='LOGIN', help='the login that approves; verified, then cached'),
                       argv)


def main_reviewer(argv=None):
    def configure(parser):
        parser.add_argument('login', nargs='?', help='the login to verify and cache')
        parser.add_argument('--unset', action='store_true', help='clear the cached reviewer')
    return git_run.cli('reviewer', __doc__, run_reviewer, configure, argv)


if __name__ == '__main__':
    sys.exit(main_reviewer(sys.argv[2:]) if sys.argv[1:2] == ['reviewer'] else main())
