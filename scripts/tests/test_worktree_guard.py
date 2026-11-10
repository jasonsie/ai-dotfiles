"""worktree-guard: sessions sharing a checkout are kept out of each other's changes.

Run: python3 -m unittest discover -s scripts/tests -p 'test_worktree_guard.py' -v
"""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
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
        self.assertEqual(guard.git_changes('cd x && git -C sub stash'), ['x/sub'])
        self.assertEqual(guard.git_changes('git -c core.x=1 checkout -b y && git add .'), ['', ''])
        self.assertEqual(guard.git_changes('git status; git log | head; git stash list; git worktree add z'), [])

    def test_a_leading_cd_moves_the_base_for_the_commands_after_it(self):
        self.assertEqual(guard.git_changes('cd repo && git commit -am x'), ['repo'])
        self.assertEqual(guard.git_changes('cd /abs/web && git status --short && git checkout -b y main'), ['/abs/web'])
        self.assertEqual(guard.git_changes('cd a; cd b && git add .'), ['a/b'])
        self.assertEqual(guard.git_changes('cd a | git commit'), [''])  # a pipe forgets the cd


class GuardCallsTest(unittest.TestCase):
    """The worktree commands a shell line runs, as (verb, arguments): the one reading that
    person_only and the first-edit naming share."""

    def verbs(self, command):
        return [verb for verb, _ in guard.guard_calls(command)]

    def test_a_command_in_command_position_is_found_with_its_arguments(self):
        self.assertEqual(guard.guard_calls('ai-dotfiles worktree new fix/x'), [('new', ['fix/x'])])
        self.assertEqual(guard.guard_calls('cd /x && FOO=1 ai-dotfiles worktree new --repo . fix/x; ls'),
                         [('new', ['--repo', '.', 'fix/x', ';', 'ls'])])
        self.assertEqual(self.verbs('sh -c "ai-dotfiles worktree list"'), ['list'])
        self.assertEqual(self.verbs('python3 skills/worktree-guard/scripts/worktree_guard.py rm a'), ['rm'])

    def test_text_that_only_mentions_a_command_is_not_one(self):
        for command in ('echo "ai-dotfiles worktree new fix/x"', 'cat <<EOF\nai-dotfiles worktree new x\nEOF',
                        'echo ai-dotfiles worktree new x # ai-dotfiles worktree new y', 'ai-dotfiles worktree'):
            self.assertEqual(guard.guard_calls(command), [], command)

    def test_the_name_is_the_first_argument_that_is_not_an_option(self):
        self.assertEqual(guard.new_names('ai-dotfiles worktree new fix/x'), ['fix/x'])
        self.assertEqual(guard.new_names('ai-dotfiles worktree new --repo /a b/c && ls x/y'), ['b/c'])
        self.assertEqual(guard.new_names('ai-dotfiles worktree list; ai-dotfiles worktree new a/b'), ['a/b'])
        self.assertEqual(guard.new_names('ai-dotfiles worktree new'), [])

    def test_a_pr_fix_is_named_by_its_number_apart_from_any_work_name(self):
        self.assertEqual(guard.new_names('ai-dotfiles worktree pr 7'), ['#7'])
        self.assertEqual(guard.new_names('cd x && ai-dotfiles worktree pr --repo . 12 && ls'), ['#12'])
        self.assertEqual(guard.new_names('ai-dotfiles worktree pr'), [])


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

    def plain(self, reply):
        """Whether `reply` lets the call through untouched and unannounced, in any CLI's format."""
        return reply is None or reply == {'decision': 'allow'}


class GuardTest(Repo):
    def test_in_a_repo_that_is_off_every_edit_passes_with_no_claim_and_no_message(self):
        other = self.repo.parent / 'other'
        other.mkdir()
        git(other, 'init', '-q', '-b', 'main')
        git(other, 'config', 'user.email', 't@example.com')
        git(other, 'config', 'user.name', 'T')
        (other / 'f.txt').write_text('x\n')
        git(other, 'add', '.')
        git(other, 'commit', '-q', '-m', 'init')
        for cli, session, pid in (('claude', 'aaaa1111', ME), ('codex', 'bbbb2222', PARENT), ('pi', 'dddd4444', ME),
                                  ('agy', 'eeee5555', PARENT), ('claude', 'cccc3333', PARENT)):
            for _ in range(2):
                self.assertTrue(self.plain(self.edit(cli, session, pid)), (cli, session))
            if cli != 'agy':
                self.assertTrue(self.plain(self.shell(cli, session, pid, 'git commit -am x')), (cli, session))
        reply = self.shell('claude', 'aaaa1111', ME, f'cd {shlex.quote(str(other))} && git commit --allow-empty -m x')
        self.assertIsNone(reply)
        self.assertEqual(list(guard.state_root().glob('claims/*.json')), [])  # nobody owns anything
        self.assertFalse((self.repo / '.claude').exists())  # nothing was made
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')

    def test_session_end_releases_and_a_shared_worktree_lets_anyone_edit(self):
        git(self.repo, 'config', '--local', guard.FLOW_KEY, 'true')
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(self.linked('fix-x')))
        inside = '.claude/worktrees/fix-x/a.txt'
        self.assertIsNone(self.edit('claude', 'aaaa1111', ME, path=inside))
        self.assertTrue(self.edit('codex', 'bbbb2222', PARENT, path=inside))  # busy: refused
        self.assertIsNone(self.run_hook('claude', {'session_id': 'aaaa1111'}, kind='end'))
        self.assertIsNone(self.edit('codex', 'bbbb2222', PARENT, path=inside))  # free again
        path = guard.claim_file(self.linked('fix-x'))
        path.write_text(json.dumps({**json.loads(path.read_text()), 'shared': True}))
        self.assertIsNone(self.edit('pi', 'ffff6666', ME, path=inside))

    def test_overrides_are_for_people_and_outside_git_nothing_happens(self):
        reply = self.shell('codex', 'bbbb2222', ME, 'ai-dotfiles worktree release')
        self.assertEqual(reply['hookSpecificOutput']['permissionDecision'], 'deny')
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(outside.rmdir)
        self.assertIsNone(self.run_hook('claude', {'session_id': 's', 'cwd': str(outside), 'pid': ME,
                                                   'tool_name': 'Write', 'tool_input': {'file_path': str(outside / 'x')}}))

    def test_make_worktree_without_a_branch_detaches_and_keeps_the_rest(self):
        (self.repo / '.worktreeinclude').write_text('.env\n')
        git(self.repo, 'add', '.worktreeinclude')
        git(self.repo, 'commit', '-q', '-m', 'include')
        (self.repo / '.env').write_text('SECRET=1\n')
        (self.repo / 'build').mkdir()
        (self.repo / 'build/x').write_text('x\n')
        head = git(self.repo, 'rev-parse', 'HEAD')
        me = {'session': 's', 'cli': 'claude', 'pid': ME, 'started': guard.started(ME)}
        linked = guard.make_worktree(self.repo, 'fix-x', head, None, source=self.repo, owner=me,
                                     table=guard.process_table())
        self.assertEqual(linked, self.linked('fix-x'))
        self.assertEqual(git(linked, 'rev-parse', 'HEAD'), head)
        self.assertEqual(subprocess.run(['git', '-C', str(linked), 'symbolic-ref', '-q', 'HEAD']).returncode, 1)
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')
        self.assertEqual((linked / '.env').read_text(), 'SECRET=1\n')
        self.assertFalse((linked / 'build').exists())  # only what .worktreeinclude lists
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')
        self.assertIsNone(guard.read_meta(self.repo, 'fix-x')['branch'])
        self.assertEqual(guard.read_claim(guard.claim_file(linked))['session'], 's')

    def test_a_failure_says_the_edit_was_not_protected(self):
        git(self.repo, 'config', '--local', guard.FLOW_KEY, 'true')
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(self.linked('fix-x')))
        broken = Path(tempfile.mkstemp()[1])  # the state "folder" is a file: claims cannot be kept
        self.addCleanup(broken.unlink)
        data = {'session_id': 's', 'cwd': str(self.repo), 'tool_name': 'Edit',
                'tool_input': {'file_path': str(self.linked('fix-x') / 'a.txt')}}
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
    """list, done, rm, prune, release and share, on a worktree of the retired agent/<cli>-<id8> kind
    (the guard no longer makes them; ones made before still can be listed and removed)."""

    def setUp(self):
        super().setUp()
        owner = {'session': 'bbbb2222', 'cli': 'codex', 'pid': PARENT, 'started': guard.started(PARENT)}
        self.wt = guard.make_worktree(self.repo, 'codex-bbbb2222', self.base, 'agent/codex-bbbb2222',
                                      source=self.repo, owner=owner, table=guard.process_table(),
                                      meta={'from': 'main', 'busy': str(self.repo), 'cli': 'codex',
                                            'session': 'bbbb2222', 'model': ''})

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

    def make_stale(self):
        """Remove the linked worktree and its branch by hand, leaving only the .json record."""
        git(self.repo, 'worktree', 'remove', '--force', str(self.wt))
        git(self.repo, 'branch', '-D', 'agent/codex-bbbb2222')
        self.end()
        self.assertTrue((self.repo / '.claude/worktrees/codex-bbbb2222.json').exists())

    def test_prune_drops_a_sidecar_whose_worktree_and_branch_are_gone(self):
        self.make_stale()
        status, out = self.cli('prune', '--repo', str(self.repo))
        self.assertEqual(status, 0, out)
        self.assertIn('removed codex-bbbb2222', out)
        self.assertIn('stale record', out)
        self.assertFalse((self.repo / '.claude/worktrees/codex-bbbb2222.json').exists())
        self.assertIn('no linked worktrees', self.cli('list', '--repo', str(self.repo))[1])

    def test_rm_on_a_stale_sidecar_does_not_raise(self):
        self.make_stale()
        status, out = self.cli('rm', 'codex-bbbb2222', '--repo', str(self.repo))  # no --force needed
        self.assertEqual(status, 0, out)
        self.assertIn('already gone', out)
        self.assertFalse((self.repo / '.claude/worktrees/codex-bbbb2222.json').exists())
        # list over a stale sidecar must not crash either
        status, out = self.cli('list', '--repo', str(self.repo))
        self.assertEqual(status, 0, out)

    def test_a_missing_folder_with_a_live_branch_is_still_kept(self):
        self.work()  # a commit of its own, so the branch is unmerged
        git(self.repo, 'worktree', 'remove', '--force', str(self.wt))  # folder gone, branch agent/codex-bbbb2222 stays
        self.end()
        status, out = self.cli('rm', 'codex-bbbb2222', '--repo', str(self.repo))
        self.assertEqual(status, 1, out)  # unmerged branch: kept, not treated as stale
        self.assertIn('neither merged into main nor pushed', out)
        self.assertTrue((self.repo / '.claude/worktrees/codex-bbbb2222.json').exists())

    def test_release_and_share(self):
        git(self.repo, 'config', '--local', guard.FLOW_KEY, 'true')  # a repo that is off keeps no owners
        inside = '.claude/worktrees/codex-bbbb2222/a.txt'
        self.assertIn('released', self.cli('release', str(self.wt))[1])
        self.assertIn('nobody owns', self.cli('release', str(self.wt))[1])
        self.assertIsNone(self.edit('claude', 'aaaa1111', ME, path=inside))  # first edit: owns it again
        self.assertTrue(self.edit('pi', 'ffff6666', PARENT, path=inside)['block'])  # another session: refused
        self.assertIn('any session may edit', self.cli('share', str(self.wt))[1])
        self.assertIsNone(self.edit('pi', 'ffff6666', PARENT, path=inside))

    def test_done_only_inside_a_linked_worktree(self):
        status, out = self.cli('done', 'x', '--path', str(self.repo))
        self.assertEqual(status, 1)
        self.assertIn('inside a linked worktree', out)


