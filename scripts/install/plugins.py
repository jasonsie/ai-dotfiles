#!/usr/bin/env python3
"""Install the plugins config/plugins.json lists into each CLI; writes unless --dry-run.

Each listed plugin has a pin (an exact version) and the CLIs that should get it. For each
targeted CLI that config/ai-clis.json switches on, the step installs the pin's release tag
`<name>--v<version>` through the CLI's own plugin manager, and moves a CLI whose version
differs. Before any install or move, every tag it needs must exist on GitHub, and each
listed plugin's manifest at its tag must agree with the list: named as its key, and every
dependency it declares listed for the same CLIs and pinned inside its range. A plugin the
CLI already had when first listed is taken over: moved to its pin, never removed.

A receipt records, per plugin and CLI, whether the step installed it or took it over.
Dropping a plugin, or a CLI from its targets, removes it there only where the step
installed it. A CLI switched off, and --uninstall, leave every plugin in place and list it.
Plugins the list does not name are never touched.

A plugin's commands, the executables in its bin/ at the tag, are linked into ~/.local/bin from
one checkout at the tag under ~/.local/share/ai-dotfiles/plugins/<name>, like an npm global
install, for every CLI and the shell; a name the step did not create is refused. A dropped
plugin loses its links and checkout on a full run; --uninstall leaves them and lists them.

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
import tempfile
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
SHARE = '.local/share/ai-dotfiles/plugins'  # one checkout per plugin whose bin/ holds commands
BIN = '.local/bin'  # where those commands are linked, beside ai-dotfiles and daily-log


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


class Commands:
    """Several outside commands as one step, run in order."""

    def __init__(self, *commands):
        self.commands = [Command(args) for args in commands if args]

    def preview(self):
        return [line for command in self.commands for line in command.preview()]

    def run(self, runner):
        for command in self.commands:
            command.run(runner)


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


def with_declaration(text, marketplace, repo, ref):
    """Claude's settings with one marketplace declared in `extraKnownMarketplaces`: its GitHub
    source at `ref`, auto-update off; every other key and the entry's other fields kept."""
    data = json.loads(text) if text.strip() else {}
    declared = data.setdefault('extraKnownMarketplaces', {}) if isinstance(data, dict) else None
    if not isinstance(declared, dict):
        raise ValueError('Claude settings: "extraKnownMarketplaces" is not an object')
    old = declared.get(marketplace) if isinstance(declared.get(marketplace), dict) else {}
    declared[marketplace] = {**old, 'source': {'source': 'github', 'repo': repo, 'ref': ref}, 'autoUpdate': False}
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


class Claude:
    """Claude Code's plugins, each from its GitHub marketplace pinned to the release tag with
    auto-update off, declared in `extraKnownMarketplaces` in Claude's settings. Install with
    `claude plugin marketplace add '<repo>#<tag>' --json`, which names the marketplace and
    declares it, turn auto-update off in that declaration, then `claude plugin install`. Move,
    or take over a plugin from an unpinned marketplace (declared, or known from a git URL), by
    writing the declaration, running the same `marketplace add`, then `claude plugin update`:
    Claude refuses an add its declaration does not match, and removing a marketplace deletes its
    plugins' data. Remove with `claude plugin uninstall`, then `claude plugin marketplace remove
    --scope user` when no other plugin comes from that marketplace. Read `claude plugin
    marketplace list --json`, the declarations and `claude plugin list --json` (user scope; a
    version Claude resolved as a dependency carries a 12-character commit suffix), keyed by name
    and repo, (version, ref, auto-update off) as the marker. installed() runs first in each plan
    and keeps the marketplaces it found for install()."""

    GITHUB = re.compile(r'https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?')
    SUFFIX = re.compile(r'-[0-9a-f]{12}$')

    def __init__(self):
        self.catalog = {}

    def call(self, runner, args):
        code, out, err = runner(args)
        if code != 0:
            raise ValueError(f'{" ".join(args)} failed: {(err or out).strip()}')
        return json.loads(out or '[]')

    def installed(self, home, runner):
        """{(name, owner/repo): ((version, ref, auto-update off), (name, marketplace, alone))}."""
        path = installer.path(home, 'claude', 'settings')
        declared = (json.loads(path.read_text() or '{}') if path.is_file() else {}).get('extraKnownMarketplaces') or {}
        self.catalog = {}
        for m in self.call(runner, ['claude', 'plugin', 'marketplace', 'list', '--json']):
            match = self.GITHUB.fullmatch(m.get('url') or '') if m.get('source') == 'git' else None
            repo = m.get('repo') if m.get('source') == 'github' else (match[1] if match else None)
            if repo:
                off = (declared.get(m['name']) or {}).get('autoUpdate') is False
                self.catalog[repo.lower()] = (m['name'], m.get('ref'), off)
        repos = {mp: (repo, ref, off) for repo, (mp, ref, off) in self.catalog.items()}
        listing = [p for p in self.call(runner, ['claude', 'plugin', 'list', '--json'])
                   if isinstance(p, dict) and '@' in str(p.get('id', ''))]
        found = {}
        for plugin in listing:
            name, marketplace = plugin['id'].rsplit('@', 1)
            if plugin.get('scope') != 'user' or marketplace not in repos:
                continue
            repo, ref, off = repos[marketplace]
            alone = all(p is plugin or not p['id'].endswith('@' + marketplace) for p in listing)
            version = self.SUFFIX.sub('', str(plugin.get('version', '')))
            found[(name, repo)] = ((version, ref, off), (name, marketplace, alone))
        return found

    def key(self, name, repo):
        return (name, repo.lower())

    def pin(self, name, entry):
        return (entry['version'], tag(name, entry), True)

    def install(self, home, name, entry, current):
        return ClaudeInstall(home, name, entry, current, self.catalog.get(entry['source'].lower()))

    def remove(self, handle):
        name, marketplace, alone = handle
        return Commands(['claude', 'plugin', 'uninstall', f'{name}@{marketplace}', '--json'],
                        ['claude', 'plugin', 'marketplace', 'remove', marketplace, '--scope', 'user', '--json']
                        if alone else None)


