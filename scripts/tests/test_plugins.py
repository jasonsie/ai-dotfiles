"""The plugins step end to end: a plugin list and a temporary home in, every outside command
answered by a fake runner (by prefix, every call recorded), commands, files and the receipt out.

Run: python3 -m unittest discover -s scripts/tests -p 'test_plugins.py' -v
"""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from support import load, registry, where
import installer

plugins = load('install/plugins.py')

WEB_CLIPPER = {'source': 'jasonsie/web-clipper', 'version': '2.2.0', 'targets': ['pi']}
PI_SETTINGS = where('pi', 'settings')
GIT = 'git:github.com/jasonsie/web-clipper'
TAGS = 'git ls-remote --exit-code --tags https://github.com/jasonsie/web-clipper'
AGY_URL = 'https://github.com/jasonsie/web-clipper'
CODEX_CONFIG = where('codex', 'settings')
CLAUDE_SETTINGS = where('claude', 'settings')
CODEX_ADD = 'codex plugin marketplace add jasonsie/web-clipper --ref web-clipper--v2.2.0 --json'


class FakePi:
    """Answers commands by prefix and records each; `pi install` and `pi remove` edit Pi's
    settings the way Pi does (one entry per repo, the ref replaced)."""

    def __init__(self, home, **answers):
        self.home, self.calls = home, []
        self.answers = {TAGS: (0, 'abc\trefs/tags/x\n', ''), 'pi install': self.install, 'pi remove': self.remove,
                        **answers}

    def __call__(self, args):
        key = ' '.join(args)
        self.calls.append(key)
        for prefix in sorted(self.answers, key=len, reverse=True):
            if key.startswith(prefix):
                answer = self.answers[prefix]
                return answer(args) if callable(answer) else answer
        return 1, '', f'unexpected: {key}'

    def ran(self, prefix):
        return [c for c in self.calls if c.startswith(prefix)]

    def packages(self):
        path = self.home / PI_SETTINGS
        return json.loads(path.read_text()).get('packages', []) if path.is_file() else []

    def save(self, packages):
        path = self.home / PI_SETTINGS
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text()) if path.is_file() else {}
        path.write_text(json.dumps({**data, 'packages': packages}))

    def install(self, args):
        repo = args[2].rsplit('@', 1)[0]
        self.save([p for p in self.packages() if (p if isinstance(p, str) else p['source']).rsplit('@', 1)[0] != repo]
                  + [args[2]])
        return 0, '', ''

    def remove(self, args):
        self.save([p for p in self.packages() if p != args[2]])
        return 0, '', ''


class FakeAgy:
    """Antigravity's plugins in memory, the way `agy plugin` keeps them: `install` of a
    `/tree/<name>--v<version>` URL replaces the plugin by name and keeps its enabled state."""

    URL = re.compile(r'https://github\.com/[^/]+/[^/]+/tree/(.+)--v(.+)')

    def __init__(self):
        self.plugins = {}

    def answers(self):
        return {'agy plugin list --json': self.list, 'agy plugin install': self.install,
                'agy plugin uninstall': self.uninstall}

    def have(self, name, version, enabled=True):
        self.plugins[name] = {'name': name, 'enabled': enabled, 'version': version, 'source': 'claude-code'}

    def list(self, args):
        return 0, json.dumps(list(self.plugins.values())), ''

    def install(self, args):
        name, version = self.URL.fullmatch(args[3]).groups()
        self.have(name, version, self.plugins.get(name, {}).get('enabled', True))
        return 0, '', ''

    def uninstall(self, args):
        self.plugins.pop(args[3], None)
        return 0, '', ''


class FakeCodex:
    """Codex's plugins the way `codex plugin` keeps them: GitHub marketplaces in Codex's TOML
    config (pinned with `ref`), installed plugins in memory. `plugin add` installs the version
    the marketplace's ref holds and enables the plugin; `marketplace upgrade` refreshes the
    installed ones and keeps their enabled state; a second `marketplace add` from another
    source is refused. A plugin named in `hooks` ships hooks in its installed copy."""

    LATEST = '2.4.0'  # what an unpinned marketplace holds

    def __init__(self, home):
        self.home, self.plugins, self.hooks = home, {}, set()

    def answers(self):
        return {'codex plugin list --json': self.list, 'codex plugin marketplace add': self.add_marketplace,
                'codex plugin marketplace upgrade': self.upgrade, 'codex plugin add': self.add,
                'codex plugin remove': self.remove}

    def config(self):
        path = self.home / CODEX_CONFIG
        return tomllib.loads(path.read_text()) if path.is_file() else {}

    def marketplace(self, repo, ref=None):
        name = repo.split('/')[1] + '-marketplace'
        path = self.home / CODEX_CONFIG
        path.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text() if path.is_file() else ''
        text += (f'\n[marketplaces.{name}]\nsource_type = "git"\nsource = "https://github.com/{repo}.git"\n'
                 + (f'ref = "{ref}"\n' if ref else ''))
        path.write_text(text)
        return name

    def version_at(self, marketplace):
        ref = self.config()['marketplaces'][marketplace].get('ref')
        return ref.rsplit('--v', 1)[1] if ref else self.LATEST

    def put(self, name, marketplace, version, enabled=True):
        self.plugins[name] = {'pluginId': f'{name}@{marketplace}', 'name': name, 'marketplaceName': marketplace,
                              'version': version, 'installed': True, 'enabled': enabled}
        if name in self.hooks:
            hooks = self.home / CODEX_CONFIG.rsplit('/', 1)[0] / 'plugins/cache' / marketplace / name / version / 'hooks'
            hooks.mkdir(parents=True, exist_ok=True)
            (hooks / 'hooks.json').write_text('{"hooks": {}}')

    def list(self, args):
        remote = {'pluginId': 'work-pets@openai-curated-remote', 'name': 'work-pets',
                  'marketplaceName': 'openai-curated-remote', 'version': '0.1.6', 'installed': True, 'enabled': True}
        return 0, json.dumps({'installed': [remote, *self.plugins.values()], 'available': []}), ''

    def add_marketplace(self, args):
        repo, ref = args[4], args[6]
        name = repo.split('/')[1] + '-marketplace'
        if name in self.config().get('marketplaces', {}):
            return 1, '', f"Error: marketplace '{name}' is already added from a different source"
        self.marketplace(repo, ref)
        return 0, json.dumps({'marketplaceName': name, 'installedRoot': '/x', 'alreadyAdded': False}), ''

    def upgrade(self, args):
        for plugin in list(self.plugins.values()):
            if plugin['marketplaceName'] == args[4]:
                self.put(plugin['name'], args[4], self.version_at(args[4]), plugin['enabled'])
        return 0, '{}', ''

    def add(self, args):
        name, marketplace = args[3].split('@')
        self.put(name, marketplace, self.version_at(marketplace))
        return 0, json.dumps({'pluginId': args[3], 'version': self.plugins[name]['version']}), ''

    def remove(self, args):
        self.plugins.pop(args[3].split('@')[0], None)
        return 0, '{}', ''


