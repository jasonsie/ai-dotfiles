"""small-commits: every `git commit` an agent runs stays small, one concern, and says why.

Run: python3 -m unittest discover -s scripts/tests -p 'test_small_commits.py' -v
"""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT

SCRIPT = ROOT / 'skills/small-commits/scripts/small_commits.py'
SPEC = importlib.util.spec_from_file_location('small_commits', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sc = importlib.util.module_from_spec(SPEC)
sys.modules['small_commits'] = sc  # dataclasses resolve their annotations through sys.modules
SPEC.loader.exec_module(sc)

GOOD = 'feat(x): add the thing\n\nWhy: the user asked\nScope: x\nVerified: none'
HEREDOC = '''git commit -m "$(cat <<'EOF'
fix(daily-log): keep one entry per project

A longer body here.

Why: two entries confused the pass
Scope: daily-log writer
Verified: unittest 3 passed
EOF
)"'''


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class ParsingTest(unittest.TestCase):
    def test_finds_each_git_commit_and_its_options(self):
        (one,) = sc.commits_in('git add -A && git commit -am "x: y" -F msg --trailer "Why: z" && git push')
        self.assertEqual((one.all, one.messages, one.file, one.trailers, one.where), (True, ['x: y'], 'msg', ['Why: z'], ''))
        (two,) = sc.commits_in('cd sub && git -C deeper commit --amend --no-edit -o a.py -- b.py -c.py')
        self.assertEqual((two.where, two.amend, two.only, two.pathspecs), ('sub/deeper', True, True, ['a.py', 'b.py', '-c.py']))
        (three,) = sc.commits_in('git commit -m"joined" --message=long -mthird 2>&1')
        self.assertEqual((three.messages, three.pathspecs), (['joined', 'long', 'third'], []))
        (four,) = sc.commits_in('git commit --fixup=HEAD~2 -i a.py --squash HEAD')
        self.assertEqual((four.fixup, four.include, four.pathspecs), ('HEAD', True, ['a.py']))
        self.assertEqual(len(sc.commits_in('git commit -m a; git commit -m b')), 2)

    def test_leaves_other_commands_alone(self):
        for command in ('git status && echo "git commit"', 'git log --oneline', 'echo commit', 'git -C x stash'):
            self.assertEqual(sc.commits_in(command), [], command)

    def test_the_override_is_read_from_the_command_line(self):
        self.assertTrue(sc.OVERRIDE_SET.search('ALLOW_LARGE_COMMIT="a vendored file" git commit -m x'))
        self.assertTrue(sc.OVERRIDE_SET.search('export ALLOW_LARGE_COMMIT=why; git commit'))
        self.assertFalse(sc.OVERRIDE_SET.search('echo $ALLOW_LARGE_COMMIT; git commit'))
