#!/usr/bin/env python3
"""approve: land a reviewed branch: push, PR, approval, merge, archive tag, branch gone.

  approve [--title T --body-file F] [--reviewer LOGIN] [--dry-run]   land the current branch
  approve reviewer [LOGIN | --unset]                                show, set or clear this repo's reviewer

The user has reviewed the branch and said "approve"; the commits and the PR body are already
written. Each step is skipped when it is already done, so a run that stopped can be rerun:

  1. preflight    a branch other than the base, no tracked changes, commits ahead of the base
  2. reviewer     `git config --local approve.reviewer`, or --reviewer LOGIN verified and cached:
                  LOGIN has a `gh auth` token, is not the PR's author, and can read the repo
  3. push         the branch to origin (a remote branch at another commit stops the run)
  4. pr           the open PR for the branch, or a new one from --title and --body-file
  5. review       an approval as the reviewer, through that account's token
  6. tag          annotated `archive/<branch without type/>` at the branch tip, pushed
  7. merge        a merge commit
  8. cleanup      base checked out and pulled; branch deleted locally and on origin

Nothing is undone on failure: the run stops, names the step, and exits 1. Exit 3 means no
reviewer is known for this repo: ask the user which login reviews here and rerun with
--reviewer. The reviewer is never invited to a repository by this script.
Python 3.11+, stdlib only; needs git and an authenticated gh.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import datetime as dt
import json
import os
import re
import subprocess
import sys

KEY = 'approve.reviewer'
NO_REVIEWER = 3
TYPE_PREFIX = re.compile(r'^[a-z]+/')
NOT_MERGEABLE = ('DIRTY', 'BLOCKED', 'BEHIND')
APPROVAL = 'Approved: the owner reviewed this branch locally and said so.'


class Stop(Exception):
    """The run stops here; the message names the step and the fix."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def sh(args, env=None):
    """Run a command; (exit code, stdout, stderr), never raising."""
    full = dict(os.environ, **env) if env else None
    try:
        done = subprocess.run(args, env=full, capture_output=True, text=True)
    except OSError as error:
        return 127, '', str(error)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def out(args, env=None, what=None):
    """stdout of a read-only command; Stop when it fails."""
    code, stdout, stderr = sh(args, env)
    if code != 0:
        raise Stop(f'{what or " ".join(args[:2])}: {stderr or stdout or f"exit {code}"}')
    return stdout


def act(args, dry, env=None):
    """A command that changes something: printed in a dry run, otherwise run and checked."""
    if dry:
        print('   would  ' + ' '.join(a if ' ' not in a else repr(a) for a in args))
        return
    code, stdout, stderr = sh(args, env)
    if code != 0:
        raise Stop(f'{" ".join(args[:2])}: {stderr or stdout or f"exit {code}"}')


@dataclass
class Repo:
    base: str          # the default branch, e.g. main
    branch: str        # the branch to land
    tip: str           # its commit
    slug: str          # owner/name on GitHub
    author: str        # the gh login that opens the PR


# --- steps -----------------------------------------------------------------------------------

def github():
    slug = out(['gh', 'repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'], what='gh repo view')
    author = out(['gh', 'api', 'user', '-q', '.login'], what='gh api user')
    return slug, author


