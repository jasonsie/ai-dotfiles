"""worktree-guard: sessions sharing a checkout are kept out of each other's changes.

Run: python3 -m unittest discover -s scripts/tests -p 'test_worktree_guard.py' -v
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT

SCRIPT = ROOT / 'skills/worktree-guard/scripts/worktree_guard.py'
SPEC = importlib.util.spec_from_file_location('worktree_guard', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

ME, PARENT = os.getpid(), os.getppid()  # two live processes: two live sessions


def dead_pid():
    process = subprocess.Popen(['true'])
    process.wait()
    return process.pid


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class GitChangesTest(unittest.TestCase):
    def test_git_commands_that_change_a_tree_or_the_index(self):
        self.assertEqual(guard.git_changes('git commit -m "a b"'), [''])
        self.assertEqual(guard.git_changes('cd x && git -C sub stash'), ['sub'])
        self.assertEqual(guard.git_changes('git -c core.x=1 checkout -b y && git add .'), ['', ''])
        self.assertEqual(guard.git_changes('git status; git log | head; git stash list; git worktree add z'), [])


class GuardTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='worktree guard 空間 ')
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        self.repo = base / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q', '-b', 'main')
        git(self.repo, 'config', 'user.email', 't@example.com')
        git(self.repo, 'config', 'user.name', 'T')
        (self.repo / 'a.txt').write_text('one\n')
        (self.repo / '.gitignore').write_text('.env\nbuild/\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-q', '-m', 'init')
        self.base = git(self.repo, 'rev-parse', 'HEAD')
        patcher = patch.dict(os.environ, {guard.ENV: str(base / 'state')})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_hook(self, cli, data, kind='pre'):
        return guard.answer(cli, kind)(data)

    def edit(self, cli, session, pid, path='a.txt'):
        """`cli`'s own hook input for an edit of `path` (relative to the repo)."""
        absolute = str(self.repo / path)
        if cli == 'claude':
            data = {'tool_name': 'Edit', 'tool_input': {'file_path': absolute}}
        elif cli == 'codex':
            data = {'tool_name': 'apply_patch', 'tool_input': {'command': f'*** Begin Patch\n*** Update File: {path}\n@@\n-one\n+two\n*** End Patch\n'}}
        elif cli == 'pi':
            data = {'tool_name': 'edit', 'tool_input': {'path': path}}
        else:
            return self.run_hook('agy', {'conversationId': session, 'workspacePaths': [str(self.repo)], 'pid': pid,
                                         'toolCall': {'name': 'replace_file_content', 'args': {'TargetFile': absolute}}})
        return self.run_hook(cli, {'session_id': session, 'cwd': str(self.repo), 'pid': pid, **data})

    def shell(self, cli, session, pid, command):
        return self.run_hook(cli, {'session_id': session, 'cwd': str(self.repo), 'pid': pid,
                                   'tool_name': 'Bash' if cli in ('claude', 'codex') else 'bash',
                                   'tool_input': {'command': command}})

    def linked(self, name):
        return self.repo / '.claude/worktrees' / name

    def test_a_lone_session_claims_its_worktree_and_is_left_alone(self):
        self.assertIsNone(self.edit('claude', 'aaaa1111', ME))
        self.assertIsNone(self.edit('claude', 'aaaa1111', ME))
        self.assertIsNone(self.shell('claude', 'aaaa1111', ME, 'git commit -am x'))
        claim = json.loads(guard.claim_file(self.repo).read_text())
        self.assertEqual((claim['session'], claim['cli'], claim['pid']), ('aaaa1111', 'claude', ME))

    def test_a_second_codex_session_is_moved_into_a_linked_worktree(self):
        self.edit('claude', 'aaaa1111', ME)
        reply = self.edit('codex', 'bbbb2222', PARENT)['hookSpecificOutput']
        linked = self.linked('codex-bbbb2222')
        self.assertEqual(reply['permissionDecision'], 'allow')
        self.assertIn('*** Update File: .claude/worktrees/codex-bbbb2222/a.txt', reply['updatedInput']['command'])
        self.assertIn('is busy: claude session aaaa1111', reply['additionalContext'])
        self.assertIn('branch agent/codex-bbbb2222, from main at ' + self.base[:7], reply['additionalContext'])
        self.assertEqual(git(linked, 'rev-parse', 'HEAD'), self.base)
        self.assertEqual(git(linked, 'symbolic-ref', '--short', 'HEAD'), 'agent/codex-bbbb2222')
        self.assertIn('/.claude/worktrees/', (self.repo / '.git/info/exclude').read_text())
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')  # the linked worktree stays out of it
        # From now on its calls follow it there; no second worktree is made.
        again = self.edit('codex', 'bbbb2222', PARENT)['hookSpecificOutput']
        self.assertIn('.claude/worktrees/codex-bbbb2222/a.txt', again['updatedInput']['command'])
        self.assertNotIn('additionalContext', again)
        command = self.shell('codex', 'bbbb2222', PARENT, f'git commit -am x && cat {self.repo}/a.txt')
        steered = command['hookSpecificOutput']['updatedInput']['command']
        self.assertTrue(steered.startswith(f"cd '{linked}' && git commit"), steered)
        self.assertIn(f'cat {linked}/a.txt', steered)
        self.assertEqual(sorted(p.name for p in (self.repo / '.claude/worktrees').iterdir()), ['codex-bbbb2222'])

    def test_claude_is_told_to_enter_the_linked_worktree(self):
        self.edit('codex', 'aaaa1111', ME)
        reply = self.edit('claude', 'cccc3333', PARENT)['hookSpecificOutput']
        linked = self.linked('claude-cccc3333')
        self.assertEqual(reply['permissionDecision'], 'deny')
        self.assertIn(f'Call EnterWorktree with path "{linked}"', reply['permissionDecisionReason'])
        self.assertIn('git merge agent/claude-cccc3333', reply['permissionDecisionReason'])
        self.assertTrue(linked.is_dir())
        entered = self.run_hook('claude', {'session_id': 'cccc3333', 'cwd': str(linked), 'pid': PARENT,
                                           'tool_name': 'Write', 'tool_input': {'file_path': str(linked / 'b.txt')}})
        self.assertIsNone(entered)

    def test_pi_and_agy_reads_and_writes_follow_the_move(self):
        self.edit('claude', 'aaaa1111', ME)
        moved = self.edit('pi', 'dddd4444', PARENT)
        self.assertEqual(moved['input'], {'path': str(self.linked('pi-dddd4444') / 'a.txt')})
        self.assertIn('is busy', moved['note'])
        read = self.run_hook('pi', {'session_id': 'dddd4444', 'cwd': str(self.repo), 'pid': PARENT,
                                    'tool_name': 'read', 'tool_input': {'path': 'a.txt', 'offset': 1}})
        self.assertEqual(read, {'input': {'path': str(self.linked('pi-dddd4444') / 'a.txt'), 'offset': 1}})
        agy = self.edit('agy', 'eeee5555', PARENT)
        self.assertEqual(agy['decision'], 'allow')
        self.assertEqual(agy['overwrite']['TargetFile'], str(self.linked('agy-eeee5555') / 'a.txt'))
        view = self.run_hook('agy', {'conversationId': 'eeee5555', 'workspacePaths': [str(self.repo)], 'pid': PARENT,
                                     'toolCall': {'name': 'run_command', 'args': {'CommandLine': 'ls', 'Cwd': str(self.repo)}}})
        self.assertEqual(view['overwrite']['Cwd'], str(self.linked('agy-eeee5555')))

    def test_a_dead_owner_is_replaced_and_its_leftovers_named_once(self):
        self.edit('claude', 'aaaa1111', dead_pid())
        (self.repo / 'a.txt').write_text('half done\n')
        note = self.edit('codex', 'bbbb2222', ME)['hookSpecificOutput']['additionalContext']
        self.assertIn('already had 1 uncommitted change(s)', note)
        self.assertIn('last owner: claude session aaaa1111, no longer running', note)
        self.assertIsNone(self.edit('codex', 'bbbb2222', ME))
        self.assertFalse((self.repo / '.claude').exists())  # no clash, no linked worktree

    def test_session_end_releases_and_a_shared_worktree_lets_anyone_edit(self):
        self.edit('claude', 'aaaa1111', ME)
        self.assertIsNone(self.run_hook('claude', {'session_id': 'aaaa1111'}, kind='end'))
        self.assertIsNone(self.edit('codex', 'bbbb2222', PARENT))  # free again: claimed, no move
        path = guard.claim_file(self.repo)
        path.write_text(json.dumps({**json.loads(path.read_text()), 'shared': True}))
        self.assertIsNone(self.edit('pi', 'ffff6666', ME))
        self.assertFalse((self.repo / '.claude').exists())

    def test_overrides_are_for_people_and_outside_git_nothing_happens(self):
        reply = self.shell('codex', 'bbbb2222', ME, 'ai-dotfiles worktree release')
        self.assertEqual(reply['hookSpecificOutput']['permissionDecision'], 'deny')
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(outside.rmdir)
        self.assertIsNone(self.run_hook('claude', {'session_id': 's', 'cwd': str(outside), 'pid': ME,
                                                   'tool_name': 'Write', 'tool_input': {'file_path': str(outside / 'x')}}))

    def test_worktreeinclude_copies_gitignored_files_only(self):
        (self.repo / '.worktreeinclude').write_text('.env\na.txt\n')
        git(self.repo, 'add', '.worktreeinclude')
        git(self.repo, 'commit', '-q', '-m', 'include')
        (self.repo / '.env').write_text('SECRET=1\n')
        (self.repo / 'build').mkdir()
        (self.repo / 'build/x').write_text('x\n')
        self.edit('claude', 'aaaa1111', ME)
        self.edit('codex', 'bbbb2222', PARENT)
        linked = self.linked('codex-bbbb2222')
        self.assertEqual((linked / '.env').read_text(), 'SECRET=1\n')
        self.assertFalse((linked / 'build').exists())

    def test_a_failure_says_the_edit_was_not_protected(self):
        broken = Path(tempfile.mkstemp()[1])  # the state "folder" is a file: claims cannot be kept
        self.addCleanup(broken.unlink)
        data = {'session_id': 's', 'cwd': str(self.repo), 'tool_name': 'Edit',
                'tool_input': {'file_path': str(self.repo / 'a.txt')}}
        run = subprocess.run([sys.executable, str(SCRIPT), 'hook', 'pre', '--cli', 'claude'], input=json.dumps(data),
                             capture_output=True, text=True, env={**os.environ, guard.ENV: str(broken)})
        self.assertEqual((run.returncode, run.stderr), (0, ''))
        self.assertIn('this edit was not protected', json.loads(run.stdout)['hookSpecificOutput']['additionalContext'])

    def test_the_command_never_fails_or_speaks_outside_json(self):
        for stdin, args in (('not json', ['hook', 'pre', '--cli', 'codex']), ('[]', ['hook', 'end', '--cli', 'claude']),
                            ('{}', ['hook', 'bogus', '--cli', 'claude']), ('{}', ['hook', 'pre'])):
            run = subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True)
            self.assertEqual((run.returncode, run.stderr), (0, ''), args)
            if run.stdout.strip():
                json.loads(run.stdout)


if __name__ == '__main__':
    unittest.main()
