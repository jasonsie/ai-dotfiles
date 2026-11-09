"""ship: checks, push as <type>/<slug>, PR, worktree deleted; git, gh and the checks faked as in test_git_skills.

The worktree-side cleanup (`worktree shipped`) is tested for real in test_worktree_guard.py.
Run: python3 -m unittest discover -s scripts/tests -p 'test_ship.py' -v
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT
from test_git_skills import FAIL, OK, OLD, PR, TIP, land  # also loads the step skills

SCRIPT = ROOT / 'skills/git/ship/scripts/ship.py'
SPEC = importlib.util.spec_from_file_location('ship', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
ship = importlib.util.module_from_spec(SPEC)
sys.modules['ship'] = ship
SPEC.loader.exec_module(ship)

VERIFY = '''# Notes

## Verify

```bash
python3 -m unittest discover -s scripts/tests      # Python 3.11+
shellcheck scripts/*.sh scripts/ai-dotfiles
# a comment line
bash scripts/healthcheck.sh
```

## Next
```bash
echo not a check
```
'''
CHECKS = ['python3 -m unittest discover -s scripts/tests', 'shellcheck scripts/*.sh scripts/ai-dotfiles',
          'bash scripts/healthcheck.sh']
NEW_PR = 'https://github.com/o/r/pull/8'


class ChecksTest(unittest.TestCase):
    def test_the_commands_of_the_verify_block_without_comments(self):
        self.assertEqual(ship.checks_of(VERIFY), CHECKS)

    def test_no_verify_section_means_no_checks(self):
        self.assertEqual(ship.checks_of('# Repo\n\n```bash\nrm -rf /\n```\n'), [])


class ShipTest(unittest.TestCase):
    """A worktree `worktree new` made: <main>/.claude/worktrees/fix-x, detached, work fix/x."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ship 空間 ')
        self.addCleanup(self.temp.cleanup)
        self.main = Path(self.temp.name).resolve() / 'repo'
        self.linked = self.main / '.claude/worktrees/fix-x'
        self.linked.mkdir(parents=True)
        (self.linked / 'AGENTS.md').write_text(VERIFY)
        (self.main / '.claude/worktrees/fix-x.json').write_text(json.dumps({'name': 'fix-x', 'work': 'fix/x'}))
        self.body = self.main / 'body.md'
        self.body.write_text('## Summary\n')
        self.answers = {
            'git rev-parse --show-toplevel': str(self.linked),
            'git branch --show-current': '',   # detached
            'git ls-remote --heads origin refs/heads/fix/x': '',
            'gh pr list': '[]',
            'gh pr create': NEW_PR,
            'bash -c': OK,
            'python3': 'worktree-guard: removed fix-x (fix/x); its session is back in ' + str(self.main),
        }

    def ship(self, argv=None, **answers):
        argv = ['--title', 'fix(x): the thing', '--body-file', str(self.body)] if argv is None else argv
        with patch.object(ship.guard, 'main_of', return_value=self.main):  # the folders are not a real repo
            return land(argv, ship.main, **{**self.answers, **answers})

    def test_runs_the_checks_pushes_opens_the_pr_then_deletes_the_worktree(self):
        code, output, err, fake = self.ship()
        self.assertEqual(code, 0, output + err)
        steps = [line.split()[0] for line in output.splitlines() if line.startswith(('preflight', 'checks', 'push', 'pr', 'worktree'))]
        self.assertEqual(steps, ['preflight', 'checks', 'push', 'pr', 'worktree'])
        self.assertEqual([c for c in fake.ran('bash -c')], ['bash -c ' + c for c in CHECKS])
        self.assertTrue(fake.ran(f'git push -q origin HEAD:refs/heads/fix/x'))
        self.assertTrue(fake.ran(f'gh pr create --base main --head fix/x --title fix(x): the thing --body-file {self.body}'))
        calls = [c for c, _ in fake.calls]
        order = [next(i for i, c in enumerate(calls) if c.startswith(p))
                 for p in ('bash -c', 'git push', 'gh pr create', 'python3')]
        self.assertEqual(order, sorted(order), 'checks, push, PR, then the worktree goes')
        self.assertIn(f'shipped {NEW_PR}', output)
        self.assertIn(f'shipped fix-x --repo {self.main}', fake.ran('python3')[0])
        self.assertEqual(fake.ran('python3')[0].split()[1], str(ship.GUARD))
        self.assertIn('ExitWorktree', output.splitlines()[-1])
        self.assertIn(str(self.main), output.splitlines()[-1])

    def test_the_checks_run_in_the_worktree(self):
        _, _, _, fake = self.ship()
        self.assertEqual({cwd for call, cwd in fake.dirs if call.startswith('bash -c')}, {str(self.linked)})
        self.assertEqual({cwd for call, cwd in fake.dirs if call.startswith('python3')}, {str(self.main)},
                         'the cleanup runs from the main checkout, not from the folder it deletes')

    def test_a_failing_check_stops_before_the_push_naming_the_command(self):
        code, output, err, fake = self.ship(**{'bash -c shellcheck': (2, 'SC1000', 'bad quoting')})
        self.assertEqual(code, 1)
        self.assertIn('checks: `shellcheck scripts/*.sh scripts/ai-dotfiles` failed (exit 2): bad quoting', err)
        self.assertEqual(fake.ran('bash -c'), ['bash -c ' + c for c in CHECKS[:2]], 'later checks do not run')
        for mutating in ('git push', 'gh pr create', 'python3'):
            self.assertEqual(fake.ran(mutating), [], mutating)

    def test_a_branch_already_on_origin_elsewhere_is_refused(self):
        code, _, err, fake = self.ship(**{'git ls-remote --heads origin refs/heads/fix/x': f'{OLD}\trefs/heads/fix/x'})
        self.assertEqual(code, 1)
        self.assertIn('push: origin already has fix/x at bbbbbbb', err)
        self.assertEqual(fake.ran('git push') + fake.ran('gh pr create') + fake.ran('python3'), [])

    def test_a_rerun_after_the_push_skips_it_and_a_known_pr_is_reused(self):
        code, output, err, fake = self.ship([], **{
            'git ls-remote --heads origin refs/heads/fix/x': f'{TIP}\trefs/heads/fix/x',
            'gh pr list': json.dumps([PR])})
        self.assertEqual(code, 0, err)
        self.assertIn('push       already pushed', output)
        self.assertIn('pr         #7 exists (open)', output)
        self.assertEqual(fake.ran('git push') + fake.ran('gh pr create'), [])
        self.assertTrue(fake.ran('python3'), 'the worktree still goes')

    def test_an_existing_pr_needs_no_title_or_body(self):
        code, output, err, fake = self.ship([], **{'gh pr list': json.dumps([PR])})
        self.assertEqual(code, 0, err)
        self.assertIn('shipped https://github.com/o/r/pull/7', output)

    def test_no_pr_and_no_title_or_body_stops_before_the_checks(self):
        code, _, err, fake = self.ship([])
        self.assertEqual(code, 1)
        self.assertIn('ship: no PR for fix/x yet; pass --title and --body-file', err)
        self.assertEqual(fake.ran('bash -c'), [])
        code, _, err, fake = self.ship(['--title', 't', '--body-file', str(self.main / 'missing.md')])
        self.assertEqual(code, 1)
        self.assertIn('body file not found', err)
        self.assertEqual(fake.ran('bash -c'), [])

    def test_a_pr_that_fails_to_open_keeps_the_worktree(self):
        code, _, err, fake = self.ship(**{'gh pr create': (1, '', 'boom')})
        self.assertEqual(code, 1)
        self.assertIn('gh pr create', err)
        self.assertTrue(fake.ran('git push'))
        self.assertEqual(fake.ran('python3'), [])

    def test_a_worktree_that_refuses_to_go_is_reported_after_the_pr_exists(self):
        code, output, err, fake = self.ship(**{'python3': (1, '', 'worktree-guard: kept fix-x: 1 uncommitted change(s)')})
        self.assertEqual(code, 1)
        self.assertIn(f'shipped {NEW_PR}', output)
        self.assertIn('worktree: kept fix-x: 1 uncommitted change(s)', err)

    def test_nothing_ahead_of_the_base_has_nothing_to_ship(self):
        code, _, err, fake = self.ship(**{'git rev-list origin/main..HEAD': ''})
        self.assertEqual(code, 1)
        self.assertIn('nothing to ship', err)
        self.assertEqual(fake.ran('bash -c') + fake.ran('git push'), [])

    def test_tracked_changes_stop_it(self):
        code, _, err, fake = self.ship(**{'git status --porcelain': ' M a.py'})
        self.assertEqual(code, 1)
        self.assertIn('not committed', err)

    def test_a_folder_that_worktree_new_did_not_make_is_refused(self):
        (self.main / '.claude/worktrees/fix-x.json').unlink()
        code, _, err, fake = self.ship()
        self.assertEqual(code, 1)
        self.assertIn('ship: fix-x was not made by `ai-dotfiles worktree new`', err)
        self.assertEqual(fake.ran('bash -c') + fake.ran('git push'), [])

    def test_dry_run_changes_nothing(self):
        code, output, err, fake = self.ship(['--dry-run', '--title', 't', '--body-file', str(self.body)])
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.ran('bash -c') + fake.ran('git push') + fake.ran('gh pr create') + fake.ran('python3'), [])
        for line in ("would  bash -c 'shellcheck", 'would  git push -q origin HEAD:refs/heads/fix/x', 'would  gh pr create',
                     'would  python3'):
            self.assertIn(line, output)
        self.assertIn('would ship', output)

    def test_a_repo_without_a_verify_block_has_no_checks(self):
        (self.linked / 'AGENTS.md').write_text('# Repo\n')
        code, output, err, fake = self.ship()
        self.assertEqual(code, 0, err)
        self.assertIn('checks     none: AGENTS.md has no Verify block', output)
        self.assertEqual(fake.ran('bash -c'), [])


