"""The git step skills (skills/git/), each run alone; every git and gh call faked through git_run.sh.

approve, which runs them all, is in test_approve.py. Fake, land and the answers are shared with it.
Run: python3 -m unittest discover -s scripts/tests -p 'test_git_skills.py' -v
"""
from contextlib import redirect_stderr, redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from support import ROOT

sys.path.insert(0, str(ROOT / 'skills/git/scripts'))
import git_run  # noqa: E402
STEPS = ('push-branch', 'open-pr', 'approve-pr', 'archive-tag', 'merge-pr', 'prune-branch')
git_run.use(*STEPS)
push_branch, open_pr, approve_pr, archive_tag, merge_pr, prune_branch = (importlib.import_module(s.replace('-', '_')) for s in STEPS)
TODAY = time.strftime('%Y-%m-%d')

TIP = 'a' * 40
OLD = 'b' * 40


class Fake:
    """Answers for commands by prefix; records every command run and the GH_TOKEN it ran with."""

    def __init__(self, **answers):
        self.answers = dict(DEFAULTS, **answers)
        self.calls = []
        self.dirs = []   # (command, cwd) of every call

    def __call__(self, args, env=None, cwd=None):
        key = ' '.join(args)
        self.calls.append((key, (env or {}).get('GH_TOKEN')))
        self.dirs.append((key, cwd))
        for prefix in sorted(self.answers, key=len, reverse=True):
            if key.startswith(prefix):
                answer = self.answers[prefix]
                return answer if isinstance(answer, tuple) else (0, answer, '')
        return 1, '', f'unexpected: {key}'

    def ran(self, prefix):
        return [c for c, _ in self.calls if c.startswith(prefix)]


OK, FAIL = (0, '', ''), (1, '', 'no')
PR = {'number': 7, 'url': 'https://github.com/o/r/pull/7', 'state': 'OPEN', 'title': 'feat(x): the thing'}
DEFAULTS = {
    'git rev-parse --is-inside-work-tree': 'true',
    'git branch --show-current': 'feat/x',
    'git symbolic-ref --short refs/remotes/origin/HEAD': 'origin/main',
    'git status --porcelain': '',
    'git fetch': OK,
    'git rev-list origin/main..HEAD': 'c1',
    'git rev-parse HEAD': TIP,
    'gh repo view': 'o/r',
    'gh api user': 'owner',
    'git log -1 --format=%s feat/x': 'feat(x): last',
    'git config --local approve.reviewer': 'second',
    'git config --local approve.reviewer second': OK,  # the set, as opposed to the read
    'git config --local --unset': OK,
    'gh auth token --user second': 'tok-second',
    'git rev-parse --verify -q refs/remotes/origin/feat/x': FAIL,
    'git push': OK,
    'gh pr list': json.dumps([PR]),
    'gh pr view 7 --json reviews': '',
    'gh pr review': OK,
    'git rev-parse --verify -q feat/x^{commit}': TIP,
    'git rev-list -n 1 archive/x': FAIL,
    'git log --format=%ad --date=format:%Y-%m-%d origin/main..feat/x': '2026-11-03\n2026-11-02',
    'git tag': OK,
    'git ls-remote --exit-code --tags origin archive/x': FAIL,
    'gh pr view 7 --json mergeStateStatus': 'CLEAN',
    'gh pr merge': OK,
    'git checkout': OK,
    'git pull': OK,
    'git rev-parse --verify -q refs/heads/feat/x': TIP,
    'git branch -q -D': OK,
    'git ls-remote --exit-code --heads origin feat/x': OK,
    'gh pr view 7 --json number': json.dumps(dict(PR, headRefName='feat/x', baseRefName='main', headRefOid=TIP,
                                                  author={'login': 'owner'})),
    'git rev-parse --verify -q ' + TIP + '^{commit}': TIP,
    'git log --format=%ad --date=format:%Y-%m-%d origin/main..' + TIP: '2026-11-03\n2026-11-02',
    'git rev-parse --show-toplevel': '/repo',
    'git worktree list --porcelain': 'worktree /repo\nHEAD ' + TIP + '\nbranch refs/heads/feat/x',
}


def as_reviewer(fake):
    """gh api user answers as the reviewer when run with the reviewer's token."""
    original = fake.__call__

    def call(args, env=None, cwd=None):
        if args[:3] == ['gh', 'api', 'user'] and (env or {}).get('GH_TOKEN') == 'tok-second':
            fake.calls.append((' '.join(args), 'tok-second'))
            return 0, 'second', ''
        if args[:3] == ['gh', 'api', 'repos/o/r'] and (env or {}).get('GH_TOKEN') == 'tok-second':
            fake.calls.append((' '.join(args), 'tok-second'))
            return fake.answers.get('gh api repos/o/r', (0, '1', ''))
        return original(args, env, cwd)
    return call


def land(argv, main, **answers):
    """Run a skill's main(argv) against the fake; (exit code, stdout, stderr, fake)."""
    fake = Fake(**answers)
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(git_run, 'sh', as_reviewer(fake)), redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue(), fake


