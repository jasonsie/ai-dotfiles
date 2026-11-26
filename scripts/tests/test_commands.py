"""lib/commands.py: `ai-dotfiles <command>` runs what a feature's declaration adds, and --help prints from them.

Run: python3 -m unittest discover -s scripts/tests -p 'test_commands.py' -v
"""
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from support import ROOT

sys.path.insert(0, str(ROOT / 'lib'))
import commands  # noqa: E402
import features  # noqa: E402

SCRIPT = 'import sys\nprint("ran", *sys.argv[1:])\n'


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='commands 空間 ')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.declare('tools', {'hello': {'run': 'hello.py', 'help': 'says hello', 'usage': '[name]'},
                               'tool push': {'run': 'push.py', 'help': 'pushes'},
                               'tool reviewer': {'run': 'review.py', 'args': ['reviewer'], 'help': 'the reviewer'}})

    def declare(self, name, commands_, top='skills'):
        folder = self.root / top / name
        folder.mkdir(parents=True)
        for script in {entry['run'] for entry in commands_.values()}:
            (folder / script).write_text(SCRIPT)
        (folder / features.DECLARATION).write_text(json.dumps({'version': 1, 'cloud': False, 'commands': commands_}))

    def main(self, *argv):
        """(status, stdout, stderr, what would have been executed)."""
        out, err, launched = io.StringIO(), io.StringIO(), []
        status = commands.main(list(argv), root=self.root, stdout=out, stderr=err,
                               execute=lambda program, args: launched.append((program, args)))
        return status, out.getvalue(), err.getvalue(), launched


class RunTest(Fixture):
    def test_a_command_runs_its_script_with_the_rest_of_the_line(self):
        status, _, _, launched = self.main('hello', 'a', '--b')
        script = self.root / 'skills/tools/hello.py'
        self.assertEqual((status, launched), (0, [(sys.executable, [sys.executable, str(script), 'a', '--b'])]))

    def test_a_step_runs_with_its_fixed_words_first(self):
        _, _, _, launched = self.main('tool', 'reviewer', '--unset')
        script = self.root / 'skills/tools/review.py'
        self.assertEqual(launched, [(sys.executable, [sys.executable, str(script), 'reviewer', '--unset'])])

    def test_a_flag_after_the_name_goes_to_the_script(self):
        _, out, _, launched = self.main('hello', '--help')
        self.assertEqual((out, launched[0][1][-1]), ('', '--help'))

    def test_a_command_still_runs_after_its_folder_moves(self):
        before = self.main('tool', 'push', 'x')
        (self.root / 'features').mkdir()
        shutil.move(str(self.root / 'skills/tools'), str(self.root / 'features/tools'))
        after = self.main('tool', 'push', 'x')
        self.assertEqual(before[0], after[0])
        self.assertEqual(Path(after[3][0][1][1]), self.root / 'features/tools/push.py')
        self.assertEqual(after[3][0][1][2:], ['x'])

    def test_a_command_that_does_not_exist_says_so(self):
        status, out, err, launched = self.main('bogus')
        self.assertEqual((status, out, launched), (1, '', []))
        self.assertIn('[ERR] Unknown command: bogus', err)
        self.assertIn('ai-dotfiles hello [name]', err)  # and the usage

    def test_a_step_that_does_not_exist_names_the_steps(self):
        for argv, got in ((('tool', 'zap'), 'zap'), (('tool',), '')):
            status, _, err, launched = self.main(*argv)
            self.assertEqual((status, launched), (1, []))
            self.assertIn(f'[ERR] ai-dotfiles tool <step>: push, reviewer; got: {got}', err)

    def test_a_declaration_that_does_not_check_stops_it_and_names_the_file(self):
        (self.root / 'skills/tools/feature.json').write_text('{"version": 1, "cloud": false, "oops": 1}')
        status, _, err, launched = self.main('hello')
        self.assertEqual((status, launched), (1, []))
        self.assertIn('skills/tools/feature.json: unknown key "oops"', err)


class HelpTest(Fixture):
    def test_help_lists_each_declared_command_after_the_doors_own(self):
        for flag in ('--help', '-h', 'help'):
            status, out, err, launched = self.main(flag)
            self.assertEqual((status, err, launched), (0, '', []), flag)
        lines = out.splitlines()
        names = [line.split()[1] for line in lines if line.startswith('  ai-dotfiles ')]
        self.assertEqual(names, ['[install]', 'update', 'uninstall', 'check', 'statusline', 'hook',
                                 'hello', 'tool', 'tool'])  # the door's own, then the declared by name
        self.assertRegex(out, r'ai-dotfiles hello \[name\] +says hello')
        self.assertRegex(out, r'ai-dotfiles tool push +pushes')
        self.assertRegex(out, r'ai-dotfiles tool reviewer +the reviewer')

    def test_this_repos_help_lists_every_command_its_declarations_make(self):
        _, out, _, _ = self.run_repo('--help')
        declared = [name for feature in features.find() for name in feature.commands]
        self.assertTrue(declared)
        for name in declared:
            self.assertRegex(out, rf'(?m)^  ai-dotfiles {name}\b', name)

    def run_repo(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        status = commands.main(list(argv), stdout=out, stderr=err)
        return status, out.getvalue(), err.getvalue(), None

    def test_the_doors_own_commands_are_the_ones_the_wrapper_runs(self):
        wrapper = (ROOT / 'scripts/ai-dotfiles').read_text()
        runs = {word for line in wrapper.splitlines() if line.startswith('  ') and ')' in line
                for word in line.split(')')[0].replace('|', ' ').split() if word.isalpha()}
        own = {name for name, _, _ in commands.OWN}
        self.assertEqual(own, own & runs)
        self.assertEqual(own, own & set(features.OWN_COMMANDS))


if __name__ == '__main__':
    unittest.main()