class FixShipTest(unittest.TestCase):
    """A worktree `worktree pr 7` made: detached on origin/feat/thing, which was at OLD when it was made."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ship 空間 ')
        self.addCleanup(self.temp.cleanup)
        self.main = Path(self.temp.name).resolve() / 'repo'
        self.linked = self.main / '.claude/worktrees/feat-thing'
        self.linked.mkdir(parents=True)
        (self.linked / 'AGENTS.md').write_text(VERIFY)
        self.meta = self.main / '.claude/worktrees/feat-thing.json'
        self.set_meta(base=OLD)
        self.remote = 'git ls-remote --heads origin refs/heads/feat/thing'
        self.answers = {
            'git rev-parse --show-toplevel': str(self.linked),
            'git branch --show-current': '',
            self.remote: f'{OLD}\trefs/heads/feat/thing',
            'git merge-base --is-ancestor': OK,
            'gh pr list': json.dumps([PR]),
            'bash -c': OK,
            'python3': 'worktree-guard: removed feat-thing (feat/thing); its session is back in ' + str(self.main),
        }

    def set_meta(self, **fields):
        self.meta.write_text(json.dumps({'name': 'feat-thing', 'work': 'feat/thing', **fields}))

    def ship(self, argv=(), **answers):
        with patch.object(ship.guard, 'main_of', return_value=self.main):  # the folders are not a real repo
            return land(list(argv), ship.main, **{**self.answers, **answers})

    def test_it_pushes_to_the_prs_branch_updates_the_pr_and_deletes_the_worktree(self):
        self.set_meta(pr=7, base=OLD)
        code, output, err, fake = self.ship()
        self.assertEqual(code, 0, output + err)
        self.assertIn('push       feat/thing updated', output)
        self.assertIn('pr         #7 updated', output)
        self.assertEqual(fake.ran('git push'), ['git push -q origin HEAD:refs/heads/feat/thing'])
        self.assertEqual(fake.ran('gh pr create'), [], 'no new PR')
        self.assertTrue(fake.ran('git fetch -q origin feat/thing'), 'the branch is fetched to compare')
        self.assertIn('shipped https://github.com/o/r/pull/7', output)
        self.assertIn(f'shipped feat-thing --repo {self.main}', fake.ran('python3')[0])
        calls = [c for c, _ in fake.calls]
        order = [next(i for i, c in enumerate(calls) if c.startswith(p)) for p in ('bash -c', 'git push', 'python3')]
        self.assertEqual(order, sorted(order), 'checks, push, then the worktree goes')

    def test_a_branch_that_moved_on_origin_stops_before_the_push_and_deletes_nothing(self):
        self.set_meta(pr=7, base=OLD)
        code, _, err, fake = self.ship(**{self.remote: f'{"c" * 40}\trefs/heads/feat/thing',
                                          'git merge-base --is-ancestor': FAIL})
        self.assertEqual(code, 1)
        self.assertIn('push: origin has feat/thing at ccccccc, which this worktree does not contain', err)
        self.assertEqual(fake.ran('git push') + fake.ran('python3'), [])

    def test_a_push_origin_refuses_stops_with_its_message_and_deletes_nothing(self):
        self.set_meta(pr=7, base=OLD)
        code, output, err, fake = self.ship(**{'git push': (1, '', 'remote: protected branch')})
        self.assertEqual(code, 1)
        self.assertIn('git push: remote: protected branch', err)
        self.assertNotIn('shipped', output)
        self.assertEqual(fake.ran('python3'), [])

    def test_a_pr_that_is_no_longer_open_stops_before_the_checks(self):
        self.set_meta(pr=7, base=OLD)
        for listing in ('[]', json.dumps([dict(PR, state='MERGED')]), json.dumps([dict(PR, number=9)])):
            code, _, err, fake = self.ship(**{'gh pr list': listing})
            self.assertEqual(code, 1, listing)
            self.assertIn('ship: PR #7 is not open', err)
            self.assertEqual(fake.ran('bash -c') + fake.ran('git push'), [])

    def test_nothing_on_top_of_the_branch_has_nothing_to_ship(self):
        self.set_meta(pr=7, base=TIP)
        code, _, err, fake = self.ship()
        self.assertEqual(code, 1)
        self.assertIn('nothing to ship: no commit on top of origin/feat/thing', err)
        self.assertEqual(fake.ran('bash -c') + fake.ran('git push'), [])

    def test_a_rerun_after_the_push_skips_it_and_still_deletes_the_worktree(self):
        self.set_meta(pr=7, base=OLD)
        code, output, err, fake = self.ship(**{self.remote: f'{TIP}\trefs/heads/feat/thing'})
        self.assertEqual(code, 0, err)
        self.assertIn('push       already pushed', output)
        self.assertEqual(fake.ran('git push'), [])
        self.assertTrue(fake.ran('python3'))

    def test_a_failing_check_stops_before_the_push(self):
        self.set_meta(pr=7, base=OLD)
        code, _, err, fake = self.ship(**{'bash -c shellcheck': (2, '', 'bad')})
        self.assertEqual(code, 1)
        self.assertEqual(fake.ran('git push') + fake.ran('python3'), [])

    def test_a_branch_gone_from_origin_is_not_recreated(self):
        self.set_meta(pr=7, base=OLD)
        code, _, err, fake = self.ship(**{self.remote: ''})
        self.assertEqual(code, 1)
        self.assertIn('push: origin no longer has feat/thing', err)
        self.assertEqual(fake.ran('git push'), [])

    def test_dry_run_changes_nothing(self):
        self.set_meta(pr=7, base=OLD)
        code, output, err, fake = self.ship(['--dry-run'])
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.ran('git push') + fake.ran('python3') + fake.ran('gh pr create'), [])
        self.assertIn('would  git push -q origin HEAD:refs/heads/feat/thing', output)

    def test_work_that_is_not_a_pr_fix_still_cannot_take_an_existing_branch(self):
        code, _, err, fake = self.ship(['--title', 't', '--body-file', __file__], **{'gh pr list': '[]'})
        self.assertEqual(code, 1)
        self.assertIn('push: origin already has feat/thing at bbbbbbb', err)
        self.assertEqual(fake.ran('git push'), [])