def preflight():
    if sh(['git', 'rev-parse', '--is-inside-work-tree'])[0] != 0:
        raise Stop('preflight: not in a git repository')
    branch = out(['git', 'branch', '--show-current'])
    if not branch:
        raise Stop('preflight: detached HEAD; check out the branch to land')
    code, head, _ = sh(['git', 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD'])
    base = head.split('/', 1)[1] if code == 0 and '/' in head else 'main'
    if branch == base:
        raise Stop(f'preflight: on {base}; the work to land must be on its own branch')
    if out(['git', 'status', '--porcelain', '--untracked-files=no']):
        raise Stop('preflight: tracked changes are not committed; commit them first (small-commits)')
    out(['git', 'fetch', '-q', 'origin', base], what='git fetch')
    if not out(['git', 'rev-list', f'origin/{base}..HEAD']):
        raise Stop(f'preflight: no commits ahead of origin/{base}; nothing to land')
    slug, author = github()
    return Repo(base, branch, out(['git', 'rev-parse', 'HEAD']), slug, author)


def cached_reviewer():
    code, login, _ = sh(['git', 'config', '--local', KEY])
    return login if code == 0 and login else None


def verify_reviewer(login, repo):
    """The reviewer's token, once the account is not the author and can read the repo."""
    if login == repo.author:
        raise Stop(f'reviewer: {login} opens the PR; GitHub refuses self-approval. Name another account')
    code, token, stderr = sh(['gh', 'auth', 'token', '--user', login])
    if code != 0 or not token:
        raise Stop(f'reviewer: no gh token for {login} ({stderr}); `gh auth login` as that account first')
    env = {'GH_TOKEN': token}
    whoami = out(['gh', 'api', 'user', '-q', '.login'], env, what=f'gh api user as {login}')
    if whoami != login:
        raise Stop(f'reviewer: the token for {login} belongs to {whoami}')
    code, _, stderr = sh(['gh', 'api', f'repos/{repo.slug}', '-q', '.id'], env)
    if code != 0:
        why = stderr.splitlines()[0] if stderr else f'exit {code}'
        raise Stop(f'reviewer: {login} cannot read {repo.slug} ({why}). Invite that account as a '
                   f'collaborator (triage is enough), accept the invite, then rerun')
    return token


def reviewer(repo, wanted, dry):
    login = wanted or cached_reviewer()
    if not login:
        raise Stop(f'reviewer: none cached for {repo.slug}. Ask the user which GitHub login reviews here, '
                   f'then rerun with --reviewer <login>', NO_REVIEWER)
    token = verify_reviewer(login, repo)
    if login != cached_reviewer():
        act(['git', 'config', '--local', KEY, login], dry)
    return login, token


def push(repo, dry):
    code, remote, _ = sh(['git', 'rev-parse', '--verify', '-q', f'refs/remotes/origin/{repo.branch}'])
    if code == 0 and remote == repo.tip:
        return 'already pushed'
    if code == 0 and sh(['git', 'merge-base', '--is-ancestor', remote, repo.tip])[0] != 0:
        raise Stop(f'push: origin/{repo.branch} is at {remote[:7]}, not behind HEAD; reconcile first')
    act(['git', 'push', '-q', '-u', 'origin', repo.branch], dry)
    return 'pushed'


def find_pr(repo):
    text = out(['gh', 'pr', 'list', '--head', repo.branch, '--state', 'all', '--limit', '5',
                '--json', 'number,url,state,title'], what='gh pr list')
    prs = [pr for pr in json.loads(text or '[]') if pr['state'] != 'CLOSED']
    return prs[0] if prs else None


def pull_request(repo, title, body_file, dry):
    pr = find_pr(repo)
    if pr:
        return pr, f'#{pr["number"]} exists ({pr["state"].lower()})'
    if not title or not body_file:
        raise Stop('pr: no open PR for this branch; pass --title and --body-file (pr skill) to open one')
    if not os.path.isfile(body_file):
        raise Stop(f'pr: body file not found: {body_file}')
    create = ['gh', 'pr', 'create', '--base', repo.base, '--head', repo.branch, '--title', title, '--body-file', body_file]
    if dry:
        act(create, dry)
        return {'number': 0, 'url': '(dry run)', 'state': 'OPEN', 'title': title}, 'would open'
    url = out(create, what='gh pr create')
    pr = find_pr(repo) or {'number': int(url.rstrip('/').rsplit('/', 1)[-1]), 'url': url, 'state': 'OPEN', 'title': title}
    return pr, f'#{pr["number"]} opened'


def review(pr, login, token, dry):
    if pr['state'] == 'MERGED':
        return 'merged already'
    if pr['number']:
        approvers = out(['gh', 'pr', 'view', str(pr['number']), '--json', 'reviews', '-q',
                         '[.reviews[] | select(.state == "APPROVED") | .author.login] | join(" ")'], what='gh pr view')
        if login in approvers.split():
            return f'approved by {login} already'
    act(['gh', 'pr', 'review', str(pr['number']), '--approve', '--body', APPROVAL], dry, env={'GH_TOKEN': token})
    return f'approved as {login}'


def tag_name(branch):
    return 'archive/' + TYPE_PREFIX.sub('', branch).replace('/', '-')


def tag_message(repo, title, today=None):
    day = (today or dt.date.today()).strftime('%b %-d, %Y')
    return f'Archive of branch {repo.branch} ({day}; {title}), kept before the branch was merged and deleted.'


def tag(repo, title, dry):
    name = tag_name(repo.branch)
    code, at, _ = sh(['git', 'rev-list', '-n', '1', name])
    if code == 0 and at and at != repo.tip:
        raise Stop(f'tag: {name} exists at {at[:7]}, not at this branch tip; move or rename it first')
    if code != 0 or not at:
        act(['git', 'tag', '-a', name, repo.tip, '-m', tag_message(repo, title)], dry)
    if sh(['git', 'ls-remote', '--exit-code', '--tags', 'origin', name])[0] == 0:
        return f'{name} pushed already'
    act(['git', 'push', '-q', 'origin', name], dry)
    return f'{name} pushed'


def merge(pr, dry):
    if pr['state'] == 'MERGED':
        return 'merged already'
    if pr['number']:
        state = out(['gh', 'pr', 'view', str(pr['number']), '--json', 'mergeStateStatus', '-q', '.mergeStateStatus'])
        if state in NOT_MERGEABLE:
            raise Stop(f'merge: PR #{pr["number"]} is {state.lower()}; resolve that, then rerun')
    act(['gh', 'pr', 'merge', str(pr['number']), '--merge'], dry)
    return f'#{pr["number"]} merged'


def in_linked_worktree():
    return sh(['git', 'rev-parse', '--git-dir'])[1] != sh(['git', 'rev-parse', '--git-common-dir'])[1]


def cleanup(repo, dry):
    done = []
    linked = in_linked_worktree()
    if out(['git', 'branch', '--show-current']) == repo.branch:
        if linked:  # the base is checked out in the main checkout; another session may own it
            act(['git', 'checkout', '-q', '--detach', f'origin/{repo.base}'], dry)
            done.append(f'detached at origin/{repo.base}; pull {repo.base} in the main checkout yourself')
        else:
            act(['git', 'checkout', '-q', repo.base], dry)
            done.append(f'on {repo.base}')
    if not linked:
        act(['git', 'pull', '-q', '--ff-only', 'origin', repo.base], dry)
    if sh(['git', 'rev-parse', '--verify', '-q', f'refs/heads/{repo.branch}'])[0] == 0:
        act(['git', 'branch', '-q', '-D', repo.branch], dry)
        done.append('local branch deleted')
    if sh(['git', 'ls-remote', '--exit-code', '--heads', 'origin', repo.branch])[0] == 0:
        act(['git', 'push', '-q', 'origin', '--delete', repo.branch], dry)
        done.append('remote branch deleted')
    return ', '.join(done) or 'nothing left'


# --- the run -----------------------------------------------------------------------------------

def step(name, result):
    print(f'{name:<10} {result}')


def run(args):
    dry = args.dry_run
    repo = preflight()
    step('preflight', f'{repo.branch} -> {repo.base} in {repo.slug}, as {repo.author}')
    login, token = reviewer(repo, args.reviewer, dry)
    step('reviewer', login)
    step('push', push(repo, dry))
    pr, said = pull_request(repo, args.title, args.body_file, dry)
    step('pr', said)
    step('review', review(pr, login, token, dry))
    step('tag', tag(repo, pr.get('title') or repo.branch, dry))
    step('merge', merge(pr, dry))
    step('cleanup', cleanup(repo, dry))
    print(('would land ' if dry else 'landed ') + pr['url'])
    return 0


def cmd_reviewer(args):
    if args.unset:
        act(['git', 'config', '--local', '--unset', KEY], False)
        print('reviewer cleared')
        return 0
    if args.login:
        slug, author = github()
        verify_reviewer(args.login, Repo('', '', '', slug, author))
        act(['git', 'config', '--local', KEY, args.login], False)
    login = cached_reviewer()
    print(login or 'no reviewer cached for this repo')
    return 0 if login else NO_REVIEWER


def parser():
    top = argparse.ArgumentParser(prog='approve', description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    top.add_argument('--title', help='the PR title, when no PR is open for the branch')
    top.add_argument('--body-file', help='the PR body (pr skill), when no PR is open for the branch')
    top.add_argument('--reviewer', metavar='LOGIN', help='the GitHub login that approves; verified, then cached')
    top.add_argument('--dry-run', action='store_true', help='print what would change; read-only commands still run')
    top.set_defaults(run=run)
    sub = top.add_subparsers(dest='command')
    rev = sub.add_parser('reviewer', help="this repo's cached reviewer: show, set LOGIN (verified), or --unset")
    rev.add_argument('login', nargs='?')
    rev.add_argument('--unset', action='store_true')
    rev.set_defaults(run=cmd_reviewer)
    return top


def main(argv=None):
    args = parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    try:
        return args.run(args)
    except Stop as stop:
        print(f'approve stopped at {stop}', file=sys.stderr)
        return stop.code


if __name__ == '__main__':
    sys.exit(main())
