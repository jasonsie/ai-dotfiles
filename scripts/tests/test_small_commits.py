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

    def test_the_heredoc_message_and_computed_ones(self):
        (commit,) = sc.commits_in(HEREDOC)
        self.assertEqual(sc.message_of(commit, '.').splitlines()[0], 'fix(daily-log): keep one entry per project')
        self.assertIn('Verified: unittest 3 passed', sc.message_of(commit, '.'))
        (computed,) = sc.commits_in('git commit -m "$(printf "x")"')
        self.assertIsNone(sc.message_of(computed, '.'))

    def test_the_override_is_read_from_the_command_line(self):
        self.assertTrue(sc.OVERRIDE_SET.search('ALLOW_LARGE_COMMIT="a vendored file" git commit -m x'))
        self.assertTrue(sc.OVERRIDE_SET.search('export ALLOW_LARGE_COMMIT=why; git commit'))
        self.assertFalse(sc.OVERRIDE_SET.search('echo $ALLOW_LARGE_COMMIT; git commit'))

    def test_message_problems(self):
        self.assertEqual(sc.message_problems(GOOD, [], large=False), [])
        self.assertEqual(sc.message_problems('feat(x): add\n\nWhy: a\nScope: b', ['Verified=none'], False), [])
        problems = sc.message_problems('Add the thing', [], large=True)
        self.assertEqual(len(problems), 2)
        self.assertIn('type(scope): outcome', problems[0])
        self.assertIn('Why:, Scope:, Verified:, Large-commit:', problems[1])
        (long,) = sc.message_problems('feat(x): ' + 'a' * 70 + '\n\nWhy: a\nScope: b\nVerified: c', [], False)
        self.assertIn('79 characters', long)
        (part,) = sc.message_problems(GOOD + '\nPart: two', [], False)
        self.assertIn('n/m', part)
        (unknown,) = sc.message_problems('wip(x): thing\n\nWhy: a\nScope: b\nVerified: c', [], False)
        self.assertIn('types:', unknown)


class Repo(unittest.TestCase):
    """A temp repo with one commit, hook state of its own, and each CLI's hook input."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='small commits 空間 ')
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        self.repo = base / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'config', 'user.email', 't@example.com')
        git(self.repo, 'config', 'user.name', 'T')
        self.write('a.txt', 'one\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-q', '-m', 'init')
        patcher = patch.dict(os.environ, {sc.ENV: str(base / 'state')})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, text=None, lines=0):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text is not None else ''.join(f'line {n}\n' for n in range(lines)))
        return path

    def stage(self, *names):
        git(self.repo, 'add', '-A', *names)

    def hook(self, cli, command, session='s1', cwd=None):
        """The rendered reply to `command` run by `cli` in this repo."""
        cwd = str(cwd or self.repo)
        if cli == 'agy':
            data = {'conversationId': session, 'workspacePaths': [cwd],
                    'toolCall': {'name': 'run_command', 'args': {'CommandLine': command, 'Cwd': cwd}}}
        else:
            tool = 'Bash' if cli in ('claude', 'codex') else 'bash'
            data = {'session_id': session, 'cwd': cwd, 'tool_name': tool, 'tool_input': {'command': command}}
        return sc.answer(cli, 'pre')(data)

    def denied(self, reply, cli='claude'):
        """The reason a reply blocks with, or None when it lets the call run."""
        if reply is None:
            return None
        if cli in ('claude', 'codex'):
            out = reply['hookSpecificOutput']
            return out.get('permissionDecisionReason') if out.get('permissionDecision') == 'deny' else None
        if cli == 'agy':
            return reply.get('reason') if reply.get('decision') == 'deny' else None
        return reply.get('reason') if reply.get('block') else None

    def note(self, reply):
        return (reply or {}).get('hookSpecificOutput', {}).get('additionalContext')

    def measure(self, *args):
        commit = sc.Commit()
        sc.commit_options(commit, list(args), 0)
        return sc.measure(commit, self.repo)


class MeasureTest(Repo):
    def test_staged_all_paths_and_amend(self):
        self.write('a.txt', 'two\n')      # 1 added, 1 deleted; not staged
        self.write('b.py', lines=10)     # staged
        self.stage('b.py')
        self.assertEqual((self.measure().lines, self.measure().files), (10, (('b.py', 10),)))
        self.assertEqual(self.measure('-a').lines, 12)
        self.assertEqual(self.measure('a.txt').files, (('a.txt', 2),))
        self.assertEqual(self.measure('-i', 'a.txt').lines, 12)
        self.assertEqual(self.measure('-o', 'b.py').lines, 10)
        git(self.repo, 'commit', '-q', '-m', 'b')
        self.write('c.py', lines=5)
        self.stage('c.py')
        self.assertEqual(self.measure('--amend').lines, 15)  # the amended commit holds b.py and c.py
        self.assertEqual(self.measure('--amend', '-a').lines, 17)

    def test_what_is_left_out(self):
        self.write('uv.lock', lines=400)
        self.write('package-lock.json', lines=400)
        self.write('gen/out.md', lines=400)
        self.write('vendor/big.js', lines=400)
        self.write('pic.png', '\x89PNG\x00\x01\x02\n')
        self.write('.gitattributes', 'gen/** linguist-generated\nvendor/* -diff\n')
        self.write('b.py', lines=3)
        self.stage()
        size = self.measure()
        self.assertEqual(size.files, (('b.py', 3), ('.gitattributes', 2)))
        self.assertEqual(size.left_out, ('gen/out.md', 'package-lock.json', 'uv.lock', 'vendor/big.js', 'pic.png'))

    def test_a_rename_counts_nothing_and_a_fresh_repo_has_a_base(self):
        git(self.repo, 'mv', 'a.txt', 'renamed.txt')
        self.assertEqual(self.measure().files, (('renamed.txt', 0),))
        fresh = self.repo.parent / 'fresh'
        fresh.mkdir()
        git(fresh, 'init', '-q')
        (fresh / 'x.py').write_text('a\nb\n')
        git(fresh, 'add', '.')
        commit = sc.Commit()
        self.assertEqual(sc.measure(commit, fresh).lines, 2)
        commit.all = True
        self.assertEqual(sc.measure(commit, fresh).lines, 2)
