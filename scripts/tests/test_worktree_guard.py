"""worktree-guard: sessions sharing a checkout are kept out of each other's changes.

Run: python3 -m unittest discover -s scripts/tests -p 'test_worktree_guard.py' -v
"""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
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


class Repo(unittest.TestCase):
    """A temp repo with one commit, guard state of its own, and each CLI's hook input."""

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


class GuardTest(Repo):
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
        self.assertEqual(sorted(p.name for p in (self.repo / '.claude/worktrees').iterdir()),
                         ['codex-bbbb2222', 'codex-bbbb2222.json'])
        meta = json.loads((self.repo / '.claude/worktrees/codex-bbbb2222.json').read_text())
        self.assertEqual({k: meta[k] for k in ('branch', 'from', 'base', 'cli', 'session')},
                         {'branch': 'agent/codex-bbbb2222', 'from': 'main', 'base': self.base, 'cli': 'codex',
                          'session': 'bbbb2222'})

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

    def test_a_session_that_names_the_repo_through_a_symlink_is_steered_too(self):
        alias = self.repo.parent / 'alias'
        alias.symlink_to(self.repo)  # like /var -> /private/var on macOS, or a symlinked project folder
        self.edit('claude', 'aaaa1111', ME)
        reply = self.run_hook('pi', {'session_id': 'dddd4444', 'cwd': str(alias), 'pid': PARENT,
                                     'tool_name': 'write', 'tool_input': {'path': 'a.txt', 'content': 'x'}})
        self.assertEqual(reply['input']['path'], str(self.linked('pi-dddd4444') / 'a.txt'))
        shell = self.run_hook('pi', {'session_id': 'dddd4444', 'cwd': str(alias), 'pid': PARENT,
                                     'tool_name': 'bash', 'tool_input': {'command': f'cat {alias}/a.txt'}})
        self.assertEqual(shell['input']['command'],
                         f"cd '{self.linked('pi-dddd4444')}' && cat {self.linked('pi-dddd4444')}/a.txt")

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


class CommandsTest(Repo):
    """list, done, rm, prune, release and share, on a repo where codex-bbbb2222 was moved aside."""

    def setUp(self):
        super().setUp()
        self.edit('claude', 'aaaa1111', ME)
        self.edit('codex', 'bbbb2222', PARENT)
        self.wt = self.linked('codex-bbbb2222')

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = guard.main(list(args))
        return status, out.getvalue() + err.getvalue()

    def work(self, text='two\n'):
        (self.wt / 'a.txt').write_text(text)
        git(self.wt, 'commit', '-q', '-am', 'change a')

    def end(self, session='bbbb2222'):
        self.run_hook('codex', {'session_id': session}, kind='end')

    def test_list_names_branch_owner_and_merge_state(self):
        status, out = self.cli('list', '--repo', str(self.repo))
        self.assertEqual(status, 0)
        self.assertIn('codex-bbbb2222  agent/codex-bbbb2222  from main  no commits yet  owner: codex session bbbb2222', out)
        self.work()
        self.assertIn('from main  not merged  owner:', self.cli('list', '--repo', str(self.repo))[1])

    def test_done_then_rm_waits_for_the_owner_and_the_merge_then_archives(self):
        self.work()
        self.assertEqual(self.cli('done', 'make a.txt say two', '--path', str(self.wt))[0], 0)
        status, out = self.cli('rm', 'codex-bbbb2222', '--repo', str(self.repo))
        self.assertEqual(status, 1)
        self.assertIn('codex session bbbb2222 still works there', out)
        self.assertIn('neither merged into main nor pushed', out)
        self.end()
        git(self.repo, 'merge', '-q', '--no-ff', '-m', 'merge', 'agent/codex-bbbb2222')
        status, out = self.cli('rm', 'codex-bbbb2222', '--repo', str(self.repo))
        self.assertEqual(status, 0, out)
        self.assertIn('archived as archive/codex-bbbb2222', out)
        message = git(self.repo, 'tag', '-l', '--format=%(contents)', 'archive/codex-bbbb2222')
        today = time.strftime('%b ') + str(time.localtime().tm_mday) + time.strftime(', %Y')
        self.assertTrue(message.startswith(f'Archive of branch agent/codex-bbbb2222 ({today}; make a.txt say two), '
                                           'kept before the branch was merged and deleted.'), message)
        self.assertIn('Agent: codex, session bbbb2222; redirected from branch main.', message)
        self.assertFalse(self.wt.exists())
        self.assertEqual(git(self.repo, 'branch', '--list', 'agent/*'), '')
        self.assertFalse((self.repo / '.claude/worktrees/codex-bbbb2222.json').exists())

    def test_rm_keeps_uncommitted_work_unless_forced(self):
        self.work()
        (self.wt / 'b.txt').write_text('new\n')
        self.end()
        status, out = self.cli('rm', 'codex-bbbb2222', '--repo', str(self.repo))
        self.assertEqual(status, 1)
        self.assertIn('1 uncommitted change(s)', out)
        self.assertTrue(self.wt.exists())
        git(self.repo, 'tag', 'archive/codex-bbbb2222')  # the plain name is taken: a date goes on
        status, out = self.cli('rm', 'codex-bbbb2222', '--force', '--repo', str(self.repo))
        self.assertEqual(status, 0, out)
        tag = 'archive/codex-bbbb2222-' + time.strftime('%Y-%m-%d')
        self.assertIn(tag, out)
        self.assertIn('kept before the branch was deleted unmerged.', git(self.repo, 'tag', '-l', '--format=%(contents)', tag))
        self.assertFalse(self.wt.exists())

    def test_prune_removes_only_merged_clean_unowned_worktrees(self):
        self.work()
        git(self.repo, 'merge', '-q', '--no-ff', '-m', 'merge', 'agent/codex-bbbb2222')
        self.assertIn('nothing to prune', self.cli('prune', '--repo', str(self.repo))[1])  # still owned
        self.end()
        status, out = self.cli('prune', '--repo', str(self.repo))
        self.assertIn('removed codex-bbbb2222', out)
        self.assertFalse(self.wt.exists())

    def test_release_and_share(self):
        self.assertIn('released', self.cli('release', str(self.repo))[1])
        self.assertIn('nobody owns', self.cli('release', str(self.repo))[1])
        self.edit('claude', 'aaaa1111', ME)
        self.assertIn('any session may edit', self.cli('share', str(self.repo))[1])
        self.assertIsNone(self.edit('pi', 'ffff6666', PARENT))  # shared: no move

    def test_done_only_inside_a_linked_worktree(self):
        status, out = self.cli('done', 'x', '--path', str(self.repo))
        self.assertEqual(status, 1)
        self.assertIn('inside a linked worktree', out)


if __name__ == '__main__':
    unittest.main()
