"""approve: land a reviewed branch; every git and gh call is faked through approve.sh.

Run: python3 -m unittest discover -s scripts/tests -p 'test_approve.py' -v
"""
from contextlib import redirect_stderr, redirect_stdout
import datetime as dt
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT

SCRIPT = ROOT / 'skills/approve/scripts/approve.py'
SPEC = importlib.util.spec_from_file_location('approve', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
ap = importlib.util.module_from_spec(SPEC)
sys.modules['approve'] = ap
SPEC.loader.exec_module(ap)

TIP = 'a' * 40
OLD = 'b' * 40


class Fake:
    """Answers for commands by prefix; records every command run and the GH_TOKEN it ran with."""

    def __init__(self, **answers):
        self.answers = dict(DEFAULTS, **answers)
        self.calls = []

    def __call__(self, args, env=None):
        key = ' '.join(args)
        self.calls.append((key, (env or {}).get('GH_TOKEN')))
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
    'git config --local approve.reviewer': 'second',
    'git config --local approve.reviewer second': OK,  # the set, as opposed to the read
    'git config --local --unset': OK,
    'gh auth token --user second': 'tok-second',
    'git rev-parse --verify -q refs/remotes/origin/feat/x': FAIL,
    'git push': OK,
    'gh pr list': json.dumps([PR]),
    'gh pr view 7 --json reviews': '',
    'gh pr review': OK,
    'git rev-list -n 1 archive/x': FAIL,
    'git tag': OK,
    'git ls-remote --exit-code --tags origin archive/x': FAIL,
    'gh pr view 7 --json mergeStateStatus': 'CLEAN',
    'gh pr merge': OK,
    'git checkout': OK,
    'git pull': OK,
    'git rev-parse --git-dir': '.git',
    'git rev-parse --git-common-dir': '.git',
    'git rev-parse --verify -q refs/heads/feat/x': TIP,
    'git branch -q -D': OK,
    'git ls-remote --exit-code --heads origin feat/x': OK,
}


def as_reviewer(fake):
    """gh api user answers as the reviewer when run with the reviewer's token."""
    original = fake.__call__

    def call(args, env=None):
        if args[:3] == ['gh', 'api', 'user'] and (env or {}).get('GH_TOKEN') == 'tok-second':
            fake.calls.append((' '.join(args), 'tok-second'))
            return 0, 'second', ''
        if args[:3] == ['gh', 'api', 'repos/o/r'] and (env or {}).get('GH_TOKEN') == 'tok-second':
            fake.calls.append((' '.join(args), 'tok-second'))
            return fake.answers.get('gh api repos/o/r', (0, '1', ''))
        return original(args, env)
    return call


def land(argv=(), **answers):
    fake = Fake(**answers)
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(ap, 'sh', as_reviewer(fake)), redirect_stdout(stdout), redirect_stderr(stderr):
        code = ap.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue(), fake


