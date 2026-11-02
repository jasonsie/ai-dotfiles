#!/usr/bin/env python3
"""daily-log: the daily logger's grammar as one command, and the hook that asks for an entry.

  daily-log add  [--date D] [--done|--open] [--if-absent] [--session ID] [--root DIR]
                 [--dry-run] [--show block|file] LABEL [LINE ...]   lines also on stdin
  daily-log show [--date D] [--root DIR]                             a day's block
  daily-log path [--date D] [--root DIR]                             a day's week file
  daily-log tutor-daily --key K --subject S --item N --tutor T --paste-hint H
                 [--items Ns] [--weekend-day Sat] [--resolves 2] [--note TEXT ...]
  daily-log hook (tool|stop) --cli (claude|codex|agy|pi)             JSON in; JSON or nothing out

The grammar is LOG-FORMAT.md in this skill's folder. The journal root is --root, else
$DAILY_LOGGER_ROOT, else ~/Documents/Claude/Projects/daily-logger; year and month folders
are created, the root never is. Hook state is one file per session under $DAILY_LOG_STATE,
else ~/.local/state/ai-dotfiles/daily-log/, deleted after 7 days. A hook call never exits
non-zero and prints nothing but JSON, so a broken hook cannot block a session. The CLIs'
hook formats live in the repo's scripts/agent_hooks.py, shared with other hooks.
Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import calendar
import contextlib
from datetime import date
import io
import os
from pathlib import Path
import re
import sys
import tempfile

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL.parents[1] / 'scripts'))
import agent_hooks  # noqa: E402  (the CLIs' hook formats, in the repo's scripts folder)

DEFAULT_ROOT = '~/Documents/Claude/Projects/daily-logger'
DEFAULT_STATE = '~/.local/state/ai-dotfiles/daily-log'
DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
SEPARATOR = '-' * 84
RULE = '-' * 12
HEADING = re.compile(r'^#\s*(\d{1,2})/(\d{1,2})\s*\(')
ENTRY = re.compile(r'^-\s*\[(?P<mark>[^\]]*)\]\s*(?P<label>.+?)\s*$')
DONE_MARKS = {'x', 'ｘ'}
MAX_NUDGES = 2
KEEP_SECONDS = 7 * 24 * 3600
NUDGE = (
    'Files changed in this session ({edits} edits) and today\'s daily log has no entry from it. '
    'If a unit of work is finished, record it now: '
    'daily-log add --done --session {session} "<label>" "<line>" ... '
    '(label = the project or skill; up to 3 terse sub-bullets, telegraphic). '
    'If nothing is finished yet, say so in one line and stop.')
TEMPLATE_FIELDS = ('key', 'subject', 'item', 'items', 'tutor', 'paste_hint', 'weekend_day', 'resolves', 'notes')


# --- the journal -------------------------------------------------------------------------

def root_dir(given=None):
    return Path(given or os.environ.get('DAILY_LOGGER_ROOT') or DEFAULT_ROOT).expanduser()


def week_file(root, day):
    """<root>/<yyyy>/<Mon>/week-<i>: the week holding `day` in the day's own month."""
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(day.year, day.month)
    index = next(i for i, week in enumerate(weeks, 1) if day in week)
    return Path(root) / str(day.year) / str(calendar.month_abbr[day.month]) / f'week-{index}'


def heading(day):
    return f'# {day.month}/{day.day} ({DAYS[day.weekday()]})'


def normalize(line):
    """One sub-bullet: verbatim when already indented, else one TAB and a bullet."""
    line = line.rstrip()
    if not line.strip():
        return None
    if line.startswith('\t'):
        return line
    if line.startswith('↳'):
        return '\t\t' + line
    if line.startswith('- '):
        return '\t' + line
    return '\t- ' + line


def find_day(lines, day):
    wanted = heading(day)
    return next((i for i, line in enumerate(lines) if line.strip() == wanted), None)


def block_end(lines, start):
    """The index of the line that closes the day block begun at `start`: the next separator or heading."""
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped == SEPARATOR or stripped.startswith('# '):
            return j
    return len(lines)


def find_entry(lines, start, end, label):
    for k in range(start + 1, end):
        if lines[k].startswith(('\t', ' ')):
            continue
        match = ENTRY.match(lines[k].strip())
        if match and match.group('label').strip() == label.strip():
            return k
    return None


def entry_end(lines, index, end):
    j = index + 1
    while j < end and lines[j].startswith(('\t', ' ')):
        j += 1
    return j


