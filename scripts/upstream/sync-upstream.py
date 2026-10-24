#!/usr/bin/env python3
"""Mirror upstream docs into docs/upstream/ and index them; the sources are config/upstream-docs.json.

Kinds of source:
  llms       an llms.txt index (Claude Code, Codex, Antigravity): every listed URL is fetched as
             Markdown, as listed when it ends in .md, otherwise with .md appended, and saved under
             its path below `prefix`; a `?surface=<s>` variant is saved as <page>.surface-<s>.md.
  docs-json  a docs.json whose `navigation` lists .md pages in a GitHub repository (Pi).
  github     files in GitHub repositories, named by path or glob under `repos` and fetched raw from
             the branch in `ref`; .html and .rst are converted to Markdown with pandoc.

Output, per source: docs/upstream/<source>/, one file per page with a static header (no timestamp,
so an unchanged page produces no diff), MIRROR-INDEX.md (the pages, their `when` labels and the
source's notes) and MIRROR-INDEX.json (per page: title, description, when, source URL, license, last
commit, size and the heading outline with line numbers). docs/upstream/INDEX.md lists the sources.
Each directory is rebuilt per run, so pages removed upstream disappear here too. A source fails
closed: when its index lists, or its fetches return, fewer pages than its floor (for GitHub sources,
every explicit path and every glob's own floor), the previous copy stays and the run exits non-zero.

Usage: sync-upstream.py [source ...] [--index-only] [--mirror DIR]      (default: every source)
  --index-only rebuilds the indexes from the pages already on disk; nothing is fetched except an
  llms.txt for page descriptions. GitHub API calls use GH_TOKEN, GITHUB_TOKEN or `gh auth token`.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.parse

WORKSPACE = Path(__file__).resolve().parents[2]
CONFIG = WORKSPACE / 'config/upstream-docs.json'
MIRROR = WORKSPACE / 'docs/upstream'
USER_AGENT = 'ai-dotfiles-docs-sync/1.0 (+https://github.com)'
WORKFLOW = '.github/workflows/sync-cli-docs.yml'
MAINTAINED = f'> Mirror maintained by {WORKFLOW} — do not edit by hand.\n'
INDEX_MD, INDEX_JSON, CATALOG = 'MIRROR-INDEX.md', 'MIRROR-INDEX.json', 'INDEX.md'
KINDS = {'llms': ('index', 'urls', 'prefix', 'floor'), 'docs-json': ('index', 'raw', 'pages', 'floor'),
         'github': ('owner', 'repos')}
STRINGS = ('name', 'description', 'index', 'urls', 'prefix', 'raw', 'pages', 'owner')
CONVERT = {'.html': 'html', '.rst': 'rst'}  # pandoc readers by extension
OUTLINED = {'.md', '.mdx', '.markdown'}


def sources(path=CONFIG):
    """{id: spec} from config/upstream-docs.json, checked strictly."""
    data = json.loads(path.read_text())
    if data.get('version') != 1 or not isinstance(data.get('sources'), dict) or not data['sources']:
        raise ValueError(f'{path}: expected "version": 1 and a non-empty "sources" object')
    for sid, spec in data['sources'].items():
        where = f'{path}: {sid}'
        if not re.fullmatch(r'[a-z][a-z0-9-]*', sid):
            raise ValueError(f'{where}: a source id is lowercase letters, digits and dashes')
        if not isinstance(spec, dict) or spec.get('kind') not in KINDS:
            raise ValueError(f'{where}: "kind" must be one of {", ".join(KINDS)}')
        check_keys(where, spec, ('name', 'description', 'kind', *KINDS[spec['kind']]), ('notes',))
        for key in STRINGS:
            if key in spec and not (isinstance(spec[key], str) and spec[key]):
                raise ValueError(f'{where}: "{key}" must be a non-empty string')
        if 'floor' in spec and not positive(spec['floor']):
            raise ValueError(f'{where}: "floor" must be a positive integer')
        notes = spec.get('notes', {})
        listed = lambda v: isinstance(v, list) and all(isinstance(s, str) for s in v)  # noqa: E731
        if not isinstance(notes, dict) or not all(listed(v) for v in notes.values()):
            raise ValueError(f'{where}: "notes" must map titles to lists of strings')
        if spec['kind'] == 'github':
            check_repos(where, spec['repos'])
    return data['sources']


def positive(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def check_keys(where, mapping, required, optional=()):
    if not isinstance(mapping, dict):
        raise ValueError(f'{where}: expected an object')
    missing = [key for key in required if key not in mapping]
    unknown = sorted(set(mapping) - set(required) - set(optional))
    if missing or unknown:
        problems = [f'is missing "{key}"' for key in missing] + [f'has unknown key "{key}"' for key in unknown]
        raise ValueError(f'{where} ' + ', '.join(problems))


def check_repos(where, repos):
    if not isinstance(repos, dict) or not repos:
        raise ValueError(f'{where}: "repos" must be a non-empty object')
    for repo, rspec in repos.items():
        here = f'{where} {repo}'
        check_keys(here, rspec, ('ref', 'license', 'paths'))
        if not all(isinstance(rspec[key], str) and rspec[key] for key in ('ref', 'license')):
            raise ValueError(f'{here}: "ref" and "license" must be non-empty strings')
        if not isinstance(rspec['paths'], list) or not rspec['paths']:
            raise ValueError(f'{here}: "paths" must be a non-empty list')
        for entry in rspec['paths']:
            check_keys(here, entry, ('path', 'when'), ('floor', 'exclude', 'convert'))
            name = f'{here} {entry["path"]}'
            if not all(isinstance(entry[key], str) and entry[key] for key in ('path', 'when')):
                raise ValueError(f'{name}: "path" and "when" must be non-empty strings')
            if not isinstance(entry.get('convert', True), bool):
                raise ValueError(f'{name}: "convert" must be true or false')
            if not all(isinstance(x, str) for x in entry.get('exclude', [])):
                raise ValueError(f'{name}: "exclude" must be a list of globs')
            if is_glob(entry['path']) and not positive(entry.get('floor')):
                raise ValueError(f'{name}: a glob needs a positive "floor"')
            if not is_glob(entry['path']) and ('floor' in entry or 'exclude' in entry):
                raise ValueError(f'{name}: "floor" and "exclude" belong to globs')


def is_glob(pattern):
    return any(c in pattern for c in '*?[')


def glob_regex(pattern):
    """A regex for a path glob: `*` and `?` stay inside one segment, `**` spans segments."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
        elif pattern.startswith('**', i):
            out.append('.*')
            i += 2
        elif pattern[i] in '*?':
            out.append('[^/]*' if pattern[i] == '*' else '[^/]')
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile(''.join(out) + r'\Z')