class ClaudeInstall:
    """The step that installs or moves one plugin in Claude Code, as Claude's class says. An
    `add` that re-registers a marketplace rewrites its declaration without `autoUpdate`, so the
    declaration is written again after it; `install` and `update` keep it."""

    def __init__(self, home, name, entry, current, known):
        self.home, self.name, self.entry, self.current, self.known = home, name, entry, current, known
        self.settings = installer.path(home, 'claude', 'settings')

    def todo(self):
        """(marketplace or None until Claude names it, the operations in order)."""
        if self.known is None:
            return None, ['add', 'declare', 'install']
        marketplace, ref, off = self.known
        moved = ref != tag(self.name, self.entry)
        ops = ['declare', 'add', 'declare'] if moved else ([] if off else ['declare'])
        if self.current is None:
            ops.append('install')
        elif moved or self.current[0] != self.entry['version']:
            ops.append('update')
        return marketplace, ops

    def command(self, op, marketplace):
        if op == 'add':
            return ['claude', 'plugin', 'marketplace', 'add', f'{self.entry["source"]}#{tag(self.name, self.entry)}', '--json']
        return ['claude', 'plugin', op, f'{self.name}@{marketplace}', '--json']

    def preview(self):
        marketplace, ops = self.todo()
        return [f'Would update: {self.settings}' if op == 'declare' else
                'Would run: ' + ' '.join(self.command(op, marketplace or '<its marketplace>')) for op in ops]

    def run(self, runner):
        marketplace, ops = self.todo()
        for op in ops:
            if op == 'declare':
                want = tag(self.name, self.entry)
                change = installer.edit(self.settings, lambda old: with_declaration(
                    old.decode(), marketplace, self.entry['source'], want).encode())
                if change:
                    installer.show([change], True)
                    print(f'Backup: {installer.apply(self.home, [change], backup="settings")}')
                continue
            args = self.command(op, marketplace)
            print('Run: ' + ' '.join(args))
            code, out, err = runner(args)
            if code != 0:
                raise ValueError(f'{" ".join(args)} failed: {(err or out).strip()}')
            result = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
            if op == 'add':
                marketplace = result['marketplace']
            if op == 'update' and Claude.SUFFIX.sub('', str(result.get('newVersion', ''))) != self.entry['version']:
                print(f'Claude: {result.get("message", "the update stopped short of the pin")}')


CLIS = {'pi': Pi(), 'agy': Antigravity(), 'codex': Codex(), 'claude': Claude()}  # the CLIs this step serves


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


RANGE = re.compile(r'(\^|~|>=|<=|>|<|=)?v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(-[0-9A-Za-z.-]+)?')


def satisfies(version, spec):
    """Whether an exact version meets a dependency's range, read as Claude and npm read it: ^, ~,
    an exact or partial version, or one comparator (>=, >, <=, <). None for any other form."""
    match = RANGE.fullmatch(spec.strip())
    if not match:
        return None
    op, parts = match[1] or '=', [int(part) for part in match.groups()[1:4] if part is not None]
    pinned = SEMVER.fullmatch(version)
    if pinned[4] and not match[5]:
        return False  # a range matches a pre-release only when it names one
    core, low, last = tuple(int(pinned[i]) for i in (1, 2, 3)), tuple(parts + [0] * (3 - len(parts))), len(parts) - 1

    def above(i):
        return low[:i] + (low[i] + 1,) + (0,) * (2 - i)

    if op == '^':
        return low <= core < above(next((i for i, part in enumerate(parts) if part), last))
    if op == '~':
        return low <= core < above(1 if len(parts) > 1 else 0)
    full = len(parts) == 3
    return {'=': core == low if full else low <= core < above(last),
            '>=': core >= low, '<': core < low,
            '>': core > low if full else core >= above(last),
            '<=': core <= low if full else core < above(last)}[op]