class OriginRepo(Repo):
    """A repo whose origin is a local bare repo, so fetch, push and ls-remote work offline."""

    def setUp(self):
        super().setUp()
        base = self.repo.parent
        self.origin = base / 'origin.git'
        git(base, 'init', '-q', '--bare', '-b', 'main', str(self.origin))
        git(self.repo, 'remote', 'add', 'origin', str(self.origin))
        git(self.repo, 'push', '-q', '-u', 'origin', 'main')
        git(self.repo, 'remote', 'set-head', 'origin', 'main')

    def advance_origin(self, name='b.txt'):
        """Another clone pushes a commit, so the main checkout lags (spec D2); returns its sha."""
        clone = self.repo.parent / 'other'
        git(self.repo.parent, 'clone', '-q', str(self.origin), str(clone))
        git(clone, 'config', 'user.email', 't@example.com')
        git(clone, 'config', 'user.name', 'T')
        (clone / name).write_text('x\n')
        git(clone, 'add', '.')
        git(clone, 'commit', '-q', '-m', 'ahead')
        git(clone, 'push', '-q', 'origin', 'main')
        return git(clone, 'rev-parse', 'HEAD')

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = guard.main(list(args))
        return status, out.getvalue() + err.getvalue()


class DetachedTest(OriginRepo):
    """list, rm and prune on a worktree with no branch: where the work name stands in for one."""

    def setUp(self):
        super().setUp()
        me = {'session': 's1', 'cli': 'claude', 'pid': ME, 'started': guard.started(ME)}
        self.wt = guard.make_worktree(self.repo, 'fix-x', self.base, None, source=self.repo, owner=me,
                                      table=guard.process_table(), meta={'work': 'fix/x', 'from': 'origin/main'})

    def work(self):
        (self.wt / 'a.txt').write_text('two\n')
        git(self.wt, 'commit', '-q', '-am', 'change a')
        return git(self.wt, 'rev-parse', 'HEAD')

    def test_list_names_the_work_where_a_branch_would_be(self):
        status, out = self.cli('list', '--repo', str(self.repo))
        self.assertEqual(status, 0, out)
        self.assertIn('fix-x  fix/x (no branch)  from origin/main  no commits yet  owner: claude session s1', out)
        self.work()
        self.assertIn('from origin/main  not merged  owner:', self.cli('list', '--repo', str(self.repo))[1])

    def test_rm_keeps_unpushed_commits_unless_forced_then_tags_the_tip(self):
        tip = self.work()
        guard.release('s1')
        status, out = self.cli('rm', 'fix-x', '--repo', str(self.repo))
        self.assertEqual(status, 1)
        self.assertIn('fix/x is neither merged into origin/main nor pushed', out)
        status, out = self.cli('rm', 'fix-x', '--force', '--repo', str(self.repo))
        self.assertEqual(status, 0, out)
        self.assertIn('removed fix-x; archived as archive/x', out)
        self.assertEqual(git(self.repo, 'rev-list', '-n', '1', 'archive/x'), tip)
        self.assertFalse(self.wt.exists())
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')

    def test_rm_lets_go_of_pushed_work_and_of_work_with_no_commits(self):
        tip = self.work()
        guard.release('s1')
        git(self.wt, 'push', '-q', 'origin', 'HEAD:refs/heads/fix/x')
        status, out = self.cli('rm', 'fix-x', '--repo', str(self.repo))
        self.assertEqual(status, 0, out)
        self.assertEqual(git(self.repo, 'rev-list', '-n', '1', 'archive/x'), tip)
        self.assertIn('archive/x pushed to origin', out)
        guard.make_worktree(self.repo, 'fix-y', self.base, None, source=self.repo, meta={'work': 'fix/y'})
        status, out = self.cli('rm', 'fix-y', '--repo', str(self.repo))
        self.assertEqual(status, 0, out)
        self.assertIn('no commits of its own, no tag', out)

    def test_prune_removes_a_clean_unowned_one_and_keeps_the_rest(self):
        guard.make_worktree(self.repo, 'fix-y', self.base, None, source=self.repo, meta={'work': 'fix/y'})
        self.assertIn('removed fix-y', self.cli('prune', '--repo', str(self.repo))[1])
        self.assertTrue(self.wt.exists())  # still owned


