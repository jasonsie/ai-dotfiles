import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import ROOT


class EntrypointsTest(unittest.TestCase):
    """install.sh, uninstall.sh and the ai-dotfiles wrapper against an isolated home."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='entrypoints 空間 ')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / 'home'
        self.home.mkdir()
        # No CLI on PATH, so the MCP step adds nothing; no vault, so knowledge is skipped.
        self.env = {**os.environ, 'HOME': str(self.home), 'PATH': '/usr/bin:/bin', 'PYTHON': sys.executable}
        for key in ('ZKFY_DIR', 'ZKFY_VAULT'):
            self.env.pop(key, None)

    def run_script(self, *args, script='scripts/install.sh'):
        result = subprocess.run(['bash', str(ROOT / script), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def into_repo(self):
        """Links into the repo and files naming it, outside the installers' own state."""
        found = []
        for path in self.home.rglob('*'):
            if '.local/state' in str(path):
                continue
            if path.is_symlink():
                if str(ROOT) in os.readlink(path):
                    found.append(path)
            elif path.is_file() and str(ROOT) in path.read_text(errors='ignore'):
                found.append(path)
        return found

    def test_install_writes_by_default_and_uninstall_leaves_nothing_pointing_into_the_repo(self):
        self.run_script('--dry-run')
        self.assertEqual(list(self.home.iterdir()), [])
        out = self.run_script()
        self.assertIn('Hint: add', out)  # ~/.local/bin is not on this PATH
        command = self.home / '.local/bin/ai-dotfiles'
        self.assertEqual(Path(os.readlink(command)), ROOT / 'scripts/ai-dotfiles')
        self.assertTrue((self.home / '.claude/CLAUDE.md').is_symlink())
        self.assertNotIn(' 1 changes', self.run_script('--dry-run'))
        self.assertTrue(self.into_repo())
        self.run_script('--dry-run', script='scripts/uninstall.sh')
        self.assertTrue(command.is_symlink())
        out = self.run_script(script='scripts/uninstall.sh')
        self.assertIn('Left in place:', out)  # managed settings keys stay
        self.assertEqual(self.into_repo(), [])
        self.assertFalse(command.exists() or command.is_symlink())

    def test_switches_in_ai_clis_decide_what_is_installed(self):
        checkout = Path(self.temp.name).resolve() / 'checkout'
        for folder in ('scripts', 'config', 'skills'):
            shutil.copytree(ROOT / folder, checkout / folder, ignore=shutil.ignore_patterns('__pycache__'))
        registry = checkout / 'config/ai-clis.json'

        def install(agy_on):
            data = json.loads(registry.read_text())
            data['clis']['agy']['on'] = agy_on
            registry.write_text(json.dumps(data, indent=2))
            result = subprocess.run(['bash', str(checkout / 'scripts/install.sh')], env=self.env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        install(agy_on=False)
        self.assertFalse((self.home / '.gemini').exists())  # nothing for a CLI switched off
        self.assertTrue((self.home / '.claude/CLAUDE.md').is_symlink())
        install(agy_on=True)
        self.assertTrue((self.home / '.gemini/GEMINI.md').is_symlink())
        self.assertTrue(any((self.home / '.gemini/config/skills').iterdir()))
        install(agy_on=False)
        self.assertFalse((self.home / '.gemini/GEMINI.md').is_symlink())
        self.assertEqual(list((self.home / '.gemini/config/skills').iterdir()), [])
        self.assertTrue((self.home / '.claude/CLAUDE.md').is_symlink())

    def test_wrapper_dispatches_through_its_link(self):
        self.run_script()
        command = self.home / '.local/bin/ai-dotfiles'
        run = lambda *a: subprocess.run([str(command), *a], env=self.env, capture_output=True, text=True)  # noqa: E731
        self.assertIn('ai-dotfiles update', run('--help').stdout)
        self.assertIn('Preview only', run('--dry-run').stdout)  # flags alone mean install
        self.assertIn('Preview only', run('uninstall', '--dry-run').stdout)
        bad = run('bogus')
        self.assertEqual(bad.returncode, 1)
        self.assertIn('Unknown command', bad.stderr)

    def test_update_refuses_off_main_or_with_a_dirty_tree(self):
        clone = Path(self.temp.name) / 'clone'
        subprocess.run(['git', 'clone', '-q', str(ROOT), str(clone)], check=True)
        subprocess.run(['git', '-C', str(clone), 'switch', '-q', '-c', 'topic'], check=True)
        # Run the working copy's install.sh inside the clone, so the guard sees the clone.
        target = clone / 'scripts/install.sh'
        target.write_text((ROOT / 'scripts/install.sh').read_text())
        result = subprocess.run(['bash', str(target), '--update', '--dry-run'], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('pulls main only', result.stderr)
        subprocess.run(['git', '-C', str(clone), 'switch', '-q', '-C', 'main'], check=True)
        (clone / 'stray.txt').write_text('uncommitted\n')
        result = subprocess.run(['bash', str(target), '--update', '--dry-run'], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('clean tree', result.stderr)

    def test_update_fast_forwards_then_installs_from_the_pulled_copy(self):
        git = lambda repo, *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True)  # noqa: E731
        upstream = Path(self.temp.name) / 'upstream'
        subprocess.run(['git', 'clone', '-q', str(ROOT), str(upstream)], check=True)
        git(upstream, 'switch', '-q', '-C', 'main')
        shutil.rmtree(upstream / 'tools', ignore_errors=True)  # config/ before it had that name
        for folder in ('scripts', 'config'):
            shutil.rmtree(upstream / folder, ignore_errors=True)
            shutil.copytree(ROOT / folder, upstream / folder, ignore=shutil.ignore_patterns('__pycache__'))
        git(upstream, 'add', '-A')
        git(upstream, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'working copy')
        work = Path(self.temp.name).resolve() / 'work'
        subprocess.run(['git', 'clone', '-q', str(upstream), str(work)], check=True)
        (upstream / 'NEW.txt').write_text('new\n')
        git(upstream, 'add', 'NEW.txt')
        git(upstream, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'incoming change')
        result = subprocess.run(['bash', str(work / 'scripts/install.sh'), '--update'], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('incoming change', result.stdout)
        self.assertTrue((work / 'NEW.txt').is_file())
        self.assertIn('Done.', result.stdout)
        self.assertEqual(Path(os.readlink(self.home / '.local/bin/ai-dotfiles')), work / 'scripts/ai-dotfiles')


if __name__ == '__main__':
    unittest.main()
