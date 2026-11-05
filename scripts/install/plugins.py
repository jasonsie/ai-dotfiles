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

Every outside command goes through one runner, `shell`, which tests replace. Each CLI's
class answers the same five questions: what it has installed ({key: (marker, handle)}),
the key a plugin has there, the marker that means "at its pin", the command (or step) that
installs or moves one, and the command that removes one.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

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


class Command:
    """One outside command as a step. A CLI's install may instead return a step of its own
    that takes several commands or a file edit; every step offers the same two methods: the
    lines a dry run prints (one per change), and doing it."""

    def __init__(self, args):
        self.args = args

    def preview(self):
        return ['Would run: ' + ' '.join(self.args)]

    def run(self, runner):
        print('Run: ' + ' '.join(self.args))
        code, _, err = runner(self.args)
        if code != 0:
            raise ValueError(f'{" ".join(self.args)} failed: {err.strip()}')


def step(command):
    """The step for an action's command: a CLI's own step as is, a plain command wrapped."""
    return command if hasattr(command, 'run') else Command(command)


class Pi:
    """Pi's packages: install and move with `pi install git:github.com/<repo>@<tag>`, which
    replaces the entry and moves the checkout; remove with `pi remove`; read the installed
    ones from the packages in Pi's settings, keyed by repo, the tag as their marker."""

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

    def install(self, home, name, entry, current):
        return ['pi', 'install', f'git:github.com/{entry["source"]}@{tag(name, entry)}']

    def remove(self, source):
        return ['pi', 'remove', source]


class Antigravity:
    """Antigravity's plugins: install and move with `agy plugin install <repo URL>/tree/<tag>`
    (a `#<tag>` suffix is ignored and installs the latest), which replaces the installed copy
    and keeps a plugin the user disabled disabled; remove with `agy plugin uninstall <name>`;
    read the installed ones with `agy plugin list --json`, keyed by name, the version as their
    marker. A plugin's name there is its manifest name, which the list uses as its key."""

    def installed(self, home, runner):
        """{name: (version or None, name)}."""
        code, out, err = runner(['agy', 'plugin', 'list', '--json'])
        if code != 0:
            raise ValueError(f'agy plugin list --json failed: {(err or out).strip()}')
        listing = json.loads(out or '[]')
        return {p['name']: (p.get('version'), p['name']) for p in listing
                if isinstance(p, dict) and isinstance(p.get('name'), str)}

    def key(self, name, repo):
        return name

    def pin(self, name, entry):
        return entry['version']

    def install(self, home, name, entry, current):
        return ['agy', 'plugin', 'install', f'https://github.com/{entry["source"]}/tree/{tag(name, entry)}']

    def remove(self, name):
        return ['agy', 'plugin', 'uninstall', name]


def with_ref(text, marketplace, ref):
    """Codex's config with `ref` set in one marketplace's table, every other line kept; checked
    to parse to the same config but that key."""
    lines = text.splitlines(keepends=True)
    name = re.escape(marketplace)
    header = re.compile(rf'\s*\[\s*marketplaces\s*\.\s*(?:"{name}"|{name})\s*\]\s*(?:#.*)?')
    start = next((i for i, line in enumerate(lines) if header.fullmatch(line.rstrip('\r\n'))), None)
    if start is None:
        raise ValueError(f'Codex config has no [marketplaces.{marketplace}] table to pin')
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith('[')), len(lines))
    line = f'ref = {json.dumps(ref)}\n'
    at = next((i for i in range(start + 1, end) if re.match(r'\s*ref\s*=', lines[i])), None)
    if at is None:
        at = max(i for i in range(start, end) if lines[i].strip()) + 1
        if not lines[at - 1].endswith('\n'):
            lines[at - 1] += '\n'
        lines.insert(at, line)
    else:
        lines[at] = line
    result = ''.join(lines)
    before, after = tomllib.loads(text), tomllib.loads(result)
    pinned = after['marketplaces'][marketplace].pop('ref', None)
    before['marketplaces'][marketplace].pop('ref', None)
    if pinned != ref or after != before:
        raise ValueError(f'Codex config did not round-trip pinning {marketplace}')
    return result