def add_entry(text, day, label, sub_lines, done=False, if_absent=False):
    """(new text, changed): `label` and its sub-bullets in `day`'s block, merged if present."""
    lines = text.splitlines()
    label_line = f'- [{"X" if done else ""}] {label}'
    start = find_day(lines, day)
    if start is None:
        block = [heading(day), RULE, label_line, *sub_lines]
        if not lines:
            lines = ['# Week Goal', RULE, '# Thought', '', SEPARATOR, '', '', *block, '', '', SEPARATOR]
        else:
            trailing = [SEPARATOR, ''] if lines[-1].strip() != SEPARATOR else []
            lines = lines + ['', *trailing, *block, '', '', SEPARATOR]
        return '\n'.join(lines) + '\n', True
    end = block_end(lines, start)
    index = find_entry(lines, start, end, label)
    if index is not None:
        if if_absent:
            return text if text.endswith('\n') else text + '\n', False
        last = entry_end(lines, index, end)
        present = {line.rstrip() for line in lines[index + 1:last]}
        added = []
        for line in sub_lines:
            if line.rstrip() not in present:
                added.append(line)
                present.add(line.rstrip())
        match = ENTRY.match(lines[index].strip())
        mark = match.group('mark').strip().lower() if match else ''
        changed = bool(added)
        if done and mark not in DONE_MARKS:
            lines[index] = re.sub(r'^(\s*-\s*)\[[^\]]*\]', r'\g<1>[X]', lines[index], count=1)
            changed = True
        lines = lines[:last] + added + lines[last:]
        return '\n'.join(lines) + '\n', changed
    tail = end
    while tail > start + 1 and lines[tail - 1].strip() == '':
        tail -= 1
    content = [line for line in lines[start + 1:tail] if line.strip() and line.strip() != RULE]
    entry = ([''] if content else []) + [label_line, *sub_lines]
    lines = lines[:tail] + entry + lines[tail:]
    return '\n'.join(lines) + '\n', True


def day_block(text, day):
    """The lines of `day`'s block (heading to the line before its separator), or None."""
    lines = text.splitlines()
    start = find_day(lines, day)
    if start is None:
        return None
    block = lines[start:block_end(lines, start)]
    while block and block[-1].strip() == '':
        block.pop()
    return '\n'.join(block) + '\n'


def write_text(path, text):
    """Write atomically; a new file is world-readable like the hand-written ones."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        handle.write(text)
    os.chmod(handle.name, mode)
    os.replace(handle.name, path)


def parse_day(value):
    return date.fromisoformat(value) if value else date.today()


def cmd_add(args):
    root = root_dir(args.root)
    if not root.is_dir():
        print(f'daily-log: journal root not found: {root}', file=sys.stderr)
        return 1
    raw = list(args.lines)
    if not raw and not sys.stdin.isatty():
        raw = sys.stdin.read().splitlines()
    sub_lines = [line for line in (normalize(line) for line in raw) if line is not None]
    day = parse_day(args.date)
    path = week_file(root, day)
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    new_text, changed = add_entry(text, day, args.label, sub_lines, done=args.done, if_absent=args.if_absent)
    if changed and not args.dry_run:
        write_text(path, new_text)
    if args.session and not args.dry_run:
        mark_logged(args.session)
    print(new_text if args.show == 'file' else day_block(new_text, day), end='')
    return 0


def cmd_show(args):
    path = week_file(root_dir(args.root), parse_day(args.date))
    block = day_block(path.read_text(encoding='utf-8'), parse_day(args.date)) if path.exists() else None
    if block is None:
        print(f'daily-log: no block for {parse_day(args.date).isoformat()} in {path}', file=sys.stderr)
        return 1
    print(block, end='')
    return 0


def cmd_path(args):
    print(week_file(root_dir(args.root), parse_day(args.date)))
    return 0


# --- the tutor-daily template -----------------------------------------------------------

def render_template(template, values):
    """Replace `{field}` for the known fields only; other braces stay as they are."""
    text = re.sub(r'\{(' + '|'.join(TEMPLATE_FIELDS) + r')\}', lambda m: values[m.group(1)], template)
    return '\n'.join(line for line in text.split('\n') if line.strip() != '{notes-blank}')


def cmd_tutor_daily(args):
    values = {
        'key': args.key, 'subject': args.subject, 'item': args.item, 'items': args.items or args.item + 's',
        'tutor': args.tutor, 'paste_hint': args.paste_hint, 'weekend_day': args.weekend_day,
        'resolves': str(args.resolves),
        'notes': '\n'.join(f'- {note}' for note in args.note) if args.note else '{notes-blank}',
    }
    print(render_template((SKILL / 'TUTOR-DAILY.md').read_text(encoding='utf-8'), values), end='')
    return 0


# --- the hook ---------------------------------------------------------------------------

STORE = agent_hooks.Store('DAILY_LOG_STATE', DEFAULT_STATE, KEEP_SECONDS)


def mark_logged(session):
    state = STORE.load(session)
    state['logged'] = True
    STORE.save(session, state)


def on_tool(event, state):
    if event.edit:
        state['edits'] = state.get('edits', 0) + 1
    return None


def on_stop(event, state):
    if event.continuation or not event.model_stopped:
        return None  # our own continuation; or an error or step-cap stop (Antigravity)
    edits = state.get('edits', 0)
    if not edits or state.get('logged') or state.get('nudges', 0) >= MAX_NUDGES:
        return None
    if edits <= state.get('edits_at_nudge', 0):
        return None
    state['nudges'] = state.get('nudges', 0) + 1
    state['edits_at_nudge'] = edits
    return agent_hooks.Continue(NUDGE.format(edits=edits, session=event.session))


def decide(event, state):
    return on_tool(event, state) if event.kind == 'tool' else on_stop(event, state)


def hook(mode, cli, data, now=None):
    """The reply for one hook call, or None; the session's state is read and written around it."""
    return agent_hooks.call(cli, mode, data, decide, STORE, now)