def inspect(name, entry, runner):
    """(manifest, the command files in bin/) of the plugin at its release tag, from one shallow
    clone without files: the Claude manifest, and bin/'s executables and links."""
    with tempfile.TemporaryDirectory(prefix='ai-dotfiles-plugin-') as folder:
        clone = ['git', 'clone', '--quiet', '--depth', '1', '--branch', tag(name, entry), '--no-checkout',
                 '--filter=blob:none', f'https://github.com/{entry["source"]}', folder]
        outs = []
        for args in (clone, ['git', '-C', folder, 'show', 'HEAD:.claude-plugin/plugin.json'],
                     ['git', '-C', folder, 'ls-tree', 'HEAD', 'bin/']):
            code, out, err = runner(args)
            if code != 0:
                raise ValueError(f'cannot read {entry["source"]} at {tag(name, entry)}: {(err or out).strip()}')
            outs.append(out)
    data = json.loads(outs[1])
    files = sorted(Path(line.split('\t', 1)[1]).name for line in outs[2].splitlines()
                   if '\t' in line and line.split()[0] in ('100755', '120000'))
    return (data if isinstance(data, dict) else {}), files


def dependency_problems(listed, look):
    """Each listed plugin's manifest at its tag against the list: named as its key, and each
    dependency it declares listed, aimed at every CLI it is, and pinned inside its range."""
    problems = []
    for name, entry in sorted(listed.items()):
        data = look(name)[0]
        if data.get('name') != name:
            problems.append(f'{name}: {entry["source"]} at {tag(name, entry)} is named {data.get("name")!r}; '
                            f'list it under that name')
        for dependency in data.get('dependencies') or []:
            wanted, spec = (dependency, None) if isinstance(dependency, str) else (dependency.get('name'), dependency.get('version'))
            wanted = str(wanted).split('@')[0]
            needs = f'{name} {entry["version"]} needs {wanted}' + (f' {spec}' if spec else '')
            if wanted not in listed:
                problems.append(f'{needs}, which is not listed')
                continue
            fewer = sorted(set(entry['targets']) - set(listed[wanted]['targets']))
            if fewer:
                problems.append(f'{needs}, pinned at {listed[wanted]["version"]}, in {", ".join(fewer)} too; '
                                f'add them to its targets')
            fits = satisfies(listed[wanted]['version'], spec) if spec else True
            if fits is None:
                problems.append(f'{needs}: a range this step cannot read (^, ~, =, >=, >, <=, < or a version)')
            elif not fits:
                problems.append(f'{needs}, pinned at {listed[wanted]["version"]}')
    return problems


def current_tag(folder, runner):
    """The release tag a checkout stands at, read locally; None without one."""
    if not folder.is_dir():
        return None
    code, out, _ = runner(['git', '-C', str(folder), 'describe', '--tags', '--exact-match', 'HEAD'])
    return out.strip() if code == 0 else None


class Checkout:
    """The step that puts a plugin's checkout at its release tag: a shallow clone the first time,
    then a fetch of the tag and a checkout of it."""

    def __init__(self, folder, name, entry):
        self.folder, self.name, self.entry = folder, name, entry

    def commands(self):
        want = tag(self.name, self.entry)
        if not self.folder.is_dir():
            return [['git', 'clone', '--quiet', '--depth', '1', '--branch', want,
                     f'https://github.com/{self.entry["source"]}', str(self.folder)]]
        return [['git', '-C', str(self.folder), 'fetch', '--quiet', '--depth', '1', 'origin', 'tag', want],
                ['git', '-C', str(self.folder), 'checkout', '--quiet', want]]

    def preview(self):
        return ['Would run: ' + ' '.join(args) for args in self.commands()]

    def run(self, runner):
        for args in self.commands():
            Command(args).run(runner)


class Links:
    """The step that sets links in ~/.local/bin, through the installer's safe writes, and takes
    away a checkout no longer needed."""

    def __init__(self, home, changes, gone=None):
        self.home, self.changes, self.gone = home, changes, gone

    def preview(self):
        lines = [f'Would link: {path} -> {after[1]}' if after[0] == 'link' else f'Would remove: {path}'
                 for path, _, after in self.changes]
        return lines + ([f'Would remove folder: {self.gone}'] if self.gone else [])

    def run(self, runner):
        installer.show(self.changes, True)
        installer.apply(self.home, self.changes)
        if self.gone:
            print(f'Remove folder: {self.gone}')
            shutil.rmtree(self.gone)


