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

import installer
import settings

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / 'lib'))
import adapters  # noqa: E402  (what differs between the CLIs)
SERVERS = WORKSPACE / 'config/mcp-servers.json'


def names_in(cli, text):
    """Names of the MCP servers a CLI's config file (its text) holds."""
    return set(settings.parse(cli, text).get(adapters.get(cli).mcp_key, {}))


def configured(home, cli):
    """Names of user-scope MCP servers already known to a CLI."""
    path = installer.path(home, cli, 'mcp')
    return names_in(cli, path.read_text()) if path.is_file() else set()


def leftovers(home, clis, servers):
    """(cli, name) of shared servers present: uninstall leaves them; they do not depend on this repo."""
    names = {server['name'] for server in servers}
    return [(cli, name) for cli in clis for name in sorted(configured(home, cli) & names)]


def add_command(cli, server):
    command = adapters.get(cli).mcp_add(server)
    if command is None:
        raise ValueError(cli)
    return command


def add_servers(cli, old, servers):
    """The mcp_config.json (bytes) of a CLI with no `mcp add`, with the given stdio servers added."""
    data = settings.parse_json(old.decode())
    entries = data.setdefault(adapters.get(cli).mcp_key, {})
    for server in servers:
        entries[server['name']] = {'command': server['command'], 'args': server.get('args', [])}
    return (json.dumps(data, indent=2) + '\n').encode()


def goes_to(server, cli_id):
    """Whether config/mcp-servers.json sends the server to the CLI: its `targets`, or every CLI when it has none."""
    return cli_id in server.get('targets', [cli_id])


def plan(home, clis, servers, which=shutil.which):
    """Native commands to run, and file edits for a CLI without one."""
    commands, files = [], []
    for cli in clis:
        if not which(cli):
            print(f'mcp: skip {cli} (not on PATH)')
            continue
        present = configured(home, cli)
        missing = [s for s in servers if goes_to(s, cli) and s['name'] not in present]
        if not missing:
            continue
        native = [adapters.get(cli).mcp_add(server) for server in missing]
        if None in native:
            path = installer.path(home, cli, 'mcp')
            if not path.parent.is_dir():
                print(f'mcp: skip {cli} (not set up on this machine)')
                continue
            change = installer.edit(path, lambda old, cli=cli, missing=missing: add_servers(cli, old, missing))
            files += [change] if change else []
        else:
            commands += native
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


CHECKS_TITLE = 'mcp (each CLI switched on in config/ai-clis.json; Antigravity has no list, so its file is read)'


def listed(cli, name):
    """The first line of `<cli> mcp list` that names the server, or ''."""
    try:
        done = subprocess.run([cli, 'mcp', 'list'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except OSError:
        return ''
    return next((line for line in done.stdout.splitlines() if name in line), '')


def in_file(cli, file, name):
    """Whether the config file of a CLI with no `mcp list` holds the server."""
    try:
        return name in names_in(cli, file.read_text())
    except (OSError, ValueError, AttributeError):
        return False


def checks(options):
    """Each shared server, in each CLI switched on, as the healthcheck's lines. Servers and CLIs come from
    the live checkout's config."""
    servers = [server['name'] for server in json.loads((options.live / 'config/mcp-servers.json').read_text())['servers']]
    results = []
    for cli, entry in json.loads((options.live / 'config/ai-clis.json').read_text())['clis'].items():
        if not entry['on']:
            continue
        file = options.home / entry['mcp'][2:]
        for name in servers:
            if not adapters.get(cli).mcp_lists:  # its file is read
                if not file.is_file():
                    results.append(('skip', f'{cli} not set up'))
                elif in_file(cli, file, name):
                    results.append(('ok', f'{cli}: {name} (in {file.name})'))
                else:
                    results.append(('FAIL', f'{cli}: {name} not in {file}'))
            elif not shutil.which(cli):
                results.append(('skip', f'{cli} not on PATH'))
            else:
                line = listed(cli, name)
                if not line:
                    results.append(('FAIL', f'{cli}: {name} not listed'))
                elif 'Disabled' in line:
                    # A server disabled for the current folder is still configured; count it as present.
                    results.append(('ok', f'{cli}: {name} (configured; disabled in this untrusted folder)'))
                else:
                    results.append(('ok', f'{cli}: {name}'))
    return results


def main():
    args = installer.parser(__doc__).parse_args()
    return installer.finish('mcp', lambda: run(args.home, args.target, not args.dry_run, args.uninstall))


if __name__ == '__main__':
    sys.exit(main())
