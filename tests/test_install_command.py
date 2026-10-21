from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('command', ROOT / 'scripts/install-command.py')
command = importlib.util.module_from_spec(spec)
spec.loader.exec_module(command)


class InstallCommandTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='command 空間 ')
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.target = self.root / 'repo/scripts/ai-dotfiles'
        self.target.parent.mkdir(parents=True)
        self.target.write_text('#!/bin/sh\n')
        self.link = self.home / command.LINK

    def tearDown(self):
        self.temp.cleanup()

    def install(self, apply=False, uninstall=False, target=None, path_env=''):
        out = io.StringIO()
        with redirect_stdout(out):
            count = command.install(self.home, target or self.target, apply, uninstall, path_env)
        self.output = out.getvalue()
        return count

    def test_dry_run_then_apply_links_once(self):
        self.assertEqual(self.install(), 1)
        self.assertEqual(list(self.home.iterdir()), [])
        self.install(apply=True)
        self.assertEqual(os.readlink(self.link), str(self.target))
        receipt = json.loads((self.home / command.RECEIPT).read_text())
        self.assertEqual(receipt['target'], str(self.target))
        self.assertEqual(self.install(), 0)

    def test_path_hint_only_when_folder_missing_from_path(self):
        self.install()
        self.assertIn('Hint: add', self.output)
        self.install(path_env=f'/usr/bin{os.pathsep}{self.link.parent}/')
        self.assertNotIn('Hint', self.output)

    def test_refuses_an_entry_it_did_not_create(self):
        self.link.parent.mkdir(parents=True)
        self.link.write_text('mine\n')
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(apply=True)
        self.link.unlink()
        self.link.symlink_to(self.root / 'elsewhere')
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(apply=True)

    def test_moved_repo_replaces_its_own_dangling_link(self):
        self.install(apply=True)
        moved = self.root / 'moved/scripts/ai-dotfiles'
        moved.parent.mkdir(parents=True)
        self.target.rename(moved)
        self.assertEqual(self.install(apply=True, target=moved), 1)
        self.assertEqual(os.readlink(self.link), str(moved))

    def test_uninstall_removes_only_its_link(self):
        self.assertEqual(self.install(uninstall=True), 0)  # nothing recorded
        self.install(apply=True)
        self.assertEqual(self.install(uninstall=True), 1)
        self.assertTrue(self.link.is_symlink())  # dry-run kept it
        self.install(apply=True, uninstall=True)
        self.assertFalse(self.link.is_symlink())
        self.assertFalse((self.home / command.RECEIPT).exists())
        self.assertEqual(self.install(uninstall=True), 0)

    def test_uninstall_leaves_a_link_the_user_changed(self):
        self.install(apply=True)
        self.link.unlink()
        self.link.symlink_to(self.root / 'elsewhere')
        self.install(apply=True, uninstall=True)
        self.assertEqual(os.readlink(self.link), str(self.root / 'elsewhere'))
        self.assertFalse((self.home / command.RECEIPT).exists())

    def test_failed_receipt_restores_the_link(self):
        with patch.object(command, 'write_receipt', side_effect=OSError('injected')), self.assertRaises(OSError):
            self.install(apply=True)
        self.assertFalse(self.link.is_symlink())


if __name__ == '__main__':
    unittest.main()
