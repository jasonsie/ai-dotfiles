#!/usr/bin/env python3
"""Survey a GitHub organization or repository for coding-style, style-guide and docs-writing files.

Usage: survey.py <org | owner/repo> [--pattern REGEX] [--files REGEX] [--all] [--limit N] [--json]

An org is listed with `gh repo list` (at most --limit repos; a listing that fills the limit warns) and
filtered: a repo stays when --pattern matches its name, description or a topic; --all keeps every repo.
An owner/repo skips the listing and the filter. The default-branch tree of each kept repo is scanned for
files whose path matches --files and whose extension is .md .mdx .rst .html .adoc or .txt. --files defaults
to guide-like names (style, convention, contributing...) for an org and to `.`, every document file, for an
owner/repo: a guide repository keeps its guides behind plain names (review/index.md). Both regexes ignore
case. Needs the `gh` CLI, logged in. Standard library only, Python 3.11+.

Stdout: one Markdown table row per candidate file, sorted by repo then path (a JSON array of the same
rows with --json). Stderr: warnings, then "<n> repos scanned, <m> candidate files"; n counts the repos
whose tree was read. Columns:

  Repo      owner/repo
  Branch    the default branch that was scanned
  Archived  yes when the repo is archived
  Fork      yes when the repo is a fork
  License   SPDX id, or none; an org listing gives gh's lowercase license key instead (mit, not MIT)
  Pushed    date of the last push
  File      path in the repo
  KB        size in kilobytes, one decimal
"""
import argparse
import json
import re
import subprocess
import sys

REPO_PATTERN = r'style|convention|guideline|eng-practices|docs?-?writ|technical.?writ|documentation'
FILE_PATTERN = r'style|convention|guideline|coding|contributing|writing|docguide|eng-practices|agents\.md|claude\.md'
EXTENSIONS = ('.md', '.mdx', '.rst', '.html', '.adoc', '.txt')
FIELDS = 'name,description,repositoryTopics,isArchived,isFork,pushedAt,licenseInfo,defaultBranchRef'
HEADER = ('Repo', 'Branch', 'Archived', 'Fork', 'License', 'Pushed', 'File', 'KB')


def gh(*args):
    """Run the gh CLI and return its JSON output."""
    return json.loads(subprocess.run(['gh', *args], check=True, capture_output=True, text=True).stdout)


def reason(error):
    """Why a call failed, on one line: gh's own message when it printed one."""
    return ' '.join((getattr(error, 'stderr', None) or str(error)).split())


def repo_row(entry):
    """A repository row from one `gh repo list` entry; null fields become '', [] or 'none'."""
    info = entry.get('licenseInfo') or {}
    return {'name': entry['name'], 'description': entry.get('description') or '',
            'topics': [topic['name'] for topic in entry.get('repositoryTopics') or []],
            'archived': entry['isArchived'], 'fork': entry['isFork'], 'pushed': (entry.get('pushedAt') or '')[:10],
            'license': info.get('spdxId') or info.get('key') or 'none',
            'branch': (entry.get('defaultBranchRef') or {}).get('name') or ''}


def single_repo_row(owner, repo, data):
    """A repository row, named owner/repo, from `gh api repos/<owner>/<repo>`."""
    return {'name': f'{owner}/{repo}', 'description': data.get('description') or '',
            'topics': data.get('topics') or [], 'archived': data['archived'], 'fork': data['fork'],
            'pushed': (data.get('pushed_at') or '')[:10],
            'license': (data.get('license') or {}).get('spdx_id') or 'none',
            'branch': data.get('default_branch') or ''}


def matches(row, pattern):
    """True when the pattern matches the repo's name, description or any topic."""
    return any(re.search(pattern, text, re.IGNORECASE) for text in (row['name'], row['description'], *row['topics']))


def candidate_files(tree_entries, pattern):
    """The blobs of a git tree whose path matches the pattern and ends in a document extension."""
    return [entry for entry in tree_entries
            if entry['type'] == 'blob' and entry['path'].lower().endswith(EXTENSIONS)
            and re.search(pattern, entry['path'], re.IGNORECASE)]


def ordered(rows):
    """Candidate rows sorted by repo, then path."""
    return sorted(rows, key=lambda row: (row['repo'], row['path']))


def table(rows):
    """The candidate rows as a Markdown table."""
    lines = ['| ' + ' | '.join(HEADER) + ' |', '|' + '---|' * len(HEADER)]
    for row in ordered(rows):
        cells = [row['repo'], row['branch'], 'yes' if row['archived'] else '', 'yes' if row['fork'] else '',
                 row['license'], row['pushed'], row['path'], row['kb']]
        lines.append('| ' + ' | '.join(str(cell) for cell in cells) + ' |')
    return '\n'.join(lines)


def repos(args):
    """The repository rows to scan, each named owner/repo."""
    owner, _, repo = args.target.partition('/')
    if repo:
        return [single_repo_row(owner, repo, gh('api', f'repos/{owner}/{repo}'))]
    listing = gh('repo', 'list', owner, '--limit', str(args.limit), '--json', FIELDS)
    if len(listing) >= args.limit:
        print(f'warning: {owner} listing hit --limit {args.limit}; raise it to see more repos', file=sys.stderr)
    rows = [repo_row(entry) for entry in listing]
    return [dict(row, name=f'{owner}/{row["name"]}') for row in rows if args.all or matches(row, args.pattern)]


def scan(row, pattern):
    """Candidate rows from one repo's default-branch tree; None when that tree cannot be read."""
    name, branch = row['name'], row['branch']
    if not branch:
        print(f'warning: {name} has no default branch; skipped', file=sys.stderr)
        return None
    try:
        tree = gh('api', f'repos/{name}/git/trees/{branch}?recursive=1')
    except subprocess.CalledProcessError as error:
        print(f'warning: {name}: {reason(error)}; skipped', file=sys.stderr)
        return None
    if tree.get('truncated'):
        print(f'warning: {name} tree truncated; scan it with code search', file=sys.stderr)
    return [{'repo': name, 'branch': branch, 'archived': row['archived'], 'fork': row['fork'],
             'license': row['license'], 'pushed': row['pushed'], 'path': blob['path'],
             'kb': round(blob['size'] / 1024, 1)} for blob in candidate_files(tree['tree'], pattern)]


def parse(argv):
    """The command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('target', metavar='org|owner/repo', help='an organization, or one repository')
    parser.add_argument('--pattern', default=REPO_PATTERN, help='repos kept: regex on name, description, topics')
    parser.add_argument('--files', help='files kept: regex on the path '
                                        '(default: a style-guide pattern; `.` for owner/repo)')
    parser.add_argument('--all', action='store_true', help='keep every repo, ignoring --pattern')
    parser.add_argument('--limit', type=int, default=1000, help='most repos to list (default: 1000)')
    parser.add_argument('--json', action='store_true', help='print JSON rows instead of a table')
    return parser.parse_args(argv)


def main(argv=None):
    """Survey the target; 1 when gh is missing, a gh call other than a tree scan fails, or a regex is bad."""
    args = parse(argv)
    files = args.files or ('.' if args.target.partition('/')[2] else FILE_PATTERN)
    scanned, found = 0, []
    try:
        for row in repos(args):
            rows = scan(row, files)
            if rows is not None:
                scanned += 1
                found += rows
    except (subprocess.CalledProcessError, FileNotFoundError, re.error) as error:
        print(f'survey: {reason(error)}', file=sys.stderr)
        return 1
    print(json.dumps(ordered(found), indent=1) if args.json else table(found))
    print(f'{scanned} repos scanned, {len(found)} candidate files', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
