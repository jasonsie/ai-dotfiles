import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import ROOT
import installer

LIVE = installer.live_root(ROOT)  # where installs link: the main checkout when the suite runs in a worktree


class EntrypointsTest(unittest.TestCase):
    """install.sh, uninstall.sh and the ai-dotfiles wrapper against an isolated home."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='entrypoints 空間 ')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / 'home'
        self.home.mkdir()
        # No CLI on PATH, so the MCP step adds nothing.
        self.env = {**os.environ, 'HOME': str(self.home), 'PATH': '/usr/bin:/bin', 'PYTHON': sys.executable}

    def run_script(self, *args, script='scripts/install.sh', root=ROOT):
        result = subprocess.run(['bash', str(root / script), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def working_copy(self):
        """scripts/, lib/, config/, skills/ and features/ copied outside git, so an install there links the copy itself
        (in a worktree, an install from ROOT links the main checkout, which runs other code)."""
        checkout = Path(self.temp.name).resolve() / 'checkout'
        for folder in ('scripts', 'lib', 'config', 'skills', 'features'):
            shutil.copytree(ROOT / folder, checkout / folder, ignore=shutil.ignore_patterns('__pycache__'))
        return checkout

    def into_repo(self):
        """Links into the repo and files naming it, outside the installers' own state."""
        found = []
        for path in self.home.rglob('*'):
            if '.local/state' in str(path):
                continue
            if path.is_symlink():
                if str(LIVE) in os.readlink(path):
                    found.append(path)
            elif path.is_file() and str(LIVE) in path.read_text(errors='ignore'):
                found.append(path)
        return found

    def test_a_cloud_install_sets_up_claude_alone_without_plugins_or_launchd(self):
        """scripts/cloud/setup.sh runs install.sh --cloud on a cloud session's VM: Claude's rules, the
        skills a cloud session can run and the commit gate; no other CLI, plugin manager or launchd."""
        checkout = self.working_copy()
        out = self.run_script('--cloud', '--target=codex', root=checkout)  # --cloud means Claude, whatever follows
        self.assertIn('plugins: skipped in a cloud session', out)
        self.assertIn('launchd: skipped in a cloud session', out)
        self.assertEqual(Path(os.readlink(self.home / '.claude/CLAUDE.md')), checkout / 'config/global-agents.md')
        local = json.loads((checkout / 'config/cloud.json').read_text())['local_only']
        names = {p.name for p in (self.home / '.claude/skills').iterdir()}
        self.assertIn('grilling', names)
        self.assertEqual(names & set(local), set())
        hooks = json.loads((self.home / '.claude/settings.json').read_text())['hooks']
        self.assertEqual(list(hooks), ['PreToolUse'])  # the commit gate's event alone: no guard, no Herdr title
        self.assertEqual(hooks['PreToolUse'][0]['matcher'], 'Bash')
        self.assertIn('ai-dotfiles hook pre --cli claude', hooks['PreToolUse'][0]['hooks'][0]['command'])
        for other in ('.codex', '.pi', '.gemini', '.agents', 'Library'):
            self.assertFalse((self.home / other).exists(), other)

    def test_install_writes_by_default_and_uninstall_leaves_nothing_pointing_into_the_repo(self):
        self.run_script('--dry-run')
        self.assertEqual(list(self.home.iterdir()), [])
        out = self.run_script()
        self.assertIn('Hint: add', out)  # ~/.local/bin is not on this PATH
        command = self.home / '.local/bin/ai-dotfiles'
        self.assertEqual(Path(os.readlink(command)), LIVE / 'scripts/ai-dotfiles')
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
        checkout = self.working_copy()
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
        checkout = self.working_copy()
        self.run_script(root=checkout)
        command = self.home / '.local/bin/ai-dotfiles'
        self.assertEqual(Path(os.readlink(command)), checkout / 'scripts/ai-dotfiles')  # this code, not main's
        run = lambda *a: subprocess.run([str(command), *a], env=self.env, capture_output=True, text=True)  # noqa: E731
        self.assertIn('ai-dotfiles update', run('--help').stdout)
        self.assertIn('Preview only', run('--dry-run').stdout)  # flags alone mean install
        self.assertIn('Preview only', run('uninstall', '--dry-run').stdout)
        shown = subprocess.run([str(command), 'statusline'], env=self.env, capture_output=True, text=True,
                               input='{"model": {"display_name": "Opus"}, "version": "1", "cwd": "/"}')
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn('Opus', shown.stdout)
        bare = {k: v for k, v in self.env.items() if k not in ('HOME', 'PYTHON')}  # the door falls back to python3
        for env in (self.env, {**bare, 'PATH': f'{Path(sys.executable).parent}:{bare["PATH"]}'}):
            door = subprocess.run([str(command), 'hook', 'stop', '--cli', 'codex'], env=env, capture_output=True,
                                  text=True, input='{}')  # what the hook entries run
            self.assertEqual((door.returncode, door.stdout), (0, '{}\n'), door.stderr)
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
        (clone / 'lib/install/run.py').write_text((ROOT / 'lib/install/run.py').read_text())  # the runner install.sh calls
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
        for folder in ('scripts', 'lib', 'config'):
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

    def test_a_linked_worktree_installs_into_its_main_checkout(self):
        """ship-pr runs the Verify block in a worktree it then deletes, so nothing live may name the worktree."""
        git = lambda repo, *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True)  # noqa: E731
        main = Path(self.temp.name).resolve() / 'main'
        subprocess.run(['git', 'clone', '-q', str(ROOT), str(main)], check=True)
        for folder in ('scripts', 'lib', 'config', 'skills', 'features'):  # the working copy, committed so the worktree has it
            shutil.rmtree(main / folder, ignore_errors=True)
            shutil.copytree(ROOT / folder, main / folder, ignore=shutil.ignore_patterns('__pycache__'))
        git(main, 'add', '-A')
        git(main, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'working copy')
        linked = main / '.claude/worktrees/fix-x'
        git(main, 'worktree', 'add', '-q', '--detach', str(linked))

        def run(checkout, *args):
            done = subprocess.run(['bash', str(checkout / 'scripts/install.sh'), *args], env=self.env,
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            return done.stdout

        run(linked)
        named = [path for path in self.home.rglob('*') if '.local/state' not in str(path) and str(linked) in (
            os.readlink(path) if path.is_symlink() else path.read_text(errors='ignore') if path.is_file() else '')]
        self.assertEqual(named, [])
        self.assertEqual(Path(os.readlink(self.home / '.local/bin/ai-dotfiles')), main / 'scripts/ai-dotfiles')
        for checkout in (linked, main):
            self.assertNotRegex(run(checkout, '--dry-run'), r'(?m)(^|: )[1-9][0-9]* changes')


if __name__ == '__main__':
    unittest.main()