class SweepTest(OriginRepo):
    """Leftovers: worktrees whose owner is gone. Those with nothing to lose go when a worktree is
    made and when a session ends; the rest stay."""

    def setUp(self):
        super().setUp()
        self.n = 0

    def leftover(self, **meta):
        """A detached worktree at origin/main whose owner died."""
        self.n += 1
        dead = {'session': f'old{self.n}', 'cli': 'claude', 'pid': dead_pid(), 'started': ''}
        return guard.make_worktree(self.repo, f'fix-l{self.n}', self.base, None, source=self.repo, owner=dead,
                                   table=guard.process_table(), meta={'work': f'fix/l{self.n}', 'from': 'origin/main', **meta})

    def commit(self, wt):
        (wt / 'a.txt').write_text('two\n')
        git(wt, 'commit', '-q', '-am', 'change a')

    def sweep(self):
        """Make a worktree, which sweeps first."""
        return self.cli('new', 'fix/fresh', '--repo', str(self.repo))

    def test_a_leftover_with_nothing_to_lose_goes_when_a_worktree_is_made(self):
        wt = self.leftover()
        status, out = self.sweep()
        self.assertEqual(status, 0, out)
        self.assertIn(f'removed {wt.name}', out)
        self.assertFalse(wt.exists())
        self.assertIsNone(guard.read_meta(self.repo, wt.name))
        self.assertFalse(guard.claim_file(wt).exists())
        self.assertTrue(self.linked('fix-fresh').is_dir())

    def test_a_leftover_with_work_at_risk_is_never_deleted(self):
        dirty = self.leftover()  # each is made, and so sweeps, before the next
        (dirty / 'a.txt').write_text('edited\n')
        untracked = self.leftover()
        (untracked / 'new.txt').write_text('x\n')
        ahead = self.leftover()
        self.commit(ahead)
        self.assertEqual(self.sweep()[0], 0)
        for wt in (dirty, untracked, ahead):
            self.assertTrue(wt.is_dir(), wt.name)
        self.run_hook('claude', {'session_id': 'x'}, kind='end')
        for wt in (dirty, untracked, ahead):
            self.assertTrue(wt.is_dir(), wt.name)

    def test_commits_pushed_to_any_remote_ref_are_nothing_to_lose(self):
        wt = self.leftover()
        self.commit(wt)
        git(wt, 'push', '-q', 'origin', 'HEAD:refs/heads/fix/l1')
        self.sweep()
        self.assertFalse(wt.exists())

    def test_a_worktree_with_a_live_owner_stays(self):
        me = {'session': 's1', 'cli': 'claude', 'pid': ME, 'started': guard.started(ME)}
        wt = guard.make_worktree(self.repo, 'fix-live', self.base, None, source=self.repo, owner=me,
                                 table=guard.process_table(), meta={'work': 'fix/live'})
        self.sweep()
        self.assertTrue(wt.is_dir())

    def test_a_fresh_worktree_nobody_claimed_yet_stays_until_it_is_old(self):
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(self.linked('fix-new')))
        meta = {'name': 'fix-new', 'work': 'fix/new', 'branch': None, 'base': self.base}
        guard.write_meta(self.repo, 'fix-new', {**meta, 'created': int(time.time())})
        self.sweep()
        self.assertTrue(self.linked('fix-new').is_dir())
        guard.write_meta(self.repo, 'fix-new', {**meta, 'created': int(time.time()) - 7200})
        self.sweep()
        self.assertFalse(self.linked('fix-new').exists())

    def test_a_session_ending_takes_its_own_clean_worktree_with_it(self):
        me = {'session': 's1', 'cli': 'claude', 'pid': ME, 'started': guard.started(ME)}
        table = guard.process_table()
        clean = guard.make_worktree(self.repo, 'fix-a', self.base, None, source=self.repo, owner=me, table=table,
                                    meta={'work': 'fix/a'})
        busy = guard.make_worktree(self.repo, 'fix-b', self.base, None, source=self.repo, owner=me, table=table,
                                   meta={'work': 'fix/b'})
        (busy / 'a.txt').write_text('edited\n')
        self.run_hook('claude', {'session_id': 's1'}, kind='end')
        self.assertFalse(clean.exists())
        self.assertTrue(busy.is_dir())
        self.assertFalse(guard.claim_file(busy).exists())  # released: the owner is gone

    def test_a_session_ending_sweeps_the_repos_it_worked_in_not_only_ones_it_released(self):
        """It ran `worktree new` (its worktree shipped and went, so no claim is left to release), or
        was stopped at the main checkout: either way the repo it touched is swept at its end."""
        git(self.repo, 'config', '--local', guard.FLOW_KEY, 'true')
        for session, command in (('s1', 'ai-dotfiles worktree new fix/z'), ('s2', 'ai-dotfiles worktree pr 7')):
            wt = self.leftover()
            self.shell('claude', session, ME, command)
            self.assertTrue(wt.is_dir())  # a hook call does not sweep
            self.run_hook('claude', {'session_id': session}, kind='end')
            self.assertFalse(wt.exists(), command)
        wt = self.leftover()
        self.assertTrue(self.edit('claude', 's3', ME))  # stopped at the main checkout: claims nothing
        self.run_hook('claude', {'session_id': 's3'}, kind='end')
        self.assertFalse(wt.exists())

    def test_a_repo_that_is_off_is_not_swept_for_a_session_that_only_ran_a_command_there(self):
        wt = self.leftover()
        self.shell('claude', 's1', ME, 'ai-dotfiles worktree new fix/z')
        self.run_hook('claude', {'session_id': 's1'}, kind='end')
        self.assertTrue(wt.is_dir())

    def test_list_flags_what_was_left_with_counts(self):
        wt = self.leftover()
        (wt / 'a.txt').write_text('edited\n')
        (wt / 'new.txt').write_text('x\n')
        (wt / 'other.txt').write_text('y\n')
        self.assertIn('owner gone, 3 files uncommitted', self.cli('list', '--repo', str(self.repo))[1])
        git(wt, 'add', '-A')
        git(wt, 'commit', '-q', '-m', 'wip')
        git(wt, 'commit', '-q', '--allow-empty', '-m', 'more')
        out = self.cli('list', '--repo', str(self.repo))[1]
        self.assertIn('fix-l1  fix/l1 (no branch)', out)
        self.assertIn('LEFT BEHIND: owner gone, 2 commits not pushed', out)
        (wt / 'a.txt').write_text('again\n')
        self.assertIn('owner gone, 2 commits not pushed, 1 file uncommitted', self.cli('list', '--repo', str(self.repo))[1])

    def test_list_does_not_flag_a_live_owner_or_work_with_nothing_to_lose(self):
        me = {'session': 's1', 'cli': 'claude', 'pid': ME, 'started': guard.started(ME)}
        live = guard.make_worktree(self.repo, 'fix-live', self.base, None, source=self.repo, owner=me,
                                   table=guard.process_table(), meta={'work': 'fix/live'})
        (live / 'a.txt').write_text('edited\n')
        out = self.cli('list', '--repo', str(self.repo))[1]
        self.assertIn('fix-live', out)
        self.assertNotIn('LEFT BEHIND', out)

    def test_a_new_session_takes_over_a_flagged_worktree_and_hears_what_it_holds(self):
        self.assertEqual(self.cli('on', '--repo', str(self.repo))[0], 0)  # a repo that is off keeps no owners
        wt = self.leftover()
        self.commit(wt)
        (wt / 'new.txt').write_text('x\n')
        data = {'session_id': 'new1', 'cwd': str(wt), 'pid': PARENT, 'tool_name': 'Edit',
                'tool_input': {'file_path': str(wt / 'a.txt')}}
        reply = self.run_hook('claude', data)['hookSpecificOutput']
        self.assertNotEqual(reply.get('permissionDecision'), 'deny')
        self.assertIn('1 uncommitted change(s)', reply['additionalContext'])
        self.assertIn('1 commit(s) not pushed', reply['additionalContext'])
        self.assertEqual(guard.read_claim(guard.claim_file(wt))['session'], 'new1')
        self.assertIn('last owner: claude session old1, no longer running', reply['additionalContext'])
        self.assertIsNone(self.run_hook('claude', data))  # said once
        self.assertNotIn('LEFT BEHIND', self.cli('list', '--repo', str(self.repo))[1])
        self.sweep()
        self.assertTrue(wt.is_dir())  # owned again

    def test_rm_of_a_flagged_worktree_tags_its_tip_before_deleting_it(self):
        wt = self.leftover()
        self.commit(wt)
        tip = git(wt, 'rev-parse', 'HEAD')
        status, out = self.cli('rm', 'fix-l1', '--repo', str(self.repo))
        self.assertEqual(status, 1)
        self.assertTrue(wt.is_dir())
        status, out = self.cli('rm', 'fix-l1', '--force', '--repo', str(self.repo))
        self.assertEqual(status, 0, out)
        self.assertEqual(git(self.repo, 'rev-list', '-n', '1', 'archive/l1'), tip)
        self.assertFalse(wt.exists())

    def test_a_sweep_that_fails_does_not_stop_the_work(self):
        self.leftover()
        with patch.object(guard, 'remove', side_effect=RuntimeError('boom')):
            self.assertEqual(self.sweep()[0], 0)
        self.assertTrue(self.linked('fix-fresh').is_dir())


class NewTest(OriginRepo):
    """`worktree new <type>/<slug>`: a detached worktree from a freshly fetched origin default."""

    def new(self, name='fix/x'):
        return self.cli('new', name, '--repo', str(self.repo))

    def test_it_starts_from_the_fetched_origin_default_with_no_branch(self):
        (self.repo / '.worktreeinclude').write_text('.env\n')
        (self.repo / '.env').write_text('SECRET=1\n')
        ahead = self.advance_origin()
        self.assertNotEqual(git(self.repo, 'rev-parse', 'HEAD'), ahead)  # the main checkout lags
        status, out = self.new()
        linked = self.linked('fix-x')
        self.assertEqual(status, 0, out)
        self.assertIn(str(linked), out)
        self.assertEqual(git(linked, 'rev-parse', 'HEAD'), ahead)
        self.assertEqual(subprocess.run(['git', '-C', str(linked), 'symbolic-ref', '-q', 'HEAD']).returncode, 1)
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')
        self.assertEqual((linked / '.env').read_text(), 'SECRET=1\n')  # an included ignored file
        meta = guard.read_meta(self.repo, 'fix-x')
        self.assertEqual((meta['work'], meta['branch'], meta['base'], meta['from']), ('fix/x', None, ahead, 'origin/main'))

    def test_the_default_comes_from_origin_even_when_its_head_was_never_set(self):
        git(self.repo, 'remote', 'set-head', 'origin', '-d')
        ahead = self.advance_origin()
        self.assertEqual(self.new()[0], 0)
        self.assertEqual(git(self.linked('fix-x'), 'rev-parse', 'HEAD'), ahead)

    def test_a_taken_name_is_refused_and_nothing_is_made(self):
        self.assertEqual(self.new()[0], 0)
        status, out = self.new()
        self.assertEqual(status, 1)
        self.assertIn('fix/x: .claude/worktrees/fix-x is taken', out)
        git(self.repo, 'push', '-q', 'origin', 'HEAD:refs/heads/fix/y')
        status, out = self.new('fix/y')
        self.assertEqual(status, 1)
        self.assertIn('fix/y: origin already has a branch of that name', out)
        git(self.repo, 'branch', 'fix/z')
        status, out = self.new('fix/z')
        self.assertEqual(status, 1)
        self.assertIn('fix/z: a local branch of that name exists', out)
        self.assertEqual(sorted(p.name for p in (self.repo / '.claude/worktrees').iterdir()), ['fix-x', 'fix-x.json'])

    def test_a_name_must_be_type_slash_slug(self):
        for name in ('fix', 'Fix/x', 'fix/', '/x', 'fix/x/y', 'fix/x y', '../x', 'fix/-x'):
            status, out = self.new(name)
            self.assertEqual(status, 1, name)
            self.assertIn('<type>/<slug>', out)
        self.assertFalse((self.repo / '.claude').exists())

    def test_offline_it_starts_from_the_last_origin_state_and_says_so(self):
        git(self.repo, 'remote', 'set-url', 'origin', str(self.repo.parent / 'gone.git'))
        status, out = self.new()
        self.assertEqual(status, 0, out)
        self.assertIn('could not fetch origin', out)
        self.assertEqual(git(self.linked('fix-x'), 'rev-parse', 'HEAD'), self.base)

    def test_without_an_origin_it_starts_from_the_local_default(self):
        git(self.repo, 'remote', 'remove', 'origin')
        status, out = self.new()
        self.assertEqual(status, 0, out)
        self.assertIn('no origin', out)
        self.assertEqual(git(self.linked('fix-x'), 'rev-parse', 'HEAD'), self.base)

    def test_a_worktree_nobody_bound_is_unowned_and_the_message_covers_every_cli(self):
        status, out = self.new()
        self.assertEqual(status, 0, out)
        self.assertFalse(guard.claim_file(self.linked('fix-x')).exists())
        self.assertIn(f'Claude Code: call EnterWorktree with path "{self.linked("fix-x")}"', out)
        self.assertIn('other CLIs', out)