class ArchiveTagTest(unittest.TestCase):
    def test_tag_name_drops_the_first_segment(self):
        for branch, name in (('feat/small-commits', 'archive/small-commits'), ('fix/a/b', 'archive/a-b'),
                             ('upstream-sync', 'archive/upstream-sync'), ('agent/claude-4ef2', 'archive/claude-4ef2')):
            self.assertEqual(archive_tag.stem(branch), name)

    def test_a_name_taken_elsewhere_gets_the_date_and_a_rerun_reuses_the_tag(self):
        code, output, _, fake = land([], archive_tag.main, **{'git rev-list -n 1 archive/x': OLD,
                                                              f'git rev-list -n 1 archive/x-{TODAY}': FAIL})
        self.assertEqual(code, 0, output)
        self.assertIn(f'git tag -a archive/x-{TODAY} {TIP}', fake.ran('git tag')[0])
        code, output, _, fake = land([], archive_tag.main, **{'git rev-list -n 1 archive/x': OLD,
                                                              f'git rev-list -n 1 archive/x-{TODAY}': TIP})
        self.assertEqual(code, 0, output)
        self.assertEqual(fake.ran('git tag'), [], 'the tag at the tip is reused')
        self.assertIn(f'tag        archive/x-{TODAY} pushed', output)

    def test_message_says_merged_or_unmerged_and_carries_the_callers_lines(self):
        self.assertEqual(archive_tag.message('feat/approve', 'Nov 3, 2026', 'approve lands a branch', True),
                         'Archive of branch feat/approve (Nov 3, 2026; approve lands a branch), '
                         'kept before the branch was merged and deleted.')
        self.assertEqual(archive_tag.message('agent/x', 'Nov 3, 2026', 'd', False, ('Agent: pi',)),
                         'Archive of branch agent/x (Nov 3, 2026; d), kept before the branch was deleted unmerged.'
                         '\n\nAgent: pi')

    def test_a_branch_that_is_gone_gets_no_tag(self):
        fake = Fake(**{'git rev-parse --verify -q feat/x^{commit}': FAIL})
        with patch.object(git_run, 'sh', fake):
            self.assertIsNone(archive_tag.archive('feat/x', 'd', True, 'origin/main'))
        self.assertEqual(fake.ran('git tag'), [])

    def test_tag_alone_describes_the_branch_by_its_last_commit(self):
        code, output, err, fake = land(['--unmerged'], archive_tag.main)
        self.assertEqual(code, 0, err)
        self.assertIn('feat(x): last), kept before the branch was deleted unmerged.', fake.ran('git tag')[0])
        self.assertIn('tag        archive/x pushed', output)


if __name__ == '__main__':
    unittest.main()


class StepTest(unittest.TestCase):
    """Each step skill runs alone as `ai-dotfiles git <step>`."""


    def test_merge_alone_finds_the_pr_and_merges(self):
        code, output, err, fake = land([], merge_pr.main)
        self.assertEqual(code, 0, err)
        self.assertEqual(output.strip(), 'merge      #7 merged')
        self.assertTrue(fake.ran('gh pr merge 7 --merge'))
        self.assertEqual(fake.ran('git push') + fake.ran('gh pr review'), [])

    def test_merge_alone_without_a_pr_stops(self):
        code, _, err, _ = land([], merge_pr.main, **{'gh pr list': '[]'})
        self.assertEqual(code, 1)
        self.assertIn('merge stopped at pr: no open PR for feat/x', err)

    def test_push_and_prune_alone_in_a_dry_run(self):
        code, output, _, fake = land(['--dry-run'], push_branch.main)
        self.assertEqual(code, 0)
        self.assertIn('would  git push -q -u origin feat/x', output)
        code, output, _, fake = land(['--dry-run'], prune_branch.main)
        self.assertEqual(code, 0)
        self.assertIn('would  git push -q origin --delete feat/x', output)
        self.assertEqual(fake.ran('git push'), [])

    def test_prune_in_a_linked_worktree_detaches_at_the_base(self):
        worktrees = 'worktree /main\nHEAD 1\nbranch refs/heads/main\n\nworktree /repo\nHEAD 2\nbranch refs/heads/feat/x'
        code, output, err, fake = land([], prune_branch.main, **{'git worktree list --porcelain': worktrees})
        self.assertEqual(code, 0, err)
        self.assertTrue(fake.ran('git checkout -q --detach origin/main'))
        self.assertEqual(fake.ran('git checkout -q main') + fake.ran('git pull'), [])
        self.assertIn('detached at origin/main', output)
        self.assertTrue(fake.ran('git branch -q -D feat/x'))

    def test_a_diverged_remote_branch_stops_before_push(self):
        code, _, err, _ = land([], push_branch.main, **{'git rev-parse --verify -q refs/remotes/origin/feat/x': OLD,
                                                    'git merge-base --is-ancestor': FAIL})
        self.assertEqual(code, 1)
        self.assertIn('push: origin/feat/x is at bbbbbbb', err)


