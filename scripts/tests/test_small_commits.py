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


class HookTest(Repo):
    def test_a_small_well_formed_commit_passes_in_every_cli(self):
        self.write('b.py', lines=10)
        self.stage()
        for cli in sc.agent_hooks.CLIS:
            self.assertIsNone(self.denied(self.hook(cli, f'git commit -m {shlex.quote(GOOD)}'), cli), cli)
        self.assertIsNone(self.hook('claude', 'git status; ls'))

    def test_the_message_is_checked_in_every_cli(self):
        self.write('b.py', lines=10)
        self.stage()
        for cli in sc.agent_hooks.CLIS:
            reason = self.denied(self.hook(cli, 'git commit -m "add b"'), cli)
            self.assertIn('the message needs work', reason, cli)
            self.assertIn('Why:, Scope:, Verified:', reason)
        # Several -m are paragraphs; git reads trailers from the last one only.
        reason = self.denied(self.hook('claude', "git commit -m 'feat(x): add' -m 'Why: a' -m 'Scope: b'"))
        self.assertIn('missing trailers Why:, Verified:', reason)
        reason = self.denied(self.hook('claude', "git commit -m 'feat(x): add' -m 'Why: a\nScope: b'"))
        self.assertIn('missing trailer Verified:', reason)
        self.assertIsNone(self.hook('claude', "git commit -m 'feat(x): add' -m 'Why: a\nScope: b\nVerified: none'"))
        self.assertIsNone(self.hook('claude', HEREDOC))

    def test_over_300_blocks_once_then_lets_the_same_commit_through(self):
        self.write('b.py', lines=350)
        self.stage()
        command = f'git commit -m {shlex.quote(GOOD)}'
        reason = self.denied(self.hook('claude', command))
        self.assertIn('350 lines across 1 file: over 300', reason)
        self.assertIn('  350  b.py', reason)
        self.assertIn('small-commits skill', reason)
        again = self.hook('claude', command)
        self.assertIsNone(self.denied(again))
        self.assertIn('let through on retry', self.note(again))
        self.assertIn('over 300', self.denied(self.hook('claude', command, session='s2')))  # another session: warned anew
        self.write('c.py', lines=20)  # the diff changed: warned again
        self.stage()
        self.assertIn('370 lines across 2 files', self.denied(self.hook('claude', command)))

    def test_over_600_is_a_wall_the_user_opens(self):
        self.write('b.py', lines=650)
        self.stage()
        command = f'git commit -m {shlex.quote(GOOD)}'
        for _ in range(2):
            reason = self.denied(self.hook('claude', command))
            self.assertIn('over 600, the wall', reason)
            self.assertIn('ALLOW_LARGE_COMMIT="<reason>"', reason)
            self.assertIn('missing trailer Large-commit:', reason)
        allowed = f'ALLOW_LARGE_COMMIT="vendored" git commit -m {shlex.quote(GOOD + chr(10) + "Large-commit: vendored")}'
        reply = self.hook('claude', allowed)
        self.assertIsNone(self.denied(reply))
        self.assertIn('let through on ALLOW_LARGE_COMMIT', self.note(reply))
        half = f'ALLOW_LARGE_COMMIT=1 git commit -m {shlex.quote(GOOD)}'  # the env alone: the trailer is still owed
        self.assertIn('missing trailer Large-commit:', self.denied(self.hook('claude', half)))

    def test_a_commit_git_writes_and_a_fixup_pass_untouched(self):
        self.write('b.py', lines=10)
        self.stage()
        git(self.repo, 'commit', '-q', '-m', 'b')
        git(self.repo, 'checkout', '-q', '-b', 'side', 'HEAD~1')
        self.write('a.txt', 'side\n')
        git(self.repo, 'commit', '-q', '-am', 'side')
        git(self.repo, 'checkout', '-q', 'main')
        self.write('a.txt', 'main\n')
        git(self.repo, 'commit', '-q', '-am', 'main')
        subprocess.run(['git', '-C', str(self.repo), 'merge', 'side'], capture_output=True)  # conflicts
        self.assertTrue((self.repo / '.git/MERGE_HEAD').exists())
        self.assertIsNone(self.hook('claude', 'git commit --no-edit'))
        git(self.repo, 'merge', '--abort')
        self.write('a.txt', 'fix\n')
        self.stage()
        self.assertIsNone(self.hook('claude', 'git commit --fixup HEAD'))
        self.assertIsNone(self.hook('claude', 'git commit -m "no shape" --squash HEAD'))

    def test_the_folder_follows_cd_and_dash_c(self):
        self.write('b.py', lines=350)
        self.stage()
        outside = self.repo.parent
        command = f'cd {shlex.quote(str(self.repo))} && git commit -m {shlex.quote(GOOD)}'
        self.assertIn('over 300', self.denied(self.hook('claude', command, cwd=outside)))
        command = f'git -C repo commit -m {shlex.quote(GOOD)}'
        self.assertIn('over 300', self.denied(self.hook('codex', command, session='s3', cwd=outside), 'codex'))
        self.assertIsNone(self.hook('claude', 'git commit -m x', cwd=outside))  # not a repository: nothing to say

    def test_an_amend_without_trailers_is_sent_back(self):
        self.write('b.py', lines=3)
        self.stage()
        reason = self.denied(self.hook('claude', 'git commit --amend --no-edit'))
        self.assertIn('the subject is not', reason)  # HEAD's message, "init", is what --no-edit keeps
        self.assertIsNone(self.hook('claude', f'git commit --amend -m {shlex.quote(GOOD)}'))

    def test_a_failure_says_the_commit_was_not_checked(self):
        broken = Path(tempfile.mkstemp()[1])  # the state "folder" is a file
        self.addCleanup(broken.unlink)
        self.write('b.py', lines=350)
        self.stage()
        data = {'session_id': 's', 'cwd': str(self.repo), 'tool_name': 'Bash',
                'tool_input': {'command': f'git commit -m {shlex.quote(GOOD)}'}}
        run = subprocess.run([sys.executable, str(SCRIPT), 'hook', 'pre', '--cli', 'claude'], input=json.dumps(data),
                             capture_output=True, text=True, env={**os.environ, sc.ENV: str(broken)})
        self.assertEqual((run.returncode, run.stderr), (0, ''))
        self.assertIn('this commit was not checked', json.loads(run.stdout)['hookSpecificOutput']['additionalContext'])

    def test_the_command_never_fails_or_speaks_outside_json(self):
        for stdin, args in (('not json', ['hook', 'pre', '--cli', 'codex']), ('{}', ['hook', 'end', '--cli', 'claude']),
                            ('{}', ['hook', 'pre'])):
            run = subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True)
            self.assertEqual((run.returncode, run.stderr), (0, ''), args)
            if run.stdout.strip():
                json.loads(run.stdout)


