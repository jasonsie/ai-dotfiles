"""run_tests: one suite over scripts/tests and every features/*/tests, found by glob.

Run: python3 -m unittest discover -s scripts/tests -p 'test_run_tests.py' -v
"""
from pathlib import Path
import tempfile
import unittest

from support import ROOT, load

runner = load('run_tests.py')

PASSING = 'import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n'


def write(path, text=PASSING):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class RunTestsTest(unittest.TestCase):
    # Module names differ per test: discovery keeps each in sys.modules, and a name found in a
    # second temporary folder would be refused as imported from the wrong path.
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_the_repo_reaches_every_tests_folder_under_features(self):
        found = runner.test_folders(ROOT)
        self.assertEqual(found[0], ROOT / 'scripts/tests')
        self.assertEqual(found[1:], sorted((ROOT / 'features').glob('*/tests')))

    def test_a_tests_folder_of_a_new_feature_is_run_with_no_list_to_edit(self):
        write(self.root / 'scripts/tests/test_a.py')
        write(self.root / 'features/one-feature/tests/test_b.py')
        write(self.root / 'features/two/tests/test_c.py')
        self.assertEqual([p.relative_to(self.root).as_posix() for p in runner.test_folders(self.root)],
                         ['scripts/tests', 'features/one-feature/tests', 'features/two/tests'])
        self.assertEqual(runner.suite(self.root).countTestCases(), 3)

    def test_no_features_folder_is_only_scripts_tests(self):
        write(self.root / 'scripts/tests/test_d.py')
        self.assertEqual(runner.suite(self.root).countTestCases(), 1)

    def test_two_modules_with_one_name_are_refused(self):
        write(self.root / 'scripts/tests/test_same.py')
        write(self.root / 'features/x/tests/test_same.py')
        with self.assertRaisesRegex(ValueError, 'two test modules named test_same'):
            runner.suite(self.root)

    def test_the_pattern_picks_the_files(self):
        write(self.root / 'scripts/tests/test_e.py')
        write(self.root / 'features/x/tests/test_f.py')
        self.assertEqual(runner.suite(self.root, 'test_f.py').countTestCases(), 1)


if __name__ == '__main__':
    unittest.main()
