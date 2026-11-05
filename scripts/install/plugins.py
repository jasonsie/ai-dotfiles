#!/usr/bin/env python3
"""Install the plugins config/plugins.json lists into each CLI; writes unless --dry-run.

Each listed plugin has a pin (an exact version) and the CLIs that should get it. For each
targeted CLI that config/ai-clis.json switches on, the step installs the pin's release tag
`<name>--v<version>` through the CLI's own plugin manager, and moves a CLI whose version
differs. Before any install or move, every tag it needs must exist on GitHub. A plugin the
CLI already had when first listed is taken over: moved to its pin, never removed.

A receipt records, per plugin and CLI, whether the step installed it or took it over.
Dropping a plugin, or a CLI from its targets, removes it there only where the step
installed it. A CLI switched off, and --uninstall, leave every plugin in place and list it.
Plugins the list does not name are never touched.

Every outside command goes through one runner, `shell`, which tests replace.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import installer

WORKSPACE = Path(__file__).resolve().parents[2]
PLUGINS = WORKSPACE / 'config/plugins.json'
RECEIPT = installer.STATE + '/plugins.json'
KEYS = ('source', 'version', 'targets')
NAME = re.compile(r'[a-z0-9][a-z0-9-]*')
SOURCE = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+')
SEMVER = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?')
INSTALLED, TAKEN_OVER = 'installed', 'taken over'


def shell(args):
    """Run one outside command: (exit code, stdout, stderr)."""
    done = subprocess.run(args, capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


def tag(name, entry):
    return f'{name}--v{entry["version"]}'


def plugins():
    """{name: entry} from config/plugins.json, checked strictly."""
    data = json.loads(PLUGINS.read_text())
    if data.get('version') != 1 or not isinstance(data.get('plugins'), dict):
        raise ValueError(f'{PLUGINS}: expected "version": 1 and a "plugins" object')
    listed = installer.clis()
    for name, entry in data['plugins'].items():
        where = f'{PLUGINS}: plugin {name!r}'
        if not NAME.fullmatch(name):
            raise ValueError(f'{where}: a name is lowercase letters, digits and hyphens')
        if not isinstance(entry, dict):
            raise ValueError(f'{where}: expected an object')
        problems = [f'is missing "{key}"' for key in KEYS if key not in entry]
        problems += [f'has unknown key "{key}"' for key in sorted(set(entry) - set(KEYS))]
        if problems:
            raise ValueError(f'{where} ' + ', '.join(problems))
        if not (isinstance(entry['source'], str) and SOURCE.fullmatch(entry['source'])):
            raise ValueError(f'{where}: "source" must be a GitHub owner/repo')
        if not (isinstance(entry['version'], str) and SEMVER.fullmatch(entry['version'])):
            raise ValueError(f'{where}: "version" must be an exact semver, like 2.2.0')
        targets = entry['targets']
        if not (isinstance(targets, list) and targets and all(isinstance(t, str) for t in targets)
                and len(set(targets)) == len(targets)):
            raise ValueError(f'{where}: "targets" must be a non-empty list of CLI ids, each once')
        for cli in targets:
            if cli not in listed:
                raise ValueError(f'{where}: target {cli!r} is not in config/ai-clis.json')
            if cli not in CLIS:
                raise ValueError(f'{where}: no plugins support for {cli} yet')
    return data['plugins']


class Pi:
    """Pi's packages: install and move with `pi install git:github.com/<repo>@<tag>`, which
    replaces the entry and moves the checkout; remove with `pi remove`; read the installed
    ones from the packages in Pi's settings, keyed by repo, the tag as their marker.

    Each CLI's class answers the same five questions: what it has installed ({key: (marker,
    handle)}), the key a plugin has there, the marker that means "at its pin", and the
    commands that install (or move) and remove one."""

    GIT = re.compile(r'git:github\.com/([^@]+?)(?:\.git)?(?:@(.+))?')

    def installed(self, home, runner):
        """{owner/repo (lowercase): (ref or None, the source as Pi has it)}."""
        path = installer.path(home, 'pi', 'settings')
        data = json.loads(path.read_text() or '{}') if path.is_file() else {}
        found = {}
        for package in data.get('packages', []):
            source = package if isinstance(package, str) else package.get('source', '')
            match = self.GIT.fullmatch(source)
            if match:
                found[match[1].lower()] = (match[2], source)
        return found

    def key(self, name, repo):
        return repo.lower()

    def pin(self, name, entry):
        return tag(name, entry)

    def install(self, name, entry):
        return ['pi', 'install', f'git:github.com/{entry["source"]}@{tag(name, entry)}']

    def remove(self, source):
        return ['pi', 'remove', source]


CLIS = {'pi': Pi()}  # the CLIs this step knows how to install into


def released(name, entry, runner):
    """True when the pin's release tag exists on GitHub."""
    code, out, _ = runner(['git', 'ls-remote', '--exit-code', '--tags',
                           f'https://github.com/{entry["source"]}', f'refs/tags/{tag(name, entry)}'])
    return code == 0 and bool(out.strip())


