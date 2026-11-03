#!/usr/bin/env python3
"""archive-tag: keep a branch's record as an annotated tag before the branch is deleted.

  ai-dotfiles git tag [--description TEXT] [--unmerged] [--dry-run]   tag the current branch, push it

The one archive format, shared by approve and worktree-guard. The name is
`archive/<branch without its first segment>` (`feat/a/b` -> `archive/a-b`); a name already
taken by another commit gets the date, then -2, -3; a tag already at the branch tip is reused,
so a rerun makes no second tag. The message:

  Archive of branch <branch> (<first to last commit date>; <description>), kept before the
  branch was merged and deleted.     (or: deleted unmerged.)

  <one line per caller, e.g. PR: <url> or Agent: ...>
"""
from __future__ import annotations

import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import git_run  # noqa: E402  (the bundle's runner, in skills/git/scripts)
from git_run import Stop  # noqa: E402


def stem(branch):
    return 'archive/' + (branch.split('/', 1)[1] if '/' in branch else branch).replace('/', '-')


def tag_name(branch, tip, cwd=None):
    """(name, already there): the tag at the tip under this branch's names, else the first free name."""
    today = time.strftime('%Y-%m-%d')
    base = stem(branch)
    for name in (base, f'{base}-{today}', *(f'{base}-{today}-{n}' for n in range(2, 100))):
        code, at, _ = git_run.sh(['git', 'rev-list', '-n', '1', name], cwd=cwd)
        if code != 0 or not at:
            return name, False
        if at == tip:
            return name, True
    raise Stop(f'tag: {base}-{today}-2 to -99 are all taken; delete some archive tags')


def day(text):
    stamp = time.strptime(text, '%Y-%m-%d')
    return time.strftime('%b', stamp) + f' {stamp.tm_mday}', stamp.tm_year


def span(base, branch, cwd=None):
    """'Oct 26, 2026' or 'Jul 31 to Oct 5, 2026' for the branch's own commits; '' for none."""
    code, text, _ = git_run.sh(['git', 'log', '--format=%ad', '--date=format:%Y-%m-%d', f'{base}..{branch}'], cwd=cwd)
    dates = text.split() if code == 0 else []
    if not dates:
        return ''
    (last, last_year), (first, first_year) = day(dates[0]), day(dates[-1])
    if (first, first_year) == (last, last_year):
        return f'{first}, {first_year}'
    if first_year == last_year:
        return f'{first} to {last}, {last_year}'
    return f'{first}, {first_year} to {last}, {last_year}'


def message(branch, when, description, merged, extra=()):
    text = (f"Archive of branch {branch} ({when}; {description}), kept before the branch was "
            f"{'merged and ' if merged else ''}deleted{'' if merged else ' unmerged'}.")
    return text + ('\n\n' + '\n'.join(extra) if extra else '')


def archive(branch, description, merged, base, cwd=None, extra=(), dry=False):
    """The archive tag's name, made at the branch tip when not there yet; None for a branch that is gone or has no commits of its own."""
    code, tip, _ = git_run.sh(['git', 'rev-parse', '--verify', '-q', f'{branch}^{{commit}}'], cwd=cwd)
    if code != 0 or not tip:
        return None
    name, there = tag_name(branch, tip, cwd)
    if there:
        return name
    when = span(base, branch, cwd)
    if not when:
        return None
    git_run.act(['git', 'tag', '-a', name, tip, '-m', message(branch, when, description, merged, extra)], dry, cwd=cwd)
    return name


def push_tag(name, cwd=None, dry=False):
    """Push the tag to origin unless it is there; Stop when the push fails."""
    if git_run.sh(['git', 'ls-remote', '--exit-code', '--tags', 'origin', name], cwd=cwd)[0] == 0:
        return f'{name} pushed already'
    git_run.act(['git', 'push', '-q', 'origin', f'refs/tags/{name}'], dry, cwd=cwd)
    return f'{name} pushed'


def run(args):
    repo = git_run.preflight()
    description = args.description or git_run.out(['git', 'log', '-1', '--format=%s', repo.branch])
    name = archive(repo.branch, description, not args.unmerged, f'origin/{repo.base}', dry=args.dry_run)
    if not name:
        raise Stop(f'tag: {repo.branch} has no commits of its own; nothing to archive')
    git_run.step('tag', push_tag(name, dry=args.dry_run))


def configure(parser):
    parser.add_argument('--description', help="the tag's one-line summary; default: the last commit's subject")
    parser.add_argument('--unmerged', action='store_true', help='the branch goes without being merged')


def main(argv=None):
    return git_run.cli('tag', __doc__, run, configure, argv)


if __name__ == '__main__':
    sys.exit(main())