CLIS = ('claude', 'codex', 'pi', 'agy')


class BoundTest(OriginRepo):
    """The session that ran `worktree new` owns the worktree, and its later calls land there."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.cli('on', '--repo', str(self.repo))[0], 0)

    def say(self, cli, session, pid, command):
        """The pre-hook call for a shell command the agent is about to run."""
        if cli == 'agy':
            return self.run_hook('agy', {'conversationId': session, 'workspacePaths': [str(self.repo)], 'pid': pid,
                                         'toolCall': {'name': 'run_command',
                                                      'args': {'CommandLine': command, 'Cwd': str(self.repo)}}})
        return self.shell(cli, session, pid, command)

    def new(self, cli, session, pid, name):
        """What an agent does: the hook sees `worktree new`, then the command runs."""
        reply = self.say(cli, session, pid, f'ai-dotfiles worktree new {name}')
        status, out = self.cli('new', name, '--repo', str(self.repo))
        self.assertEqual(status, 0, out)
        return reply, out

    def plain(self, cli, reply):
        return reply is None or reply == {'decision': 'allow'}

    def test_every_cli_is_told_or_steered_and_its_edits_never_land_in_the_main_checkout(self):
        for cli in CLIS:
            session, name = f'{cli}-sess', f'fix/{cli}'
            linked = self.linked(f'fix-{cli}')
            reply, out = self.new(cli, session, ME, name)
            self.assertTrue(self.plain(cli, reply), (cli, reply))  # the command keeps its own permissions
            claim = guard.read_claim(guard.claim_file(linked))
            self.assertEqual((claim['session'], claim['cli'], claim['pid']), (session, cli, ME), cli)
            self.assertEqual(guard.SESSIONS.load(session)['moved']['linked'], str(linked), cli)
            self.assertEqual('EnterWorktree' in out, cli == 'claude', (cli, out))
            if cli == 'claude':
                self.assertIn(f'Call EnterWorktree with path "{linked}"', out)
            else:
                self.assertIn('moved there automatically', out)
            aimed = self.edit(cli, session, ME)  # at the main checkout's a.txt
            if cli == 'claude':
                reason = aimed['hookSpecificOutput']['permissionDecisionReason']
                self.assertEqual(aimed['hookSpecificOutput']['permissionDecision'], 'deny')
                self.assertIn(str(linked), reason)
                self.assertNotIn('worktree new', reason)
            elif cli == 'codex':
                self.assertIn(f'*** Update File: .claude/worktrees/fix-{cli}/a.txt',
                              aimed['hookSpecificOutput']['updatedInput']['command'])
            elif cli == 'pi':
                self.assertEqual(aimed['input']['path'], str(linked / 'a.txt'))
            else:
                self.assertEqual(aimed['overwrite']['TargetFile'], str(linked / 'a.txt'))
            inside = self.edit(cli, session, ME, path=f'.claude/worktrees/fix-{cli}/a.txt')
            self.assertTrue(self.plain(cli, inside), (cli, inside))
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')

    def test_a_tree_changing_git_command_follows_the_session_into_its_worktree(self):
        self.new('codex', 'cdx', ME, 'fix/c')
        steered = self.shell('codex', 'cdx', ME, 'git commit -am x')['hookSpecificOutput']['updatedInput']['command']
        self.assertTrue(steered.startswith(f"cd '{self.linked('fix-c')}' && git commit"), steered)

    def test_reads_follow_the_session_into_its_worktree(self):
        self.new('pi', 'dddd4444', ME, 'fix/p')
        read = self.run_hook('pi', {'session_id': 'dddd4444', 'cwd': str(self.repo), 'pid': ME,
                                    'tool_name': 'read', 'tool_input': {'path': 'a.txt', 'offset': 1}})
        self.assertEqual(read, {'input': {'path': str(self.linked('fix-p') / 'a.txt'), 'offset': 1},
                                'status': 'fix/p'})  # the first call after the worktree is made also sets Pi's footer
        self.new('agy', 'eeee5555', PARENT, 'fix/a')
        view = self.run_hook('agy', {'conversationId': 'eeee5555', 'workspacePaths': [str(self.repo)], 'pid': PARENT,
                                     'toolCall': {'name': 'run_command',
                                                  'args': {'CommandLine': 'ls', 'Cwd': str(self.repo)}}})
        self.assertEqual(view['overwrite']['Cwd'], str(self.linked('fix-a')))

    def test_a_session_that_names_the_repo_through_a_symlink_is_steered_too(self):
        alias = self.repo.parent / 'alias'
        alias.symlink_to(self.repo)  # like /var -> /private/var on macOS, or a symlinked project folder
        self.new('pi', 'dddd4444', ME, 'fix/p')
        linked = self.linked('fix-p')
        reply = self.run_hook('pi', {'session_id': 'dddd4444', 'cwd': str(alias), 'pid': ME,
                                     'tool_name': 'write', 'tool_input': {'path': 'a.txt', 'content': 'x'}})
        self.assertEqual(reply['input']['path'], str(linked / 'a.txt'))
        shell = self.run_hook('pi', {'session_id': 'dddd4444', 'cwd': str(alias), 'pid': ME,
                                     'tool_name': 'bash', 'tool_input': {'command': f'cat {alias}/a.txt'}})
        self.assertEqual(shell['input']['command'], f"cd '{linked}' && cat {linked}/a.txt")

    def test_two_sessions_work_side_by_side_and_cannot_touch_each_others_worktree(self):
        self.new('codex', 'aaaa1111', ME, 'fix/a')
        self.new('pi', 'bbbb2222', PARENT, 'fix/b')
        mine = self.edit('pi', 'bbbb2222', PARENT)
        self.assertEqual(mine['input']['path'], str(self.linked('fix-b') / 'a.txt'))
        theirs = self.edit('pi', 'bbbb2222', PARENT, path='.claude/worktrees/fix-a/a.txt')
        self.assertTrue(theirs['block'], theirs)
        self.assertIn('codex session aaaa1111', theirs['reason'])
        self.assertEqual(sorted(p.name for p in (self.repo / '.claude/worktrees').iterdir()),
                         ['fix-a', 'fix-a.json', 'fix-b', 'fix-b.json'])  # no agent/ worktree was made
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')

    def test_a_session_that_has_not_named_its_work_cannot_edit_anothers_worktree(self):
        self.new('codex', 'aaaa1111', ME, 'fix/a')
        reply = self.edit('claude', 'cccc3333', PARENT, path='.claude/worktrees/fix-a/a.txt')
        out = reply['hookSpecificOutput']
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('codex session aaaa1111', out['permissionDecisionReason'])
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')

    def test_a_command_run_by_nobody_the_hook_saw_is_unbound(self):
        self.say('claude', 'sess', dead_pid(), 'ai-dotfiles worktree new fix/x')  # not this process's CLI
        self.assertEqual(self.cli('new', 'fix/x', '--repo', str(self.repo))[0], 0)
        self.assertFalse(guard.claim_file(self.linked('fix-x')).exists())
        self.assertNotIn('moved', guard.SESSIONS.load('sess'))
        self.say('claude', 'sess', ME, 'ai-dotfiles worktree new fix/other')  # another name
        self.assertEqual(self.cli('new', 'fix/y', '--repo', str(self.repo))[0], 0)
        self.assertFalse(guard.claim_file(self.linked('fix-y')).exists())

    def test_text_that_only_mentions_the_command_records_nothing(self):
        self.say('claude', 'sess', ME, 'echo "ai-dotfiles worktree new fix/x"')
        self.say('claude', 'sess', ME, 'ai-dotfiles worktree list')
        self.assertEqual(self.cli('new', 'fix/x', '--repo', str(self.repo))[0], 0)
        self.assertFalse(guard.claim_file(self.linked('fix-x')).exists())

    def test_a_record_goes_stale_and_is_used_once(self):
        self.say('claude', 'sess', ME, 'ai-dotfiles worktree new fix/x')
        with patch.object(guard.time, 'time', return_value=time.time() + 3600):
            self.assertEqual(self.cli('new', 'fix/x', '--repo', str(self.repo))[0], 0)
        self.assertFalse(guard.claim_file(self.linked('fix-x')).exists())
        self.say('claude', 'sess', ME, 'ai-dotfiles worktree new fix/y')
        self.assertEqual(self.cli('new', 'fix/y', '--repo', str(self.repo))[0], 0)
        self.assertTrue(guard.claim_file(self.linked('fix-y')).exists())
        self.assertEqual(self.cli('new', 'fix/y', '--repo', str(self.repo))[0], 1)  # taken; the record is gone
        self.assertEqual(list((guard.state_root() / 'naming').glob('*.json')), [])

    def test_the_session_in_the_cli_process_above_the_command_is_the_one_bound(self):
        self.say('claude', 'sess', PARENT, 'ai-dotfiles worktree new fix/x')  # the CLI is this process's parent
        self.assertEqual(self.cli('new', 'fix/x', '--repo', str(self.repo))[0], 0)
        self.assertEqual(guard.read_claim(guard.claim_file(self.linked('fix-x')))['pid'], PARENT)


STOP = 'ai-dotfiles worktree new <type>/<slug>'


class FlowTest(Repo):
    """The flow switch (`worktree on|off`) and the first-edit gate it arms, in all four CLIs."""

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = guard.main(list(args))
        return status, out.getvalue() + err.getvalue()

    def on(self, repo=None):
        self.assertEqual(self.cli('on', '--repo', str(repo or self.repo))[0], 0)

    def stopped(self, cli, reply):
        """Whether `reply`, in `cli`'s own format, denies and names the way out."""
        if cli in ('claude', 'codex'):
            out = reply['hookSpecificOutput']
            denied, text = out['permissionDecision'] == 'deny', out['permissionDecisionReason']
        elif cli == 'pi':
            denied, text = reply['block'], reply['reason']
        else:
            denied, text = reply['decision'] == 'deny', reply['reason']
        return denied and STOP in text

    def denied(self, cli, reply):
        if reply is None:
            return False
        if cli in ('claude', 'codex'):
            return reply['hookSpecificOutput'].get('permissionDecision') == 'deny'
        return bool(reply.get('block')) if cli == 'pi' else reply.get('decision') == 'deny'

    def shell_in(self, cli, command):
        if cli == 'agy':
            return self.run_hook('agy', {'conversationId': 'ee', 'workspacePaths': [str(self.repo)], 'pid': ME,
                                         'toolCall': {'name': 'run_command',
                                                      'args': {'CommandLine': command, 'Cwd': str(self.repo)}}})
        return self.shell(cli, 'ee', ME, command)

    def second_repo(self):
        other = self.repo.parent / 'other'
        other.mkdir()
        git(other, 'init', '-q', '-b', 'main')
        git(other, 'config', 'user.email', 't@example.com')
        git(other, 'config', 'user.name', 'T')
        (other / 'f.txt').write_text('x\n')
        git(other, 'add', '.')
        git(other, 'commit', '-q', '-m', 'init')
        return other

    def test_on_and_off_set_one_local_config_key_and_list_shows_it(self):
        self.assertIn('flow: off', self.cli('list', '--repo', str(self.repo))[1])
        self.assertIn('flow: on', self.cli('on', '--repo', str(self.repo))[1])
        self.assertEqual(git(self.repo, 'config', '--local', '--get', guard.FLOW_KEY), 'true')
        self.assertIn('flow: on', self.cli('list', '--repo', str(self.repo))[1])
        self.assertEqual(self.cli('on', '--repo', str(self.repo))[0], 0)  # idempotent
        self.assertIn('flow: off', self.cli('off', '--repo', str(self.repo))[1])
        unset = subprocess.run(['git', '-C', str(self.repo), 'config', '--local', '--get', guard.FLOW_KEY],
                               capture_output=True)
        self.assertEqual(unset.returncode, 1)
        self.assertEqual(self.cli('off', '--repo', str(self.repo))[0], 0)  # idempotent

    def test_the_switch_is_per_repo_whichever_worktree_asks(self):
        self.on()
        git(self.repo, 'worktree', 'add', '-q', '-b', 'side', str(self.linked('side')))
        self.assertIn('flow: on', self.cli('list', '--repo', str(self.linked('side')))[1])
        self.assertIn('flow: off', self.cli('list', '--repo', str(self.second_repo()))[1])

    def test_on_outside_a_repo_says_so(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(outside.rmdir)
        with self.assertRaises(SystemExit):
            self.cli('on', '--repo', str(outside))

    def test_an_agent_cannot_flip_the_switch_in_any_cli(self):
        for cli in CLIS:
            for word in ('on', 'off'):
                reply = self.shell_in(cli, f'ai-dotfiles worktree {word}')
                self.assertTrue(self.denied(cli, reply), (cli, word, reply))
        for allowed in ('ai-dotfiles worktree list', 'ai-dotfiles worktree new fix/x', 'echo worktree on'):
            self.assertFalse(self.denied('claude', self.shell_in('claude', allowed)), allowed)

    def test_only_a_real_invocation_is_refused_not_text_that_mentions_one(self):
        wt = 'ai-dotfiles worktree'
        refused = (f'{wt} release', f'{wt} share /x', f'cd /x && {wt} on', f'ls; {wt} off', f'true | {wt} on',
                   f'cd /tmp\n{wt} on', f'FOO=1 {wt} share', f'sudo {wt} on', f'({wt} on)', f'ls || {wt} off',
                   f'bash -c "{wt} on"', f"sh -lc '{wt} off'", 'python3 skills/worktree-guard/scripts/worktree_guard.py on',
                   'worktree-guard release', f'cat <<EOF > f\ntext\nEOF\n{wt} on', f'echo "x" && cd y; {wt} off')
        mentioned = (f'echo "{wt} on"', f"grep -n 'worktree release' notes.txt", f'git commit -m "docs: {wt} off"',
                     f"cat <<'EOF'\n{wt} on\nEOF", f'cat <<EOF > f\nrun {wt} release\nEOF', f'cat docs/{wt} on',
                     f'echo {wt}-on', f'{wt} list', f'{wt} new fix/x', f'echo hi # {wt} on', "echo 'a\nai-dotfiles worktree on'")
        for cli in CLIS:
            for command in refused:
                self.assertTrue(self.denied(cli, self.shell_in(cli, command)), (cli, command))
            for command in mentioned:
                self.assertFalse(self.denied(cli, self.shell_in(cli, command)), (cli, command))

    def test_in_a_repo_that_is_on_the_first_edit_is_stopped_in_every_cli(self):
        self.on()
        for cli, session, pid in (('claude', 'aaaa1111', ME), ('codex', 'bbbb2222', PARENT),
                                  ('pi', 'dddd4444', ME), ('agy', 'eeee5555', PARENT)):
            reply = self.edit(cli, session, pid)
            self.assertTrue(self.stopped(cli, reply), (cli, reply))
            self.assertTrue(self.stopped(cli, self.edit(cli, session, pid)), cli)  # until it names the work
            self.assertFalse(guard.claim_file(self.repo).exists(), cli)  # a stopped edit claims nothing

    def test_a_tree_changing_git_command_is_stopped_but_reads_pass(self):
        self.on()
        self.assertTrue(self.stopped('claude', self.shell('claude', 'aaaa1111', ME, 'git commit -am x')))
        self.assertIsNone(self.shell('claude', 'aaaa1111', ME, 'git status && cat a.txt'))
        self.assertIsNone(self.run_hook('claude', {'session_id': 'aaaa1111', 'cwd': str(self.repo), 'pid': ME,
                                                   'tool_name': 'Read',
                                                   'tool_input': {'file_path': str(self.repo / 'a.txt')}}))
        self.assertIsNone(self.run_hook('pi', {'session_id': 'dddd4444', 'cwd': str(self.repo), 'pid': ME,
                                               'tool_name': 'read', 'tool_input': {'path': 'a.txt'}}))
        view = self.run_hook('agy', {'conversationId': 'eeee5555', 'workspacePaths': [str(self.repo)], 'pid': ME,
                                     'toolCall': {'name': 'view_file',
                                                  'args': {'AbsolutePath': str(self.repo / 'a.txt')}}})
        self.assertEqual(view, {'decision': 'allow'})

    def test_a_repo_that_is_switched_off_again_claims_and_says_nothing(self):
        self.on()
        self.cli('off', '--repo', str(self.repo))
        self.assertIsNone(self.edit('claude', 'aaaa1111', ME))
        self.assertIsNone(self.edit('codex', 'bbbb2222', PARENT))
        self.assertFalse(guard.claim_file(self.repo).exists())

    def test_the_edited_files_repo_decides_wherever_the_session_started(self):
        other = self.second_repo()
        self.on(other)  # self.repo stays off
        data = {'session_id': 'aaaa1111', 'cwd': str(self.repo), 'pid': ME, 'tool_name': 'Edit',
                'tool_input': {'file_path': str(other / 'f.txt')}}
        self.assertTrue(self.stopped('claude', self.run_hook('claude', data)))  # started in an off repo
        self.assertIsNone(self.edit('claude', 'aaaa1111', ME))  # the off repo's own file: plain
        self.on()
        self.cli('off', '--repo', str(other))
        self.assertIsNone(self.run_hook('claude', {**data, 'cwd': str(self.repo)}))  # file in a repo now off
        self.assertTrue(self.stopped('claude', self.edit('claude', 'aaaa1111', ME)))  # cwd-independent

    def test_a_file_outside_git_is_a_plain_edit(self):
        self.on()
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        data = {'session_id': 'aaaa1111', 'cwd': str(self.repo), 'pid': ME, 'tool_name': 'Write',
                'tool_input': {'file_path': str(outside / 'x.txt')}}
        self.assertIsNone(self.run_hook('claude', data))

    def test_a_linked_worktree_of_an_on_repo_is_not_the_gate(self):
        self.on()
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(self.linked('fix-x')))
        data = {'session_id': 'aaaa1111', 'cwd': str(self.repo), 'pid': ME, 'tool_name': 'Edit',
                'tool_input': {'file_path': str(self.linked('fix-x') / 'a.txt')}}
        self.assertIsNone(self.run_hook('claude', data))

    def test_a_linked_worktree_outside_the_guards_folder_is_left_alone(self):
        """Codex's and Antigravity's app worktrees: not gated, not claimed, whoever edits them."""
        self.on()
        elsewhere = self.repo.parent / 'app worktree'
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(elsewhere))
        for cli, session, pid in (('claude', 'aaaa1111', ME), ('codex', 'bbbb2222', PARENT)):
            data = {'session_id': session, 'cwd': str(elsewhere), 'pid': pid, 'tool_name': 'Edit',
                    'tool_input': {'file_path': str(elsewhere / 'a.txt')}}
            if cli == 'codex':
                data = {**data, 'tool_name': 'apply_patch', 'tool_input': {
                    'command': '*** Begin Patch\n*** Update File: a.txt\n@@\n-one\n+two\n*** End Patch\n'}}
            self.assertTrue(self.plain(self.run_hook(cli, data)), cli)
        self.assertEqual(list(guard.state_root().glob('claims/*.json')), [])
        self.assertTrue(self.plain(self.shell('claude', 'aaaa1111', ME, f'git -C {shlex.quote(str(elsewhere))} commit -am x')))

    def test_a_guard_failure_never_blocks_an_edit(self):
        self.on()
        data = {'session_id': 's', 'cwd': str(self.repo), 'tool_name': 'Edit',
                'tool_input': {'file_path': str(self.repo / 'a.txt')}}
        out, err = io.StringIO(), io.StringIO()
        with patch.object(guard, 'flow_on', side_effect=RuntimeError('boom')), redirect_stdout(out), redirect_stderr(err):
            status = guard.agent_hooks.serve('claude', 'pre', guard.answer('claude', 'pre'),
                                             stdin=io.StringIO(json.dumps(data)), stdout=out,
                                             on_error=guard.failed)
        reply = json.loads(out.getvalue())['hookSpecificOutput']
        self.assertEqual(status, 0)
        self.assertNotEqual(reply.get('permissionDecision'), 'deny')
        self.assertIn('not protected', reply['additionalContext'])


