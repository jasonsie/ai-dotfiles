"""The plugins step end to end: a plugin list and a temporary home in, every outside command
answered by a fake runner (by prefix, every call recorded), commands, files and the receipt out.

Run: python3 -m unittest discover -s scripts/tests -p 'test_plugins.py' -v
"""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re
import tempfile
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


class PluginsStepTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir()
        self.fake = FakePi(self.home)
        self.agy = FakeAgy()
        self.fake.answers.update(self.agy.answers())
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
            'web-clipper.*no plugins support for codex': ({'web-clipper': {**WEB_CLIPPER, 'targets': ['codex']}}, 1),
        }
        for message, (entries, version) in cases.items():
            with self.subTest(message):
                self.listed(entries, version)
                with self.assertRaisesRegex(ValueError, message):
                    self.step()
        self.assertEqual(self.fake.calls, [])

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
        self.assertEqual(count, 1)

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
        self.assertEqual(self.fake.calls, [f'pi remove {GIT}@web-clipper--v2.2.0'])
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
        self.assertEqual(self.fake.calls, [])
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

    def test_a_failed_command_stops_and_the_receipt_keeps_what_was_done(self):
        self.listed({'web-clipper': WEB_CLIPPER, 'zkfy': {**WEB_CLIPPER, 'source': 'jasonsie/zkfy'}})
        self.fake.answers['git ls-remote'] = (0, 'abc\trefs/tags/x\n', '')
        self.fake.answers['pi install git:github.com/jasonsie/zkfy'] = (1, '', 'clone failed')
        with self.assertRaisesRegex(ValueError, 'clone failed'):
            self.step()
        self.assertEqual(self.receipt(), {'web-clipper': {'pi': 'installed'}})


if __name__ == '__main__':
    unittest.main()