class Codex:
    """Codex's plugins, each from its GitHub marketplace pinned to the release tag. Install with
    `codex plugin marketplace add <repo> --ref <tag> --json`, then `codex plugin add
    <name>@<marketplace>`, the marketplace named by the first command's output. Move by setting
    the marketplace's `ref` in Codex's config, backed up, then `codex plugin marketplace
    upgrade`, which refreshes the installed plugin: Codex refuses a second `marketplace add`
    with a new ref, and another `plugin add` would re-enable a plugin the user disabled. Remove
    with `codex plugin remove <name>@<marketplace>`. Read `codex plugin list --json` and the
    marketplaces in Codex's config, keyed by name and repo, (version, ref) as the marker."""

    GITHUB = re.compile(r'https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?')

    def marketplaces(self, home):
        """{owner/repo (lowercase): (marketplace, ref or None)} of Codex's GitHub marketplaces."""
        path = installer.path(home, 'codex', 'settings')
        data = tomllib.loads(path.read_text()) if path.is_file() else {}
        found = {}
        for marketplace, conf in (data.get('marketplaces') or {}).items():
            match = self.GITHUB.fullmatch(str(conf.get('source', ''))) if isinstance(conf, dict) else None
            if match:
                found[match[1].lower()] = (marketplace, conf.get('ref'))
        return found

    def installed(self, home, runner):
        """{(name, owner/repo): ((version, ref), (name, marketplace))}, plugins from those marketplaces."""
        code, out, err = runner(['codex', 'plugin', 'list', '--json'])
        if code != 0:
            raise ValueError(f'codex plugin list --json failed: {(err or out).strip()}')
        sources = {mp: (repo, ref) for repo, (mp, ref) in self.marketplaces(home).items()}
        found = {}
        for plugin in json.loads(out or '{}').get('installed', []):
            repo, ref = sources.get(plugin.get('marketplaceName'), (None, None))
            if repo and isinstance(plugin.get('name'), str):
                found[(plugin['name'], repo)] = ((plugin.get('version'), ref), (plugin['name'], plugin['marketplaceName']))
        return found

    def key(self, name, repo):
        return (name, repo.lower())

    def pin(self, name, entry):
        return (entry['version'], tag(name, entry))

    def install(self, home, name, entry, current):
        return CodexInstall(self, home, name, entry, installed=current is not None)

    def remove(self, handle):
        name, marketplace = handle
        return ['codex', 'plugin', 'remove', f'{name}@{marketplace}']


class CodexInstall:
    """The step that installs or moves one plugin in Codex, as Codex's class says: the
    marketplace's name comes from Codex, and a move edits Codex's config."""

    def __init__(self, codex, home, name, entry, installed):
        self.codex, self.home, self.name, self.entry, self.installed = codex, home, name, entry, installed
        self.config = installer.path(home, 'codex', 'settings')

    def todo(self):
        """(marketplace or None until Codex names it, the operations in order)."""
        want = tag(self.name, self.entry)
        marketplace, ref = self.codex.marketplaces(self.home).get(self.entry['source'].lower(), (None, None))
        if marketplace is None:
            return None, ['add', 'plugin']
        ops = (['ref'] if ref != want else []) + (['upgrade'] if self.installed or ref != want else [])
        return marketplace, ops + ([] if self.installed else ['plugin'])

    def command(self, op, marketplace):
        if op == 'add':
            return ['codex', 'plugin', 'marketplace', 'add', self.entry['source'], '--ref', tag(self.name, self.entry), '--json']
        if op == 'upgrade':
            return ['codex', 'plugin', 'marketplace', 'upgrade', marketplace]
        return ['codex', 'plugin', 'add', f'{self.name}@{marketplace}', '--json']

    def preview(self):
        marketplace, ops = self.todo()
        return [f'Would update: {self.config}' if op == 'ref' else
                'Would run: ' + ' '.join(self.command(op, marketplace or '<its marketplace>')) for op in ops]

    def run(self, runner):
        marketplace, ops = self.todo()
        for op in ops:
            if op == 'ref':
                self.pin_ref(marketplace)
                continue
            args = self.command(op, marketplace)
            print('Run: ' + ' '.join(args))
            code, out, err = runner(args)
            if code != 0:
                raise ValueError(f'{" ".join(args)} failed: {(err or out).strip()}')
            if op == 'add':
                marketplace = json.loads(out)['marketplaceName']
        hooks = self.config.parent / 'plugins/cache' / marketplace / self.name / self.entry['version'] / 'hooks/hooks.json'
        if hooks.is_file():
            print(f"Codex: approve {self.name}'s hooks once with /hooks; Codex runs no unreviewed hook.")

    def pin_ref(self, marketplace):
        want = tag(self.name, self.entry)
        change = installer.edit(self.config, lambda old: with_ref(old.decode(), marketplace, want).encode())
        if change:
            installer.show([change], True)
            print(f'Backup: {installer.apply(self.home, [change], backup="settings")}')


CLIS = {'pi': Pi(), 'agy': Antigravity(), 'codex': Codex()}  # the CLIs this step knows how to install into


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
                actions.append((manager.install(home, name, entry, marker), name, cli, record))
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
    steps = [step(command) for command, *_ in actions if command]
    changes = sum(len(s.preview()) for s in steps)

    def content(done):
        after = recorded(owned, done)
        return {'version': 1, 'plugins': after,
                'sources': {name: listed[name]['source'] if name in listed else sources[name] for name in after}}

    files = [] if content(actions) == old else [(receipt, installer.state(receipt), installer.receipt(content(actions)))]
    if not write:
        for line in (line for s in steps for line in s.preview()):
            print(line)
        installer.show(files, False)
        return changes + len(files)
    done = []
    try:
        for action in actions:
            if action[0]:
                step(action[0]).run(runner)
            done.append(action)
    finally:
        if content(done) != old:
            change = (receipt, installer.state(receipt), installer.receipt(content(done)))
            installer.show([change], True)
            installer.apply(home, [change])
    return changes + len(files)


def main():
    args = installer.parser(__doc__).parse_args()
    return installer.finish('plugins', lambda: run(args.home, args.target, not args.dry_run, args.uninstall))


if __name__ == '__main__':
    sys.exit(main())
