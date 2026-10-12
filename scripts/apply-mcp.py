#!/usr/bin/env python3
"""Register shared MCP servers through each CLI's own `mcp add`; dry-run unless --apply.

Presence is read from each CLI's user-scope config; missing servers are added with
the native command, so this never hand-edits another tool's settings. Existing
entries with the same name are left alone (report only). Pi has no MCP support.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

WORKSPACE = Path(__file__).resolve().parents[1]
SERVERS = WORKSPACE / 'tools/mcp/servers.json'
CLIS = ('claude', 'codex', 'gemini')


def configured(home, cli):
    """Names of user-scope MCP servers already known to a CLI."""
    try:
        if cli == 'claude':
            return set(json.loads((home / '.claude.json').read_text()).get('mcpServers', {}))
        if cli == 'codex':
            return set(tomllib.loads((home / '.codex/config.toml').read_text()).get('mcp_servers', {}))
        if cli == 'gemini':
            return set(json.loads((home / '.gemini/settings.json').read_text()).get('mcpServers', {}))
    except FileNotFoundError:
        return set()
    raise ValueError(cli)


def add_command(cli, server):
    name, command, args = server['name'], server['command'], server.get('args', [])
    if cli == 'claude':
        return ['claude', 'mcp', 'add', '-s', 'user', name, '--', command, *args]
    if cli == 'codex':
        return ['codex', 'mcp', 'add', name, '--', command, *args]
    if cli == 'gemini':
        return ['gemini', 'mcp', 'add', '-s', 'user', name, command, *args]
    raise ValueError(cli)


def plan(home, targets, servers, which=shutil.which):
    commands = []
    for cli in targets:
        if not which(cli):
            print(f'mcp: skip {cli} (not on PATH)')
            continue
        present = configured(home, cli)
        for server in servers:
            if cli in server.get('targets', CLIS) and server['name'] not in present:
                commands.append(add_command(cli, server))
    return commands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--target', choices=('all', *CLIS, 'pi'), default='all')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.target == 'pi':
        print('mcp: Pi has no MCP support; nothing to do')
        return 0
    targets = CLIS if args.target == 'all' else (args.target,)
    try:
        servers = json.loads(SERVERS.read_text())['servers']
        commands = plan(args.home.expanduser(), targets, servers)
        for command in commands:
            print(('Run: ' if args.apply else 'Would run: ') + ' '.join(command))
            if args.apply:
                subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError, subprocess.CalledProcessError) as e:
        print(f'mcp: {e}', file=sys.stderr)
        return 1
    print(f'mcp: {len(commands)} changes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
