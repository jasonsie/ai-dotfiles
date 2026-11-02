#!/usr/bin/env python3
"""daily-log: the daily logger's grammar as one command.

  daily-log add  [--date D] [--done|--open] [--if-absent|--rewrite] [--root DIR]
                 [--dry-run] [--show block|file] LABEL [LINE ...]   lines also on stdin
  daily-log show [--date D] [--root DIR]                             a day's block
  daily-log path [--date D] [--root DIR]                             a day's week file
  daily-log day  [--date D] [--back N] [--rewrite] ...               a day's evidence (day_pass.py)
  daily-log tutor-daily --key K --subject S --item N --tutor T --paste-hint H
                 [--items Ns] [--weekend-day Sat] [--resolves 2] [--note TEXT ...]

The grammar is LOG-FORMAT.md in this skill's folder. The journal root is --root, else
$DAILY_LOGGER_ROOT, else ~/Documents/Claude/Projects/daily-logger; year and month folders
are created, the root never is. One entry per project and day: a label's project is the text
before ': ', else the whole label. `add` merges into the entry with the same label, refuses a
second entry for a project the block already holds, and replaces that entry with --rewrite.
`day` runs day_pass.py beside this script: the evidence the daily pass reads before it writes
the entries. This file imports nothing from the repo, so a copy of it is a complete writer
(the learning-tutor vendors one). Python 3.11+, stdlib only.
"""
from __future__ import annotations

import argparse
import calendar
from datetime import date
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SKILL = Path(__file__).resolve().parent.parent
DAY_PASS = Path(__file__).resolve().parent / 'day_pass.py'
DEFAULT_ROOT = '~/Documents/Claude/Projects/daily-logger'
DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
SEPARATOR = '-' * 84
RULE = '-' * 12
HEADING = re.compile(r'^#\s*(\d{1,2})/(\d{1,2})\s*\(')
ENTRY = re.compile(r'^-\s*\[(?P<mark>[^\]]*)\]\s*(?P<label>.+?)\s*$')
DONE_MARKS = {'x', 'ｘ'}
TEMPLATE_FIELDS = ('key', 'subject', 'item', 'items', 'tutor', 'paste_hint', 'weekend_day', 'resolves', 'notes')


class Duplicate(ValueError):
    """A second entry for a project the day's block already holds."""

    def __init__(self, existing):
        super().__init__(existing)
        self.existing = existing


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


def project(label):
    """The project a label names: the text before ': ', else the whole label."""
    head, sep, _ = label.partition(': ')
    return head.strip() if sep else label.strip()


def key(label):
    """What two labels for one project share: its name lowercased, without '_', '-' or spaces."""
    return re.sub(r'[\s_-]+', '', project(label).lower())


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


def entries(lines, start, end):
    """(index, label) of every entry in a day block."""
    found = []
    for k in range(start + 1, end):
        if lines[k].startswith(('\t', ' ')):
            continue
        match = ENTRY.match(lines[k].strip())
        if match:
            found.append((k, match.group('label').strip()))
    return found


def find_entry(lines, start, end, label):
    return next((k for k, found in entries(lines, start, end) if found == label.strip()), None)


def find_project(lines, start, end, label):
    """The entry for the same project under another label, or None."""
    wanted = key(label)
    return next((k for k, found in entries(lines, start, end) if key(found) == wanted), None)


def entry_end(lines, index, end):
    j = index + 1
    while j < end and lines[j].startswith(('\t', ' ')):
        j += 1
    return j


def add_entry(text, day, label, sub_lines, done=False, if_absent=False, rewrite=False):
    """(new text, changed): `label` and its sub-bullets in `day`'s block. The same label merges;
    another label for a project already there raises Duplicate, or replaces it with `rewrite`."""
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
    if index is None:
        other = find_project(lines, start, end, label)
        if other is not None and not rewrite:
            raise Duplicate(lines[other].strip())
        index = other
    if index is not None:
        if if_absent:
            return text if text.endswith('\n') else text + '\n', False
        last = entry_end(lines, index, end)
        if rewrite:
            wanted = [label_line, *sub_lines]
            changed = lines[index:last] != wanted
            lines = lines[:index] + wanted + lines[last:]
            return '\n'.join(lines) + '\n', changed
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
    try:
        new_text, changed = add_entry(text, day, args.label, sub_lines, done=args.done,
                                      if_absent=args.if_absent, rewrite=args.rewrite)
    except Duplicate as duplicate:
        print(f'daily-log: {day.isoformat()} already has an entry for this project: {duplicate.existing}\n'
              '  the same work: use that label, and the lines merge into it;'
              ' a replacement: add --rewrite.', file=sys.stderr)
        return 1
    if changed and not args.dry_run:
        write_text(path, new_text)
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


# --- the day pass -----------------------------------------------------------------------

def run_day(rest):
    """`daily-log day ...`: day_pass.py beside this script, with the rest of the arguments."""
    if not DAY_PASS.is_file():
        print(f'daily-log: day needs {DAY_PASS}, which this copy lacks; run the installed command',
              file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, str(DAY_PASS), *rest])


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
    repeat = add.add_mutually_exclusive_group()
    repeat.add_argument('--if-absent', action='store_true', help='change nothing when the label is already there')
    repeat.add_argument('--rewrite', action='store_true',
                        help="replace the project's entry, label and lines, instead of merging or refusing")
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

    sub.add_parser('day', help="a day's evidence for the daily pass; `daily-log day --help` for its options",
                   add_help=False)

    tutor = sub.add_parser('tutor-daily', help='render TUTOR-DAILY.md for one learning key')
    for field in ('key', 'subject', 'item', 'tutor', 'paste-hint'):
        tutor.add_argument('--' + field, required=True)
    tutor.add_argument('--items', help='plural of --item (default: item + s)')
    tutor.add_argument('--weekend-day', default='Sat')
    tutor.add_argument('--resolves', type=int, default=2)
    tutor.add_argument('--note', action='append', default=[], help='an extra Notes line; repeatable')
    tutor.set_defaults(run=cmd_tutor_daily)
    return top


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ['day']:
        return run_day(argv[1:])
    args = parser().parse_args(argv)
    return args.run(args)


if __name__ == '__main__':
    sys.exit(main())
