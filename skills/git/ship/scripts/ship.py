#!/usr/bin/env python3
"""ship: finish the work of a worktree: checks, push as <type>/<slug>, PR, worktree deleted.

  ai-dotfiles ship --title T --body-file F [--dry-run]     run from inside the worktree

For an agent that worked in a worktree made by `ai-dotfiles worktree new <type>/<slug>` (no
branch) and has committed. In order, each skipped when already done, so a stopped run can be
rerun from the same worktree:

  preflight   committed (no tracked changes), commits ahead of the base           (git_run)
  checks      the commands of the repo's AGENTS.md "Verify" block, in the worktree; the first
              failure stops the run before anything is pushed
  push        HEAD as the new branch <type>/<slug>; a branch of that name already on origin at
              another commit is refused                                           (git push)
  pr          the PR against the base from --title and --body-file, or the one already open
                                                                                  (open-pr)
  worktree    deleted once the PR exists (`worktree shipped`): the session's record of it is
              cleared, so its next first edit starts a new task                  (worktree-guard)

Prints the PR's URL, then where the session is: the main checkout. The archive tag is not made
here: approve makes it at the PR's head. Nothing is undone on failure. Python 3.11+, stdlib
only; needs git and an authenticated gh.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import git_run  # noqa: E402  (the bundle's runner, in skills/git/scripts)
from git_run import Stop  # noqa: E402

git_run.use('open-pr')
import open_pr  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'worktree-guard' / 'scripts'))
import worktree_guard as guard  # noqa: E402  (the sidecar of a worktree, and its removal)

GUARD = Path(guard.__file__).resolve()
HEADING = re.compile(r'^#{1,6}\s+(.*?)\s*$')
FENCE = re.compile(r'^\s*```\s*(bash|sh|shell|zsh)?\s*$')
COMMENT = re.compile(r'\s+#.*$')


def checks_of(text):
    """The commands in the fenced blocks under AGENTS.md's "Verify" heading, comments dropped."""
    commands, in_verify, in_fence = [], False, False
    for line in text.splitlines():
        if FENCE.match(line) or (in_fence and line.strip() == '```'):
            in_fence = not in_fence
        elif not in_fence:
            heading = HEADING.match(line)
            if heading:
                in_verify = heading.group(1).lower() == 'verify'
        elif in_verify:
            command = COMMENT.sub('', line).strip()
            if command and not command.startswith('#'):
                commands.append(command)
    return commands


def checks(top, dry):
    """Run the repo's checks in the worktree; the first failure stops the run."""
    agents = Path(top) / 'AGENTS.md'
    commands = checks_of(agents.read_text()) if agents.is_file() else []
    if not commands:
        return 'none: AGENTS.md has no Verify block'
    for command in commands:
        if dry:
            git_run.act(['bash', '-c', command], dry)
            continue
        code, stdout, stderr = git_run.sh(['bash', '-c', command], cwd=str(top))
        if code != 0:
            last = (stderr or stdout or f'exit {code}').splitlines()[-1]
            raise Stop(f'checks: `{command}` failed (exit {code}): {last}')
    return f'{len(commands)} passed' if not dry else f'{len(commands)} to run'


def push(repo, dry):
    """HEAD as the new branch; a rerun after a stop finds it at the same commit and moves on."""
    listing = git_run.out(['git', 'ls-remote', '--heads', 'origin', f'refs/heads/{repo.branch}'], what='git ls-remote')
    found = [line.split() for line in listing.splitlines()]
    remote = next((sha for sha, ref in found if ref == f'refs/heads/{repo.branch}'), '')
    if remote == repo.tip:
        return 'already pushed'
    if remote:
        raise Stop(f'push: origin already has {repo.branch} at {remote[:7]}; name this work differently '
                   f'(ai-dotfiles worktree new <type>/<slug>)')
    git_run.act(['git', 'push', '-q', 'origin', f'HEAD:refs/heads/{repo.branch}'], dry)
    return f'would push {repo.branch}' if dry else f'{repo.branch} pushed'


def where():
    """(worktree folder, main checkout, work name): this run's worktree and what made it."""
    top = Path(git_run.out(['git', 'rev-parse', '--show-toplevel'], what='git rev-parse')).resolve()
    common = Path(git_run.out(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                              what='git rev-parse')).resolve()
    main = common.parent if common.name == '.git' else top
    meta = guard.read_meta(main, top.name) if top != main else None
    if not meta or not meta.get('work'):
        raise Stop(f'ship: {top.name} was not made by `ai-dotfiles worktree new`; run ship from the worktree it made')
    return top, main, meta['work']


def run(args):
    dry, step = args.dry_run, git_run.step
    top, main, work = where()
    repo = git_run.preflight(work)
    step('preflight', f'{repo.branch} -> {repo.base} in {repo.slug}, as {repo.author}')
    if not open_pr.find_pr(repo):
        if not repo.ahead:
            raise Stop(f'ship: nothing to ship: no commits ahead of origin/{repo.base} and no PR for {work}')
        if not (args.title and args.body_file):
            raise Stop(f'ship: no PR for {work} yet; pass --title and --body-file (pr skill)')
        if not os.path.isfile(args.body_file):
            raise Stop(f'ship: body file not found: {args.body_file}')
    step('checks', checks(top, dry))
    step('push', push(repo, dry))
    pr, said = open_pr.pull_request(repo, args.title, args.body_file, dry)
    step('pr', said)
    command = ['python3', str(GUARD), 'shipped', top.name, '--repo', str(main)]
    if dry:
        git_run.act(command, dry)
        print(f'would ship {pr["url"]}')
        return
    code, stdout, stderr = git_run.sh(command, cwd=str(main))
    print(f'shipped {pr["url"]}')
    if code != 0:
        raise Stop(f'worktree: {(stderr or stdout or f"exit {code}").replace("worktree-guard: ", "")}; '
                   f'the PR is open; remove it with ai-dotfiles worktree rm {top.name} once it is clean')
    step('worktree', stdout.replace('worktree-guard: ', '') or f'{top.name} deleted')
    print(f'Back in {main}. Claude Code: call ExitWorktree (action keep) or cd there; the next first '
          f'edit starts a new task.')


def configure(parser):
    parser.prog = 'ai-dotfiles ship'
    parser.add_argument('--title', help='the PR title, when no PR is open for the work')
    parser.add_argument('--body-file', help='the PR body (pr skill), when no PR is open for the work')


def main(argv=None):
    return git_run.cli('ship', __doc__, run, configure, argv)


if __name__ == '__main__':
    sys.exit(main())
