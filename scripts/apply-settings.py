#!/usr/bin/env python3
"""Merge workspace-managed keys into each CLI's live settings; dry-run unless --apply.

tools/settings/managed.json lists, per CLI, `enforce` keys (safety settings, put
back on every run) and `default` keys (model choices, written only while the CLI
has no value of its own, so a later pick made in the CLI stays). Every other key,
credential, and runtime value is preserved. Settings files are never symlinked
because each CLI writes back to them. Backs up privately before writing and
rolls back on failure. Requires Python 3.11+ for tomllib.
"""
import argparse
import copy
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import tomllib

WORKSPACE = Path(__file__).resolve().parents[1]
MANAGED = WORKSPACE / 'tools/settings/managed.json'
FILES = {
    'claude': '.claude/settings.json',
    'codex': '.codex/config.toml',
    'pi': '.pi/agent/settings.json',
    'agy': '.gemini/antigravity-cli/settings.json',
}
KINDS = ('enforce', 'default')
MISSING = object()


def settings_path(home, cli):
    if cli == 'pi' and home == Path.home() and os.environ.get('PI_CODING_AGENT_DIR'):
        return Path(os.environ['PI_CODING_AGENT_DIR']).expanduser() / 'settings.json'
    return home / FILES[cli]


def load_managed(path):
    """Read managed.json (version 2) and refuse an old or ambiguous layout."""
    managed = json.loads(path.read_text())
    if managed.get('version') != 2:
        raise ValueError(f'{path}: expected "version": 2 with per-CLI "enforce" and "default" keys')
    for cli, spec in managed.items():
        if cli == 'version':
            continue
        if cli not in FILES:
            raise ValueError(f'{path}: unknown CLI {cli!r}')
        if not isinstance(spec, dict) or not set(spec) <= set(KINDS):
            raise ValueError(f'{path}: {cli} may only have "enforce" and "default" keys')
        both = set(spec.get('enforce', {})) & set(spec.get('default', {}))
        if both:
            raise ValueError(f'{path}: {cli} lists {", ".join(sorted(both))} as both enforce and default')
    return managed


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
    current = tomllib.loads(text) if cli == 'codex' else (json.loads(text) if text.strip() else {})
    keys = dict(spec.get('enforce', {}))
    kept = []
    for key, value in spec.get('default', {}).items():
        mine = get_dotted(current, key)
        if mine is MISSING:
            keys[key] = value
        elif mine != value:
            kept.append((key, mine, value))
    return keys, kept


def plan(home, targets, managed):
    changes = []
    for cli in targets:
        spec = managed.get(cli) or {}
        path = settings_path(home, cli)
        if not spec or not path.parent.is_dir():
            continue  # CLI not set up on this machine; it creates its own file on first run
        if path.is_symlink():
            raise ValueError(f'Refusing to write through symlinked settings: {path}')
        before = path.read_bytes() if path.exists() else b''
        text = before.decode()
        keys, _ = split_keys(cli, text, spec)
        after = (merge_toml(text, keys) if cli == 'codex' else merge_json(cli, text, keys)).encode()
        if before != after:
            changes.append((path, before, after))
    return changes


def local_choices(home, targets, managed):
    """(cli, key, this machine's value, managed default) wherever the CLI kept its own choice."""
    kept = []
    for cli in targets:
        spec = managed.get(cli) or {}
        path = settings_path(home, cli)
        if spec and path.is_file() and not path.is_symlink():
            kept += [(cli, *item) for item in split_keys(cli, path.read_text(), spec)[1]]
    return kept


def atomic_write(path, content, mode):
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temp = Path(directory) / 'settings'
        temp.write_bytes(content)
        temp.chmod(mode)
        os.replace(temp, path)


def current(path):
    return path.read_bytes() if path.exists() and not path.is_symlink() else b''


def apply(home, changes):
    root = home / '.local/state/ai-cli-workspace/settings'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix='backup-', dir=root))
    for path, before, _ in changes:
        if path.is_symlink() or current(path) != before:
            raise ValueError(f'Concurrent edit detected: {path}')
        if path.exists():
            saved = backup / path.name if not path.is_relative_to(home) else backup / path.relative_to(home)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
    done = []
    try:
        for path, before, after in changes:
            if path.is_symlink() or current(path) != before:
                raise ValueError(f'Concurrent edit detected: {path}')
            existed = path.exists()
            mode = path.stat().st_mode & 0o777 if existed else 0o600
            done.append((path, before, mode, existed))
            atomic_write(path, after, mode)
    except BaseException:
        for path, before, mode, existed in reversed(done):
            if existed:
                atomic_write(path, before, mode)
            else:
                path.unlink(missing_ok=True)
        raise
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--target', choices=('all', *FILES), default='all')
    parser.add_argument('--managed', type=Path, default=MANAGED)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    targets = tuple(FILES) if args.target == 'all' else (args.target,)
    try:
        managed = load_managed(args.managed)
        changes = plan(home, targets, managed)
        for cli, key, mine, default in local_choices(home, targets, managed):
            print(f'Local choice kept: {cli} {key} = {json.dumps(mine)} (default {json.dumps(default)})')
        for path, _, _ in changes:
            print(f'{"Update" if args.apply else "Would update"}: {path}')
        if args.apply and changes:
            print(f'Backup: {apply(home, changes)}')
    except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
        print(f'settings: {e}', file=sys.stderr)
        return 1
    print(f'settings: {len(changes)} changes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