def plan(home, selected, listed, owned, sources, which, runner):
    """(actions, notes): each action is (command, name, cli, record), where record is the
    receipt's new value for that plugin and CLI (None drops it); notes are printed as is."""
    actions, notes = [], []
    on, off = installer.split(selected)
    for cli in off:
        notes += [f'Left in place: {cli} plugin {name} ({cli} is switched off)'
                  for name in sorted(owned) if cli in owned[name]]
    for cli in on:
        if cli not in CLIS:
            continue
        if not any(cli in e['targets'] for e in listed.values()) and not any(cli in o for o in owned.values()):
            continue
        if not which(cli):
            notes.append(f'plugins: skip {cli} (not on PATH)')
            continue
        manager = CLIS[cli]
        present = manager.installed(home, runner)
        for name, entry in listed.items():
            if cli not in entry['targets']:
                continue
            marker, _ = present.get(manager.key(name, entry['source']), (None, None))
            record = owned.get(name, {}).get(cli) or (INSTALLED if marker is None else TAKEN_OVER)
            if marker != manager.pin(name, entry):
                actions.append((manager.install(name, entry), name, cli, record))
            elif owned.get(name, {}).get(cli) != record:
                actions.append((None, name, cli, record))
        for name in sorted(owned):
            entry = listed.get(name)
            if cli not in owned[name] or (entry and cli in entry['targets']):
                continue
            if owned[name][cli] == TAKEN_OVER:
                notes.append(f'Left in place: {cli} plugin {name} (taken over)')
                actions.append((None, name, cli, None))
                continue
            repo = (entry or {}).get('source') or sources.get(name, '')
            _, handle = present.get(manager.key(name, repo), (None, None))
            actions.append((manager.remove(handle) if handle else None, name, cli, None))
    return actions, notes


def recorded(owned, done):
    """The receipt's plugins after the given actions."""
    result = {name: dict(clis) for name, clis in owned.items()}
    for _, name, cli, record in done:
        if record is None:
            result.get(name, {}).pop(cli, None)
        else:
            result.setdefault(name, {})[cli] = record
    return {name: clis for name, clis in result.items() if clis}


def run(home, target, write, uninstall, runner=shell, which=shutil.which):
    """Install, move and remove listed plugins in the CLIs switched on; print what stays."""
    listed = plugins()
    selected = installer.scope(target)
    receipt = home / RECEIPT
    old = json.loads(receipt.read_text()) if receipt.is_file() else {'version': 1, 'plugins': {}, 'sources': {}}
    owned, sources = old['plugins'], old.get('sources', {})
    if uninstall:
        for name in sorted(owned):
            for cli in sorted(set(owned[name]) & set(selected)):
                print(f'Left in place: {cli} plugin {name} ({owned[name][cli]})')
        print('Plugins stay; remove them with each CLI\'s own uninstall if unwanted.')
        return 0
    actions, notes = plan(home, selected, listed, owned, sources, which, runner)
    for note in notes:
        print(note)
    pins = {name for command, name, _, record in actions if command and record}
    missing = [tag(name, listed[name]) for name in sorted(pins) if not released(name, listed[name], runner)]
    if missing:
        raise ValueError(f'no release tag on GitHub for {", ".join(missing)}; make it in the plugin '
                         f'repo with `claude plugin tag --push`, then run again')
    commands = [command for command, *_ in actions if command]

    def content(done):
        after = recorded(owned, done)
        return {'version': 1, 'plugins': after,
                'sources': {name: listed[name]['source'] if name in listed else sources[name] for name in after}}

    files = [] if content(actions) == old else [(receipt, installer.state(receipt), installer.receipt(content(actions)))]
    if not write:
        for command in commands:
            print('Would run: ' + ' '.join(command))
        installer.show(files, False)
        return len(commands) + len(files)
    done = []
    try:
        for action in actions:
            command = action[0]
            if command:
                print('Run: ' + ' '.join(command))
                code, _, err = runner(command)
                if code != 0:
                    raise ValueError(f'{" ".join(command)} failed: {err.strip()}')
            done.append(action)
    finally:
        if content(done) != old:
            change = (receipt, installer.state(receipt), installer.receipt(content(done)))
            installer.show([change], True)
            installer.apply(home, [change])
    return len(commands) + len(files)


def main():
    args = installer.parser(__doc__).parse_args()
    return installer.finish('plugins', lambda: run(args.home, args.target, not args.dry_run, args.uninstall))


if __name__ == '__main__':
    sys.exit(main())
