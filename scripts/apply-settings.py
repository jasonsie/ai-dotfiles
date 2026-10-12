#!/usr/bin/env python3
"""Merge workspace-managed keys into each CLI's live settings; dry-run unless --apply.

Only keys listed in tools/settings/managed.json are written; every other key,
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
    'gemini': '.gemini/settings.json',
    'pi': '.pi/agent/settings.json',
}


def settings_path(home, cli):
    if cli == 'pi' and home == Path.home() and os.environ.get('PI_CODING_AGENT_DIR'):
        return Path(os.environ['PI_CODING_AGENT_DIR']).expanduser() / 'settings.json'
    return home / FILES[cli]


def set_dotted(data, dotted, value):
    *parents, leaf = dotted.split('.')
    node = data
    for key in parents:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    node[leaf] = value


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
    if cli == 'pi':
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


def plan(home, targets, managed):
    changes = []
    for cli in targets:
        keys = managed.get(cli) or {}
        path = settings_path(home, cli)
        if not keys or not path.parent.is_dir():
            continue  # CLI not set up on this machine; it creates its own file on first run
        if path.is_symlink():
            raise ValueError(f'Refusing to write through symlinked settings: {path}')
        before = path.read_bytes() if path.exists() else b''
        text = before.decode()
        after = (merge_toml(text, keys) if cli == 'codex' else merge_json(cli, text, keys)).encode()
        if before != after:
            changes.append((path, before, after))
    return changes


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
        changes = plan(home, targets, json.loads(args.managed.read_text()))
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
