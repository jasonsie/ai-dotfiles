#!/usr/bin/env python3
"""Merge workspace-managed keys into each CLI's live settings; writes unless --dry-run.

config/cli-settings.json lists, per CLI, `enforce` keys (safety settings, put
back on every run) and `default` keys (model choices, written only while the CLI
has no value of its own, so a later pick made in the CLI stays). Every other key,
credential, and runtime value is preserved. Settings files are never symlinked
because each CLI writes back to them. Backs up privately before writing and
rolls back on failure. --uninstall only lists the managed keys left in place.
Requires Python 3.11+ for tomllib.
"""
import copy
import fnmatch
import json
from pathlib import Path
import re
import sys
import tomllib

import installer

WORKSPACE = Path(__file__).resolve().parents[2]
MANAGED = WORKSPACE / 'config/cli-settings.json'
KINDS = ('enforce', 'default')
MISSING = object()


def load_managed(path):
    """Read cli-settings.json (version 2) and refuse an old or ambiguous layout."""
    managed = json.loads(path.read_text())
    if managed.get('version') != 2:
        raise ValueError(f'{path}: expected "version": 2 with per-CLI "enforce" and "default" keys')
    for cli, spec in managed.items():
        if cli == 'version':
            continue
        if cli not in installer.clis():
            raise ValueError(f'{path}: {cli!r} is not in config/ai-clis.json')
        if not isinstance(spec, dict) or not set(spec) <= set(KINDS):
            raise ValueError(f'{path}: {cli} may only have "enforce" and "default" keys')
        both = set(spec.get('enforce', {})) & set(spec.get('default', {}))
        if both:
            raise ValueError(f'{path}: {cli} lists {", ".join(sorted(both))} as both enforce and default')
    return managed


def parse(cli, text):
    return tomllib.loads(text) if cli == 'codex' else (json.loads(text) if text.strip() else {})


def set_dotted(data, dotted, value):
    *parents, leaf = dotted.split('.')
    node = data
    for key in parents:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    node[leaf] = value


def get_dotted(data, dotted):
    node = data
    for key in dotted.split('.'):
        if not isinstance(node, dict) or key not in node:
            return MISSING
        node = node[key]
    return node


def check_pi(data):
    """Refuse a managed default that Pi's own enabledModels scope would hide."""
    patterns = data.get('enabledModels') or []
    full = f"{data.get('defaultProvider', '')}/{data.get('defaultModel', '')}"
    if patterns and not any(fnmatch.fnmatch(full, p) for p in patterns):
        raise ValueError(f'Pi default {full} is not in enabledModels; add it there first')


def merge_json(cli, text, keys):
    original = json.loads(text) if text.strip() else {}
    data = copy.deepcopy(original)
    for key, value in keys.items():
        set_dotted(data, key, value)
    if cli == 'pi' and keys.keys() & {'defaultProvider', 'defaultModel'}:
        check_pi(data)
    return text if data == original else json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def toml_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value)


def merge_toml(text, keys):
    """Upsert top-level scalar keys before the first table; tables are untouched."""
    tomllib.loads(text)
    lines = text.splitlines(keepends=True)
    first_table = next((i for i, line in enumerate(lines) if line.lstrip().startswith('[')), len(lines))
    header, rest = lines[:first_table], lines[first_table:]
    for key, value in keys.items():
        if '.' in key:
            raise ValueError(f'Codex managed keys must be top-level: {key}')
        line = f'{key} = {toml_value(value)}\n'
        pattern = re.compile(rf'^\s*{re.escape(key)}\s*=')
        index = next((i for i, existing in enumerate(header) if pattern.match(existing)), None)
        if index is not None:
            header[index] = line
            continue
        while header and not header[-1].strip():
            header.pop()
        if header and not header[-1].endswith('\n'):
            header[-1] += '\n'
        header.append(line)
        if rest:
            header.append('\n')
    result = ''.join(header + rest)
    parsed = tomllib.loads(result)
    for key, value in keys.items():
        if parsed.get(key) != value:
            raise ValueError(f'Codex key did not round-trip: {key}')
    return result


def split_keys(cli, text, spec):
    """Keys to write now, and the default keys for which the CLI keeps its own value.

    Enforced keys always apply. A default key applies only while the CLI has no
    value for it, so a choice made later in the CLI itself is never undone.
    """
    current = parse(cli, text)
    keys = dict(spec.get('enforce', {}))
    kept = []
    for key, value in spec.get('default', {}).items():
        mine = get_dotted(current, key)
        if mine is MISSING:
            keys[key] = value
        elif mine != value:
            kept.append((key, mine, value))
    return keys, kept


def merge(cli, spec, old):
    """The settings file `old` (bytes) with this CLI's managed keys merged in."""
    text = old.decode()
    keys, _ = split_keys(cli, text, spec)
    return (merge_toml(text, keys) if cli == 'codex' else merge_json(cli, text, keys)).encode()


def plan(home, clis, managed):
    changes = []
    for cli in clis:
        spec = managed.get(cli) or {}
        path = installer.path(home, cli, 'settings')
        if not spec or not path.parent.is_dir():
            continue  # CLI not set up on this machine; it creates its own file on first run
        change = installer.edit(path, lambda old: merge(cli, spec, old))
        if change:
            changes.append(change)
    return changes


def leftovers(home, clis, managed):
    """(path, managed keys present): uninstall leaves them; they do not depend on this repo."""
    found = []
    for cli in clis:
        spec = managed.get(cli) or {}
        path = installer.path(home, cli, 'settings')
        if not spec or not path.is_file():
            continue
        current = parse(cli, path.read_text())
        keys = [key for key in (*spec.get('enforce', {}), *spec.get('default', {}))
                if get_dotted(current, key) is not MISSING]
        if keys:
            found.append((path, keys))
    return found


def local_choices(home, clis, managed):
    """(cli, key, this machine's value, managed default) wherever the CLI kept its own choice."""
    kept = []
    for cli in clis:
        spec = managed.get(cli) or {}
        path = installer.path(home, cli, 'settings')
        if spec and path.is_file() and not path.is_symlink():
            kept += [(cli, *item) for item in split_keys(cli, path.read_text(), spec)[1]]
    return kept


def run(home, target, managed_path, write, uninstall):
    """Merge the keys for the CLIs switched on. Keys are never removed: --uninstall lists
    them, and a CLI switched off keeps them."""
    managed = load_managed(managed_path)
    selected = installer.scope(target)
    if uninstall:
        for path, keys in leftovers(home, selected, managed):
            print(f'Left in place: {path}: {", ".join(keys)}')
        print('Managed keys stay; remove them by hand if unwanted.')
        return 0
    clis = installer.split(selected)[0]
    changes = plan(home, clis, managed)
    for cli, key, mine, default in local_choices(home, clis, managed):
        print(f'Local choice kept: {cli} {key} = {json.dumps(mine)} (default {json.dumps(default)})')
    installer.show(changes, write)
    if write and changes:
        print(f'Backup: {installer.apply(home, changes, backup="settings")}')
    return len(changes)


def main():
    parser = installer.parser(__doc__)
    parser.add_argument('--managed', type=Path, default=MANAGED)
    args = parser.parse_args()
    return installer.finish('settings', lambda: run(
        args.home, args.target, args.managed, not args.dry_run, args.uninstall))


if __name__ == '__main__':
    sys.exit(main())
