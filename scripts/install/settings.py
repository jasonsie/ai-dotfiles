#!/usr/bin/env python3
"""Merge workspace-managed keys into each CLI's live settings; writes unless --dry-run.

config/cli-settings.json lists, per CLI, `enforce` keys (settings this repo owns: safety
settings and the status line, put back on every run) and `default` keys (model choices and
other values the CLI writes back, such as Claude Code's consent to a permission dialog; written
only while the CLI has no value of its own, so a later pick made in the CLI stays).
Every other key, credential, and runtime value is preserved. Settings files are never
symlinked because each CLI writes back to them. A key is a dotted path into JSON; for Codex's
TOML it is a top-level key, or `table.key` inside that table. Backs up privately before
writing and rolls back on failure. --uninstall removes a managed key whose live value runs
this repo's command (the status line's `ai-dotfiles statusline`), which would dangle once the
repo is gone, and lists the rest, which stay. Requires Python 3.11+ for tomllib.
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


def del_dotted(data, dotted):
    *parents, leaf = dotted.split('.')
    node = data
    for key in parents:
        node = node.get(key) if isinstance(node, dict) else None
    if isinstance(node, dict):
        node.pop(leaf, None)


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


def toml_section(lines, table):
    """The (start, end) line range of `table` ('' for the keys before the first table), or None when absent."""
    start = 0
    if table:
        header = re.compile(r'^\s*\[\s*' + re.escape(table) + r'\s*\]\s*(#.*)?$')
        starts = [i + 1 for i, line in enumerate(lines) if header.match(line)]
        if not starts:
            return None
        start = starts[0]
    end = next((i for i in range(start, len(lines)) if lines[i].lstrip().startswith('[')), len(lines))
    return start, end


def upsert_toml(lines, table, leaf, value):
    """The lines with `leaf = value` set in `table`, which is added at the end when absent."""
    line = f'{leaf} = {toml_value(value)}\n'
    section = toml_section(lines, table)
    if section is None:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        return lines + (['\n'] if lines else []) + [f'[{table}]\n', line]
    start, end = section
    pattern = re.compile(rf'^\s*{re.escape(leaf)}\s*=')
    index = next((i for i in range(start, end) if pattern.match(lines[i])), None)
    if index is not None:
        lines[index] = line
        return lines
    body = lines[start:end]
    while body and not body[-1].strip():
        body.pop()
    if body and not body[-1].endswith('\n'):
        body[-1] += '\n'
    body.append(line)
    if end < len(lines):
        body.append('\n')
    return lines[:start] + body + lines[end:]


def merge_toml(text, keys):
    """Upsert each key: a plain key before the first table, `table.key` inside that table; other tables untouched."""
    tomllib.loads(text)
    lines = text.splitlines(keepends=True)
    for key, value in keys.items():
        table, _, leaf = key.rpartition('.')
        if '.' in table:
            raise ValueError(f'Codex managed keys are top-level or one table deep: {key}')
        lines = upsert_toml(lines, table, leaf, value)
    result = ''.join(lines)
    parsed = tomllib.loads(result)
    for key, value in keys.items():
        if get_dotted(parsed, key) != value:
            raise ValueError(f'Codex key did not round-trip: {key}')
    return result


def drop_toml(text, keys):
    """The TOML without the lines that set `keys`; a value spanning lines fails the round trip and is refused."""
    lines = text.splitlines(keepends=True)
    for key in keys:
        table, _, leaf = key.rpartition('.')
        section = toml_section(lines, table)
        if section is None:
            continue
        start, end = section
        pattern = re.compile(rf'^\s*{re.escape(leaf)}\s*=')
        lines = [line for i, line in enumerate(lines) if not (start <= i < end and pattern.match(line))]
    result = ''.join(lines)
    parsed = tomllib.loads(result)
    for key in keys:
        if get_dotted(parsed, key) is not MISSING:
            raise ValueError(f'Codex key could not be removed: {key}')
    return result


def drop(cli, text, keys):
    """The settings text without the managed `keys`."""
    if cli == 'codex':
        return drop_toml(text, keys)
    data = json.loads(text) if text.strip() else {}
    for key in keys:
        del_dotted(data, key)
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def depends_on_repo(value):
    """A live value that runs this repo's command works only while the repo is installed."""
    return 'ai-dotfiles' in json.dumps(value)


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
    """(cli, path, remove, keep) per settings file: the managed keys present, split into those whose
    live value runs this repo's command, which an uninstall removes, and the rest, which stay."""
    found = []
    for cli in clis:
        spec = managed.get(cli) or {}
        path = installer.path(home, cli, 'settings')
        if not spec or not path.is_file():
            continue
        current = parse(cli, path.read_text())
        present = [key for key in (*spec.get('enforce', {}), *spec.get('default', {}))
                   if get_dotted(current, key) is not MISSING]
        remove = [key for key in present if depends_on_repo(get_dotted(current, key))]
        found.append((cli, path, remove, [key for key in present if key not in remove]))
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
    """Merge the keys for the CLIs switched on. --uninstall removes the keys that run this repo's
    command and lists the others, which stay; a CLI switched off keeps them all."""
    managed = load_managed(managed_path)
    selected = installer.scope(target)
    if uninstall:
        changes = []
        for cli, path, remove, keep in leftovers(home, selected, managed):
            if remove:
                change = installer.edit(path, lambda old, cli=cli, remove=remove: drop(cli, old.decode(), remove).encode())
                if change:
                    changes.append(change)
            if keep:
                print(f'Left in place: {path}: {", ".join(keep)}')
        installer.show(changes, write)
        if write and changes:
            print(f'Backup: {installer.apply(home, changes, backup="settings")}')
        print('Managed keys stay unless they run this repo; remove them by hand if unwanted.')
        return len(changes)
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
