#!/usr/bin/env python3
"""day_pass: the evidence the daily pass reads before it writes the journal's work entries.

  daily-log day [--date YYYY-MM-DD|yesterday|today] [--back N] [--cutoff H] [--rewrite]
                [--root DIR] [--home DIR] [--write]

For each day from D-N to D (default: yesterday and the 3 days before it) that has sessions,
prints the day's existing block, the keyword vocabulary (this and last month's `keyword:`
lines), then one group per working folder: its repository's facts for the day (commits,
reflog moves, uncommitted files) and its sessions (CLI, span, title, what was asked and
answered, files edited). The model running the pass (skills/daily-log/SKILL.md, "Day pass")
then writes one entry per project for the work no entry covers, through `daily-log add`.

With --write, what the LaunchAgent runs, the evidence is not printed but piped as the prompt
into one headless Claude Code session, `claude -p "/daily-log day"` (Sonnet; the Bash tool
alone, allowed for `daily-log add` only; 15 turns), whose reply goes to stdout. The pass thus
runs exactly once, outside any tool timeout, and a day range without sessions starts no
session at all. `claude` is found on PATH.

A day runs from the cutoff hour (04:00) to the next day's, in local time. Sessions come from
scripts/agent_sessions.py (Claude Code, Codex, Pi); Antigravity's transcripts name no working
folder and are not read. Nothing here writes the journal. Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import calendar
from datetime import date, timedelta
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                          # daily_log: the journal's files and blocks
sys.path.insert(0, str(HERE.parents[2] / 'scripts'))   # agent_sessions: the CLIs' session stores
import agent_sessions  # noqa: E402
import daily_log  # noqa: E402

BACK = 3           # days before --date that are checked for gaps
CUTOFF = 4         # the hour a day starts
PROMPTS = 6        # user turns shown per session, the first ones
REPLIES = 8        # assistant turns shown per session, the last ones
FILES = 20         # edited files listed per session
WIDTH = 160        # characters per shown line
COMMITS = 15
MOVES = 8
GIT_TIMEOUT = 20
KEYWORD = re.compile(r'^\s*-\s*keyword:\s*(.+?)\s*$')
PROMPT = '/daily-log day'  # the skill, whose "Day pass" section the model follows
# The writing session's leash: one tool, one command, few turns. --tools limits what exists,
# --allowedTools what runs unasked; under a permissive permission mode only the first bites.
CLAUDE_ARGS = ['-p', PROMPT, '--model', 'sonnet', '--tools', 'Bash',
               '--allowedTools', 'Bash(daily-log add *)', '--max-turns', '15']


def parse_date(value):
    if value in (None, 'yesterday'):
        return date.today() - timedelta(days=1)
    if value == 'today':
        return date.today()
    return date.fromisoformat(value)


# --- the repository ----------------------------------------------------------------------

def git(folder, *args):
    """git's stdout in `folder`, or None when it fails, is missing or hangs."""
    try:
        run = subprocess.run(['git', '-C', str(folder), *args], capture_output=True, text=True,
                             timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return run.stdout.strip() if run.returncode == 0 else None


def repo_name(url):
    return re.sub(r'\.git$', '', url.rstrip('/').rsplit('/', 1)[-1].rsplit(':', 1)[-1])


def repo_facts(folder, start, end):
    """(top, lines): the repository holding `folder` and what happened in it in the window."""
    if not folder:
        return None, ['no working folder recorded']
    if not Path(folder).is_dir():
        return None, ['folder gone']
    top = git(folder, 'rev-parse', '--show-toplevel')
    if not top:
        return None, ['not a git repository']
    lines = [f'repo: {top}']
    url = git(top, 'remote', 'get-url', 'origin')
    if url:
        lines.append(f'origin: {repo_name(url)}')
    lines.append(f'branch: {git(top, "branch", "--show-current") or "(detached)"}')
    since, until = f'--since={start.isoformat()}', f'--until={end.isoformat()}'
    commits = (git(top, 'log', '--all', since, until, '--format=%s') or '').splitlines()  # subjects: no hashes in an entry
    lines.append(f'commits in window: {len(commits)}')
    lines.extend(f'  {commit}' for commit in commits[:COMMITS])
    reflog = (git(top, 'log', '-g', since, until, '--format=%gs') or '').splitlines()
    moves = [move for move in dict.fromkeys(reflog) if move and not move.startswith('commit')]
    lines.extend(f'  reflog: {move}' for move in moves[:MOVES])
    status = git(top, 'status', '--porcelain')
    lines.append(f'uncommitted now: {len(status.splitlines()) if status else 0}')
    return top, lines


# --- the journal -------------------------------------------------------------------------

def existing_block(root, day):
    path = daily_log.week_file(root, day)
    return daily_log.day_block(path.read_text(encoding='utf-8'), day) if path.exists() else None


def keywords(root, day):
    """Tags of this and last month's `keyword:` lines, in order of first appearance."""
    this = day.replace(day=1)
    last = (this - timedelta(days=1)).replace(day=1)
    seen = {}
    for month in (last, this):
        folder = Path(root) / str(month.year) / str(calendar.month_abbr[month.month])
        for file in sorted(folder.glob('week-*')) if folder.is_dir() else ():
            for line in file.read_text(encoding='utf-8', errors='replace').splitlines():
                match = KEYWORD.match(line)
                if match:
                    for tag in match.group(1).split(','):
                        if tag.strip():
                            seen.setdefault(tag.strip(), None)
    return list(seen)


# --- the rendering -----------------------------------------------------------------------

def first_line(text, width=WIDTH):
    line = next((part.strip() for part in text.strip().splitlines() if part.strip()), '')
    return line if len(line) <= width else line[:width - 1] + '…'


def relative(path, top):
    try:
        return str(Path(path).relative_to(top)) if top else path
    except ValueError:
        return path


def render_session(session, top):
    span = f'{session.started.astimezone():%H:%M}-{session.ended.astimezone():%H:%M}'
    out = [f'- {session.cli} {span} {session.title or "(untitled)"}']
    asked = [turn for turn in session.turns if turn.role == 'user'][:PROMPTS]
    said = [turn for turn in session.turns if turn.role == 'assistant'][-REPLIES:]
    for turn in sorted(asked + said, key=lambda turn: turn.at):
        out.append(f'    {"asked" if turn.role == "user" else "said"}: {first_line(turn.text)}')
    files = [path for path in session.files if not agent_sessions.is_temp(path)]  # scratch files say nothing
    if files:
        shown = ', '.join(relative(path, top) for path in files[:FILES])
        more = f' (+{len(files) - FILES} more)' if len(files) > FILES else ''
        out.append(f'    edited: {shown}{more}')
    return out


def render_day(day, root, home, cutoff, rewrite):
    """The day's evidence as lines, or None when no session ran in its window."""
    start, end = agent_sessions.window(day, cutoff)
    found = agent_sessions.sessions(start, end, home)
    if not found:
        return None
    out = [f'## {day.isoformat()} ({daily_log.DAYS[day.weekday()]}), '
           f'{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} {start:%Z}']
    out.append('rewrite: on, pass --rewrite to daily-log add and replace what is there' if rewrite else
               'rewrite: off, skip work the block already covers and never change an existing entry')
    block = existing_block(root, day)
    out += ['', '### Existing block', block.rstrip() if block else '(no block yet)']
    tags = keywords(root, day)
    out += ['', '### Keywords in use, reuse before coining', ', '.join(tags) if tags else '(none yet)']
    groups = {}
    for session in found:
        groups.setdefault(session.cwd, []).append(session)
    for cwd, sessions in groups.items():
        top, facts = repo_facts(cwd, start, end)
        out += ['', f'### {cwd}'] + [f'  {line}' for line in facts]
        for session in sessions:
            out += render_session(session, top)
    out += ['', '### Write',
            f'daily-log add --date {day.isoformat()} --done{" --rewrite" if rewrite else ""} '
            '"<project>: <what the day was about>" "keyword: <tags>" "description: <one line>"',
            'One entry per project; the rules are in skills/daily-log/SKILL.md, "Day pass".']
    return out


def write(evidence):
    """Run the writing session with `evidence` as the piped part of its prompt; its exit status."""
    claude = shutil.which('claude')
    if not claude:
        print('daily-log day: claude not on PATH; nothing written', file=sys.stderr)
        return 1
    sys.stdout.flush()
    return subprocess.run([claude, *CLAUDE_ARGS], input=evidence, text=True).returncode


def main(argv=None):
    options = argparse.ArgumentParser(prog='daily-log day', description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    options.add_argument('--date', default='yesterday', help='YYYY-MM-DD, yesterday (default) or today')
    options.add_argument('--back', type=int, default=BACK, help=f'also the N days before --date (default {BACK})')
    options.add_argument('--cutoff', type=int, default=CUTOFF, help=f'the hour a day starts (default {CUTOFF})')
    options.add_argument('--rewrite', action='store_true', help='have the pass replace existing entries')
    options.add_argument('--root', help='journal root (default: $DAILY_LOGGER_ROOT or ' + daily_log.DEFAULT_ROOT + ')')
    options.add_argument('--home', help='home folder holding the session stores (default: ~)')
    options.add_argument('--write', action='store_true',
                         help='pipe the evidence into one claude -p session that writes the entries (the LaunchAgent)')
    args = options.parse_args(argv)
    root = daily_log.root_dir(args.root)
    home = Path(args.home).expanduser() if args.home else None
    last = parse_date(args.date)
    days = [last - timedelta(days=i) for i in range(max(args.back, 0), -1, -1)]
    rendered = [(day, render_day(day, root, home, args.cutoff, args.rewrite)) for day in days]
    with_sessions = [day.isoformat() for day, lines in rendered if lines]
    head = (f'# Day pass {days[0].isoformat()} to {last.isoformat()}; days with sessions: '
            + (', '.join(with_sessions) or 'none'))
    body = ''.join('\n' + '\n'.join(lines) + '\n' for _, lines in rendered if lines)
    print(head)
    if not args.write:
        print(body, end='')
        return 0
    if not with_sessions:
        return 0  # nothing to read: no session to start
    return write(head + '\n' + body)


if __name__ == '__main__':
    sys.exit(main())
