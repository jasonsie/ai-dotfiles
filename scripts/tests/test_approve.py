"""approve: the six git step skills in order, as one resumable run; git and gh faked as in test_git_skills.

Run: python3 -m unittest discover -s scripts/tests -p 'test_approve.py' -v
"""
import importlib.util
import json
import sys
import tempfile
import unittest

from support import ROOT
from test_git_skills import FAIL, OK, OLD, PR, TIP, land  # also loads the step skills

SCRIPT = ROOT / 'skills/git/approve/scripts/approve.py'
SPEC = importlib.util.spec_from_file_location('approve', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
ap = importlib.util.module_from_spec(SPEC)
sys.modules['approve'] = ap
SPEC.loader.exec_module(ap)


def run(argv=(), **answers):
    return land(argv, ap.main, **answers)


class RunTest(unittest.TestCase):
    def test_lands_the_branch_in_order(self):
        code, output, _, fake = run()
        self.assertEqual(code, 0, output)
        steps = [line.split()[0] for line in output.splitlines()[:-1]]
        self.assertEqual(steps, ['preflight', 'reviewer', 'push', 'pr', 'review', 'tag', 'merge', 'prune'])
        self.assertIn('landed https://github.com/o/r/pull/7', output)
        order = [c for c, _ in fake.calls if c.startswith(('git push', 'gh pr review', 'git tag', 'gh pr merge', 'git branch -q -D'))]
        self.assertEqual([o.split()[1] for o in order], ['push', 'pr', 'tag', 'push', 'pr', 'branch', 'push'])
        review = next(token for c, token in fake.calls if c.startswith('gh pr review'))
        self.assertEqual(review, 'tok-second', 'the approval runs as the reviewer')
        self.assertIn('git tag -a archive/x ' + TIP, fake.ran('git tag')[0])
        self.assertIn('(Nov 2 to Nov 3, 2026; feat(x): the thing), kept before the branch was merged and deleted.'
                      '\n\nPR: https://github.com/o/r/pull/7', fake.ran('git tag')[0])
        self.assertTrue(fake.ran('gh pr merge 7 --merge'))
        self.assertTrue(fake.ran('git push -q origin --delete feat/x'))

    def test_dry_run_changes_nothing(self):
        code, output, _, fake = run(['--dry-run'])
        self.assertEqual(code, 0, output)
        self.assertEqual([c for c, _ in fake.calls if c.startswith(('git push', 'gh pr review', 'git tag', 'gh pr merge',
                                                                     'git branch -q', 'git checkout'))], [])
        self.assertIn('would  gh pr merge 7 --merge', output)
        self.assertIn('would land', output)

    def test_skips_what_is_done_already(self):
        merged = dict(PR, state='MERGED')
        code, output, _, fake = run(**{
            'git rev-parse --verify -q refs/remotes/origin/feat/x': TIP,
            'gh pr list': json.dumps([merged]),
            'git rev-list -n 1 archive/x': TIP,
            'git ls-remote --exit-code --tags origin archive/x': OK,
            'git branch --show-current': 'main',
            'git rev-parse --verify -q refs/heads/feat/x': FAIL,
            'git ls-remote --exit-code --heads origin feat/x': FAIL,
        })
        self.assertEqual(code, 1, output)  # on main: preflight refuses
        code, output, _, fake = run(**{
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

    def test_opens_the_pr_from_title_and_body(self):
        with tempfile.NamedTemporaryFile('w', suffix='.md') as body:
            body.write('## Summary\n')
            body.flush()
            answers = {'gh pr list': (0, '[]', ''), 'gh pr create': 'https://github.com/o/r/pull/8',
                       'gh pr view 8': 'CLEAN', 'gh pr view 8 --json reviews': ''}
            code, output, err, fake = run(['--title', 'feat(x): the thing', '--body-file', body.name], **answers)
            self.assertEqual(code, 0, output + err)
            self.assertIn('pr         #8 opened', output)
            self.assertTrue(fake.ran('gh pr create --base main --head feat/x --title feat(x): the thing --body-file ' + body.name))
            self.assertTrue(fake.ran('gh pr merge 8'))
        code, _, err, _ = run(**{'gh pr list': (0, '[]', '')})
        self.assertEqual(code, 1)
        self.assertIn('pr: no open PR for this branch; pass --title and --body-file', err)


class StopTest(unittest.TestCase):
    def test_refuses_main_dirty_tree_and_nothing_ahead(self):
        for answers, text in (({'git branch --show-current': 'main'}, 'on main'),
                              ({'git status --porcelain': ' M a.py'}, 'not committed'),
                              ({'git rev-list origin/main..HEAD': '', 'gh pr list': '[]'}, 'nothing to land')):
            code, _, err, fake = run(**answers)
            self.assertEqual(code, 1)
            self.assertIn(text, err)
            self.assertEqual(fake.ran('git push'), [])

    def test_an_unmergeable_pr_stops_with_its_state(self):
        code, _, err, fake = run(**{'gh pr view 7 --json mergeStateStatus': 'DIRTY'})
        self.assertEqual(code, 1)
        self.assertIn('merge: PR #7 is dirty', err)
        self.assertEqual(fake.ran('gh pr merge'), [])
        self.assertTrue(fake.ran('git push -q origin refs/tags/archive/x'), 'the tag is kept: evidence of the attempt')


MAIN = '/main checkout'   # the first worktree listed; a space on purpose
ON_MAIN = {'git worktree list --porcelain': f'worktree {MAIN}\nHEAD {OLD}\nbranch refs/heads/main\n\n'
                                            f'worktree /elsewhere\nHEAD {TIP}\nbranch refs/heads/feat/x'}
BEHIND = {**ON_MAIN,   # the main checkout lags origin/main by one commit that adds b.txt, and is clean
          f'git -C {MAIN} rev-parse HEAD': OLD,
          f'git -C {MAIN} rev-parse origin/main': TIP,
          f'git -C {MAIN} merge-base --is-ancestor {OLD} {TIP}': OK,
          f'git -C {MAIN} diff --name-only -z --no-renames {OLD} {TIP}': 'b.txt',
          f'git -C {MAIN} diff --name-only -z --no-renames': '',
          f'git -C {MAIN} diff --name-only -z --no-renames --cached': '',
          f'git -C {MAIN} ls-files -z --others --exclude-standard': '',
          f'git -C {MAIN} merge --ff-only origin/main': OK}
NOT_LOCAL = ('git branch --show-current', 'git rev-list origin/main..HEAD', 'git status', 'git checkout', 'git pull',
             'git rev-parse HEAD', 'git branch -q -D', 'git push -q -u')


class ByNumberTest(unittest.TestCase):
    """`approve 7`: no local branch, no worktree, no preflight."""

    def test_lands_pr_7_from_anywhere(self):
        code, output, err, fake = run(['7'], **BEHIND)
        self.assertEqual(code, 0, output + err)
        steps = [line.split()[0] for line in output.splitlines()[:-1]]
        self.assertEqual(steps, ['pr', 'reviewer', 'review', 'tag', 'merge', 'branch', 'main'])
        self.assertIn('landed https://github.com/o/r/pull/7', output)
        for prefix in NOT_LOCAL:
            self.assertEqual(fake.ran(prefix), [], prefix)
        review = next(token for c, token in fake.calls if c.startswith('gh pr review'))
        self.assertEqual(review, 'tok-second', 'the approval runs as the reviewer')
        self.assertIn(f'git tag -a archive/x {TIP}', fake.ran('git tag')[0])
        self.assertIn('Archive of branch feat/x (Nov 2 to Nov 3, 2026; feat(x): the thing), kept before the branch was '
                      'merged and deleted.\n\nPR: https://github.com/o/r/pull/7', fake.ran('git tag')[0])
        self.assertTrue(fake.ran('git fetch -q origin main refs/pull/7/head'), 'the PR head comes from GitHub, not a branch')
        order = [c.split()[0:3] for c, _ in fake.calls
                 if c.startswith(('gh pr review', 'git push -q origin refs/tags', 'gh pr merge', 'git push -q origin --delete',
                                  f'git -C {MAIN} merge --ff-only'))]
        self.assertEqual([' '.join(o) for o in order], ['gh pr review', 'git push -q', 'gh pr merge', 'git push -q', 'git -C /main'])
        self.assertTrue(fake.ran('git push -q origin --delete feat/x'))
        self.assertTrue(fake.ran(f'git -C {MAIN} merge --ff-only origin/main'))
        self.assertIn('main       fast-forwarded', output)

    def test_dry_run_changes_nothing(self):
        code, output, _, fake = run(['7', '--dry-run'], **BEHIND)
        self.assertEqual(code, 0, output)
        self.assertEqual([c for c, _ in fake.calls if c.startswith(('git push', 'gh pr review', 'git tag', 'gh pr merge', 'git -C'))
                          and ' merge-base ' not in c and ' rev-parse ' not in c and ' diff ' not in c and ' ls-files ' not in c], [])
        self.assertIn('would  gh pr merge 7 --merge', output)
        self.assertIn('would land', output)
        self.assertEqual(fake.ran('git fetch'), [], 'a dry run writes no refs, and a fetch does')
        self.assertIn('would  git fetch', output)

    def test_a_dry_run_whose_pr_head_is_not_fetched_says_so_instead_of_skipping_the_tag(self):
        code, output, _, fake = run(['7', '--dry-run'], **{**BEHIND, 'git rev-parse --verify -q ' + TIP + '^{commit}': FAIL})
        self.assertEqual(code, 0, output)
        self.assertIn('would tag archive/x at aaaaaaa', output)
        self.assertEqual(fake.ran('git tag') + fake.ran('git fetch'), [])

    def test_every_step_is_skipped_when_done(self):
        code, output, err, fake = run(['7'], **{
            'gh pr view 7 --json number': json.dumps(dict(PR, state='MERGED', headRefName='feat/x', baseRefName='main',
                                                          headRefOid=TIP, author={'login': 'owner'})),
            'git rev-list -n 1 archive/x': TIP,
            'git ls-remote --exit-code --tags origin archive/x': OK,
            'git ls-remote --exit-code --heads origin feat/x': FAIL,
            **ON_MAIN, f'git -C {MAIN} rev-parse HEAD': TIP, f'git -C {MAIN} rev-parse origin/main': TIP})
        self.assertEqual(code, 0, output + err)
        for line in ('review     merged already', 'tag        archive/x pushed already', 'merge      merged already',
                     'branch     gone already', 'main       up to date already'):
            self.assertIn(line, output)
        self.assertEqual(fake.ran('gh pr review') + fake.ran('gh pr merge') + fake.ran('git tag') + fake.ran('git push')
                         + fake.ran(f'git -C {MAIN} merge --ff-only'), [])

    def test_the_reviewer_must_not_be_the_prs_author(self):
        code, _, err, fake = run(['7'], **{'gh pr view 7 --json number': json.dumps(dict(PR, headRefName='feat/x', baseRefName='main',
                                                                                          headRefOid=TIP, author={'login': 'second'}))})
        self.assertEqual(code, 1)
        self.assertIn('self-approval', err)
        self.assertEqual(fake.ran('gh pr review'), [])

    def test_no_cached_reviewer_exits_3(self):
        code, _, err, fake = run(['7'], **{'git config --local approve.reviewer': (1, '', '')})
        self.assertEqual(code, 3)
        self.assertEqual(fake.ran('gh pr review'), [])

    def test_a_closed_pr_is_not_landed(self):
        code, _, err, fake = run(['7'], **{'gh pr view 7 --json number': json.dumps(dict(PR, state='CLOSED', headRefName='feat/x',
                                                                                          baseRefName='main', headRefOid=TIP,
                                                                                          author={'login': 'owner'}))})
        self.assertEqual(code, 1)
        self.assertIn('PR #7 is closed', err)
        self.assertEqual(fake.ran('gh pr review') + fake.ran('git tag') + fake.ran('gh pr merge'), [])

    def test_the_one_run_flags_do_not_mix_with_a_number(self):
        code, _, err, _ = run(['7', '--title', 'x'])
        self.assertEqual(code, 1)
        self.assertIn('--title and --body-file', err)


class FastForwardTest(unittest.TestCase):
    """The main checkout moves only when git can do it without touching uncommitted files."""

    def land(self, **answers):
        code, output, err, fake = run(['7'], **{**BEHIND, **answers})
        self.assertEqual(code, 0, output + err)
        return output, fake

    def merged(self, fake):
        return fake.ran(f'git -C {MAIN} merge --ff-only')

    def test_dirty_files_unrelated_to_the_incoming_change_stay_and_the_checkout_moves(self):
        output, fake = self.land(**{f'git -C {MAIN} diff --name-only -z --no-renames': 'a.txt',
                                    f'git -C {MAIN} ls-files -z --others --exclude-standard': 'notes.md'})
        self.assertEqual(len(self.merged(fake)), 1)
        self.assertIn('main       fast-forwarded', output)

    def test_an_uncommitted_file_the_merge_would_change_stops_the_move(self):
        for name, answer in (('diff --name-only -z --no-renames', 'x\0b.txt'), ('diff --name-only -z --no-renames --cached', 'b.txt'),
                             ('ls-files -z --others --exclude-standard', 'b.txt')):
            output, fake = self.land(**{f'git -C {MAIN} {name}': answer})
            self.assertEqual(self.merged(fake), [], name)
            self.assertIn('main       skipped: uncommitted changes in b.txt', output)
        for word in ('stash', 'reset', 'checkout', 'clean'):
            self.assertEqual(fake.ran(f'git -C {MAIN} {word}') + fake.ran(f'git {word}'), [], word)

    def test_a_main_checkout_on_another_branch_is_left_alone(self):
        output, fake = self.land(**{'git worktree list --porcelain': f'worktree {MAIN}\nHEAD {OLD}\nbranch refs/heads/feat/y'})
        self.assertEqual(self.merged(fake), [])
        self.assertIn('main       skipped: the main checkout is on feat/y, not main', output)
        output, fake = self.land(**{'git worktree list --porcelain': f'worktree {MAIN}\nHEAD {OLD}\ndetached'})
        self.assertIn('main       skipped: the main checkout is on a detached HEAD, not main', output)

    def test_a_local_main_that_is_not_behind_is_left_alone(self):
        output, fake = self.land(**{f'git -C {MAIN} merge-base --is-ancestor {OLD} {TIP}': FAIL})
        self.assertEqual(self.merged(fake), [])
        self.assertIn('main       skipped: main has commits origin/main lacks', output)

    def test_when_git_itself_refuses_the_move_is_skipped_with_its_reason(self):
        output, fake = self.land(**{f'git -C {MAIN} merge --ff-only origin/main': (1, '', 'error: Your local changes would be overwritten')})
        self.assertIn('main       skipped: git refused: error: Your local changes would be overwritten', output)


if __name__ == '__main__':
    unittest.main()