class RunTest(unittest.TestCase):
    def test_lands_the_branch_in_order(self):
        code, output, _, fake = land()
        self.assertEqual(code, 0, output)
        steps = [line.split()[0] for line in output.splitlines()[:-1]]
        self.assertEqual(steps, ['preflight', 'reviewer', 'push', 'pr', 'review', 'tag', 'merge', 'cleanup'])
        self.assertIn('landed https://github.com/o/r/pull/7', output)
        order = [c for c, _ in fake.calls if c.startswith(('git push', 'gh pr review', 'git tag', 'gh pr merge', 'git branch -q -D'))]
        self.assertEqual([o.split()[1] for o in order], ['push', 'pr', 'tag', 'push', 'pr', 'branch', 'push'])
        review = next(token for c, token in fake.calls if c.startswith('gh pr review'))
        self.assertEqual(review, 'tok-second', 'the approval runs as the reviewer')
        self.assertIn('git tag -a archive/x ' + TIP, fake.ran('git tag')[0])
        self.assertTrue(fake.ran('gh pr merge 7 --merge'))
        self.assertTrue(fake.ran('git push -q origin --delete feat/x'))

    def test_dry_run_changes_nothing(self):
        code, output, _, fake = land(['--dry-run'])
        self.assertEqual(code, 0, output)
        self.assertEqual([c for c, _ in fake.calls if c.startswith(('git push', 'gh pr review', 'git tag', 'gh pr merge',
                                                                     'git branch -q', 'git checkout'))], [])
        self.assertIn('would  gh pr merge 7 --merge', output)
        self.assertIn('would land', output)

    def test_skips_what_is_done_already(self):
        merged = dict(PR, state='MERGED')
        code, output, _, fake = land(**{
            'git rev-parse --verify -q refs/remotes/origin/feat/x': TIP,
            'gh pr list': json.dumps([merged]),
            'git rev-list -n 1 archive/x': TIP,
            'git ls-remote --exit-code --tags origin archive/x': OK,
            'git branch --show-current': 'main',
            'git rev-parse --verify -q refs/heads/feat/x': FAIL,
            'git ls-remote --exit-code --heads origin feat/x': FAIL,
        })
        self.assertEqual(code, 1, output)  # on main: preflight refuses
        code, output, _, fake = land(**{
            'git rev-parse --verify -q refs/remotes/origin/feat/x': TIP,
            'gh pr list': json.dumps([merged]),
            'git rev-list -n 1 archive/x': TIP,
            'git ls-remote --exit-code --tags origin archive/x': OK,
        })
        self.assertEqual(code, 0, output)
        for line in ('push       already pushed', 'pr         #7 exists (merged)', 'review     merged already',
                     'tag        archive/x pushed already', 'merge      merged already'):
            self.assertIn(line, output)
        self.assertEqual(fake.ran('gh pr review') + fake.ran('gh pr merge') + fake.ran('git tag') + fake.ran('git push -q -u'), [])

    def test_in_a_linked_worktree_detaches_and_leaves_the_base_alone(self):
        code, output, err, fake = land(**{'git rev-parse --git-dir': '/r/.git/worktrees/w'})
        self.assertEqual(code, 0, err)
        self.assertTrue(fake.ran('git checkout -q --detach origin/main'))
        self.assertEqual(fake.ran('git pull'), [], 'the main checkout is another session\'s')
        self.assertIn('detached at origin/main', output)
        self.assertTrue(fake.ran('git branch -q -D feat/x'))

    def test_opens_the_pr_from_title_and_body(self):
        with tempfile.NamedTemporaryFile('w', suffix='.md') as body:
            body.write('## Summary\n')
            body.flush()
            answers = {'gh pr list': (0, '[]', ''), 'gh pr create': 'https://github.com/o/r/pull/8',
                       'gh pr view 8': 'CLEAN', 'gh pr view 8 --json reviews': ''}
            code, output, err, fake = land(['--title', 'feat(x): the thing', '--body-file', body.name], **answers)
            self.assertEqual(code, 0, output + err)
            self.assertIn('pr         #8 opened', output)
            self.assertTrue(fake.ran('gh pr create --base main --head feat/x --title feat(x): the thing --body-file ' + body.name))
            self.assertTrue(fake.ran('gh pr merge 8'))
        code, _, err, _ = land(**{'gh pr list': (0, '[]', '')})
        self.assertEqual(code, 1)
        self.assertIn('pr: no open PR for this branch; pass --title and --body-file', err)