class FakeClaude:
    """Claude Code's plugins the way `claude plugin` keeps them: marketplaces in memory, their
    declarations in `extraKnownMarketplaces` in Claude's settings (written by `marketplace
    add`), installed plugins in memory. `marketplace add` is refused when a declaration names
    another source, as Claude refuses it; `install` and `update` take the version the
    marketplace's ref holds; `marketplace remove` drops the declaration and the plugins."""

    LATEST = '2.4.0'

    def __init__(self, home):
        self.home, self.marketplaces, self.plugins, self.held = home, {}, {}, {}

    def answers(self):
        return {'claude plugin marketplace list --json': self.list_marketplaces,
                'claude plugin list --json': self.list_plugins, 'claude plugin marketplace add': self.add,
                'claude plugin marketplace remove': self.remove_marketplace, 'claude plugin install': self.install,
                'claude plugin update': self.update, 'claude plugin uninstall': self.uninstall}

    def settings(self):
        path = self.home / CLAUDE_SETTINGS
        return json.loads(path.read_text()) if path.is_file() else {}

    def save(self, data):
        path = self.home / CLAUDE_SETTINGS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + '\n')

    def declare(self, marketplace, source, auto_update=None):
        data = self.settings()
        entry = {'source': source, **({} if auto_update is None else {'autoUpdate': auto_update})}
        data.setdefault('extraKnownMarketplaces', {})[marketplace] = entry
        self.save(data)

    def know(self, repo, ref=None, url=False):
        name = repo.split('/')[1] + '-marketplace'
        self.marketplaces[name] = ({'source': 'git', 'url': f'https://github.com/{repo}.git'} if url
                                   else {'source': 'github', 'repo': repo, **({'ref': ref} if ref else {})})
        return name

    def put(self, name, marketplace, version, enabled=True, scope='user'):
        self.plugins[(name, scope)] = {'id': f'{name}@{marketplace}', 'version': version, 'scope': scope, 'enabled': enabled}

    def version_at(self, marketplace):
        ref = self.marketplaces[marketplace].get('ref')
        return ref.rsplit('--v', 1)[1] if ref else self.LATEST

    def list_marketplaces(self, args):
        return 0, json.dumps([{'name': n, **m, 'installLocation': '/x'} for n, m in self.marketplaces.items()]), ''

    def list_plugins(self, args):
        return 0, json.dumps(list(self.plugins.values())), ''

    def add(self, args):
        repo, ref = args[4].split('#')
        name = repo.split('/')[1] + '-marketplace'
        declared = self.settings().get('extraKnownMarketplaces', {}).get(name)
        if declared and declared['source'] != {'source': 'github', 'repo': repo, 'ref': ref}:
            return 1, json.dumps({'command': 'marketplace-add', 'outcome': 'error', 'message': 'its source does not match'}), ''
        self.know(repo, ref)
        self.declare(name, {'source': 'github', 'repo': repo, 'ref': ref})  # as Claude does: autoUpdate dropped
        return 0, 'Cloning...\n' + json.dumps({'command': 'marketplace-add', 'outcome': 'ok', 'marketplace': name}), ''

    def remove_marketplace(self, args):
        self.marketplaces.pop(args[4], None)
        data = self.settings()
        data.get('extraKnownMarketplaces', {}).pop(args[4], None)
        self.save(data)
        self.plugins = {k: p for k, p in self.plugins.items() if not p['id'].endswith('@' + args[4])}
        return 0, '{}', ''

    def install(self, args):
        name, marketplace = args[3].split('@')
        self.put(name, marketplace, self.version_at(marketplace))
        return 0, '{}', ''

    def update(self, args):
        name, marketplace = args[3].split('@')
        plugin = self.plugins[(name, 'user')]
        version = self.held.get(name) or self.version_at(marketplace)
        self.put(name, marketplace, version, plugin['enabled'])
        message = f'{name} is already at the latest version satisfying ^2.2 (required by zkfy).' if name in self.held else 'updated'
        return 0, json.dumps({'command': 'update', 'outcome': 'ok', 'message': message, 'newVersion': version}), ''

    def uninstall(self, args):
        self.plugins.pop((args[3].split('@')[0], 'user'), None)
        return 0, '{}', ''


class FakeGit:
    """Plugin repos at their release tags. A clone with --no-checkout is a look at a tag: `show`
    answers the manifest set for that repo and tag (else one named after the repo, no
    dependencies) and `ls-tree HEAD bin/` the commands set for the repo. Any other clone is the
    step's checkout: a real folder whose tag `describe` reports and `fetch` plus `checkout` move."""

    def __init__(self):
        self.manifests, self.bins, self.looked, self.checkouts = {}, {}, {}, {}

    def answers(self):
        return {'git clone': self.clone, 'git -C': self.git}

    def clone(self, args):
        repo, tag, folder = args[-2].split('github.com/')[1], args[args.index('--branch') + 1], args[-1]
        if '--no-checkout' in args:
            self.looked[folder] = (repo, tag)
        else:
            for name in self.bins.get(repo, []):
                (Path(folder) / 'bin').mkdir(parents=True, exist_ok=True)
                (Path(folder) / 'bin' / name).write_text('#!/bin/sh\n')
            Path(folder).mkdir(parents=True, exist_ok=True)
            self.checkouts[folder] = (repo, tag)
        return 0, '', ''

    def git(self, args):
        folder, command = args[2], args[3]
        if command == 'show':
            repo, tag = self.looked[folder]
            default = {'name': repo.split('/')[1], 'version': tag.rsplit('--v', 1)[1]}
            return 0, json.dumps(self.manifests.get((repo, tag), default)), ''
        if command == 'ls-tree':
            return 0, ''.join(f'100755 blob abc\tbin/{name}\n' for name in self.bins.get(self.looked[folder][0], [])), ''
        if command == 'describe':
            return (0, self.checkouts[folder][1] + '\n', '') if folder in self.checkouts else (128, '', 'no tag')
        if command == 'checkout':
            self.checkouts[folder] = (self.checkouts[folder][0], args[-1])
        return 0, '', ''


class PluginsStepTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir()
        self.fake = FakePi(self.home)
        self.agy = FakeAgy()
        self.fake.answers.update(self.agy.answers())
        self.codex = FakeCodex(self.home)
        self.fake.answers.update(self.codex.answers())
        self.claude = FakeClaude(self.home)
        self.fake.answers.update(self.claude.answers())
        self.fake.answers['git ls-remote --exit-code --tags https://github.com/jasonsie/zkfy'] = (0, 'abc\trefs/tags/x\n', '')
        self.git = FakeGit()
        self.fake.answers.update(self.git.answers())
        self.listed({'web-clipper': WEB_CLIPPER})
        self.switch()

    def tearDown(self):
        self.temp.cleanup()

    def listed(self, entries, version=1):
        path = Path(self.temp.name) / 'plugins.json'
        path.write_text(json.dumps({'version': version, 'plugins': entries}))
        patcher = patch.object(plugins, 'PLUGINS', path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def switch(self, **switches):
        patcher = patch.object(installer, 'REGISTRY', registry(self.temp.name, **switches))
        patcher.start()
        self.addCleanup(patcher.stop)

    def step(self, write=True, uninstall=False, target='all'):
        """(changes, printed) of one run of the step as install.sh runs it."""
        out = io.StringIO()
        with redirect_stdout(out):
            count = plugins.run(self.home, target, write, uninstall, runner=self.fake, which=lambda _: True)
        return count, out.getvalue()

    def receipt(self):
        path = self.home / plugins.RECEIPT
        return json.loads(path.read_text())['plugins'] if path.is_file() else {}

    # The plugin list, checked strictly

    def test_a_bad_plugin_list_stops_the_run_naming_the_entry(self):
        cases = {
            'version': ({'web-clipper': WEB_CLIPPER}, 2),
            'unknown key "ref"': ({'web-clipper': {**WEB_CLIPPER, 'ref': 'main'}}, 1),
            'web-clipper.*source': ({'web-clipper': {**WEB_CLIPPER, 'source': 'https://github.com/a/b'}}, 1),
            'web-clipper.*exact semver': ({'web-clipper': {**WEB_CLIPPER, 'version': '^2.2'}}, 1),
            'web-clipper.*missing "version"': ({'web-clipper': {'source': 'a/b', 'targets': ['pi']}}, 1),
            'web-clipper.*non-empty': ({'web-clipper': {**WEB_CLIPPER, 'targets': []}}, 1),
            'web-clipper.*emacs.*ai-clis.json': ({'web-clipper': {**WEB_CLIPPER, 'targets': ['emacs']}}, 1),
        }
        for message, (entries, version) in cases.items():
            with self.subTest(message):
                self.listed(entries, version)
                with self.assertRaisesRegex(ValueError, message):
                    self.step()
        self.assertEqual(self.fake.calls, [])

    def test_a_cli_the_step_cannot_serve_yet_stops_the_run(self):
        with patch.dict(plugins.CLIS):
            del plugins.CLIS['claude']
            self.listed({'web-clipper': {**WEB_CLIPPER, 'targets': ['claude']}})
            with self.assertRaisesRegex(ValueError, 'web-clipper.*no plugins support for claude'):
                self.step()

    def test_the_repo_plugin_list_passes_the_check(self):
        self.assertIsInstance(plugins.plugins(), dict)

    # Install, move, remove

    def test_install_puts_the_pin_into_pi_and_a_second_run_makes_no_changes(self):
        count, out = self.step()
        self.assertEqual(self.fake.ran('pi '), [f'pi install {GIT}@web-clipper--v2.2.0'])
        self.assertIn(f'Run: pi install {GIT}@web-clipper--v2.2.0', out)
        self.assertEqual(self.receipt(), {'web-clipper': {'pi': 'installed'}})
        self.assertEqual(count, 2)  # the install and the receipt
        self.fake.calls.clear()
        self.assertEqual(self.step()[0], 0)
        self.assertEqual(self.fake.ran('pi '), [])

    def test_a_dry_run_prints_the_plan_and_writes_nothing(self):
        count, out = self.step(write=False)
        self.assertIn(f'Would run: pi install {GIT}@web-clipper--v2.2.0', out)
        self.assertIn(f'Would write: {self.home / plugins.RECEIPT}', out)
        self.assertEqual(count, 2)
        self.assertEqual(self.fake.ran('pi '), [])
        self.assertFalse((self.home / plugins.RECEIPT).exists())

    def test_a_changed_pin_moves_pi(self):
        self.step()
        self.listed({'web-clipper': {**WEB_CLIPPER, 'version': '2.3.0'}})
        self.fake.calls.clear()
        count, _ = self.step()
        self.assertEqual(self.fake.ran('pi '), [f'pi install {GIT}@web-clipper--v2.3.0'])
        self.assertEqual(self.fake.packages(), [f'{GIT}@web-clipper--v2.3.0'])
        self.assertEqual(self.receipt(), {'web-clipper': {'pi': 'installed'}})
        self.assertEqual(count, 2)  # the move, and the receipt records the new tag's commands

    def test_a_missing_release_tag_stops_before_any_change(self):
        self.fake.answers[TAGS] = (2, '', '')
        with self.assertRaisesRegex(ValueError, r'web-clipper--v2\.2\.0.*claude plugin tag --push'):
            self.step()
        self.assertEqual(self.fake.ran('pi '), [])
        self.assertFalse((self.home / plugins.RECEIPT).exists())

    def test_dropping_the_entry_or_pi_from_its_targets_removes_it(self):
        for dropped in ({}, {'other': {**WEB_CLIPPER, 'source': 'a/other'}}):
            with self.subTest(dropped=dropped):
                self.fake.answers['git ls-remote'] = (0, 'abc\trefs/tags/x\n', '')
                self.listed({'web-clipper': WEB_CLIPPER})
                self.step()
                self.fake.calls.clear()
                self.listed(dropped)
                self.step()
                self.assertEqual(self.fake.ran('pi remove'), [f'pi remove {GIT}@web-clipper--v2.2.0'])
                self.assertNotIn('web-clipper', self.receipt())
                self.fake.save([])

    def test_dropping_pi_from_the_targets_removes_it_from_pi_only(self):
        class Codex(plugins.Pi):  # a second CLI that already has the plugin at its pin
            def installed(self, home, runner):
                return {'jasonsie/web-clipper': ('web-clipper--v2.2.0', 'codex-source')}

        with patch.dict(plugins.CLIS, {'codex': Codex()}):
            self.listed({'web-clipper': {**WEB_CLIPPER, 'targets': ['pi', 'codex']}})
            self.step()
            self.fake.calls.clear()
            self.listed({'web-clipper': {**WEB_CLIPPER, 'targets': ['codex']}})
            self.step()
        self.assertEqual(self.fake.ran('pi '), [f'pi remove {GIT}@web-clipper--v2.2.0'])
        self.assertEqual(self.receipt(), {'web-clipper': {'codex': 'taken over'}})

    def test_a_plugin_already_in_pi_is_taken_over_moved_and_never_removed(self):
        self.fake.save(['npm:other-package', {'source': f'{GIT}@web-clipper--v2.1.0', 'skills': []}])
        self.step()
        self.assertEqual(self.fake.ran('pi '), [f'pi install {GIT}@web-clipper--v2.2.0'])
        self.assertEqual(self.receipt(), {'web-clipper': {'pi': 'taken over'}})
        self.fake.calls.clear()
        self.listed({})
        _, out = self.step()
        self.assertEqual(self.fake.ran('pi '), [])
        self.assertIn('Left in place: pi plugin web-clipper (taken over)', out)
        self.assertEqual(self.receipt(), {})

    def test_a_plugin_already_at_its_pin_is_taken_over_without_a_command(self):
        self.fake.save([f'{GIT}@web-clipper--v2.2.0'])
        count, _ = self.step()
        self.assertEqual(self.fake.ran('pi '), [])
        self.assertEqual(self.receipt(), {'web-clipper': {'pi': 'taken over'}})
        self.assertEqual(count, 1)

    # Antigravity

    def test_install_puts_the_pin_into_antigravity_and_a_second_run_makes_no_changes(self):
        self.listed({'web-clipper': {**WEB_CLIPPER, 'targets': ['agy']}})
        count, out = self.step()
        self.assertEqual(self.fake.ran('agy plugin install'), [f'agy plugin install {AGY_URL}/tree/web-clipper--v2.2.0'])
        self.assertEqual(self.agy.plugins['web-clipper']['version'], '2.2.0')
        self.assertEqual(self.receipt(), {'web-clipper': {'agy': 'installed'}})
        self.assertEqual(count, 2)
        self.fake.calls.clear()
        self.assertEqual(self.step()[0], 0)
        self.assertEqual(self.fake.ran('agy plugin install'), [])

    def test_a_changed_pin_reinstalls_in_antigravity_and_a_disabled_plugin_stays_disabled(self):
        self.listed({'web-clipper': {**WEB_CLIPPER, 'targets': ['agy']}})
        self.step()
        self.agy.plugins['web-clipper']['enabled'] = False
        self.assertEqual(self.step()[0], 0)  # disabled is the user's choice, not a change
        self.listed({'web-clipper': {**WEB_CLIPPER, 'version': '2.3.0', 'targets': ['agy']}})
        self.fake.calls.clear()
        self.step()
        self.assertEqual(self.fake.ran('agy plugin install'), [f'agy plugin install {AGY_URL}/tree/web-clipper--v2.3.0'])
        self.assertEqual(self.agy.plugins['web-clipper'], {**self.agy.plugins['web-clipper'], 'version': '2.3.0', 'enabled': False})
        self.assertEqual(self.fake.ran('agy plugin enable'), [])

    def test_dropping_the_plugin_or_antigravity_from_its_targets_uninstalls_it(self):
        for dropped in ({}, {'web-clipper': WEB_CLIPPER}):  # gone, or Pi only
            with self.subTest(dropped=dropped):
                self.listed({'web-clipper': {**WEB_CLIPPER, 'targets': ['agy']}})
                self.step()
                self.fake.calls.clear()
                self.listed(dropped)
                self.step()
                self.assertEqual(self.fake.ran('agy plugin uninstall'), ['agy plugin uninstall web-clipper'])
                self.assertNotIn('web-clipper', self.agy.plugins)
                self.assertNotIn('agy', self.receipt().get('web-clipper', {}))
                self.fake.save([])
                self.agy.plugins.clear()

    def test_a_plugin_already_in_antigravity_is_taken_over_moved_and_never_removed(self):
        self.agy.have('web-clipper', '2.1.0')
        self.agy.have('firebase', None)  # the user's own, unlisted: untouched
        self.listed({'web-clipper': {**WEB_CLIPPER, 'targets': ['agy']}})
        self.step()
        self.assertEqual(self.fake.ran('agy plugin install'), [f'agy plugin install {AGY_URL}/tree/web-clipper--v2.2.0'])
        self.assertEqual(self.receipt(), {'web-clipper': {'agy': 'taken over'}})
        self.fake.calls.clear()
        self.listed({})
        _, out = self.step()
        self.assertEqual(self.fake.ran('agy plugin'), ['agy plugin list --json'])
        self.assertIn('Left in place: agy plugin web-clipper (taken over)', out)
        self.assertEqual(sorted(self.agy.plugins), ['firebase', 'web-clipper'])

    def test_one_pin_installs_into_pi_and_antigravity_alike(self):
        self.listed({'web-clipper': {**WEB_CLIPPER, 'targets': ['pi', 'agy']}})
        self.step()
        self.assertEqual(self.receipt(), {'web-clipper': {'agy': 'installed', 'pi': 'installed'}})
        self.assertEqual(self.fake.packages(), [f'{GIT}@web-clipper--v2.2.0'])
        self.assertEqual(self.agy.plugins['web-clipper']['version'], '2.2.0')

    def test_a_failed_antigravity_listing_stops_before_any_change(self):
        self.listed({'web-clipper': {**WEB_CLIPPER, 'targets': ['agy']}})
        self.fake.answers['agy plugin list --json'] = (1, '', 'not signed in')
        with self.assertRaisesRegex(ValueError, 'agy plugin list --json failed: not signed in'):
            self.step()
        self.assertEqual(self.fake.ran('agy plugin install'), [])

    # Codex

    def codex_listed(self, version='2.2.0'):
        self.listed({'web-clipper': {**WEB_CLIPPER, 'version': version, 'targets': ['codex']}})

    def test_install_puts_the_pin_into_codex_and_a_second_run_makes_no_changes(self):
        self.codex_listed()
        count, out = self.step()
        self.assertEqual(self.fake.ran('codex plugin m') + self.fake.ran('codex plugin add'),
                         [CODEX_ADD, 'codex plugin add web-clipper@web-clipper-marketplace --json'])
        self.assertEqual(self.codex.config()['marketplaces']['web-clipper-marketplace']['ref'], 'web-clipper--v2.2.0')
        self.assertEqual(self.codex.plugins['web-clipper']['version'], '2.2.0')
        self.assertEqual(self.receipt(), {'web-clipper': {'codex': 'installed'}})
        self.assertNotIn('/hooks', out)
        self.assertEqual(count, 3)  # two commands and the receipt
        self.fake.calls.clear()
        self.assertEqual(self.step()[0], 0)
        self.assertEqual(self.fake.ran('codex plugin'), ['codex plugin list --json'])

    def test_a_changed_pin_moves_codex_by_its_config_ref_and_keeps_a_disabled_plugin_disabled(self):
        path = self.home / CODEX_CONFIG
        path.parent.mkdir(parents=True)
        path.write_text('model = "gpt-6"\n\n[mcp_servers.context7]\ncommand = "npx"\n')
        self.codex_listed()
        self.step()
        self.codex.plugins['web-clipper']['enabled'] = False
        before = path.read_text()
        self.codex_listed('2.3.0')
        self.fake.calls.clear()
        _, out = self.step()
        self.assertEqual(self.fake.ran('codex plugin m') + self.fake.ran('codex plugin add'),
                         ['codex plugin marketplace upgrade web-clipper-marketplace'])
        self.assertEqual(path.read_text(), before.replace('web-clipper--v2.2.0', 'web-clipper--v2.3.0'))
        self.assertEqual(self.codex.plugins['web-clipper']['version'], '2.3.0')
        self.assertFalse(self.codex.plugins['web-clipper']['enabled'])
        backups = list((self.home / installer.STATE / 'settings').glob('backup-*/' + CODEX_CONFIG))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), before)
        self.assertIn(f'Update: {path}', out)

    def test_installing_a_plugin_with_hooks_into_codex_prints_the_hooks_reminder(self):
        self.codex.hooks.add('web-clipper')
        self.codex_listed()
        _, out = self.step()
        self.assertIn('approve web-clipper\'s hooks once with /hooks', out)

    def test_dropping_the_plugin_or_codex_from_its_targets_removes_it_from_codex(self):
        for dropped in ({}, {'web-clipper': WEB_CLIPPER}):  # gone, or Pi only
            with self.subTest(dropped=dropped):
                self.codex_listed()
                self.step()
                self.fake.calls.clear()
                self.listed(dropped)
                self.step()
                self.assertEqual(self.fake.ran('codex plugin remove'), ['codex plugin remove web-clipper@web-clipper-marketplace'])
                self.assertNotIn('web-clipper', self.codex.plugins)
                self.assertNotIn('codex', self.receipt().get('web-clipper', {}))
                self.fake.save([])

    def test_a_plugin_already_in_codex_is_taken_over_pinned_and_never_removed(self):
        self.codex.put('web-clipper', self.codex.marketplace('jasonsie/web-clipper'), '2.2.0')  # added by hand, no ref
        self.codex_listed()
        self.step()
        self.assertEqual(self.fake.ran('codex plugin m') + self.fake.ran('codex plugin add'),
                         ['codex plugin marketplace upgrade web-clipper-marketplace'])
        self.assertEqual(self.codex.config()['marketplaces']['web-clipper-marketplace']['ref'], 'web-clipper--v2.2.0')
        self.assertEqual(self.receipt(), {'web-clipper': {'codex': 'taken over'}})
        self.fake.calls.clear()
        self.listed({})
        _, out = self.step()
        self.assertEqual(self.fake.ran('codex plugin remove'), [])
        self.assertIn('Left in place: codex plugin web-clipper (taken over)', out)

    def test_a_dry_run_for_codex_prints_each_step_and_writes_nothing(self):
        self.codex_listed()
        count, out = self.step(write=False)
        self.assertIn(f'Would run: {CODEX_ADD}', out)
        self.assertIn('Would run: codex plugin add web-clipper@<its marketplace> --json', out)
        self.assertEqual(count, 3)
        self.assertFalse((self.home / CODEX_CONFIG).exists())
        self.step()
        self.codex_listed('2.3.0')
        count, out = self.step(write=False)
        self.assertIn(f'Would update: {self.home / CODEX_CONFIG}', out)
        self.assertIn('Would run: codex plugin marketplace upgrade web-clipper-marketplace', out)
        self.assertEqual(count, 3)  # the ref, the upgrade, the receipt
        self.assertEqual(self.codex.config()['marketplaces']['web-clipper-marketplace']['ref'], 'web-clipper--v2.2.0')

    def test_a_failed_codex_listing_stops_before_any_change(self):
        self.codex_listed()
        self.fake.answers['codex plugin list --json'] = (1, '', 'not logged in')
        with self.assertRaisesRegex(ValueError, 'codex plugin list --json failed: not logged in'):
            self.step()
        self.assertEqual(self.fake.ran('codex plugin m'), [])

    # Claude Code

    def claude_listed(self, version='2.2.0', **more):
        self.listed({'web-clipper': {**WEB_CLIPPER, 'version': version, 'targets': ['claude']}, **more})

    def claude_runs(self):
        return [c for c in self.fake.ran('claude plugin') if 'list --json' not in c]

    def declared(self, marketplace='web-clipper-marketplace'):
        return self.claude.settings()['extraKnownMarketplaces'][marketplace]

    def test_install_puts_the_pin_into_claude_with_auto_update_off(self):
        self.claude_listed()
        count, out = self.step()
        self.assertEqual(self.claude_runs(), [
            'claude plugin marketplace add jasonsie/web-clipper#web-clipper--v2.2.0 --json',
            'claude plugin install web-clipper@web-clipper-marketplace --json'])
        self.assertEqual(self.declared(), {'source': {'source': 'github', 'repo': 'jasonsie/web-clipper',
                                                      'ref': 'web-clipper--v2.2.0'}, 'autoUpdate': False})
        self.assertEqual(self.claude.plugins[('web-clipper', 'user')]['version'], '2.2.0')
        self.assertEqual(self.receipt(), {'web-clipper': {'claude': 'installed'}})
        self.assertIn(f'Update: {self.home / CLAUDE_SETTINGS}', out)
        self.assertEqual(count, 4)  # two commands, the settings and the receipt
        self.fake.calls.clear()
        self.assertEqual(self.step()[0], 0)
        self.assertEqual(self.claude_runs(), [])

    def test_a_changed_pin_moves_claude_and_keeps_a_disabled_plugin_and_other_settings(self):
        self.claude.save({'model': 'opus', 'hooks': {'PreToolUse': []}, 'enabledPlugins': {'other@x': True}})
        self.claude_listed()
        self.step()
        self.claude.plugins[('web-clipper', 'user')]['enabled'] = False
        before = self.claude.settings()
        self.claude_listed('2.3.0')
        self.fake.calls.clear()
        self.step()
        self.assertEqual(self.claude_runs(), [
            'claude plugin marketplace add jasonsie/web-clipper#web-clipper--v2.3.0 --json',
            'claude plugin update web-clipper@web-clipper-marketplace --json'])
        plugin = self.claude.plugins[('web-clipper', 'user')]
        self.assertEqual((plugin['version'], plugin['enabled']), ('2.3.0', False))
        after = self.claude.settings()
        self.assertEqual(after['extraKnownMarketplaces']['web-clipper-marketplace']['source']['ref'], 'web-clipper--v2.3.0')
        self.assertEqual({k: v for k, v in after.items() if k != 'extraKnownMarketplaces'},
                         {k: v for k, v in before.items() if k != 'extraKnownMarketplaces'})
        backups = (self.home / installer.STATE / 'settings').glob('backup-*/' + CLAUDE_SETTINGS)
        self.assertIn(before, [json.loads(b.read_text()) for b in backups])
        self.assertIs(self.declared()['autoUpdate'], False)

    def test_a_version_with_a_commit_suffix_counts_as_its_pin(self):
        marketplace = self.claude.know('jasonsie/web-clipper', 'web-clipper--v2.2.0')
        self.claude.declare(marketplace, {'source': 'github', 'repo': 'jasonsie/web-clipper',
                                          'ref': 'web-clipper--v2.2.0'}, auto_update=False)
        self.claude.put('web-clipper', marketplace, '2.2.0-b1f6b17dca62')
        self.claude_listed()
        count, _ = self.step()
        self.assertEqual((count, self.claude_runs()), (1, []))  # only the receipt
        self.assertEqual(self.receipt(), {'web-clipper': {'claude': 'taken over'}})

    def test_todays_hand_installs_are_taken_over_pinned_and_never_removed(self):
        # As on this Mac: web-clipper declared without a ref, auto-update on, installed as zkfy's
        # dependency; zkfy's marketplace known from a git URL only.
        web = self.claude.know('jasonsie/web-clipper')
        self.claude.declare(web, {'source': 'github', 'repo': 'jasonsie/web-clipper'}, auto_update=True)
        self.claude.put('web-clipper', web, '2.4.0-b1f6b17dca62')
        zkfy = self.claude.know('jasonsie/zkfy', url=True)
        self.claude.put('zkfy', zkfy, '1.6.0')
        self.claude_listed('2.4.0', zkfy={'source': 'jasonsie/zkfy', 'version': '1.6.0', 'targets': ['claude']})
        self.step()
        self.assertEqual(self.claude_runs(), [
            'claude plugin marketplace add jasonsie/web-clipper#web-clipper--v2.4.0 --json',
            'claude plugin update web-clipper@web-clipper-marketplace --json',
            'claude plugin marketplace add jasonsie/zkfy#zkfy--v1.6.0 --json',
            'claude plugin update zkfy@zkfy-marketplace --json'])
        for name, marketplace in (('web-clipper', web), ('zkfy', zkfy)):
            self.assertEqual(self.declared(marketplace)['autoUpdate'], False)
            self.assertEqual(self.claude.marketplaces[marketplace]['source'], 'github')
        self.assertEqual(self.receipt(), {'web-clipper': {'claude': 'taken over'}, 'zkfy': {'claude': 'taken over'}})
        self.fake.calls.clear()
        self.assertEqual(self.step()[0], 0)
        self.listed({})
        _, out = self.step()
        self.assertEqual(self.claude_runs(), [])
        self.assertIn('Left in place: claude plugin zkfy (taken over)', out)

    def test_dropping_a_plugin_from_claude_uninstalls_it_and_its_marketplace_when_alone(self):
        self.claude_listed()
        self.step()
        self.fake.calls.clear()
        self.listed({})
        self.step()
        self.assertEqual(self.claude_runs(), [
            'claude plugin uninstall web-clipper@web-clipper-marketplace --json',
            'claude plugin marketplace remove web-clipper-marketplace --scope user --json'])
        self.assertEqual((self.claude.plugins, self.claude.marketplaces), ({}, {}))
        self.assertNotIn('web-clipper-marketplace', self.claude.settings()['extraKnownMarketplaces'])
        self.assertEqual(self.receipt(), {})

    def test_a_marketplace_another_plugin_still_uses_stays(self):
        self.claude_listed()
        self.step()
        self.claude.put('web-clipper-extras', 'web-clipper-marketplace', '1.0.0')  # the user's own
        self.fake.calls.clear()
        self.listed({'web-clipper': WEB_CLIPPER})  # Claude dropped from its targets
        self.step()
        self.assertEqual(self.claude_runs(), ['claude plugin uninstall web-clipper@web-clipper-marketplace --json'])
        self.assertIn('web-clipper-marketplace', self.claude.marketplaces)

    def test_auto_update_turned_back_on_is_turned_off_without_a_reinstall(self):
        self.claude_listed()
        self.step()
        entry = self.declared()
        self.claude.declare('web-clipper-marketplace', entry['source'], auto_update=True)  # toggled in /plugin
        self.fake.calls.clear()
        count, _ = self.step()
        self.assertEqual((count, self.claude_runs()), (1, []))
        self.assertIs(self.declared()['autoUpdate'], False)

    def test_a_move_claude_will_not_make_stops_the_run_with_its_reason(self):
        self.claude_listed()
        self.step()
        self.claude.held['web-clipper'] = '2.2.0-b1f6b17dca62'  # zkfy needs ^2.2
        self.claude_listed('2.1.0')
        with self.assertRaisesRegex(ValueError, r'not at its pin.*claude web-clipper.*2\.1\.0'):
            _, out = self.step()
        self.assertEqual(self.receipt(), {'web-clipper': {'claude': 'installed'}})

    def test_a_dry_run_for_claude_prints_each_step_and_writes_nothing(self):
        self.claude_listed()
        count, out = self.step(write=False)
        self.assertIn('Would run: claude plugin marketplace add jasonsie/web-clipper#web-clipper--v2.2.0 --json', out)
        self.assertIn(f'Would update: {self.home / CLAUDE_SETTINGS}', out)
        self.assertIn('Would run: claude plugin install web-clipper@<its marketplace> --json', out)
        self.assertEqual(count, 4)
        self.assertEqual((self.claude.marketplaces, self.claude.settings()), ({}, {}))

    def test_a_failed_claude_listing_stops_before_any_change(self):
        self.claude_listed()
        self.fake.answers['claude plugin marketplace list --json'] = (1, '', 'boom')
        with self.assertRaisesRegex(ValueError, 'claude plugin marketplace list --json failed: boom'):
            self.step()
        self.assertEqual(self.claude_runs(), [])

    # Dependencies, read from each plugin's manifest at its tag

    ZKFY = {'source': 'jasonsie/zkfy', 'version': '1.6.0', 'targets': ['pi']}

    def needs(self, version_range, **web_clipper):
        dependency = {'name': 'web-clipper', 'marketplace': 'web-clipper-marketplace', 'version': version_range}
        self.git.manifests[('jasonsie/zkfy', 'zkfy--v1.6.0')] = {'name': 'zkfy', 'version': '1.6.0', 'dependencies': [dependency]}
        self.listed({'zkfy': self.ZKFY, 'web-clipper': {**WEB_CLIPPER, **web_clipper}})

    def test_zkfy_with_the_web_clipper_it_needs_installs(self):
        self.needs('^2.2')
        self.step()
        self.assertEqual(sorted(self.fake.ran('pi install')), [f'pi install {GIT}@web-clipper--v2.2.0',
                                                               'pi install git:github.com/jasonsie/zkfy@zkfy--v1.6.0'])

    def test_a_dependency_problem_stops_the_run_before_any_change_naming_both_pins(self):
        cases = {
            r'zkfy 1\.6\.0 needs web-clipper \^2\.2, pinned at 2\.1\.0': ('^2.2', {'version': '2.1.0'}),
            r'zkfy 1\.6\.0 needs web-clipper ~2\.1\.0, pinned at 2\.2\.0': ('~2.1.0', {}),
            r'zkfy 1\.6\.0 needs web-clipper =2\.2\.1, pinned at 2\.2\.0': ('=2.2.1', {}),
            r'zkfy 1\.6\.0 needs web-clipper \^2\.2, pinned at 2\.2\.0, in agy too': ('^2.2', {}),
        }
        for message, (version_range, web_clipper) in cases.items():
            with self.subTest(message):
                self.needs(version_range, **web_clipper)
                if 'in agy too' in message:
                    self.listed({'zkfy': {**self.ZKFY, 'targets': ['pi', 'agy']}, 'web-clipper': WEB_CLIPPER})
                self.fake.calls.clear()
                with self.assertRaisesRegex(ValueError, message):
                    self.step()
                self.assertEqual(self.fake.ran('pi install') + self.fake.ran('agy plugin install'), [])

    def test_an_unlisted_dependency_stops_the_run(self):
        self.needs('^2.2')
        self.listed({'zkfy': self.ZKFY})
        with self.assertRaisesRegex(ValueError, r'zkfy 1\.6\.0 needs web-clipper \^2\.2, which is not listed'):
            self.step()
        self.assertEqual(self.fake.ran('pi install'), [])

    def test_a_dependency_as_a_bare_name_needs_only_to_be_listed(self):
        self.git.manifests[('jasonsie/zkfy', 'zkfy--v1.6.0')] = {'name': 'zkfy', 'dependencies': ['web-clipper@web-clipper-marketplace']}
        self.listed({'zkfy': self.ZKFY, 'web-clipper': {**WEB_CLIPPER, 'version': '1.0.0'}})
        self.step()
        self.assertEqual(len(self.fake.ran('pi install')), 2)

    def test_a_manifest_named_otherwise_than_its_key_stops_the_run(self):
        self.git.manifests[('jasonsie/web-clipper', 'web-clipper--v2.2.0')] = {'name': 'clipper'}
        with self.assertRaisesRegex(ValueError, r"web-clipper: jasonsie/web-clipper at web-clipper--v2\.2\.0 is named 'clipper'"):
            self.step()

    def test_a_run_with_nothing_to_change_reads_no_manifest(self):
        self.step()
        self.fake.calls.clear()
        self.step()
        self.assertEqual(self.fake.ran('git'), [])

    def test_ranges_read_as_claude_and_npm_read_them(self):
        table = [('^2.2', '2.2.0', True), ('^2.2', '2.9.1', True), ('^2.2', '3.0.0', False), ('^2.2', '2.1.9', False),
                 ('^0.2.3', '0.2.9', True), ('^0.2.3', '0.3.0', False), ('^0.0.3', '0.0.4', False), ('^0', '0.9.0', True),
                 ('~2.1.0', '2.1.7', True), ('~2.1.0', '2.2.0', False), ('~2', '2.9.0', True), ('~2', '3.0.0', False),
                 ('2.1.0', '2.1.0', True), ('=2.1.0', '2.1.1', False), ('2.1', '2.1.5', True), ('2.1', '2.2.0', False),
                 ('>=1.4', '1.4.0', True), ('>=1.4', '1.3.9', False), ('<2', '1.9.9', True), ('>1.4', '1.4.9', False),
                 ('>1.4', '1.5.0', True), ('<=1.4', '1.4.9', True), ('<=1.4', '1.5.0', False), ('^2.2', '2.3.0-beta.1', False)]
        for version_range, version, expected in table:
            with self.subTest(range=version_range, version=version):
                self.assertIs(plugins.satisfies(version, version_range), expected)
        self.assertIsNone(plugins.satisfies('2.2.0', '>=2.1 <3'))

    # Commands on PATH

    def link(self, name='web-clipper'):
        return self.home / plugins.BIN / name

    def checkout(self, name='web-clipper'):
        return self.home / plugins.SHARE / name

    def test_a_plugins_commands_are_linked_from_its_checkout_at_the_pin(self):
        self.git.bins['jasonsie/web-clipper'] = ['web-clipper']
        count, out = self.step()
        self.assertEqual(self.fake.ran(f'git clone --quiet --depth 1 --branch web-clipper--v2.2.0 https'),
                         [f'git clone --quiet --depth 1 --branch web-clipper--v2.2.0 https://github.com/jasonsie/web-clipper {self.checkout()}'])
        self.assertEqual(os.readlink(self.link()), str(self.checkout() / 'bin/web-clipper'))
        self.assertTrue(self.link().resolve().is_file())
        self.assertIn(f'Link: {self.link()} -> {self.checkout() / "bin/web-clipper"}', out)
        receipt = json.loads((self.home / plugins.RECEIPT).read_text())
        self.assertEqual(receipt['bin'], {'web-clipper': {'tag': 'web-clipper--v2.2.0', 'files': ['web-clipper']}})
        self.assertEqual(count, 4)  # pi install, the clone, the link, the receipt
        self.fake.calls.clear()
        self.assertEqual(self.step()[0], 0)
        self.assertEqual([c for c in self.fake.ran('git') if 'describe' not in c], [])  # offline: a local describe only

    def test_a_command_name_something_else_owns_stops_the_run_before_any_change(self):
        self.git.bins['jasonsie/web-clipper'] = ['web-clipper']
        self.link().parent.mkdir(parents=True)
        self.link().write_text('#!/bin/sh\necho mine\n')
        with self.assertRaisesRegex(ValueError, f'refusing to replace: {self.link()}'):
            self.step()
        self.assertEqual((self.fake.ran('pi install'), self.fake.ran('git clone --quiet --depth 1 --branch web-clipper--v2.2.0 https')), ([], []))
        self.assertEqual(self.link().read_text(), '#!/bin/sh\necho mine\n')

    def test_a_recorded_name_that_no_longer_holds_our_link_is_refused_too(self):
        self.git.bins['jasonsie/web-clipper'] = ['web-clipper']
        self.step()
        self.link().unlink()
        self.link().write_text('#!/bin/sh\necho mine\n')
        with self.assertRaisesRegex(ValueError, f'refusing to replace: {self.link()}'):
            self.step()
        self.assertEqual(self.link().read_text(), '#!/bin/sh\necho mine\n')
        self.link().unlink()
        os.symlink('/elsewhere/web-clipper', self.link())
        with self.assertRaisesRegex(ValueError, f'refusing to replace: {self.link()}'):
            self.step()
        self.assertEqual(os.readlink(self.link()), '/elsewhere/web-clipper')

    def test_a_changed_pin_moves_the_checkout_and_keeps_the_link(self):
        self.git.bins['jasonsie/web-clipper'] = ['web-clipper']
        self.step()
        self.listed({'web-clipper': {**WEB_CLIPPER, 'version': '2.3.0'}})
        self.fake.calls.clear()
        self.step()
        self.assertEqual(self.fake.ran(f'git -C {self.checkout()} fetch') + self.fake.ran(f'git -C {self.checkout()} checkout'),
                         [f'git -C {self.checkout()} fetch --quiet --depth 1 origin tag web-clipper--v2.3.0',
                          f'git -C {self.checkout()} checkout --quiet web-clipper--v2.3.0'])
        self.assertEqual(os.readlink(self.link()), str(self.checkout() / 'bin/web-clipper'))
        self.assertEqual(self.step()[0], 0)

    def test_dropping_the_plugin_removes_its_links_and_checkout_and_uninstall_leaves_them(self):
        self.git.bins['jasonsie/web-clipper'] = ['web-clipper']
        self.step()
        _, out = self.step(uninstall=True)
        self.assertIn(f'Left in place: {self.link()} (web-clipper\'s command)', out)
        self.assertIn(f'Left in place: {self.checkout()}', out)
        self.assertTrue(self.link().is_symlink())
        self.listed({})
        _, out = self.step()
        self.assertFalse(self.link().is_symlink() or self.checkout().exists())
        self.assertIn(f'Remove folder: {self.checkout()}', out)
        self.assertNotIn('bin', json.loads((self.home / plugins.RECEIPT).read_text()))

    def test_a_plugin_without_commands_gets_no_checkout_and_is_not_looked_at_again(self):
        self.step()
        self.assertFalse(self.checkout().exists() or self.link().exists())
        self.fake.calls.clear()
        self.step()
        self.assertEqual(self.fake.ran('git'), [])

    def test_a_dry_run_shows_the_checkout_and_the_link_and_writes_nothing(self):
        self.git.bins['jasonsie/web-clipper'] = ['web-clipper']
        count, out = self.step(write=False)
        self.assertIn(f'Would run: git clone --quiet --depth 1 --branch web-clipper--v2.2.0 https://github.com/jasonsie/web-clipper {self.checkout()}', out)
        self.assertIn(f'Would link: {self.link()} -> {self.checkout() / "bin/web-clipper"}', out)
        self.assertEqual(count, 4)
        self.assertFalse(self.checkout().exists() or self.link().is_symlink())

    # Switched off, uninstall, --target

    def test_pi_switched_off_or_uninstall_leaves_the_plugin_and_lists_it(self):
        self.step()
        self.fake.calls.clear()
        self.switch(pi=False)
        count, out = self.step()
        self.assertEqual((count, self.fake.calls), (0, []))
        self.assertIn('Left in place: pi plugin web-clipper', out)
        self.switch()
        count, out = self.step(uninstall=True)
        self.assertEqual((count, self.fake.calls), (0, []))
        self.assertIn('Left in place: pi plugin web-clipper', out)
        self.assertEqual(self.fake.packages(), [f'{GIT}@web-clipper--v2.2.0'])

    def test_target_narrows_the_step_to_one_cli(self):
        self.assertEqual(self.step(target='codex'), (0, ''))
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.step(target='pi')[0], 2)

    def test_pi_not_on_path_is_skipped(self):
        out = io.StringIO()
        with redirect_stdout(out):
            count = plugins.run(self.home, 'all', True, False, runner=self.fake, which=lambda _: False)
        self.assertEqual((count, self.fake.calls), (0, []))
        self.assertIn('plugins: skip pi (not on PATH)', out.getvalue())

    def test_an_install_that_leaves_a_plugin_off_its_pin_stops_the_run(self):
        self.fake.answers['pi install'] = (0, '', '')  # says done, changes nothing
        with self.assertRaisesRegex(ValueError, r'not at its pin.*pi web-clipper'):
            self.step()

    def test_a_failed_command_stops_and_the_receipt_keeps_what_was_done(self):
        self.listed({'web-clipper': WEB_CLIPPER, 'zkfy': {**WEB_CLIPPER, 'source': 'jasonsie/zkfy'}})
        self.fake.answers['git ls-remote'] = (0, 'abc\trefs/tags/x\n', '')
        self.fake.answers['pi install git:github.com/jasonsie/zkfy'] = (1, '', 'clone failed')
        with self.assertRaisesRegex(ValueError, 'clone failed'):
            self.step()
        self.assertEqual(self.receipt(), {'web-clipper': {'pi': 'installed'}})


if __name__ == '__main__':
    unittest.main()
