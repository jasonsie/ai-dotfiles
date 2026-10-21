#!/usr/bin/env python3
"""Summarize a weekly upstream refresh for review; read-only unless --update-catalogs.

Run after scripts/sync-cli-docs.sh has refreshed upstream/docs/ and the changes are
staged (`git add upstream`). Prints Markdown for the review pull request:

1. Pages added, removed, and changed per tool.
2. Changes that touch this setup: changed lines naming something this repo relies
   on (managed setting keys, instruction files, skill folders, MCP registration).
3. Picked skills (skills/skills.lock; `path` is one file or a list) whose upstream files
   changed since the pinned commit, with a diff per changed file, and skills new in the
   watched skill collections.

--update-catalogs rewrites upstream/catalogs.json (the skill names last seen in each
watched collection) instead of printing the report. Network calls use `gh api`.
"""
import argparse
import base64
import difflib
import json
from pathlib import Path
import re
import subprocess
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
MIRROR = 'upstream/docs'
CATALOGS = 'upstream/catalogs.json'
LOCK = WORKSPACE / 'skills/skills.lock'
MANAGED = WORKSPACE / 'tools/settings/managed.json'
COLLECTIONS = ('affaan-m/everything-claude-code', 'anthropics/skills', 'mattpocock/skills')
FIXED_TERMS = ('AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md', 'GEMINI.md', 'SKILL.md',
               '.agents/skills', '.claude/skills', '.gemini/config', '.pi/agent',
               'mcpServers', 'mcp_servers', 'mcp add', 'mcp.json', 'symlink')
LIMIT = 40


def git(*args):
    return subprocess.run(['git', '-C', str(WORKSPACE), *args], check=True, capture_output=True, text=True).stdout


def gh_json(path):
    return json.loads(subprocess.run(['gh', 'api', path], check=True, capture_output=True, text=True).stdout)


def managed_keys(managed):
    return sorted({key for cli, spec in managed.items() if cli != 'version' for group in spec.values() for key in group})


def terms_in(lines, keys, fixed=FIXED_TERMS):
    """Watched names in changed lines: a key quoted, in backticks, or assigned; a fixed term anywhere."""
    found = set()
    for line in lines:
        found.update(k for k in keys if re.search(rf'[`"\']{re.escape(k)}[`"\']|(?<![\w.-]){re.escape(k)}\s*[=:]', line))
        found.update(t for t in fixed if t in line)
    return found


def parse_diff(text):
    """{path: (added lines, removed lines)} from `git diff --unified=0` output."""
    files, path = {}, None
    for line in text.splitlines():
        if line.startswith('diff --git '):
            path = line.split(' b/', 1)[1]
            files[path] = ([], [])
        elif path and line.startswith('+') and not line.startswith('+++'):
            files[path][0].append(line[1:])
        elif path and line.startswith('-') and not line.startswith('---'):
            files[path][1].append(line[1:])
    return files


def page_counts(name_status):
    """{tool: {'A': n, 'D': n, 'M': n}} from `git diff --name-status` under upstream/docs/<tool>/."""
    counts = {}
    for line in name_status.splitlines():
        status, *paths = line.split('\t')
        tool = paths[-1].split('/')[2]
        kind = {'A': 'A', 'D': 'D'}.get(status[0], 'M')
        counts.setdefault(tool, {'A': 0, 'D': 0, 'M': 0})[kind] += 1
    return counts


def new_skills(before, after):
    """{collection: names added since the last snapshot}; a first snapshot lists nothing."""
    return {repo: sorted(set(names) - set(before[repo])) for repo, names in after.items()
            if repo in before and set(names) - set(before[repo])}


def upstream_text(repo, path, ref=None):
    query = f'?ref={ref}' if ref else ''
    return base64.b64decode(gh_json(f'repos/{repo}/contents/{path}{query}')['content']).decode()


def collection_skills(repo):
    branch = gh_json(f'repos/{repo}')['default_branch']
    tree = gh_json(f'repos/{repo}/git/trees/{branch}?recursive=1')['tree']
    return sorted({Path(entry['path']).parent.name for entry in tree if entry['path'].endswith('/SKILL.md')})


def section_pages(counts):
    if not counts:
        return ['No page changes.']
    rows = ['| Tool | Added | Removed | Changed |', '|---|---|---|---|']
    rows += [f'| {tool} | {n["A"]} | {n["D"]} | {n["M"]} |' for tool, n in sorted(counts.items())]
    return rows


def section_setup(files, keys):
    hits = []
    for path, (added, removed) in sorted(files.items()):
        found = terms_in(added + removed, keys)
        if found:
            names = ', '.join(f'`{term}`' for term in sorted(found))
            hits.append(f'- `{path}` (+{len(added)} −{len(removed)}): {names}')
    if not hits:
        return ['Nothing in this refresh mentions what this setup relies on.']
    more = [f'- … and {len(hits) - LIMIT} more files'] if len(hits) > LIMIT else []
    return hits[:LIMIT] + more


def path_diff(path, pinned, latest):
    diff = ''.join(difflib.unified_diff(pinned.splitlines(True), latest.splitlines(True), 'pinned', 'upstream'))
    return ['', f'<details><summary>Upstream diff: <code>{path}</code></summary>', '', '```diff', diff.rstrip(), '```', '', '</details>']


def section_skills(lock, added):
    lines = []
    for name, entry in sorted(lock['skills'].items()):
        paths = [entry['path']] if isinstance(entry['path'], str) else entry['path']
        texts = {path: tuple(upstream_text(entry['repo'], path, ref) for ref in (entry['commit'], None)) for path in paths}
        changed = [path for path, (pinned, latest) in texts.items() if pinned != latest]
        where = f'`{name}` ({entry["repo"]}, pinned {entry["commit"][:7]})'
        if not changed:
            lines.append(f'- {where}: unchanged upstream.')
            continue
        names = ', '.join(f'`{path}`' for path in changed)
        lines.append(f'- {where}: **changed upstream** ({names}); review against the local copy.')
        for path in changed:
            lines += path_diff(path, *texts[path])
    for repo, names in sorted(added.items()):
        lines.append(f'- New in {repo}: ' + ', '.join(f'`{n}`' for n in names))
    return lines or ['No picked skills.']


def report():
    keys = managed_keys(json.loads(MANAGED.read_text()))
    files = parse_diff(git('diff', '--cached', '--unified=0', '--', MIRROR))
    counts = page_counts(git('diff', '--cached', '--name-status', '--', MIRROR))
    try:
        before = json.loads(git('show', f'HEAD:{CATALOGS}'))['collections']
    except subprocess.CalledProcessError:
        before = {}
    path = WORKSPACE / CATALOGS
    after = json.loads(path.read_text())['collections'] if path.is_file() else {}
    lock = json.loads(LOCK.read_text())
    out = ['## Upstream refresh', '', '### Pages', '', *section_pages(counts), '',
           '### Changes that touch this setup', '', *section_setup(files, keys), '',
           '### Skills', '', *section_skills(lock, new_skills(before, after)), '']
    return '\n'.join(out)


def update_catalogs():
    path = WORKSPACE / CATALOGS
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {'version': 1, 'collections': {repo: collection_skills(repo) for repo in COLLECTIONS}}
    path.write_text(json.dumps(data, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--update-catalogs', action='store_true')
    args = parser.parse_args()
    try:
        if args.update_catalogs:
            update_catalogs()
        else:
            print(report())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        print(f'report-upstream: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