def cmd_hook(args):
    return agent_hooks.serve(args.cli, args.mode, lambda data: hook(args.mode, args.cli, data))


# --- the command ------------------------------------------------------------------------

def parser():
    top = argparse.ArgumentParser(prog='daily-log', description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest='command', required=True)

    def journal(p):
        p.add_argument('--date', help='YYYY-MM-DD (default: today)')
        p.add_argument('--root', help='journal root (default: $DAILY_LOGGER_ROOT or ' + DEFAULT_ROOT + ')')

    add = sub.add_parser('add', help='record an entry in a day block')
    journal(add)
    state = add.add_mutually_exclusive_group()
    state.add_argument('--done', action='store_true', help='mark the entry [X] (default for new entries: open)')
    state.add_argument('--open', action='store_true', help='leave the entry open: - [] label')
    add.add_argument('--if-absent', action='store_true', help='change nothing when the label is already there')
    add.add_argument('--session', help='hook session id: marks the session as logged')
    add.add_argument('--dry-run', action='store_true', help='print the result, write nothing')
    add.add_argument('--show', choices=('block', 'file'), default='block', help='what to print (default: block)')
    add.add_argument('label')
    add.add_argument('lines', nargs='*', help='sub-bullets; or one per line on stdin')
    add.set_defaults(run=cmd_add)

    show = sub.add_parser('show', help="print a day's block")
    journal(show)
    show.set_defaults(run=cmd_show)

    where = sub.add_parser('path', help="print a day's week file")
    journal(where)
    where.set_defaults(run=cmd_path)

    tutor = sub.add_parser('tutor-daily', help='render TUTOR-DAILY.md for one learning key')
    for field in ('key', 'subject', 'item', 'tutor', 'paste-hint'):
        tutor.add_argument('--' + field, required=True)
    tutor.add_argument('--items', help='plural of --item (default: item + s)')
    tutor.add_argument('--weekend-day', default='Sat')
    tutor.add_argument('--resolves', type=int, default=2)
    tutor.add_argument('--note', action='append', default=[], help='an extra Notes line; repeatable')
    tutor.set_defaults(run=cmd_tutor_daily)

    hook_parser = sub.add_parser('hook', help='the CLI hook: JSON on stdin')
    hook_parser.add_argument('mode', choices=('tool', 'stop'))
    hook_parser.add_argument('--cli', choices=agent_hooks.CLIS, required=True)
    hook_parser.set_defaults(run=cmd_hook)
    return top


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    is_hook = argv[:1] == ['hook']
    try:
        # A bad hook call must stay silent and exit 0: status 2 and stderr would steer the CLI.
        with contextlib.redirect_stderr(io.StringIO() if is_hook else sys.stderr):
            args = parser().parse_args(argv)
    except SystemExit as error:
        return 0 if is_hook else int(error.code or 0)
    return args.run(args)


if __name__ == '__main__':
    sys.exit(main())
