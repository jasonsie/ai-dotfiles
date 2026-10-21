import importlib.util
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('skills', ROOT / 'scripts/install-skills.py')
skills = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skills)


class InstallSkillsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skills 空間 ')
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.source = self.root / 'repo/skills'
        for name in ('alpha', 'beta'):
            (self.source / name).mkdir(parents=True)
            (self.source / name / 'SKILL.md').write_text(f'---\nname: {name}\n---\n')
        (self.source / 'notes').mkdir()  # no SKILL.md, so not a skill

    def tearDown(self):
        self.temp.cleanup()

    def install(self, targets=tuple(skills.ROOTS), apply=False, uninstall=False):
        with redirect_stdout(io.StringIO()):
            return skills.install(self.home, targets, self.source, apply, uninstall)

    def links(self):
        found = {}
        for root in skills.ROOTS.values():
            folder = self.home / root
            if folder.is_dir():
                found.update({f'{root}/{p.name}': os.readlink(p) for p in folder.iterdir() if p.is_symlink()})
        return found

    def test_repo_skills_are_valid(self):
        names = skills.repo_skills(skills.SOURCE)
        self.assertIn('grilling', names)
        for name in names:
            text = (skills.SOURCE / name / 'SKILL.md').read_text()
            self.assertTrue(text.startswith(f'---\nname: {name}\n'), name)
            self.assertNotRegex(text, r'/Users/|/opt/homebrew')

    def test_dry_run_then_apply_links_every_root_once(self):
        self.assertEqual(self.install(), 7)  # six links and the receipt
        self.assertEqual(self.links(), {})
        self.assertFalse((self.home / '.local').exists())
        self.install(apply=True)
        self.assertEqual(len(self.links()), 6)
        for root in skills.ROOTS.values():
            self.assertEqual((self.home / root / 'alpha').resolve(), self.source / 'alpha')
            self.assertFalse((self.home / root / 'notes').exists())
        self.assertEqual(self.install(), 0)

    def test_refuses_an_entry_it_did_not_create(self):
        (self.home / '.agents/skills/beta').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(apply=True)
        self.assertEqual(self.links(), {})

    def test_removed_skill_link_goes_but_a_user_change_stays(self):
        self.install(apply=True)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        mine = self.home / '.claude/skills/alpha'
        mine.unlink()
        mine.symlink_to(elsewhere, target_is_directory=True)
        (self.source / 'alpha/SKILL.md').unlink()
        (self.source / 'beta/SKILL.md').unlink()
        self.install(apply=True)
        self.assertEqual(self.links(), {'.claude/skills/alpha': str(elsewhere)})
        self.assertEqual(self.install(), 0)

    def test_target_selection_leaves_other_roots_alone(self):
        self.install(('claude',), apply=True)
        self.assertEqual(sorted(self.links()), ['.claude/skills/alpha', '.claude/skills/beta'])
        self.install(('agy',), apply=True)
        self.assertEqual(len(self.links()), 4)
        self.assertEqual(self.install(('claude', 'agy')), 0)

    def test_uninstall_removes_only_owned_links(self):
        self.install(apply=True)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        mine = self.home / '.claude/skills/alpha'
        mine.unlink()
        mine.symlink_to(elsewhere, target_is_directory=True)
        (self.home / '.agents/skills/user-skill').mkdir()
        self.assertEqual(self.install(uninstall=True), 6)  # five links and the receipt
        self.assertEqual(len(self.links()), 6)  # dry-run removed nothing
        self.install(apply=True, uninstall=True)
        self.assertEqual(self.links(), {'.claude/skills/alpha': str(elsewhere)})
        self.assertTrue((self.home / '.agents/skills/user-skill').is_dir())
        self.assertEqual(self.install(uninstall=True), 0)

    def test_uninstall_target_selection_keeps_other_roots(self):
        self.install(apply=True)
        self.install(('claude',), apply=True, uninstall=True)
        self.assertEqual(len(self.links()), 4)
        self.assertNotIn('.claude/skills/alpha', self.links())
        self.assertEqual(self.install(), 3)  # reinstall relinks claude and records them

    def test_failed_run_restores_links(self):
        original, calls = skills.set_state, 0

        def fail_third(path, wanted):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('injected')
            return original(path, wanted)

        with patch.object(skills, 'set_state', fail_third), self.assertRaises(OSError):
            self.install(apply=True)
        self.assertEqual(self.links(), {})
        self.assertFalse((self.home / skills.RECEIPT).exists())


if __name__ == '__main__':
    unittest.main()
