"""scripts/ai-dotfiles runs a feature's declared command wherever its folder sits, and prints --help from them.

Run: python3 -m unittest discover -s scripts/tests -p 'test_wrapper_commands.py' -v
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import ROOT

sys.path.insert(0, str(ROOT / 'lib'))
import features  # noqa: E402

SCRIPT = 'import sys\nprint("ran", *sys.argv[1:])\n'


class WrapperTest(unittest.TestCase):
    """scripts/ai-dotfiles on a working copy that holds one fixture feature."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='wrapper 空間 ')
        self.addCleanup(temp.cleanup)
        self.checkout = Path(temp.name) / 'checkout'
        for folder in ('scripts', 'lib'):
            shutil.copytree(ROOT / folder, self.checkout / folder,
                            ignore=shutil.ignore_patterns('__pycache__', 'tests'))
        self.env = {**os.environ, 'HOME': temp.name, 'PATH': '/usr/bin:/bin', 'PYTHON': sys.executable}

    def feature(self, top):
        folder = self.checkout / top / 'greeter'
        folder.mkdir(parents=True)
        (folder / 'greet.py').write_text(SCRIPT)
        (folder / features.DECLARATION).write_text(json.dumps(
            {'version': 1, 'cloud': False, 'commands': {'greet': {'run': 'greet.py', 'help': 'greets'}}}))
        return folder

    def run_wrapper(self, *argv):
        return subprocess.run([str(self.checkout / 'scripts/ai-dotfiles'), *argv], env=self.env,
                              capture_output=True, text=True)

    def test_a_fixture_command_runs_and_runs_again_after_its_folder_moves(self):
        folder = self.feature('skills')
        first = self.run_wrapper('greet', 'x', 'y')
        self.assertEqual((first.returncode, first.stdout), (0, 'ran x y\n'), first.stderr)
        self.assertRegex(self.run_wrapper('--help').stdout, r'ai-dotfiles greet +greets')
        (self.checkout / 'features').mkdir()
        shutil.move(str(folder), str(self.checkout / 'features/greeter'))
        second = self.run_wrapper('greet', 'x', 'y')
        self.assertEqual((second.returncode, second.stdout), (0, 'ran x y\n'), second.stderr)

    def test_the_command_list_is_not_written_in_the_wrapper(self):
        text = (self.checkout / 'scripts/ai-dotfiles').read_text()
        for name in ('worktree', 'commit', 'ship-pr', 'approve'):
            self.assertNotIn(name, text)

    def test_an_unknown_command_exits_1(self):
        bad = self.run_wrapper('bogus')
        self.assertEqual(bad.returncode, 1)
        self.assertIn('Unknown command', bad.stderr)

    def test_help_prints_on_the_systems_older_python_too(self):
        if not Path('/usr/bin/python3').exists():
            self.skipTest('no /usr/bin/python3')
        shown = subprocess.run([str(self.checkout / 'scripts/ai-dotfiles'), '--help'],
                               env={k: v for k, v in self.env.items() if k != 'PYTHON'},
                               capture_output=True, text=True)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn('ai-dotfiles update', shown.stdout)


if __name__ == '__main__':
    unittest.main()
