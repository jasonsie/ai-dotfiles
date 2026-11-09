#!/usr/bin/env python3
"""ship: finish the work of a worktree: checks, push as <type>/<slug>, PR, worktree deleted.

  ai-dotfiles ship --title T --body-file F [--work <type>/<slug>] [--no-checks] [--dry-run]     run from inside the worktree

For an agent that worked in a worktree made by `ai-dotfiles worktree new <type>/<slug>` (no
branch) and has committed. In order, each skipped when already done, so a stopped run can be
rerun from the same worktree:

  preflight   committed (no tracked changes), commits ahead of the base           (git_run)
  checks      the commands of the repo's AGENTS.md "Verify" block, in the worktree; the first
              failure stops the run before anything is pushed, and so does a repo with no
              Verify block, unless --no-checks is passed
  push        HEAD as the new branch <type>/<slug>; a branch of that name already on origin at
              another commit is refused                                           (git push)
  pr          the PR against the base from --title and --body-file, or the one already open
                                                                                  (open-pr)
  worktree    deleted once the PR exists (`worktree shipped`): the session's record of it is
              cleared, so its next first edit starts a new task                  (worktree-guard)

A worktree made by `ai-dotfiles worktree pr <n>` fixes that open PR: its push goes to the PR's own
branch, only as a fast-forward of origin's (a branch that moved on, or a push origin refuses, stops
the run), no PR is opened, and the worktree is deleted the same way. Another worktree can never
push to a branch already on origin.

A worktree whose name is not <type>/<slug> (made by `claude -w foo` or a subagent) is never pushed
as that name: --work <type>/<slug> says what to ship it as, and ship stops without it.

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


def checks(top, dry, skip=False):
    """Run the repo's checks in the worktree; the first failure stops the run. A repo with no
    Verify block stops it too, unless `skip` (--no-checks): shipping unchecked is a choice."""
    if skip:
        return 'skipped (--no-checks)'
    agents = Path(top) / 'AGENTS.md'
    commands = checks_of(agents.read_text()) if agents.is_file() else []
    if not commands:
        raise Stop('checks: AGENTS.md has no Verify block; add one, or pass --no-checks to ship without checks')
    for command in commands:
        if dry:
            git_run.act(['bash', '-c', command], dry)
            continue
        code, stdout, stderr = git_run.sh(['bash', '-c', command], cwd=str(top))
        if code != 0:
            last = (stderr or stdout or f'exit {code}').splitlines()[-1]
            raise Stop(f'checks: `{command}` failed (exit {code}): {last}')
    return f'{len(commands)} passed' if not dry else f'{len(commands)} to run'


def on_origin(branch):
    """The commit origin has for `branch`, or '' when it has none."""
    listing = git_run.out(['git', 'ls-remote', '--heads', 'origin', f'refs/heads/{branch}'], what='git ls-remote')
    found = [line.split() for line in listing.splitlines()]
    return next((sha for sha, ref in found if ref == f'refs/heads/{branch}'), '')


def push(repo, dry):
    """HEAD as the new branch; a rerun after a stop finds it at the same commit and moves on."""
    remote = on_origin(repo.branch)
    if remote == repo.tip:
        return 'already pushed'
    if remote:
        raise Stop(f'push: origin already has {repo.branch} at {remote[:7]}; name this work differently '
                   f'(ai-dotfiles worktree new <type>/<slug>)')
    git_run.act(['git', 'push', '-q', 'origin', f'HEAD:refs/heads/{repo.branch}'], dry)
    return f'would push {repo.branch}' if dry else f'{repo.branch} pushed'


def update(repo, dry):
    """HEAD onto the PR's own branch (a worktree `worktree pr` made): the one case a branch already
    on origin may be pushed to, and only fast-forward: a branch that moved on stops the run."""
    remote = on_origin(repo.branch)
    if remote == repo.tip:
        return 'already pushed'
    if not remote:
        raise Stop(f'push: origin no longer has {repo.branch}; the PR is gone or its branch was deleted')
    git_run.act(['git', 'fetch', '-q', 'origin', repo.branch], dry)
    if git_run.sh(['git', 'merge-base', '--is-ancestor', remote, repo.tip])[0] != 0:
        raise Stop(f'push: origin has {repo.branch} at {remote[:7]}, which this worktree does not contain; '
                   f'merge or rebase it in, commit, and rerun')
    git_run.act(['git', 'push', '-q', 'origin', f'HEAD:refs/heads/{repo.branch}'], dry)
    return f'would update {repo.branch}' if dry else f'{repo.branch} updated'


def where(chosen=None):
    """(worktree folder, main checkout, its record, work name): this run's worktree, what made it
    and the branch name it ships under. A work name that is not <type>/<slug> (a worktree Claude's
    `-w` or a subagent made through its create hook is named `foo`) is never a branch name: `chosen`
    (--work) names it. A PR fix keeps the PR's own branch."""
    top = Path(git_run.out(['git', 'rev-parse', '--show-toplevel'], what='git rev-parse')).resolve()
    main = guard.main_of(top)
    meta = guard.read_meta(main, top.name) if top != main else None
    if not meta or not meta.get('work'):
        raise Stop(f'ship: {top.name} was not made by `ai-dotfiles worktree new`; run ship from the worktree it made')
    work = meta['work']
    if meta.get('pr') or guard.WORK_NAME.fullmatch(work):
        if chosen and chosen != work:
            raise Stop(f"ship: this worktree's work is already {work}; --work is only for a name that is not "
                       f"<type>/<slug>")
        return top, main, meta, work
    if not chosen:
        raise Stop(f'ship: the work name {work!r} is not <type>/<slug>; pass --work <type>/<slug> '
                   f'(for example fix/prune-worktrees) to name the branch')
    if not guard.WORK_NAME.fullmatch(chosen):
        raise Stop(f'ship: --work {chosen!r} is not <type>/<slug> (lowercase letters, digits and hyphens)')
    return top, main, meta, chosen


