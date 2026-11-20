"""worktree-flow: `/worktree-flow` toggles a repo's worktree flow once the person says yes in a dialog."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT

SCRIPT = ROOT / 'skills/worktree-flow/scripts/worktree_flow.py'
SPEC = importlib.util.spec_from_file_location('worktree_flow', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
flow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flow)


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True)


class ToggleTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve() / 'zkfy'
        self.repo.mkdir()
        git(self.repo, 'init', '-q', '-b', 'main')
        self.asked = []

    def toggle(self, answer, repo=None):
        """Run the skill's script with the dialog answering `answer`; (status, output)."""
        def ask(question):
            self.asked.append(question)
            return answer
        out = io.StringIO()
        with patch.object(flow, 'ask', ask), redirect_stdout(out), redirect_stderr(out):
            status = flow.main(['--repo', str(repo or self.repo)])
        return status, out.getvalue()

    def flow_setting(self):
        return git(self.repo, 'config', '--local', '--get', 'worktree-guard.flow').stdout.strip()

    def test_yes_turns_a_repo_that_is_off_on(self):
        status, output = self.toggle(True)
        self.assertEqual(status, 0)
        self.assertEqual(self.flow_setting(), 'true')
        self.assertEqual(self.asked, ['Turn the worktree flow on in zkfy?'])
        self.assertIn('flow: on', output)

    def test_yes_turns_a_repo_that_is_on_off(self):
        git(self.repo, 'config', '--local', 'worktree-guard.flow', 'true')
        status, output = self.toggle(True)
        self.assertEqual(status, 0)
        self.assertEqual(self.flow_setting(), '')
        self.assertEqual(self.asked, ['Turn the worktree flow off in zkfy?'])
        self.assertIn('flow: off', output)

    def test_cancel_or_no_answer_changes_nothing(self):
        for setting in (None, 'true'):
            if setting:
                git(self.repo, 'config', '--local', 'worktree-guard.flow', setting)
            status, output = self.toggle(False)
            self.assertEqual(status, 1)
            self.assertEqual(self.flow_setting(), setting or '')
            self.assertIn('unchanged, the person said no', output)

    def test_no_dialog_changes_nothing_and_says_why(self):
        status, output = self.toggle(None)
        self.assertEqual(status, 1)
        self.assertEqual(self.flow_setting(), '')
        self.assertIn('no dialog could open', output)

    def test_a_linked_worktree_switches_its_whole_repo(self):
        (self.repo / 'f.txt').write_text('x\n')
        git(self.repo, 'add', '.')
        git(self.repo, '-c', 'user.email=t@example.com', '-c', 'user.name=T', 'commit', '-q', '-m', 'init')
        linked = self.repo / '.claude/worktrees/fix-x'
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(linked))
        self.assertEqual(self.toggle(True, repo=linked)[0], 0)
        self.assertEqual(self.flow_setting(), 'true')
        self.assertEqual(self.asked, ['Turn the worktree flow on in zkfy?'])

    def test_outside_a_repository_says_so(self):
        outside = Path(tempfile.mkdtemp())
        with self.assertRaises(SystemExit):
            self.toggle(True, repo=outside)
        self.assertEqual(self.asked, [])


if __name__ == '__main__':
    unittest.main()
