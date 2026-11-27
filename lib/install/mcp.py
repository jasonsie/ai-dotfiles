#!/usr/bin/env python3
"""Register shared MCP servers in each CLI; writes unless --dry-run.

Presence is read from each CLI's user-scope config. Claude Code, Codex and Pi get a
missing server through their own `mcp add`, so this never hand-edits their files.
Antigravity has no such command, so its ~/.gemini/config/mcp_config.json is merged:
only missing servers are added, everything else is kept, and the file is backed up
first. Existing entries with the same name are left alone (report only).
--uninstall only lists the shared servers left in place.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import installer

WORKSPACE = Path(__file__).resolve().parents[2]
SERVERS = WORKSPACE / 'config/mcp-servers.json'


def configured(home, cli):
    """Names of user-scope MCP servers already known to a CLI."""
    path = installer.path(home, cli, 'mcp')
    if not path.is_file():
        return set()
    text = path.read_text()
    if cli == 'codex':
        return set(tomllib.loads(text).get('mcp_servers', {}))
    return set((json.loads(text) if text.strip() else {}).get('mcpServers', {}))


def leftovers(home, clis, servers):
    """(cli, name) of shared servers present: uninstall leaves them; they do not depend on this repo."""
    names = {server['name'] for server in servers}
    return [(cli, name) for cli in clis for name in sorted(configured(home, cli) & names)]


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


def add_servers(old, servers):
    """Antigravity's mcp_config.json (bytes) with the given stdio servers added."""
    data = json.loads(old) if old.strip() else {}
    entries = data.setdefault('mcpServers', {})
    for server in servers:
        entries[server['name']] = {'command': server['command'], 'args': server.get('args', [])}
    return (json.dumps(data, indent=2) + '\n').encode()


def plan(home, clis, servers, which=shutil.which):
    """Native commands to run, and file edits for the CLI without one (Antigravity)."""
    commands, files = [], []
    for cli in clis:
        if not which(cli):
            print(f'mcp: skip {cli} (not on PATH)')
            continue
        present = configured(home, cli)
        missing = [s for s in servers if ('targets' not in s or cli in s['targets']) and s['name'] not in present]
        if not missing:
            continue
        if cli == 'agy':
            path = installer.path(home, 'agy', 'mcp')
            if not path.parent.is_dir():
                print('mcp: skip agy (not set up on this machine)')
                continue
            change = installer.edit(path, lambda old: add_servers(old, missing))
            files += [change] if change else []
        else:
            commands += [add_command(cli, server) for server in missing]
    return commands, files


def run(home, target, write, uninstall):
    """Add missing servers to the CLIs switched on. Servers are never removed: --uninstall
    lists them, and a CLI switched off keeps them."""
    servers = json.loads(SERVERS.read_text())['servers']
    selected = installer.scope(target)
    if uninstall:
        for cli, name in leftovers(home, selected, servers):
            print(f'Left in place: {cli} MCP server {name}')
        print('Servers stay; remove them by hand if unwanted.')
        return 0
    commands, files = plan(home, installer.split(selected)[0], servers)
    for command in commands:
        print(('Run: ' if write else 'Would run: ') + ' '.join(command))
        if write:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    installer.show(files, write)
    if write and files:
        print(f'Backup: {installer.apply(home, files, backup="mcp")}')
    return len(commands) + len(files)


SUMMARY = 'config/mcp-servers.json → native `<cli> mcp add` when missing'
UNDO = 'left in place, listed: servers do not depend on this repo'


def execute(options):
    """The step as lib/install/run.py runs it: the number of changes."""
    return run(options.home, options.target, options.apply, options.uninstall)


def main():
    args = installer.parser(__doc__).parse_args()
    return installer.finish('mcp', lambda: run(args.home, args.target, not args.dry_run, args.uninstall))


if __name__ == '__main__':
    sys.exit(main())