class NativeTest(OriginRepo):
    """Claude's WorktreeCreate and WorktreeRemove hooks: a repo that is on gets our shape, one that
    is off gets what Claude would have made itself."""

    def hook(self, kind, data, cwd=None):
        """(status, stdout, stderr) of `hook <kind> --cli claude` fed `data` on stdin."""
        out, err = io.StringIO(), io.StringIO()
        data = {'session_id': 's1', 'cwd': str(cwd or self.repo), 'hook_event_name': 'x', **data}
        with patch('sys.stdin', io.StringIO(json.dumps(data))), redirect_stdout(out), redirect_stderr(err):
            status = guard.main(['hook', kind, '--cli', 'claude'])
        return status, out.getvalue(), err.getvalue()

    def create(self, name='bold-oak-a3f2', **kwargs):
        return self.hook('create', {'name': name}, **kwargs)

    def remove(self, path):
        return self.hook('remove', {'worktree_path': str(path)})

    def switch_on(self):
        git(self.repo, 'config', '--local', guard.FLOW_KEY, 'true')

    def made(self, name='bold-oak-a3f2'):
        status, out, err = self.create(name)
        self.assertEqual(status, 0, err)
        return Path(out.splitlines()[-1])

    def test_a_repo_that_is_on_gets_our_shape_from_freshly_fetched_origin(self):
        self.switch_on()
        (self.repo / '.worktreeinclude').write_text('.env\n')
        (self.repo / '.env').write_text('SECRET=1\n')
        ahead = self.advance_origin()
        status, out, err = self.create()
        linked = self.linked('bold-oak-a3f2')
        self.assertEqual((status, out), (0, f'{linked}\n'))  # nothing but the path on stdout
        self.assertEqual(git(linked, 'rev-parse', 'HEAD'), ahead)
        self.assertEqual(subprocess.run(['git', '-C', str(linked), 'symbolic-ref', '-q', 'HEAD']).returncode, 1)
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')
        self.assertEqual((linked / '.env').read_text(), 'SECRET=1\n')  # the hook copies what Claude would not
        meta = guard.read_meta(self.repo, 'bold-oak-a3f2')
        self.assertEqual((meta['branch'], meta['base'], meta['from']), (None, ahead, 'origin/main'))
        claim = guard.read_claim(guard.claim_file(linked))
        self.assertEqual(claim['session'], 's1')  # the session that asked owns it

    def test_a_repo_that_is_off_gets_claudes_own_default(self):
        (self.repo / 'a.txt').write_text('local\n')
        git(self.repo, 'commit', '-q', '-am', 'local work')  # ahead of origin: the base is HEAD
        (self.repo / '.worktreeinclude').write_text('.env\n')
        (self.repo / '.env').write_text('SECRET=1\n')
        self.advance_origin()
        status, out, err = self.create()
        linked = self.linked('bold-oak-a3f2')
        self.assertEqual((status, out), (0, f'{linked}\n'))
        self.assertEqual(git(linked, 'symbolic-ref', '--short', 'HEAD'), 'worktree-bold-oak-a3f2')
        self.assertEqual(git(linked, 'rev-parse', 'HEAD'), git(self.repo, 'rev-parse', 'HEAD'))
        self.assertEqual((linked / '.env').read_text(), 'SECRET=1\n')
        self.assertFalse(guard.meta_file(self.repo, 'bold-oak-a3f2').exists())  # no sidecar, no claim, no exclude
        self.assertFalse(guard.claim_file(linked).exists())
        self.assertNotIn('worktrees', (self.repo / '.git/info/exclude').read_text())

    def test_a_session_inside_a_linked_worktree_still_gets_one_beside_the_main_checkout(self):
        first = self.made('one')
        status, out, err = self.create('two', cwd=first)
        self.assertEqual((status, out), (0, f'{self.linked("two")}\n'), err)
        self.assertEqual(git(self.linked('two'), 'rev-parse', 'HEAD'), git(first, 'rev-parse', 'HEAD'))

    def test_asking_again_for_a_worktree_that_is_there_returns_it_untouched(self):
        for flow in (False, True):
            if flow:
                self.switch_on()
            linked = self.made(f'again-{flow}')
            (linked / 'a.txt').write_text('work\n')
            self.assertEqual(self.made(f'again-{flow}'), linked)
            self.assertEqual((linked / 'a.txt').read_text(), 'work\n')

    def test_no_repo_a_bad_name_or_no_commit_fails_with_a_reason_and_no_path(self):
        outside = self.repo.parent / 'plain'
        outside.mkdir()
        empty = self.repo.parent / 'empty'
        empty.mkdir()
        git(empty, 'init', '-q', '-b', 'main')
        for cwd, name in ((outside, 'x'), (self.repo, ''), (self.repo, '../x'), (self.repo, '-x'), (self.repo, 'a/..'),
                          (empty, 'x')):
            for flow in (False, True):
                if flow:
                    self.switch_on()
                status, out, err = self.create(name, cwd=cwd)
                self.assertEqual((status, out), (1, ''), (cwd, name))
                self.assertIn('worktree-guard:', err)
        self.assertFalse((self.repo / '.claude').exists())

    def test_a_name_with_a_slash_becomes_one_folder(self):
        self.assertEqual(self.made('feat/x'), self.linked('feat-x'))

    def test_remove_deletes_our_shape_with_its_record_and_claim(self):
        self.switch_on()
        linked = self.made()
        (linked / 'a.txt').write_text('uncommitted\n')  # Claude asked or checked first: the hook obeys
        status, out, err = self.remove(linked)
        self.assertEqual((status, out), (0, ''), err)
        self.assertFalse(linked.exists())
        self.assertFalse(guard.meta_file(self.repo, 'bold-oak-a3f2').exists())
        self.assertFalse(guard.claim_file(linked).exists())
        self.assertNotIn(str(linked), git(self.repo, 'worktree', 'list'))

    def test_remove_keeps_a_tag_for_commits_the_detached_worktree_made(self):
        self.switch_on()
        linked = self.made()
        (linked / 'a.txt').write_text('two\n')
        git(linked, 'commit', '-q', '-am', 'change a')
        tip = git(linked, 'rev-parse', 'HEAD')
        self.assertEqual(self.remove(linked)[0], 0)
        self.assertFalse(linked.exists())
        tags = git(self.repo, 'tag', '--list', 'archive/*').split()
        self.assertEqual([git(self.repo, 'rev-list', '-n', '1', t) for t in tags], [tip])

    def test_remove_in_a_repo_that_is_off_deletes_the_folder_and_claudes_branch(self):
        linked = self.made()
        git(self.repo, 'branch', 'keep-me')
        status, out, err = self.remove(linked)
        self.assertEqual((status, out), (0, ''), err)
        self.assertFalse(linked.exists())
        self.assertEqual(sorted(git(self.repo, 'branch', '--format=%(refname:short)').split()), ['keep-me', 'main'])

    def test_remove_leaves_a_branch_the_worktree_was_moved_to(self):
        linked = self.made()
        git(linked, 'switch', '-q', '-c', 'my-own-branch')
        self.assertEqual(self.remove(linked)[0], 0)
        self.assertFalse(linked.exists())
        self.assertIn('my-own-branch', git(self.repo, 'branch', '--format=%(refname:short)').split())

    def test_remove_of_what_is_gone_or_not_a_worktree_succeeds_and_touches_nothing(self):
        linked = self.made()
        self.assertEqual(self.remove(linked)[0], 0)
        self.assertEqual(self.remove(linked)[0], 0)  # already gone
        plain = self.repo.parent / 'plain'
        plain.mkdir()
        (plain / 'f').write_text('x')
        self.assertEqual(self.remove(plain)[0], 0)
        self.assertTrue((plain / 'f').exists())  # not git's worktree: left alone
        self.assertEqual(self.hook('remove', {})[0], 0)

    def test_the_script_prints_only_the_path_when_run_as_claude_runs_it(self):
        env = {**os.environ, guard.ENV: str(self.repo.parent / 'state')}
        data = json.dumps({'session_id': 's1', 'cwd': str(self.repo), 'hook_event_name': 'WorktreeCreate',
                           'name': 'cli-run'})
        run = subprocess.run([sys.executable, str(SCRIPT), 'hook', 'create', '--cli', 'claude'], input=data,
                             capture_output=True, text=True, env=env)
        self.assertEqual((run.returncode, run.stdout), (0, f'{self.linked("cli-run")}\n'), run.stderr)


