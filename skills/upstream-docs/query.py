#!/usr/bin/env python3
"""Answer questions about the mirrored upstream docs from their MIRROR-INDEX.json files.

Usage: python3 query.py [--mirror DIR] list | find TERM... | outline PAGE | show PAGE

A PAGE is written source/path, e.g. google/styleguide/pyguide.md; `COMMAND --help` lists a
command's options. `find` ranks pages by "when", title, path, description and headings
(--grep adds body lines); `outline` prints headings with section sizes; `show` prints one
slice of a page (--heading TEXT or --lines A-B, at most --max-lines). Line numbers count
newline-separated lines of the page file. The mirror defaults to docs/upstream of the repo
this script lives in. Output is compact plain text. Reads the mirror and writes nothing.
Standard library only, Python 3.11+.
"""
import argparse
import json
from operator import contains, eq
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
MIRROR = ROOT / 'docs/upstream'
INDEX = 'MIRROR-INDEX.json'
FIELD_WEIGHTS = (('when', 5), ('title', 4), ('path', 3), ('description', 2))
SCORED_HEADINGS = 3      # headings counted per term in a page's score
SHOWN_HEADINGS = 3       # matching headings printed under a hit
GREP_LINES = 30
GREP_WIDTH = 120


class QueryError(Exception):
    """A request the mirror cannot answer; main prints the message to stderr."""


def load_sources(mirror):
    """{source id: index} from every <mirror>/<source>/MIRROR-INDEX.json."""
    sources = {}
    for path in sorted(mirror.glob(f'*/{INDEX}')):
        try:
            sources[path.parent.name] = json.loads(path.read_text(encoding='utf-8'))
        except ValueError as e:
            raise QueryError(f'{path}: {e}') from e
    return sources


def pages_of(sources, only=None):
    """[(source/path, page)] sorted by reference, for one source or all."""
    if only is not None and only not in sources:
        raise QueryError(f'unknown source: {only} (known: {", ".join(sources)})')
    rows = [(f'{source}/{page["path"]}', page) for source, index in sources.items()
            if only in (None, source) for page in index.get('pages') or []]
    return sorted(rows, key=lambda row: row[0])


def find_page(sources, ref):
    """The page that `source/path` names."""
    source, _, path = ref.partition('/')
    for page in sources.get(source, {}).get('pages') or []:
        if page['path'] == path:
            return page
    raise QueryError(f'unknown page: {ref}')


def headings_of(page):
    return page.get('headings') or []


def heading_row(heading):
    """`L<line>  ## text` for one [level, text, line] heading."""
    level, text, line = heading
    return f'L{line}  {"#" * level} {text}'


def section_end(headings, index, total):
    """Last line of the section a heading opens: up to the next heading at its level or higher."""
    level = headings[index][0]
    return next((later[2] - 1 for later in headings[index + 1:] if later[0] <= level), total)


def read_lines(path):
    """A page file's lines, split on newlines only so numbers match editors and the index."""
    lines = path.read_text(encoding='utf-8', errors='replace').split('\n')
    return lines[:-1] if lines[-1] == '' else lines


def score(page, terms):
    """Weighted count of the terms found in a page's index fields and headings; 0 is no match."""
    total = 0
    for term in terms:
        total += sum(weight for field, weight in FIELD_WEIGHTS if term in (page.get(field) or '').lower())
        total += min(SCORED_HEADINGS, sum(term in heading[1].lower() for heading in headings_of(page)))
    return total


def rank_key(hit):
    """Order of find hits: best score first, an outlined page before a bare file at equal score, then by reference."""
    score, ref, page = hit
    return (-score, not headings_of(page), ref)