class StopTest(unittest.TestCase):
    def test_refuses_main_dirty_tree_and_nothing_ahead(self):
        for answers, text in (({'git branch --show-current': 'main'}, 'on main'),
                              ({'git status --porcelain': ' M a.py'}, 'not committed'),
                              ({'git rev-list origin/main..HEAD': ''}, 'nothing to land')):
            code, _, err, fake = land(**answers)
            self.assertEqual(code, 1)
            self.assertIn(text, err)
            self.assertEqual(fake.ran('git push'), [])

    def test_a_diverged_remote_branch_stops_before_push(self):
        code, _, err, _ = land(**{'git rev-parse --verify -q refs/remotes/origin/feat/x': OLD,
                                 'git merge-base --is-ancestor': FAIL})
        self.assertEqual(code, 1)
        self.assertIn('push: origin/feat/x is at bbbbbbb', err)

    def test_a_tag_elsewhere_stops_before_merge(self):
        code, _, err, fake = land(**{'git rev-list -n 1 archive/x': OLD})
        self.assertEqual(code, 1)
        self.assertIn('tag: archive/x exists at bbbbbbb', err)
        self.assertEqual(fake.ran('gh pr merge'), [])

    def test_an_unmergeable_pr_stops_with_its_state(self):
        code, _, err, fake = land(**{'gh pr view 7 --json mergeStateStatus': 'DIRTY'})
        self.assertEqual(code, 1)
        self.assertIn('merge: PR #7 is dirty', err)
        self.assertEqual(fake.ran('gh pr merge'), [])
        self.assertTrue(fake.ran('git push -q origin archive/x'), 'the tag is kept: evidence of the attempt')


class ReviewerTest(unittest.TestCase):
    def test_no_cached_reviewer_exits_3_and_asks(self):
        code, _, err, fake = land(**{'git config --local approve.reviewer': FAIL})
        self.assertEqual(code, ap.NO_REVIEWER)
        self.assertIn('Ask the user which GitHub login reviews here', err)
        self.assertEqual(fake.ran('git push'), [])

    def test_a_given_reviewer_is_verified_then_cached(self):
        code, output, err, fake = land(['--reviewer', 'second'], **{'git config --local approve.reviewer': FAIL})
        self.assertEqual(code, 0, err)
        self.assertTrue(fake.ran('git config --local approve.reviewer second'))
        self.assertIn('reviewer   second', output)

    def test_the_author_cannot_be_the_reviewer(self):
        code, _, err, fake = land(['--reviewer', 'owner'])
        self.assertEqual(code, 1)
        self.assertIn('refuses self-approval', err)
        self.assertEqual(fake.ran('git config --local approve.reviewer owner'), [])

    def test_a_reviewer_without_a_token_or_without_access_stops(self):
        code, _, err, _ = land(**{'gh auth token --user second': (1, '', 'no such account')})
        self.assertEqual(code, 1)
        self.assertIn('no gh token for second', err)
        code, _, err, _ = land(**{'gh api repos/o/r': (1, '', 'gh: Not Found (HTTP 404)')})
        self.assertEqual(code, 1)
        self.assertIn('second cannot read o/r (gh: Not Found (HTTP 404)). Invite that account', err)
        self.assertNotIn('collaborators', ' '.join(c for c, _ in Fake().calls), 'the script never invites')

    def test_reviewer_subcommand_shows_sets_and_clears(self):
        code, output, _, _ = land(['reviewer'])
        self.assertEqual((code, output.strip()), (0, 'second'))
        code, output, _, _ = land(['reviewer'], **{'git config --local approve.reviewer': FAIL})
        self.assertEqual((code, output.strip()), (ap.NO_REVIEWER, 'no reviewer cached for this repo'))
        code, _, _, fake = land(['reviewer', '--unset'])
        self.assertEqual(code, 0)
        self.assertTrue(fake.ran('git config --local --unset approve.reviewer'))


class NamingTest(unittest.TestCase):
    def test_tag_name_drops_the_type_prefix(self):
        for branch, name in (('feat/small-commits', 'archive/small-commits'), ('fix/a/b', 'archive/a-b'),
                             ('upstream-sync', 'archive/upstream-sync'), ('agent/claude-4ef2', 'archive/claude-4ef2')):
            self.assertEqual(ap.tag_name(branch), name)

    def test_tag_message_follows_the_archive_convention(self):
        repo = ap.Repo('main', 'feat/approve', TIP, 'o/r', 'owner')
        self.assertEqual(ap.tag_message(repo, 'approve lands a branch', dt.date(2026, 11, 3)),
                         'Archive of branch feat/approve (Nov 3, 2026; approve lands a branch), '
                         'kept before the branch was merged and deleted.')


if __name__ == '__main__':
    unittest.main()
