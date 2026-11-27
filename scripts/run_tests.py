#!/usr/bin/env python3
"""Run every test of this repo as one suite: scripts/tests and each features/<name>/tests.

  run_tests.py [-v] [-p PATTERN]       exit 1 on a failure, 2 on a duplicate module name;
                                       PATTERN (default test_*.py) picks the files

Nothing lists the folders: they are found by glob, so a feature that brings tests is run at once.
Each folder is discovered on its own, as unittest cannot discover across folders that are not
packages (a hyphenated feature folder cannot be one). Two test modules with one name are refused:
they would share one sys.modules entry and one would hide the other.
Python 3.11+, stdlib only.
"""
import argparse
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATTERN = 'test_*.py'


def test_folders(root=ROOT):
    """scripts/tests, then every features/*/tests, in name order."""
    return [root / 'scripts/tests', *sorted(root.glob('features/*/tests'))]


def refuse_duplicates(folders, pattern=DEFAULT_PATTERN):
    """ValueError when two test files in `folders` share a name."""
    seen = {}
    for folder in folders:
        for path in sorted(folder.glob(pattern)):
            if path.name in seen:
                raise ValueError(f'two test modules named {path.stem}: {seen[path.name]} and {path}')
            seen[path.name] = path


def suite(root=ROOT, pattern=DEFAULT_PATTERN):
    """One TestSuite of every folder's tests."""
    folders = test_folders(root)
    refuse_duplicates(folders, pattern)
    # A new loader per folder: a loader remembers the top-level folder of its first discovery.
    return unittest.TestSuite(
        unittest.TestLoader().discover(str(folder), pattern, top_level_dir=str(folder)) for folder in folders)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('-v', '--verbose', action='store_true', help='one line per test')
    parser.add_argument('-p', '--pattern', default=DEFAULT_PATTERN, help='test files to run (default: %(default)s)')
    args = parser.parse_args(argv)
    try:
        tests = suite(pattern=args.pattern)
    except ValueError as error:
        print(f'run_tests: {error}', file=sys.stderr)
        return 2
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(tests)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