def hit_lines(ref, page, terms):
    """One page's `find` output: its line, then the first headings that hold a term."""
    when = f' [{page["when"]}]' if page.get('when') else ''
    kb = max(1, (page['bytes'] + 512) // 1024)
    matching = [h for h in headings_of(page) if any(term in h[1].lower() for term in terms)]
    return [f'{ref} — {page["title"]}{when} ({kb} KB)'] + [f'  {heading_row(h)}' for h in matching[:SHOWN_HEADINGS]]


def grep_lines(mirror, pages, terms):
    """`ref:L<n>: text` for up to GREP_LINES lines holding every term, past each page's leading `>` header."""
    found = []
    for ref, _ in pages:
        in_header = True
        for number, line in enumerate(read_lines(mirror / ref), 1):
            in_header = in_header and line.startswith('>')
            if not in_header and all(term in line.lower() for term in terms):
                found.append(f'{ref}:L{number}: {line.strip()[:GREP_WIDTH]}')
                if len(found) == GREP_LINES:
                    return found
    return found


def match_headings(headings, text):
    """Indexes of the headings equal to text, else starting with it, else containing it; ignores case."""
    want = text.strip().lower()
    for test in (eq, str.startswith, contains):
        found = [i for i, heading in enumerate(headings) if test(heading[1].lower(), want)]
        if found:
            return found
    return []


def line_range(text):
    """argparse type for `A-B`: a (first, last) pair of 1-based line numbers."""
    first, _, last = text.partition('-')
    if not (first.isdecimal() and last.isdecimal() and 1 <= int(first) <= int(last)):
        raise argparse.ArgumentTypeError(f'{text!r} is not A-B with 1 <= A <= B')
    return int(first), int(last)


def cmd_list(mirror, sources, args):
    for source in sorted(sources):
        index = sources[source]
        detail = f': {index["description"]}' if index.get('description') else ''
        print(f'{source}  {len(index.get("pages") or [])} pages  {index.get("name") or source}{detail}')
    return 0


def cmd_find(mirror, sources, args):
    terms = [term.lower() for term in args.terms]
    pages = pages_of(sources, args.source)
    scored = [(score(page, terms), ref, page) for ref, page in pages]
    hits = sorted((row for row in scored if row[0]), key=rank_key)[:args.limit]
    out = [line for _, ref, page in hits for line in hit_lines(ref, page, terms)]
    if args.grep:
        body = grep_lines(mirror, pages, terms)
        out += ['grep:', *body] if body else []
    print('\n'.join(out) if out else 'no match')
    return 0


def cmd_outline(mirror, sources, args):
    page = find_page(sources, args.page)
    headings = headings_of(page)
    print(f'{args.page} — {page["title"]} ({page["lines"]} lines, {len(headings)} headings)')
    if not headings:
        print('no headings (not Markdown?)')
    for i, heading in enumerate(headings):
        if heading[0] <= args.depth:
            size = section_end(headings, i, page['lines']) - heading[2] + 1
            print(f'{heading_row(heading)}  ({size} lines)')
    return 0


def cmd_show(mirror, sources, args):
    page = find_page(sources, args.page)
    lines = read_lines(mirror / args.page)
    total = len(lines)
    first, last = 1, total
    if args.heading is not None:
        headings = headings_of(page)
        found = match_headings(headings, args.heading)
        if not found:
            print(f'no heading matches "{args.heading}"')
            return 1
        if len(found) > 1:
            print('ambiguous heading; candidates:')
            print('\n'.join(f'  {heading_row(headings[i])}' for i in found))
            return 2
        first, last = headings[found[0]][2], section_end(headings, found[0], total)
    elif args.lines:
        first, last = args.lines[0], min(args.lines[1], total)
        if first > total:
            raise QueryError(f'{args.page} has {total} lines, not {first}-{args.lines[1]}')
    print(f'# {args.page} L{first}-L{last} of {total}')
    for line in lines[first - 1:last][:args.max_lines]:
        print(line)
    hidden = last - first + 1 - args.max_lines
    if hidden > 0:
        print(f'… {hidden} more lines; use --lines {first + args.max_lines}-{last}')
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mirror', type=Path, default=MIRROR, metavar='DIR',
                        help='folder with <source>/MIRROR-INDEX.json (default: docs/upstream here)')
    commands = parser.add_subparsers(dest='command', required=True, metavar='COMMAND')
    commands.add_parser('list', help='one line per source').set_defaults(run=cmd_list)
    find = commands.add_parser('find', help='rank pages for terms')
    find.add_argument('terms', nargs='+', metavar='TERM')
    find.add_argument('--source', help='only this source')
    find.add_argument('--limit', type=int, default=10, help='most pages printed (default 10)')
    find.add_argument('--grep', action='store_true', help='also print page lines that hold every term')
    find.set_defaults(run=cmd_find)
    outline = commands.add_parser('outline', help='headings with section sizes')
    outline.add_argument('page', metavar='SOURCE/PATH')
    outline.add_argument('--depth', type=int, default=2, help='deepest heading level shown (default 2)')
    outline.set_defaults(run=cmd_outline)
    show = commands.add_parser('show', help='print one slice of a page')
    show.add_argument('page', metavar='SOURCE/PATH')
    pick = show.add_mutually_exclusive_group()
    pick.add_argument('--heading', metavar='TEXT', help='the section under this heading')
    pick.add_argument('--lines', type=line_range, metavar='A-B', help='these 1-based lines, inclusive')
    show.add_argument('--max-lines', type=int, default=200, help='most lines printed (default 200)')
    show.set_defaults(run=cmd_show)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        sources = load_sources(args.mirror)
        if not sources:
            raise QueryError(f'no {INDEX} under {args.mirror}')
        return args.run(args.mirror, sources, args)
    except (QueryError, OSError) as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