if __name__ == '__main__':
    unittest.main()


class PrTest(OriginRepo):
    """`worktree pr <n>`: a detached worktree on an open PR's remote branch, named after it (D4)."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.cli('on', '--repo', str(self.repo))[0], 0)
        bin = self.repo.parent / 'bin'
        bin.mkdir()
        (bin / 'gh').write_text('#!/bin/sh\necho "$@" >> "$GH_LOG"\n'
                                '[ -n "$GH_ERR" ] && { echo "$GH_ERR" >&2; exit 1; }\nprintf "%s" "$GH_OUT"\n')
        (bin / 'gh').chmod(0o755)
        self.log = self.repo.parent / 'gh.log'
        patcher = patch.dict(os.environ, {'PATH': f"{bin}{os.pathsep}{os.environ['PATH']}", 'GH_LOG': str(self.log),
                                          'GH_ERR': '', 'GH_OUT': ''})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tip = self.push_branch('feat/thing')
        self.say_pr()

    def push_branch(self, branch, name='p.txt'):
        """Another clone pushes a commit to `branch` (the PR's branch); the repo has not fetched it."""
        clone = self.repo.parent / 'author'
        if not clone.exists():
            git(self.repo.parent, 'clone', '-q', str(self.origin), str(clone))
            git(clone, 'config', 'user.email', 't@example.com')
            git(clone, 'config', 'user.name', 'T')
        (clone / name).write_text(f'{time.time()}\n')
        git(clone, 'add', '.')
        git(clone, 'commit', '-q', '-m', 'the pr work')
        git(clone, 'push', '-q', 'origin', f'HEAD:refs/heads/{branch}')
        return git(clone, 'rev-parse', 'HEAD')

    def say_pr(self, **fields):
        info = {'number': 7, 'state': 'OPEN', 'headRefName': 'feat/thing', 'baseRefName': 'main',
                'isCrossRepository': False, **fields}
        os.environ['GH_OUT'] = json.dumps(info)

    def pr(self, number=7):
        return self.cli('pr', str(number), '--repo', str(self.repo))

    def announce(self, cli, session):
        """The pre-hook call for the shell command `worktree pr 7`, which notes who runs it."""
        command = 'ai-dotfiles worktree pr 7'
        if cli == 'agy':
            return self.run_hook('agy', {'conversationId': session, 'workspacePaths': [str(self.repo)], 'pid': ME,
                                         'toolCall': {'name': 'run_command',
                                                      'args': {'CommandLine': command, 'Cwd': str(self.repo)}}})
        return self.shell(cli, session, ME, command)

    def test_it_fetches_and_makes_a_worktree_on_the_branch_tip_named_after_it(self):
        self.assertFalse(git(self.repo, 'branch', '-r', '--list', 'origin/feat/thing'))  # not fetched yet
        status, out = self.pr()
        linked = self.linked('feat-thing')
        self.assertEqual(status, 0, out)
        self.assertIn(str(linked), out)
        self.assertEqual(git(linked, 'rev-parse', 'HEAD'), self.tip)
        self.assertEqual(subprocess.run(['git', '-C', str(linked), 'symbolic-ref', '-q', 'HEAD']).returncode, 1)
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')  # no local branch
        meta = guard.read_meta(self.repo, 'feat-thing')
        self.assertEqual((meta['work'], meta['pr'], meta['branch'], meta['base']), ('feat/thing', 7, None, self.tip))
        self.assertIn('pr view 7 --json', self.log.read_text())

    def test_the_fix_starts_from_the_branch_as_it_is_now_on_origin(self):
        self.assertEqual(self.pr()[0], 0)
        self.assertEqual(self.cli('rm', 'feat-thing', '--repo', str(self.repo), '--force')[0], 0)
        newer = self.push_branch('feat/thing', 'q.txt')
        self.assertEqual(self.pr()[0], 0)
        self.assertEqual(git(self.linked('feat-thing'), 'rev-parse', 'HEAD'), newer)

    def test_the_session_that_ran_it_owns_the_worktree_and_is_pointed_there(self):
        for cli in CLIS:
            self.assertTrue(self.announce(cli, f'{cli}-s') in (None, {'decision': 'allow'}), cli)  # keeps its permissions
            status, out = self.pr()
            linked = self.linked('feat-thing')
            self.assertEqual(status, 0, out)
            claim = guard.read_claim(guard.claim_file(linked))
            self.assertEqual((claim['session'], claim['cli'], claim['pid']), (f'{cli}-s', cli, ME), cli)
            moved = guard.SESSIONS.load(f'{cli}-s')['moved']
            self.assertEqual((moved['linked'], moved['work'], moved['branch']), (str(linked), 'feat/thing', None), cli)
            self.assertEqual('EnterWorktree' in out, cli == 'claude', (cli, out))
            self.assertEqual(self.cli('rm', 'feat-thing', '--repo', str(self.repo), '--force')[0], 0)

    def test_the_main_checkout_stays_closed_to_the_bound_session(self):
        self.announce('claude', 'sess')
        self.assertEqual(self.pr()[0], 0)
        reason = self.edit('claude', 'sess', ME)['hookSpecificOutput']['permissionDecisionReason']
        self.assertIn(str(self.linked('feat-thing')), reason)

    def test_without_it_a_first_edit_is_still_a_new_task_from_main(self):
        denied = self.edit('claude', 'sess', ME)
        self.assertIn(STOP, denied['hookSpecificOutput']['permissionDecisionReason'])
        self.assertFalse(self.linked('feat-thing').exists())

    def test_a_pr_that_is_not_open_or_not_in_this_repo_is_refused_and_nothing_is_made(self):
        for fields, why in (({'state': 'MERGED'}, 'is merged'), ({'state': 'CLOSED'}, 'is closed'),
                            ({'isCrossRepository': True}, 'fork')):
            self.say_pr(**fields)
            status, out = self.pr()
            self.assertEqual(status, 1, fields)
            self.assertIn(why, out)
            self.assertFalse(self.linked('feat-thing').exists())
            self.assertFalse(guard.meta_file(self.repo, 'feat-thing').exists())

    def test_gh_failing_or_a_branch_origin_lacks_is_refused(self):
        os.environ['GH_ERR'] = 'no pull request found'
        status, out = self.pr(9)
        self.assertEqual(status, 1)
        self.assertIn('no pull request found', out)
        os.environ['GH_ERR'] = ''
        self.say_pr(headRefName='feat/gone')
        status, out = self.pr()
        self.assertEqual(status, 1)
        self.assertIn('feat/gone', out)
        self.assertFalse(self.linked('feat-gone').exists())

    def test_a_folder_already_taken_is_refused_and_a_pr_number_must_be_one(self):
        self.assertEqual(self.pr()[0], 0)
        status, out = self.pr()
        self.assertEqual(status, 1)
        self.assertIn('feat-thing is taken', out)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(guard.main(['pr', 'seven']), 2)


class ShippedTest(OriginRepo):
    """`worktree shipped <folder>`: ship's cleanup, once the PR exists."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.cli('on', '--repo', str(self.repo))[0], 0)
        self.shell('claude', 'sess-ship', ME, 'ai-dotfiles worktree new fix/x')  # the hook notes who runs it
        self.assertEqual(self.cli('new', 'fix/x', '--repo', str(self.repo))[0], 0)
        self.wt = self.linked('fix-x')

    def commit_and_push(self):
        (self.wt / 'a.txt').write_text('two\n')
        git(self.wt, 'commit', '-q', '-am', 'change a')
        git(self.wt, 'push', '-q', 'origin', 'HEAD:refs/heads/fix/x')

    def shipped(self):
        return self.cli('shipped', 'fix-x', '--repo', str(self.repo))

    def test_it_deletes_the_worktree_and_frees_the_session_for_a_new_task(self):
        self.commit_and_push()
        status, out = self.shipped()
        self.assertEqual(status, 0, out)
        self.assertIn('removed fix-x', out)
        self.assertFalse(self.wt.exists())
        self.assertFalse(guard.meta_file(self.repo, 'fix-x').exists())
        self.assertFalse(guard.claim_file(self.wt).exists())
        self.assertNotIn('moved', guard.SESSIONS.load('sess-ship'))
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')
        self.assertEqual(git(self.repo, 'tag', '--list'), '', 'ship leaves the archive tag to approve')
        stopped = self.edit('claude', 'sess-ship', ME)  # the next first edit starts a new task
        self.assertIn('worktree new', stopped['hookSpecificOutput']['permissionDecisionReason'])

    def test_other_state_of_the_session_is_kept(self):
        state = guard.SESSIONS.load('sess-ship')
        guard.SESSIONS.save('sess-ship', {**state, 'warned': ['x']})
        self.commit_and_push()
        self.assertEqual(self.shipped()[0], 0)
        state = guard.SESSIONS.load('sess-ship')
        self.assertEqual(state['warned'], ['x'])
        self.assertEqual(state['repos'], [str(self.repo)], 'the repo stays noted for the sweep at its end')
        self.assertNotIn('moved', state)

    def test_work_not_on_a_remote_is_kept(self):
        (self.wt / 'a.txt').write_text('two\n')
        git(self.wt, 'commit', '-q', '-am', 'change a')
        status, out = self.shipped()
        self.assertEqual(status, 1)
        self.assertIn('a commit of it is on no remote', out)
        self.assertTrue(self.wt.exists())
        self.assertEqual(guard.SESSIONS.load('sess-ship')['moved']['linked'], str(self.wt))

    def test_uncommitted_changes_are_kept(self):
        self.commit_and_push()
        (self.wt / 'new.txt').write_text('x\n')
        status, out = self.shipped()
        self.assertEqual(status, 1)
        self.assertIn('1 uncommitted change', out)
        self.assertTrue(self.wt.exists())

    def test_a_folder_that_is_not_a_guard_worktree_is_refused(self):
        status, out = self.cli('shipped', 'nope', '--repo', str(self.repo))
        self.assertEqual(status, 1)
        self.assertIn('no linked worktree named nope', out)

    def test_a_worktree_nobody_bound_goes_the_same_way(self):
        guard.make_worktree(self.repo, 'fix-y', self.base, None, source=self.repo, meta={'work': 'fix/y'})
        git(self.linked('fix-y'), 'push', '-q', 'origin', 'HEAD:refs/heads/fix/y')
        status, out = self.cli('shipped', 'fix-y', '--repo', str(self.repo))
        self.assertEqual(status, 0, out)
        self.assertFalse(self.linked('fix-y').exists())


class LandedTest(OriginRepo):
    """`landed(worktree)`: approve's last step, run inside the worktree once its PR is merged and tagged."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.cli('on', '--repo', str(self.repo))[0], 0)
        self.shell('claude', 'sess-land', ME, 'ai-dotfiles worktree new fix/x')  # this process is the owner
        self.assertEqual(self.cli('new', 'fix/x', '--repo', str(self.repo))[0], 0)
        self.wt = self.linked('fix-x')
        (self.wt / 'a.txt').write_text('two\n')
        git(self.wt, 'commit', '-q', '-am', 'change a')
        git(self.wt, 'push', '-q', 'origin', 'HEAD:refs/heads/main')  # merged; its branch deleted, as approve leaves it
        git(self.repo, 'fetch', '-q', 'origin')

    def test_merged_work_goes_with_its_record_owner_and_binding_and_no_second_tag(self):
        done, lines = guard.landed(self.wt)
        self.assertTrue(done, lines)
        self.assertIn('removed fix-x', lines[0])
        self.assertFalse(self.wt.exists())
        self.assertFalse(guard.meta_file(self.repo, 'fix-x').exists())
        self.assertFalse(guard.claim_file(self.wt).exists())
        self.assertNotIn('moved', guard.SESSIONS.load('sess-land'))
        self.assertEqual(git(self.repo, 'tag', '--list'), '', 'approve made the one tag already')
        self.assertEqual(git(self.repo, 'branch', '--list'), '* main')

    def test_a_dry_run_says_so_and_deletes_nothing(self):
        done, lines = guard.landed(self.wt, dry=True)
        self.assertTrue(done)
        self.assertIn('would remove fix-x', lines[0])
        self.assertTrue(self.wt.exists())

    def test_a_repo_whose_flow_is_off_keeps_it(self):
        self.cli('off', '--repo', str(self.repo))
        self.assertEqual(guard.landed(self.wt), (False, [f'worktree-guard: kept fix-x: the worktree flow is off in {self.repo}']))
        self.assertTrue(self.wt.exists())

    def test_a_worktree_the_guard_did_not_make_is_kept(self):
        hand = self.linked('by-hand')
        git(self.repo, 'worktree', 'add', '-q', '--detach', str(hand), 'origin/main')
        self.assertEqual(guard.landed(hand), (False, ['worktree-guard: kept by-hand: worktree-guard did not make it']))
        self.assertTrue(hand.exists())

    def test_another_live_sessions_worktree_is_kept(self):
        other = subprocess.Popen(['sleep', '30'])  # alive, and not this process or an ancestor of it
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        guard.write_claim(guard.claim_file(self.wt), {'session': 'other123', 'cli': 'codex', 'pid': other.pid,
                                                       'started': guard.started(other.pid)})
        done, lines = guard.landed(self.wt)
        self.assertFalse(done)
        self.assertIn('codex session other123 still works there', lines[0])
        self.assertTrue(self.wt.exists())

    def test_uncommitted_or_unpushed_work_is_kept(self):
        (self.wt / 'new.txt').write_text('x\n')
        self.assertIn('1 uncommitted change', guard.landed(self.wt)[1][0])
        git(self.wt, 'add', 'new.txt')
        git(self.wt, 'commit', '-q', '-m', 'after the merge')
        self.assertIn('a commit of it is on no remote', guard.landed(self.wt)[1][0])
        self.assertTrue(self.wt.exists())


class SeenTest(OriginRepo):
    """Codex has no status line to follow a steered session and Pi's footer is the extension's to set, so
    the guard tells them, on the session's next tool call, that a worktree was made or deleted."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.cli('on', '--repo', str(self.repo))[0], 0)

    def start(self, cli, session='sess-seen'):
        self.shell(cli, session, ME, 'ai-dotfiles worktree new fix/x')  # the hook notes who runs it
        self.assertEqual(self.cli('new', 'fix/x', '--repo', str(self.repo))[0], 0)
        return self.linked('fix-x')

    def look(self, cli, session='sess-seen'):
        """A harmless tool call: what the CLI shows the person for it."""
        return self.shell(cli, session, ME, 'ls')

    def ship(self, wt):
        (wt / 'a.txt').write_text('two\n')
        git(wt, 'commit', '-q', '-am', 'change a')
        git(wt, 'push', '-q', 'origin', 'HEAD:refs/heads/fix/x')
        self.assertEqual(self.cli('shipped', 'fix-x', '--repo', str(self.repo))[0], 0)

    def test_codex_is_told_once_when_its_worktree_is_made_and_once_when_it_is_deleted(self):
        self.assertIsNone(self.look('codex'))
        wt = self.start('codex')
        made = self.look('codex')  # steered into the worktree as well
        self.assertIn('updatedInput', made['hookSpecificOutput'])
        self.assertIn(f'fix/x works in {wt}', made['systemMessage'])
        self.assertNotIn('\n', made['systemMessage'])
        self.assertNotIn('systemMessage', self.look('codex'))
        self.ship(wt)
        gone = self.look('codex')
        self.assertEqual(list(gone), ['systemMessage'])
        self.assertIn(f'fix/x is deleted; the session is back in {self.repo}', gone['systemMessage'])
        self.assertIsNone(self.look('codex'))

    def test_the_notice_comes_with_the_first_edit_of_a_steered_session(self):
        self.start('codex')
        reply = self.edit('codex', 'sess-seen', ME)
        self.assertIn('fix-x/a.txt', reply['hookSpecificOutput']['updatedInput']['command'])
        self.assertIn('fix/x works in', reply['systemMessage'])
        self.assertNotIn('systemMessage', self.edit('codex', 'sess-seen', ME))

    def test_a_worktree_removed_some_other_way_is_told_as_deleted(self):
        wt = self.start('codex')
        self.look('codex')
        git(self.repo, 'worktree', 'remove', '--force', str(wt))
        self.assertIn('is deleted', self.look('codex')['systemMessage'])
        self.assertNotIn('systemMessage', self.look('codex') or {})

    def test_pi_gets_the_work_name_for_its_footer_and_then_none(self):
        self.assertIsNone(self.look('pi'))
        wt = self.start('pi')
        self.assertEqual(self.look('pi')['status'], 'fix/x')
        self.assertNotIn('status', self.look('pi'))
        self.ship(wt)
        self.assertEqual(self.look('pi'), {'status': None})
        self.assertIsNone(self.look('pi'))

    def test_pi_keeps_the_guards_own_answer_beside_the_status(self):
        self.start('pi')
        reply = self.edit('pi', 'sess-seen', ME)
        self.assertEqual(reply['status'], 'fix/x')
        self.assertIn('fix-x/a.txt', reply['input']['path'])

    def test_claude_and_antigravity_are_not_told(self):
        for cli in ('claude', 'agy'):
            session = f'sess-{cli}'
            self.start(cli, session)
            reply = self.look(cli, session)
            self.assertNotIn('systemMessage', reply or {})
            self.assertNotIn('shown', guard.SESSIONS.load(session))
            self.cli('shipped', 'fix-x', '--repo', str(self.repo))

    def test_a_move_with_no_work_name_is_not_told(self):
        guard.SESSIONS.save('sess-old', {'moved': {'busy': str(self.repo), 'linked': str(self.repo),
                                                  'name': 'codex-x', 'branch': 'agent/codex-x'}})
        self.assertNotIn('systemMessage', self.look('codex', 'sess-old') or {})