class ApprovePrTest(unittest.TestCase):
    def test_review_alone_approves_as_the_reviewer(self):
        code, output, err, fake = land([], approve_pr.main)
        self.assertEqual(code, 0, err)
        self.assertIn('review     approved as second', output)
        self.assertEqual(next(t for c, t in fake.calls if c.startswith('gh pr review')), 'tok-second')

    def test_no_cached_reviewer_exits_3_and_asks(self):
        code, _, err, fake = land([], approve_pr.main, **{'git config --local approve.reviewer': FAIL})
        self.assertEqual(code, approve_pr.NO_REVIEWER)
        self.assertIn('Ask the user which GitHub login reviews here', err)
        self.assertEqual(fake.ran('git push'), [])

    def test_a_given_reviewer_is_verified_then_cached(self):
        code, output, err, fake = land(['--reviewer', 'second'], approve_pr.main, **{'git config --local approve.reviewer': FAIL})
        self.assertEqual(code, 0, err)
        self.assertTrue(fake.ran('git config --local approve.reviewer second'))
        self.assertIn('reviewer   second', output)

    def test_the_author_cannot_be_the_reviewer(self):
        code, _, err, fake = land(['--reviewer', 'owner'], approve_pr.main)
        self.assertEqual(code, 1)
        self.assertIn('refuses self-approval', err)
        self.assertEqual(fake.ran('git config --local approve.reviewer owner'), [])

    def test_a_reviewer_without_a_token_or_without_access_stops(self):
        code, _, err, _ = land([], approve_pr.main, **{'gh auth token --user second': (1, '', 'no such account')})
        self.assertEqual(code, 1)
        self.assertIn('no gh token for second', err)
        code, _, err, _ = land([], approve_pr.main, **{'gh api repos/o/r': (1, '', 'gh: Not Found (HTTP 404)')})
        self.assertEqual(code, 1)
        self.assertIn('second cannot read o/r (gh: Not Found (HTTP 404)). Invite that account', err)
        self.assertNotIn('collaborators', ' '.join(c for c, _ in Fake().calls), 'the script never invites')

    def test_reviewer_subcommand_shows_sets_and_clears(self):
        reviewer = approve_pr.main_reviewer
        code, output, _, _ = land([], reviewer)
        self.assertEqual((code, output.strip()), (0, 'second'))
        code, output, _, _ = land([], reviewer, **{'git config --local approve.reviewer': FAIL})
        self.assertEqual((code, output.strip()), (approve_pr.NO_REVIEWER, 'no reviewer cached for this repo'))
        code, _, _, fake = land(['--unset'], reviewer)
        self.assertEqual(code, 0)
        self.assertTrue(fake.ran('git config --local --unset approve.reviewer'))


class FastForwardRealGitTest(unittest.TestCase):
    """prune_branch.fast_forward against real repositories (a local bare origin): uncommitted files survive."""

    def git(self, where, *args):
        done = subprocess.run(['git', '-C', str(where), *args], capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        env = patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': '/dev/null'})
        env.start()
        self.addCleanup(env.stop)
        self.main, other = root / 'main co', root / 'other'
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(root / 'origin.git')], check=True)
        for folder in (self.main, other):
            subprocess.run(['git', 'clone', '-q', str(root / 'origin.git'), str(folder)], check=True, capture_output=True)
            self.git(folder, 'config', 'user.email', 't@example.com')
            self.git(folder, 'config', 'user.name', 'T')
        for name in ('a.txt', 'b.txt'):
            (other / name).write_text('one\n')
        self.git(other, 'add', '.')
        self.git(other, 'commit', '-q', '-m', 'init')
        self.git(other, 'push', '-q', 'origin', 'HEAD:main')
        self.git(self.main, 'pull', '-q', 'origin', 'main')
        (other / 'b.txt').write_text('two\n')
        self.git(other, 'commit', '-q', '-am', 'change b')
        self.git(other, 'push', '-q', 'origin', 'HEAD:main')
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.main)

    def test_unrelated_uncommitted_work_stays_and_main_moves(self):
        (self.main / 'a.txt').write_text('mine\n')
        (self.main / 'notes.md').write_text('new\n')
        self.assertTrue(prune_branch.fast_forward('main', False).startswith('fast-forwarded'))
        self.assertEqual((self.main / 'b.txt').read_text(), 'two\n')
        self.assertEqual((self.main / 'a.txt').read_text(), 'mine\n')
        self.assertTrue((self.main / 'notes.md').exists())

    def test_a_file_the_move_would_change_is_left_as_it_is(self):
        (self.main / 'b.txt').write_text('mine\n')
        self.assertEqual(prune_branch.fast_forward('main', False), 'skipped: uncommitted changes in b.txt')
        self.assertEqual((self.main / 'b.txt').read_text(), 'mine\n')
        self.assertEqual(self.git(self.main, 'rev-list', '--count', 'HEAD'), '1')
        self.assertEqual(self.git(self.main, 'stash', 'list'), '')


if __name__ == '__main__':
    unittest.main()