def commands_plan(home, selected, listed, records, look, runner, which, full):
    """Actions (step or None, name, 'bin', record) that keep each listed plugin's commands, the
    executables in bin/ at its tag, linked from ~/.local/bin into its checkout, for plugins one
    of whose CLIs this run serves; a dropped plugin loses links and checkout on a full run.
    records: {name: {'tag': tag, 'files': [...]}}, so an unchanged pin needs no remote look."""
    entries = installer.clis()
    served = {cli for cli in selected if entries[cli]['on'] and which(cli)}
    actions = []
    for name, entry in sorted(listed.items()):
        if not served & set(entry['targets']):
            continue
        want, record = tag(name, entry), records.get(name) or {}
        files = record['files'] if record.get('tag') == want else look(name)[1]
        folder = home / SHARE / name
        mine = {home / BIN / f for f in record.get('files', [])}
        wanted = {home / BIN / f: str(folder / 'bin' / f) for f in files}
        for path, target in wanted.items():
            if installer.state(path) not in (('absent',), ('link', target)) and path not in mine:
                raise ValueError(f'Not created by the plugins step; refusing to replace: {path}')
        steps = [Checkout(folder, name, entry)] if files and current_tag(folder, runner) != want else []
        links = [(path, installer.state(path), ('link', target)) for path, target in wanted.items()
                 if installer.state(path) != ('link', target)]
        links += [(path, installer.state(path), ('absent',)) for path in sorted(mine - set(wanted))
                  if installer.state(path) == ('link', str(folder / 'bin' / path.name))]
        gone = folder if not files and folder.is_dir() and record.get('files') else None
        steps += [Links(home, links, gone)] if links or gone else []
        new = {'tag': want, 'files': files}
        actions += [(s, name, 'bin', new) for s in steps] or ([(None, name, 'bin', new)] if record != new else [])
    for name in sorted(set(records) - set(listed)) if full else ():
        folder = home / SHARE / name
        links = [(path, installer.state(path), ('absent',)) for path in (home / BIN / f for f in records[name]['files'])
                 if installer.state(path) == ('link', str(folder / 'bin' / path.name))]
        gone = folder if folder.is_dir() else None
        actions.append((Links(home, links, gone) if links or gone else None, name, 'bin', None))
    return actions


def verify(home, listed, actions, runner):
    """Read each CLI back after the step installed or moved plugins in it; stop when one is not
    at its pin, since a CLI can report success and keep the old version."""
    acted = {}
    for command, name, cli, record in actions:
        if command and record and cli != 'bin':
            acted.setdefault(cli, []).append(name)
    off = []
    for cli, names in acted.items():
        manager = CLIS[cli]
        present = manager.installed(home, runner)
        for name in names:
            marker, _ = present.get(manager.key(name, listed[name]['source']), (None, None))
            if marker != manager.pin(name, listed[name]):
                off.append(f'{cli} {name} reads {marker}, its pin is {manager.pin(name, listed[name])}')
    if off:
        raise ValueError('not at its pin after the step: ' + '; '.join(off))


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
        for name, record in sorted(old.get('bin', {}).items()) if target == 'all' else ():
            for file in record['files']:
                print(f'Left in place: {home / BIN / file} ({name}\'s command)')
            if (home / SHARE / name).is_dir():
                print(f'Left in place: {home / SHARE / name}')
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
    seen = {}

    def look(name):
        if name not in seen:
            seen[name] = inspect(name, listed[name], runner)
        return seen[name]

    problems = dependency_problems(listed, look) if any(command for command, *_ in actions) else []
    if problems:
        raise ValueError('dependencies: ' + '; '.join(problems))
    actions += commands_plan(home, selected, listed, old.get('bin', {}), look, runner, which, target == 'all')
    steps = [step(command) for command, *_ in actions if command]
    changes = sum(len(s.preview()) for s in steps)

    def content(done):
        after = recorded(owned, [a for a in done if a[2] != 'bin'])
        bins = dict(old.get('bin', {}))
        for _, name, cli, record in done:
            if cli == 'bin' and record is None:
                bins.pop(name, None)
            elif cli == 'bin':
                bins[name] = record
        data = {'version': 1, 'plugins': after,
                'sources': {name: listed[name]['source'] if name in listed else sources[name] for name in after}}
        return {**data, 'bin': bins} if bins else data

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
        verify(home, listed, actions, runner)
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
