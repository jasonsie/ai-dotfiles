"""approve: the six git step skills in order, as one resumable run; git and gh faked as in test_git_skills.

Run: python3 -m unittest discover -s scripts/tests -p 'test_approve.py' -v
"""
import importlib.util
import json
import sys
import tempfile
import unittest

from support import ROOT
from test_git_skills import FAIL, OK, PR, TIP, land  # also loads the step skills

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


if __name__ == '__main__':
    unittest.main()