def run(args):
    dry, step = args.dry_run, git_run.step
    top, main, meta, work = where(args.work)
    number = meta.get('pr')
    repo = git_run.preflight(work)
    step('preflight', f'{repo.branch} -> {repo.base} in {repo.slug}, as {repo.author}')
    if number:
        pr = open_pr.find_pr(repo)
        if not pr or pr['state'] != 'OPEN' or pr['number'] != number:
            raise Stop(f'ship: PR #{number} is not open any more; nothing to update (remove the worktree, or '
                       f'start again with worktree new)')
        if repo.tip == meta.get('base'):
            raise Stop(f'ship: nothing to ship: no commit on top of origin/{work}')
    elif not open_pr.find_pr(repo):
        if not repo.ahead:
            raise Stop(f'ship: nothing to ship: no commits ahead of origin/{repo.base} and no PR for {work}')
        if not (args.title and args.body_file):
            raise Stop(f'ship: no PR for {work} yet; pass --title and --body-file (pr skill)')
        if not os.path.isfile(args.body_file):
            raise Stop(f'ship: body file not found: {args.body_file}')
    step('checks', checks(top, dry, args.no_checks))
    step('push', (update if number else push)(repo, dry))
    if number:
        step('pr', f'#{number} updated')
    else:
        pr, said = open_pr.pull_request(repo, args.title, args.body_file, dry)
        step('pr', said)
    if dry:
        print(f'   would  delete the worktree {top.name} (worktree shipped)')
        print(f'would ship {pr["url"]}')
        return
    done, lines = guard.shipped(main, top.name)
    said = ' '.join(lines).replace('worktree-guard: ', '')
    print(f'shipped {pr["url"]}')
    if not done:
        raise Stop(f'worktree: {said}; the PR is open; remove it with ai-dotfiles worktree rm {top.name} once '
                   f'it is clean')
    step('worktree', said or f'{top.name} deleted')
    print(f'Back in {main}. Claude Code: call ExitWorktree (action keep) or cd there; the next first '
          f'edit starts a new task.')


def configure(parser):
    parser.prog = 'ai-dotfiles ship'
    parser.add_argument('--no-checks', action='store_true',
                        help="ship without running checks; needed when the repo's AGENTS.md has no Verify block")
    parser.add_argument('--work', metavar='<type>/<slug>',
                        help='the branch to ship as, when the worktree is named something else (made by claude -w or a subagent)')
    parser.add_argument('--title', help='the PR title, when no PR is open for the work (not for a PR fix)')
    parser.add_argument('--body-file', help='the PR body (pr skill), when no PR is open for the work')


def main(argv=None):
    return git_run.cli('ship', __doc__, run, configure, argv)


if __name__ == '__main__':
    sys.exit(main())