class CheckTest(Repo):
    def check(self, *args):
        out = io.StringIO()
        with redirect_stdout(out), patch('os.getcwd', return_value=str(self.repo)):
            status = sc.main(['check', *args])
        return status, out.getvalue()

    def test_check_shows_the_size_by_file_and_the_verdict(self):
        self.write('b.py', lines=350)
        self.write('uv.lock', lines=5)
        self.stage()
        status, text = self.check('-m', 'add b')
        self.assertEqual(status, 1)
        self.assertIn('350 lines across 1 file (limit 300, wall 600)', text)
        self.assertIn('  350  b.py', text)
        self.assertIn('skip  uv.lock', text)
        self.assertIn('BLOCKED: 350 lines', text)
        self.assertIn('BLOCKED: the message needs work', text)
        status, text = self.check()
        self.assertIn('message: not given', text)
        self.write('b.py', lines=30)
        self.stage()
        status, text = self.check('-m', GOOD)
        self.assertEqual((status, text.strip().splitlines()[-1]), (0, 'ok'))

    def test_check_outside_a_repository(self):
        with patch('os.getcwd', return_value=str(self.repo.parent)), redirect_stdout(io.StringIO()):
            self.assertEqual(sc.main(['check']), 1)


if __name__ == '__main__':
    unittest.main()