def select(paths, entry):
    """The tree paths an entry names: its explicit path when present, else the glob's matches minus excludes."""
    if not is_glob(entry['path']):
        return [entry['path']] if entry['path'] in paths else []
    wanted, unwanted = glob_regex(entry['path']), [glob_regex(x) for x in entry.get('exclude', [])]
    return sorted(p for p in paths if wanted.match(p) and not any(x.match(p) for x in unwanted))


def mirrored_name(path, convert=True):
    """Where an upstream path lands: converted formats become .md."""
    suffix = Path(path).suffix.lower()
    return path[:-len(suffix)] + '.md' if convert and suffix in CONVERT else path


def fetch(url, headers=()):
    """The body at url as bytes; retries transient failures; fails on HTTP >= 400 (curl, as the bash sync did)."""
    command = ['curl', '-fsSL', '--compressed', '--retry', '3', '--retry-delay', '2', '--max-time', '30',
               '-A', USER_AGENT]
    if headers:
        command += ['-H', '@-']
    return subprocess.run([*command, url], check=True, capture_output=True, input='\n'.join(headers).encode()).stdout


def token():
    for name in ('GH_TOKEN', 'GITHUB_TOKEN'):
        if os.environ.get(name):
            return os.environ[name]
    try:
        return subprocess.run(['gh', 'auth', 'token'], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def api(path, auth):
    headers = ['Accept: application/vnd.github+json'] + ([f'Authorization: Bearer {auth}'] if auth else [])
    return json.loads(fetch(f'https://api.github.com/{path}', headers))


def last_commit(base, ref, path, auth):
    """The SHA of the last commit that touched path on ref, or None when the API does not say."""
    try:
        commits = api(f'{base}/commits?path={urllib.parse.quote(path)}&sha={ref}&per_page=1', auth)
        return commits[0]['sha'] if commits else None
    except (subprocess.CalledProcessError, ValueError, KeyError, IndexError, TypeError):
        return None


def pandoc(body, reader):
    command = ['pandoc', '-f', reader, '-t', 'gfm', '--wrap=none']
    return subprocess.run(command, check=True, capture_output=True, input=body).stdout


def is_html(body):
    return body.startswith((b'<!DOCTYPE', b'<!doctype', b'<html'))


def page(source_url, body, license=None, converted=None):
    """The page file: static header, blank line, the body with one trailing newline (as the bash sync wrote it)."""
    head = f'> Source: {source_url}\n' + MAINTAINED
    head += f'> License: {license}\n' if license else ''
    head += f'> Converted from {converted} with pandoc.\n' if converted else ''
    return head.encode() + b'\n' + body.rstrip(b'\n') + b'\n'


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def outline(text):
    """[level, text, line] per ATX or setext heading, fenced code and front matter skipped; lines are 1-based and
    count newlines only."""
    found, fence, prev, started, front = [], None, '', False, False
    for n, line in enumerate(text.split('\n'), 1):
        s = line.strip()
        if front:
            front, prev = s != '---', ''
            continue
        if fence:
            fence, prev = (None if s.startswith(fence) else fence), ''
            continue
        if s.startswith(('```', '~~~')):
            fence, prev = s[:3], ''
            continue
        if not started and s == '---':
            front = True
            continue
        started = started or bool(s) and not s.startswith('>')
        m = re.match(r'(#{1,6})(?:\s+(.*?))?\s*$', s)
        if m:
            found.append([len(m.group(1)), heading_text(m.group(2)), n])
        elif prev and len(s) >= 3 and set(s) in ({'='}, {'-'}) and not prev.startswith(('>', '-', '*', '+', '|', '#')) \
                and not re.match(r'\d+[.)]\s', prev):
            found.append([1 if s[0] == '=' else 2, heading_text(prev), n - 1])
        prev = s
    return found


def heading_text(text):
    """A heading's text without closing hashes or inline HTML (pandoc leaves anchors in converted guides)."""
    return re.sub(r'<[^>]*>', '', re.sub(r'\s+#+$', '', text or '')).strip()


def title_of(headings, fallback):
    for level, text, _ in headings:
        if level == 1 and text:
            return text
    return headings[0][1] if headings and headings[0][1] else fallback


def meta(rel, data, title=None, description=None, when=None, source=None, license=None, commit=None):
    """One page's index entry, from the bytes written to disk (so heading lines count the header)."""
    text = data.decode('utf-8', 'replace')
    headings = outline(text) if Path(rel).suffix.lower() in OUTLINED else []
    lines = len(text.rstrip('\n').split('\n')) if text else 0
    return {'path': rel, 'title': title_of(headings, title or Path(rel).name), 'description': description, 'when': when,
            'source': source, 'license': license, 'commit': commit, 'bytes': len(data), 'lines': lines,
            'headings': headings}


def descriptions(index):
    """{url: (title, description)} from an llms.txt's `- [Title](url): description` lines."""
    found = {}
    for m in re.finditer(r'^\s*[-*]\s+\[([^\]]*)\]\(([^)\s]+)\)(?::\s*(.*?))?\s*$', index, re.M):
        found[m.group(2)] = (m.group(1), m.group(3) or None)
    return found


def described(known, source):
    """The llms.txt entry for a page's Source URL, listed with or without .md and with a surface variant."""
    for key in (source, source + '.md', source.replace('?', '.md?', 1)):
        if key in known:
            return known[key]
    return (None, None)


def sync_llms(sid, spec, stage, auth):
    index = fetch(spec['index']).decode('utf-8', 'replace')
    urls = sorted({m.group(0) for m in re.finditer(spec['urls'], index)})
    if len(urls) < spec['floor']:
        return [], [f'the index lists {len(urls)} pages (< {spec["floor"]})'], False
    known, pages, misses = descriptions(index), [], []
    for url in urls:
        md = url if url.endswith('.md') or '.md?surface=' in url else url + '.md'
        rel, source = md[len(spec['prefix']):], md.replace('.md?', '?', 1).removesuffix('.md')
        if '.md?surface=' in rel:
            base, _, surface = rel.partition('.md?surface=')
            rel = f'{base}.surface-{surface}.md'
        try:
            body = fetch(md)
        except subprocess.CalledProcessError:
            misses.append(f'failed to fetch {md}')
            continue
        if is_html(body):
            misses.append(f'{md} returned HTML, not Markdown; skipped')
            continue
        data = page(source, body)
        write(stage / rel, data)
        title, description = known.get(url, (None, None))
        pages.append(meta(rel, data, title, description, source=source))
    return pages, misses, len(pages) >= spec['floor']


def walk(node):
    """(path, title) for every docs.json navigation node that names a .md page."""
    if isinstance(node, dict):
        path = node.get('path')
        if isinstance(path, str) and path.endswith('.md') and '://' not in path and '..' not in path:
            yield path, node.get('title') if isinstance(node.get('title'), str) else None
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def sync_docs_json(sid, spec, stage, auth):
    listed = dict(walk(json.loads(fetch(spec['index']))['navigation']))
    if len(listed) < spec['floor']:
        return [], [f'docs.json lists {len(listed)} pages (< {spec["floor"]})'], False
    pages, misses = [], []
    for rel in sorted(listed):
        source = f'{spec["pages"]}/{rel}'
        try:
            body = fetch(f'{spec["raw"]}/{rel}')
        except subprocess.CalledProcessError:
            misses.append(f'failed to fetch {spec["raw"]}/{rel}')
            continue
        if is_html(body):
            misses.append(f'{spec["raw"]}/{rel} returned HTML, not Markdown; skipped')
            continue
        data = page(source, body)
        write(stage / rel, data)
        pages.append(meta(rel, data, listed[rel], source=source))
    return pages, misses, len(pages) >= spec['floor']


def sync_github(sid, spec, stage, auth):
    pages, misses = [], []
    for repo, rspec in spec['repos'].items():
        base, ref = f'repos/{spec["owner"]}/{repo}', rspec['ref']
        try:
            tree = api(f'{base}/git/trees/{ref}?recursive=1', auth)
            paths = {e['path'] for e in tree['tree'] if e.get('type') == 'blob'}
        except (subprocess.CalledProcessError, ValueError, KeyError, TypeError):
            misses.append(f'{repo}: cannot list the tree at {ref}')
            continue
        if tree.get('truncated'):
            print(f'[{sid}] WARN: {repo}: the tree listing is truncated; globs may miss files', file=sys.stderr)
        for entry in rspec['paths']:
            chosen = select(paths, entry)
            if len(chosen) < entry.get('floor', 1):
                misses.append(f'{repo}/{entry["path"]}: {len(chosen)} of {entry.get("floor", 1)} files in the tree')
                continue
            for path in chosen:
                raw = f'https://raw.githubusercontent.com/{spec["owner"]}/{repo}/{ref}/{path}'
                source = f'https://github.com/{spec["owner"]}/{repo}/blob/{ref}/{path}'
                convert = entry.get('convert', True)
                reader = CONVERT.get(Path(path).suffix.lower()) if convert else None
                try:
                    body = fetch(raw)
                    body = pandoc(body, reader) if reader else body
                except subprocess.CalledProcessError as e:
                    detail = e.stderr.decode(errors='replace').strip()[:200] or e.returncode
                    misses.append(f'{repo}/{path}: {"pandoc" if reader else "fetch"} failed ({detail})')
                    continue
                except OSError as e:
                    misses.append(f'{repo}/{path}: pandoc is not installed ({e})')
                    continue
                rel = f'{repo}/{mirrored_name(path, convert)}'
                data = page(source, body, rspec['license'], reader)
                write(stage / rel, data)
                pages.append(meta(rel, data, when=entry['when'], source=source, license=rspec['license'],
                                  commit=last_commit(base, ref, path, auth)))
    return pages, misses, not misses


SYNC = {'llms': sync_llms, 'docs-json': sync_docs_json, 'github': sync_github}


def kb(size):
    return max(1, round(size / 1024))


def index_json(data):
    """The index as JSON with one page per line, so a weekly diff shows which pages changed."""
    head = json.dumps({k: v for k, v in data.items() if k not in ('pages', 'notes')}, ensure_ascii=False)
    pages = [json.dumps(p, ensure_ascii=False) for p in data['pages']]
    body = [' ' + page + (',' if i < len(pages) - 1 else '') for i, page in enumerate(pages)]
    notes = json.dumps(data['notes'], ensure_ascii=False, indent=1).replace('\n', '\n ')
    return '\n'.join([head[:-1] + ',', '"pages": [', *body, '],', f'"notes": {notes}}}']) + '\n'


def index_md(spec, pages):
    out = [f'# {spec["name"]} — mirrored docs index', '', f'Auto-generated by `{WORKFLOW}`. Do not edit by hand.',
           spec['description'], '',
           'Consult through the `upstream-docs` skill (`find`, `outline`, `show`): read a section, not a file.',
           '', f'Pages: {len(pages)}', '']
    if spec['kind'] == 'github':
        for repo, rspec in spec['repos'].items():
            mine = [p for p in pages if p['path'].startswith(repo + '/')]
            out += [f'## {repo} (`{rspec["ref"]}`, {rspec["license"]})', '', '| When | Page | KB |', '|---|---|---|']
            out += [f'| {p["when"] or ""} | [{p["path"]}]({p["path"]}) | {kb(p["bytes"])} |' for p in mine] + ['']
    else:
        out += [f'- [{p["path"]}]({p["path"]})' + (f': {p["description"]}' if p['description'] else '')
                for p in pages] + ['']
    for title, items in spec.get('notes', {}).items():
        out += [f'## {title}', '', *[f'- {item}' for item in items], '']
    return '\n'.join(out)


def write_indexes(folder, sid, spec, pages):
    pages.sort(key=lambda p: p['path'])
    data = {'version': 1, 'source': sid, 'name': spec['name'], 'description': spec['description'], 'pages': pages,
            'notes': spec.get('notes', {})}
    (folder / INDEX_JSON).write_text(index_json(data))
    (folder / INDEX_MD).write_text(index_md(spec, pages))


def write_catalog(mirror, specs):
    """docs/upstream/INDEX.md: every source with an index on disk, in config order."""
    on_disk = [d.name for d in mirror.iterdir() if (d / INDEX_JSON).is_file()]
    rows = []
    for sid in [s for s in specs if s in on_disk] + sorted(s for s in on_disk if s not in specs):
        data = json.loads((mirror / sid / INDEX_JSON).read_text())
        kind = specs.get(sid, {}).get('kind', '?')
        rows.append(f'| [{sid}]({sid}/{INDEX_MD}) | {kind} | {len(data["pages"])} | {data["description"]} |')
    if rows:
        (mirror / CATALOG).write_text('\n'.join([
            '# Upstream docs — mirror index', '', f'Auto-generated by `{WORKFLOW}`. Do not edit by hand.',
            'Machine-written mirrors of upstream documentation, one folder per source in `config/upstream-docs.json`.',
            'Consult through the `upstream-docs` skill (`find`, `outline`, `show`); add a source with `collect-docs`.',
            '',
            '| Source | Kind | Pages | What |', '|---|---|---|---|', *rows, '']))


def finish(mirror, sid, spec, stage, pages, misses, ok):
    """Replace docs/upstream/<source>/ with the stage when the source met its floor; else keep the previous copy."""
    for miss in misses:
        print(f'[{sid}] WARN: {miss}', file=sys.stderr)
    if not ok:
        print(f'[{sid}] ERROR: only {len(pages)} pages fetched ({len(misses)} problems); '
              f'keeping the previous {mirror / sid}', file=sys.stderr)
        return False
    lower = [p['path'].lower() for p in pages]
    clash = sorted({name for name in lower if lower.count(name) > 1})
    if clash:
        print(f'[{sid}] WARN: pages differ only in case; one overwrote the other on a case-insensitive disk: '
              f'{" ".join(clash)}', file=sys.stderr)
    write_indexes(stage, sid, spec, pages)
    shutil.rmtree(mirror / sid, ignore_errors=True)
    stage.rename(mirror / sid)
    print(f'[{sid}] done: ok={len(pages)} fail={len(misses)} -> {mirror / sid}')
    return True


def header_fields(text):
    """{'source': url, 'license': spdx, ...} from a page's leading `> Key: value` lines."""
    fields = {}
    for line in text.splitlines()[:6]:
        if not line.startswith('> '):
            break
        key, sep, value = line[2:].partition(': ')
        if sep:
            fields[key.lower()] = value
    return fields


def when_for(spec, rel):
    """The `when` label a GitHub source's config gives a mirrored path, or None."""
    if spec['kind'] != 'github':
        return None
    repo, _, path = rel.partition('/')
    candidates = [path] + [path[:-3] + ext for ext in CONVERT if path.endswith('.md')]
    for entry in spec['repos'].get(repo, {}).get('paths', []):
        if select(set(candidates), entry):
            return entry['when']
    return None


def reindex(mirror, sid, spec):
    """Rebuild a source's indexes from the pages on disk; the old index supplies commits and, offline, descriptions."""
    folder = mirror / sid
    if not folder.is_dir():
        print(f'[{sid}] ERROR: nothing to index at {folder}', file=sys.stderr)
        return False
    index = folder / INDEX_JSON
    old = {p['path']: p for p in json.loads(index.read_text())['pages']} if index.is_file() else {}
    known = {}
    if spec['kind'] == 'llms':
        try:
            known = descriptions(fetch(spec['index']).decode('utf-8', 'replace'))
        except subprocess.CalledProcessError:
            print(f'[{sid}] WARN: cannot fetch {spec["index"]}; descriptions come from the previous index',
                  file=sys.stderr)
    pages = []
    for file in sorted(p for p in folder.rglob('*') if p.is_file() and p.name not in (INDEX_MD, INDEX_JSON)):
        rel, data = file.relative_to(folder).as_posix(), file.read_bytes()
        fields, before = header_fields(data.decode('utf-8', 'replace')), old.get(rel, {})
        source = fields.get('source') or before.get('source')
        title, description = described(known, source or '')
        pages.append(meta(rel, data, title or before.get('title'), description or before.get('description'),
                          when_for(spec, rel), source, fields.get('license') or before.get('license'),
                          before.get('commit')))
    write_indexes(folder, sid, spec, pages)
    print(f'[{sid}] indexed: {len(pages)} pages -> {folder}')
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('sources', nargs='*', help='source ids from config/upstream-docs.json (default: all)')
    parser.add_argument('--index-only', action='store_true', help='rebuild MIRROR-INDEX.* from the pages on disk')
    parser.add_argument('--mirror', type=Path, default=MIRROR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        specs = sources()
    except (OSError, ValueError) as e:
        print(f'sync-upstream: {e}', file=sys.stderr)
        return 1
    chosen = args.sources or list(specs)
    unknown = [s for s in chosen if s not in specs]
    if unknown:
        print(f'Unknown source: {", ".join(unknown)} ({", ".join(specs)})', file=sys.stderr)
        return 1
    mirror = args.mirror.resolve()
    mirror.mkdir(parents=True, exist_ok=True)
    auth = token() if not args.index_only and any(specs[s]['kind'] == 'github' for s in chosen) else ''
    status = 0
    for sid in chosen:
        spec = specs[sid]
        if args.index_only:
            status = status or int(not reindex(mirror, sid, spec))
            continue
        stage = mirror / f'{sid}.tmp'
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir()
        try:
            print(f'[{sid}] discovering pages from {spec.get("index") or spec["owner"] + " repositories on GitHub"}')
            if not finish(mirror, sid, spec, stage, *SYNC[spec['kind']](sid, spec, stage, auth)):
                status = 1
        except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError) as e:
            print(f'[{sid}] ERROR: {e}; keeping the previous {mirror / sid}', file=sys.stderr)
            status = 1
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    write_catalog(mirror, specs)
    return status


if __name__ == '__main__':
    sys.exit(main())
