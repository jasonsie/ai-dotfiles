import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from support import CLIS, load, registry, where
import installer

skills = load('install/skills.py')
ROOTS = sorted({where(cli, 'skills') for cli in CLIS})


class InstallSkillsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skills 空間 ')
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.repo = self.root / 'repo'
        for name in ('alpha', 'beta'):
            (self.repo / 'skills' / name).mkdir(parents=True)
            (self.repo / 'skills' / name / 'SKILL.md').write_text(f'---\nname: {name}\n---\n')
        (self.repo / 'skills/notes').mkdir()  # no SKILL.md, so not a skill
        self.command = self.home / skills.COMMAND

    def tearDown(self):
        self.temp.cleanup()

    def install(self, clis=CLIS, apply=False, uninstall=False, zkfy=None, repo=None, path_env=''):
        out = io.StringIO()
        with redirect_stdout(out):
            count = skills.install(self.home, clis, repo or self.repo, zkfy, apply, uninstall, path_env)
        self.output = out.getvalue()
        return count

    def links(self):
        """{path below home: target} of every link in the folders this step writes."""
        found = {}
        for folder in (*ROOTS, '.local/bin'):
            if (self.home / folder).is_dir():
                found.update({str(p.relative_to(self.home)): os.readlink(p)
                              for p in (self.home / folder).iterdir() if p.is_symlink()})
        return found

    def skill_links(self):
        return {path: target for path, target in self.links().items() if '/skills/' in path}

    def zkfy(self):
        zkfy = self.root / 'zkfy'
        (zkfy / 'skills/query').mkdir(parents=True, exist_ok=True)
        (zkfy / 'skills/query/SKILL.md').write_text('---\nname: query\n---\n')
        return zkfy

    def test_repo_skills_are_valid(self):
        names = skills.skills(skills.WORKSPACE / 'skills')
        self.assertIn('grilling', names)
        for name, folder in names.items():
            text = (folder / 'SKILL.md').read_text()
            self.assertTrue(text.startswith(f'---\nname: {name}\n'), name)
            self.assertNotRegex(text, r'/Users/|/opt/homebrew')

    def test_dry_run_then_apply_links_every_root_once(self):
        self.assertEqual(self.install(), 8)  # six skill links, the command, and the receipt
        self.assertEqual(self.links(), {})
        self.assertFalse((self.home / '.local').exists())
        self.install(apply=True)
        self.assertEqual(len(self.skill_links()), 6)
        for root in ROOTS:
            self.assertEqual((self.home / root / 'alpha').resolve(), self.repo / 'skills/alpha')
            self.assertFalse((self.home / root / 'notes').exists())
        self.assertEqual(os.readlink(self.command), str(self.repo / 'scripts/ai-dotfiles'))
        self.assertEqual(self.install(), 0)

    def test_refuses_an_entry_it_did_not_create(self):
        (self.home / '.agents/skills/beta').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(apply=True)
        self.assertEqual(self.links(), {})
        (self.home / '.agents/skills/beta').rmdir()
        self.command.parent.mkdir(parents=True)
        self.command.symlink_to(self.root / 'elsewhere')
        with self.assertRaisesRegex(ValueError, 'refusing'):
            self.install(apply=True)

    def test_removed_skill_link_goes_but_a_user_change_stays(self):
        self.install(apply=True)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        mine = self.home / '.claude/skills/alpha'
        mine.unlink()
        mine.symlink_to(elsewhere, target_is_directory=True)
        (self.repo / 'skills/alpha/SKILL.md').unlink()
        (self.repo / 'skills/beta/SKILL.md').unlink()
        self.install(apply=True)
        self.assertEqual(self.skill_links(), {'.claude/skills/alpha': str(elsewhere)})
        self.assertEqual(self.install(), 0)

    def test_target_selection_leaves_other_roots_alone(self):
        self.install(('claude',), apply=True)
        self.assertEqual(sorted(self.skill_links()), ['.claude/skills/alpha', '.claude/skills/beta'])
        self.install(('codex',), apply=True)  # Codex and Pi share one folder
        self.install(('agy',), apply=True)
        self.assertEqual(len(self.skill_links()), 6)
        self.assertEqual(self.install(('claude', 'pi', 'agy')), 0)

    def test_uninstall_removes_only_owned_links(self):
        self.install(apply=True)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        mine = self.home / '.claude/skills/alpha'
        mine.unlink()
        mine.symlink_to(elsewhere, target_is_directory=True)
        (self.home / '.agents/skills/user-skill').mkdir()
        self.assertEqual(self.install(uninstall=True), 7)  # five skill links, the command, the receipt
        self.assertEqual(len(self.skill_links()), 6)  # dry-run removed nothing
        self.install(apply=True, uninstall=True)
        self.assertEqual(self.links(), {'.claude/skills/alpha': str(elsewhere)})
        self.assertTrue((self.home / '.agents/skills/user-skill').is_dir())
        self.assertEqual(self.install(uninstall=True), 0)

    def test_uninstall_one_cli_keeps_other_roots_and_the_command(self):
        self.install(apply=True)
        self.install(('claude',), apply=True, uninstall=True)
        self.assertEqual(len(self.skill_links()), 4)
        self.assertNotIn('.claude/skills/alpha', self.links())
        self.assertTrue(self.command.is_symlink())  # it serves the other CLIs
        self.assertEqual(self.install(), 3)  # reinstall relinks claude and records them
        self.install(apply=True)
        self.install(apply=True, uninstall=True)
        self.assertEqual(self.links(), {})

    def test_zkfy_query_is_linked_with_the_others(self):
        zkfy = self.root / 'zkfy'
        (zkfy / 'skills/query').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'query skill'):
            self.install(zkfy=zkfy)
        zkfy = self.zkfy()
        (zkfy / 'skills/other').mkdir()  # zkfy's other skills are not shared
        (zkfy / 'skills/other/SKILL.md').write_text('---\nname: other\n---\n')
        self.install(apply=True, zkfy=zkfy)
        for root in ROOTS:
            self.assertEqual(os.readlink(self.home / root / 'query'), str(zkfy / 'skills/query'))
            self.assertFalse((self.home / root / 'other').exists())
        (self.repo / 'skills/query').mkdir()
        (self.repo / 'skills/query/SKILL.md').write_text('---\nname: query\n---\n')
        with self.assertRaisesRegex(ValueError, 'hide'):
            self.install(zkfy=zkfy)

    def test_matching_links_are_adopted_and_the_old_command_receipt_goes(self):
        # As the knowledge step and install-command.py left them before this step linked them.
        zkfy = self.zkfy()
        query = self.home / '.claude/skills/query'
        query.parent.mkdir(parents=True)
        query.symlink_to(zkfy / 'skills/query')
        self.command.parent.mkdir(parents=True)
        self.command.symlink_to(self.repo / 'scripts/ai-dotfiles')
        old = self.home / skills.COMMAND_RECEIPT
        old.parent.mkdir(parents=True)
        old.write_text(json.dumps({'version': 1, 'link': str(self.command), 'target': os.readlink(self.command)}))
        self.assertEqual(self.install(('claude',), apply=True, zkfy=zkfy), 4)  # alpha, beta, both receipts
        owned = json.loads((self.home / skills.RECEIPT).read_text())['links']
        self.assertEqual(owned[str(query)], str(zkfy / 'skills/query'))
        self.assertEqual(owned[str(self.command)], str(self.repo / 'scripts/ai-dotfiles'))
        self.assertFalse(old.exists())
        self.install(apply=True, uninstall=True)
        self.assertEqual(self.links(), {})

    def test_command_path_hint_and_moved_repo(self):
        self.install()
        self.assertIn('Hint: add', self.output)
        self.install(path_env=f'/usr/bin{os.pathsep}{self.command.parent}/')
        self.assertNotIn('Hint', self.output)
        self.install(apply=True)
        moved = self.root / 'moved'
        self.repo.rename(moved)
        self.assertEqual(self.install(('claude',), apply=True, repo=moved), 4)  # alpha, beta, command, receipt
        self.assertEqual(os.readlink(self.command), str(moved / 'scripts/ai-dotfiles'))

    def folder(self, root):
        return sorted(path for path in self.skill_links() if path.startswith(root))

    def test_a_cli_switched_off_loses_its_links_but_a_shared_folder_stays(self):
        self.install(apply=True)
        with patch.object(installer, 'REGISTRY', registry(self.root, agy=False, codex=False)):
            self.install(apply=True)
            self.assertEqual(self.folder('.gemini/'), [])
            self.assertEqual(len(self.folder('.agents/')), 2)  # Pi, still on, reads it too
            self.assertEqual(self.install(), 0)
        with patch.object(installer, 'REGISTRY', registry(self.root, pi=False)):
            self.install(apply=True)
            self.assertEqual(len(self.folder('.agents/')), 2)  # Codex, on again, reads it
            self.install(('codex',), apply=True, uninstall=True)
            self.assertEqual(self.folder('.agents/'), [])  # no CLI that is on reads it now

    def test_uninstalling_one_cli_keeps_a_folder_another_cli_reads(self):
        self.install(apply=True)
        self.install(('codex',), apply=True, uninstall=True)
        self.assertEqual(len(self.folder('.agents/')), 2)  # Pi is on and reads ~/.agents/skills
        self.install(('codex', 'pi'), apply=True, uninstall=True)
        self.assertEqual(self.folder('.agents/'), [])


if __name__ == '__main__':
    unittest.main()
