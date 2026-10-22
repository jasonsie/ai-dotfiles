from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import support  # noqa: F401  (puts scripts/ on sys.path)
import installer


class InstallerTest(unittest.TestCase):
    """The mechanics every install step shares: states, safe writes, rollback, output."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='installer 空間 ')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()

    def file(self, rel, text='x', mode=0o644):
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(mode)
        return path

    def test_states(self):
        path = self.home / 'a'
        self.assertEqual(installer.state(path), ('absent',))
        self.file('a', 'hi', 0o600)
        self.assertEqual(installer.state(path), ('file', b'hi', 0o600))
        link = self.home / 'gone'
        link.symlink_to(self.home / 'nowhere')  # a dangling link is still a link
        self.assertEqual(installer.state(link), ('link', str(self.home / 'nowhere')))
        self.assertEqual(installer.state(self.home), ('other',))

    def test_put_sets_each_kind_and_creates_parents(self):
        path = self.home / 'new/deep/entry'
        installer.put(path, ('file', b'data', 0o600))
        self.assertEqual(installer.state(path), ('file', b'data', 0o600))
        installer.put(path, ('link', '/elsewhere'))
        self.assertEqual(installer.state(path), ('link', '/elsewhere'))
        installer.put(path, ('absent',))
        self.assertEqual(installer.state(path), ('absent',))
        self.assertEqual(os.listdir(path.parent), [])  # no temporary leftovers

    def test_edit_keeps_mode_creates_private_and_refuses_links(self):
        path = self.file('settings.json', '{}', 0o640)
        self.assertIsNone(installer.edit(path, lambda old: old))
        _, before, after = installer.edit(path, lambda old: b'{"a": 1}')
        self.assertEqual((before, after), (('file', b'{}', 0o640), ('file', b'{"a": 1}', 0o640)))
        _, before, after = installer.edit(self.home / 'missing.json', lambda old: old + b'new')
        self.assertEqual((before, after), (('absent',), ('file', b'new', 0o600)))
        (self.home / 'link.json').symlink_to(path)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            installer.edit(self.home / 'link.json', lambda old: b'x')
        with self.assertRaisesRegex(ValueError, 'Not a file'):
            installer.edit(self.home, lambda old: b'x')

    def changes(self):
        """A file update, a new link, and a removal."""
        settings = self.file('.cli/settings.json', '{}', 0o600)
        link = self.home / '.cli/skills/a'
        old = self.file('.cli/old.txt', 'old', 0o644)
        return [(settings, installer.state(settings), ('file', b'{"x": 1}', 0o600)),
                (link, ('absent',), ('link', '/repo/skills/a')),
                (old, installer.state(old), ('absent',))]

    def test_apply_writes_all_and_backs_up_replaced_files(self):
        changes = self.changes()
        backup = installer.apply(self.home, changes, backup='settings')
        for path, _, after in changes:
            self.assertEqual(installer.state(path), after)
        self.assertEqual(backup.parent, self.home / installer.STATE / 'settings')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertEqual((backup / '.cli/settings.json').read_text(), '{}')
        self.assertEqual((backup / '.cli/old.txt').read_text(), 'old')
        self.assertIsNone(installer.apply(self.home, [(self.home / 'l', ('absent',), ('link', '/t'))], backup='settings'))

    def test_concurrent_edit_writes_nothing(self):
        changes = self.changes()
        changes[2][0].write_text('changed by someone else')
        with self.assertRaisesRegex(ValueError, 'Concurrent edit'):
            installer.apply(self.home, changes, backup='settings')
        self.assertEqual(changes[0][0].read_text(), '{}')
        self.assertFalse(changes[1][0].is_symlink())
        self.assertFalse((self.home / installer.STATE).exists())

    def test_failure_puts_every_path_back(self):
        changes = self.changes()
        original, calls = installer.put, 0

        def fail_third(path, wanted):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('injected')
            original(path, wanted)

        with patch.object(installer, 'put', fail_third), self.assertRaises(OSError):
            installer.apply(self.home, changes)
        for path, before, _ in changes:
            self.assertEqual(installer.state(path), before)

    def test_never_replaces_a_folder(self):
        folder = self.home / 'folder'
        folder.mkdir()
        with self.assertRaisesRegex(ValueError, 'not a file or link'):
            installer.apply(self.home, [(folder, ('other',), ('link', '/t'))])

    def test_show_previews_and_reports(self):
        out = io.StringIO()
        with redirect_stdout(out):
            installer.show(self.changes(), write=False)
            installer.show([(Path('/n'), ('absent',), ('file', b'', 0o600))], write=True)
        self.assertEqual(out.getvalue().splitlines(), [
            f'Would update: {self.home}/.cli/settings.json',
            f'Would link: {self.home}/.cli/skills/a -> /repo/skills/a',
            f'Would remove: {self.home}/.cli/old.txt',
            'Write: /n'])

    def test_receipt_is_private_sorted_json(self):
        kind, data, mode = installer.receipt({'b': 1, 'a': 2})
        self.assertEqual((kind, mode), ('file', 0o600))
        self.assertEqual(data, b'{\n  "a": 2,\n  "b": 1\n}\n')

    def test_repo_registry_lists_the_four_clis(self):
        entries = installer.clis()
        self.assertEqual(set(entries), set(installer.SUPPORTED))
        self.assertTrue(all(entry['on'] for entry in entries.values()))
        self.assertEqual(entries['codex']['skills'], entries['pi']['skills'])  # Codex and Pi share one
        self.assertEqual(installer.path(self.home, 'claude', 'skills'), self.home / '.claude/skills')

    def registry(self, change):
        """Point installer at a copy of the repo's registry, edited by change(data)."""
        data = json.loads(installer.REGISTRY.read_text())
        change(data)
        path = self.home / 'ai-clis.json'
        path.write_text(json.dumps(data))
        return patch.object(installer, 'REGISTRY', path)

    def test_registry_is_checked_strictly(self):
        broken = {
            'is missing "skills"': lambda d: d['clis']['claude'].pop('skills'),
            'unknown key "colour"': lambda d: d['clis']['claude'].update(colour='blue'),
            '"on": true or false': lambda d: d['clis']['claude'].update(on='yes'),
            'starting with ~/': lambda d: d['clis']['claude'].update(skills='/abs/skills'),
            "no installer support for 'gemini'": lambda d: d['clis'].update(gemini=d['clis']['claude']),
            '"version": 1': lambda d: d.update(version=2),
        }
        for message, change in broken.items():
            with self.subTest(message), self.registry(change), self.assertRaisesRegex(ValueError, message):
                installer.clis()

    def test_scope_and_switches(self):
        with self.registry(lambda d: d['clis']['agy'].update(on=False)):
            self.assertEqual(installer.scope('all'), ('claude', 'codex', 'pi', 'agy'))
            self.assertEqual(installer.scope('pi'), ('pi',))
            with self.assertRaisesRegex(ValueError, 'unknown target'):
                installer.scope('gemini')
            self.assertEqual(installer.split(installer.scope('all')), (('claude', 'codex', 'pi'), ('agy',)))

    def test_a_folder_override_the_registry_ignores_is_reported(self):
        with patch.dict(os.environ, {'CODEX_HOME': str(self.home / 'elsewhere'), 'CLAUDE_CONFIG_DIR': '',
                                     'PI_CODING_AGENT_DIR': str(self.home / '.pi/agent')}):
            warnings = installer.check(self.home)
        self.assertEqual(len(warnings), 1)
        self.assertIn('CODEX_HOME', warnings[0])

    def test_zkfy_dir_from_env_then_binding(self):
        with patch.dict(os.environ, {'ZKFY_DIR': ''}):
            self.assertIsNone(installer.zkfy_dir(self.home))
            self.file(installer.ZKFY_BINDING, json.dumps({'tool': '/opt/zkfy/scripts/knowledge.py'}))
            self.assertEqual(installer.zkfy_dir(self.home), Path('/opt/zkfy'))
        with patch.dict(os.environ, {'ZKFY_DIR': str(self.home)}):
            self.assertEqual(installer.zkfy_dir(self.home), self.home)

    def test_finish_reports_changes_or_the_error(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(installer.finish('step', lambda: 2), 0)
            self.assertEqual(installer.finish('step', lambda: installer.edit(self.home, bytes)), 1)
        self.assertEqual(out.getvalue(), 'step: 2 changes\n')
        self.assertIn('step: Not a file', err.getvalue())


if __name__ == '__main__':
    unittest.main()
