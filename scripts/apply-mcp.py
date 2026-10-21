#!/usr/bin/env python3
"""Register shared MCP servers in each CLI; writes unless --dry-run.

Presence is read from each CLI's user-scope config. Claude Code, Codex and Pi get a
missing server through their own `mcp add`, so this never hand-edits their files.
Antigravity has no such command, so its ~/.gemini/config/mcp_config.json is merged:
only missing servers are added, everything else is kept, and the file is backed up
first. Existing entries with the same name are left alone (report only).
--uninstall only lists the shared servers left in place.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

WORKSPACE = Path(__file__).resolve().parents[1]
SERVERS = WORKSPACE / 'tools/mcp/servers.json'
CLIS = ('claude', 'codex', 'pi', 'agy')
AGY_CONFIG = '.gemini/config/mcp_config.json'


def pi_root(home):
    if home == Path.home() and os.environ.get('PI_CODING_AGENT_DIR'):
        return Path(os.environ['PI_CODING_AGENT_DIR']).expanduser()
    return home / '.pi/agent'


def read_json(path):
    text = path.read_text()
    return json.loads(text) if text.strip() else {}


def configured(home, cli):
    """Names of user-scope MCP servers already known to a CLI."""
    try:
        if cli == 'claude':
            return set(read_json(home / '.claude.json').get('mcpServers', {}))
        if cli == 'codex':
            return set(tomllib.loads((home / '.codex/config.toml').read_text()).get('mcp_servers', {}))
        if cli == 'pi':
            return set(read_json(pi_root(home) / 'mcp.json').get('mcpServers', {}))
        if cli == 'agy':
            return set(read_json(home / AGY_CONFIG).get('mcpServers', {}))
    except FileNotFoundError:
        return set()
    raise ValueError(cli)


def leftovers(home, targets, servers):
    """(cli, name) of shared servers present: uninstall leaves them; they do not depend on this repo."""
    names = {server['name'] for server in servers}
    return [(cli, name) for cli in targets for name in sorted(configured(home, cli) & names)]


def add_command(cli, server):
    name, command, args = server['name'], server['command'], server.get('args', [])
    if cli == 'claude':
        return ['claude', 'mcp', 'add', '-s', 'user', name, '--', command, *args]
    if cli == 'codex':
        return ['codex', 'mcp', 'add', name, '--', command, *args]
    if cli == 'pi':
        described = ['--description', server['description']] if server.get('description') else []
        return ['pi', 'mcp', 'add', name, *described, '--', command, *args]
    raise ValueError(cli)


def merge_agy(path, servers):
    """(path, before, after) adding the given stdio servers to Antigravity's mcp_config.json."""
    if path.is_symlink():
        raise ValueError(f'Refusing to write through a symlinked MCP config: {path}')
    before = path.read_bytes() if path.exists() else b''
    data = json.loads(before) if before.strip() else {}
    entries = data.setdefault('mcpServers', {})
    for server in servers:
        entries[server['name']] = {'command': server['command'], 'args': server.get('args', [])}
    return path, before, (json.dumps(data, indent=2) + '\n').encode()


def plan(home, targets, servers, which=shutil.which):
    """Native commands to run, and (path, before, after) file merges for CLIs without one."""
    commands, files = [], []
    for cli in targets:
        if not which(cli):
            print(f'mcp: skip {cli} (not on PATH)')
            continue
        present = configured(home, cli)
        missing = [s for s in servers if cli in s.get('targets', CLIS) and s['name'] not in present]
        if not missing:
            continue
        if cli == 'agy':
            path = home / AGY_CONFIG
            if not path.parent.is_dir():
                print('mcp: skip agy (not set up on this machine)')
                continue
            files.append(merge_agy(path, missing))
        else:
            commands += [add_command(cli, server) for server in missing]
    return commands, files


def write_files(home, files):
    """Back up, then write each merged file atomically; restore them all if one fails."""
    root = home / '.local/state/ai-dotfiles/mcp'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix='backup-', dir=root))
    done = []
    try:
        for path, before, after in files:
            if path.is_symlink() or (path.read_bytes() if path.exists() else b'') != before:
                raise ValueError(f'Concurrent edit detected: {path}')
            mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
            if path.exists():
                saved = backup / path.relative_to(home)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, saved)
            done.append((path, before, mode))
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
                f.write(after)
            os.chmod(f.name, mode)
            os.replace(f.name, path)
    except BaseException:
        for path, before, mode in reversed(done):
            path.write_bytes(before)
            os.chmod(path, mode)
        raise
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--target', choices=('all', *CLIS), default='all')
    parser.add_argument('--dry-run', action='store_true', help='preview only; write nothing')
    parser.add_argument('--uninstall', action='store_true', help='report the shared servers left in place')
    args = parser.parse_args()
    write = not args.dry_run
    home = args.home.expanduser()
    targets = CLIS if args.target == 'all' else (args.target,)
    try:
        servers = json.loads(SERVERS.read_text())['servers']
        if args.uninstall:
            for cli, name in leftovers(home, targets, servers):
                print(f'Left in place: {cli} MCP server {name}')
            print('mcp: 0 changes (servers stay; remove them by hand if unwanted)')
            return 0
        commands, files = plan(home, targets, servers)
        for command in commands:
            print(('Run: ' if write else 'Would run: ') + ' '.join(command))
            if write:
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        for path, _, _ in files:
            print(f'{"Update" if write else "Would update"}: {path}')
        if write and files:
            print(f'Backup: {write_files(home, files)}')
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError, subprocess.CalledProcessError) as e:
        print(f'mcp: {e}', file=sys.stderr)
        return 1
    print(f'mcp: {len(commands) + len(files)} changes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
