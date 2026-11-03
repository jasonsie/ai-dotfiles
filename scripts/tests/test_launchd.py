from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT, load
import installer

launchd = load('install/launchd.py')
skills = load('install/skills.py')
day_pass = load('../skills/daily-log/scripts/day_pass.py')

CLAUDE = '/fake/bin/claude'
LABEL = 'com.ai-dotfiles.daily-log-day'  # healthcheck.sh asks launchd for this name
FOREIGN = {  # what may sit at the plist's path and is not ours
    'another label, no marker': plistlib.dumps({'Label': 'com.example.other', 'ProgramArguments': ['/bin/true']}),
    'our label, no marker': plistlib.dumps({'Label': LABEL, 'ProgramArguments': ['/bin/true']}),
    'our marker, another label': plistlib.dumps({'Label': 'com.example.other', 'ai-dotfiles': 'daily-log day'}),
    'another marker value': plistlib.dumps({'Label': LABEL, 'ai-dotfiles': 'something else'}),
    'a list': plistlib.dumps([LABEL]),
    'an empty file': b'',
    'text': b'hello',
    'truncated xml': b'<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>',
}


class LaunchdTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='launchd 空間 ')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.plist = self.home / 'Library/LaunchAgents' / f'{LABEL}.plist'
        self.logs = self.home / 'Library/Logs/ai-dotfiles'
        self.claude = CLAUDE  # what `which claude` finds; None for no claude
        self.calls = []  # every command handed to subprocess.run: none may reach the real launchctl
        self.plist_there = []  # whether the plist existed at each call
        self.statuses = {}  # launchctl verb -> the exit status to fake
        self.output = ''
        for patcher in (patch.object(launchd.shutil, 'which', self.which),
                        patch.object(launchd.subprocess, 'run', self.launchctl)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def which(self, name, *_):
        """`claude` as the test sets it."""
        return self.claude if name == 'claude' else None

    def launchctl(self, command, **kwargs):
        self.calls.append(command)
        self.plist_there.append(self.plist.exists())
        status = self.statuses.get(command[1], 0)
        if status and kwargs.get('check'):
            raise subprocess.CalledProcessError(status, command, '', 'Bootstrap failed: 5: Input/output error\n')
        return subprocess.CompletedProcess(command, status, '', '')

    def install(self, apply=False, uninstall=False):
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                return launchd.install(self.home, apply, uninstall)
        finally:
            self.output = out.getvalue()

    def data(self):
        return plistlib.loads(self.plist.read_bytes())

    def backups(self):
        return sorted((self.home / installer.STATE / 'launchd').glob('backup-*'))

    def real_home(self):
        """Make the temp home the folder launchd.load takes for the user's own (the user database's, not $HOME)."""
        patcher = patch.object(launchd, 'real_home', return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['launchd.py', *args]), redirect_stdout(out), redirect_stderr(err):
            status = launchd.main()
        return status, out.getvalue(), err.getvalue()

    def test_the_command_is_the_daily_pass_evidence_and_writer_both(self):
        self.assertEqual(launchd.arguments(self.home), [f'{self.home}/.local/bin/daily-log', 'day', '--write'])
        self.assertEqual(launchd.COMMAND, f"{skills.BIN}/daily-log")  # where skills.py links it
        self.assertIn('daily-log', skills.COMMANDS)

    def test_the_job_fires_when_the_journals_day_closes(self):
        self.assertEqual((launchd.HOUR, launchd.MINUTE), (day_pass.CUTOFF, 0))

    def test_a_pyenv_version_folder_gives_way_to_the_shims_folder(self):
        root = self.home / 'pyenv'
        (root / 'shims').mkdir(parents=True)
        (root / 'shims/python3').write_text('')
        shims = str(root / 'shims')
        versions = [str(root / 'versions' / name / 'bin/python3') for name in ('3.12.8', '3.11.9')]
        plists = set()
        for executable, wanted in [*((v, shims) for v in versions), ('/opt/py/bin/python3', '/opt/py/bin')]:
            with self.subTest(executable), patch.dict(os.environ, {'PYENV_ROOT': str(root)}):
                with patch.object(launchd.sys, 'executable', executable):
                    self.assertEqual(launchd.python_folder(), wanted)
                    plists.add(launchd.content(self.home, CLAUDE))
        self.assertEqual(len(plists), 2)  # one for both pyenv versions, one for the other python
        with patch.object(launchd.sys, 'executable', versions[0]):
            with patch.dict(os.environ):
                os.environ.pop('PYENV_ROOT', None)  # not pyenv, as far as the step can tell
                self.assertEqual(launchd.python_folder(), os.path.dirname(versions[0]))
            (root / 'shims/python3').unlink()
            with patch.dict(os.environ, {'PYENV_ROOT': str(root)}):  # nothing to stand in
                self.assertEqual(launchd.python_folder(), os.path.dirname(versions[0]))

    def test_the_real_home_comes_from_the_user_database_not_the_environment(self):
        with patch.dict(os.environ, {'HOME': str(self.home)}):
            self.assertNotEqual(launchd.real_home(), self.home)
            self.assertFalse(launchd.load(self.home, self.plist, False))
        self.assertEqual(self.calls, [])

    def test_preview_writes_nothing_and_counts_one(self):
        self.assertEqual(self.install(), 1)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertIn(f'Would write: {self.plist}', self.output)
        self.assertEqual(self.calls, [])

    def test_apply_writes_the_agent_and_a_second_apply_changes_nothing(self):
        self.assertEqual(self.install(apply=True), 1)
        self.assertIn(f'Write: {self.plist}', self.output)
        self.assertNotIn('Backup', self.output)  # nothing was replaced
        self.assertEqual(self.plist.stat().st_mode & 0o777, 0o644)
        log = str(self.logs / 'daily-log-day.log')
        self.assertEqual(self.data(), {
            'Label': LABEL,
            'ai-dotfiles': 'daily-log day',
            'ProgramArguments': [f'{self.home}/.local/bin/daily-log', 'day', '--write'],
            'StartCalendarInterval': {'Hour': 4, 'Minute': 0},
            'RunAtLoad': False,
            'WorkingDirectory': str(self.home),
            'EnvironmentVariables': {'HOME': str(self.home), 'PATH': launchd.search_path(self.home, CLAUDE)},
            'StandardOutPath': log,
            'StandardErrorPath': log,
        })
        path = self.data()['EnvironmentVariables']['PATH'].split(':')
        self.assertEqual((path[0], path[1], path[-2:]), (f'{self.home}/.local/bin', '/fake/bin', ['/usr/bin', '/bin']))
        self.assertIn(launchd.python_folder(), path)
        self.assertEqual(self.logs.stat().st_mode & 0o777, 0o700)  # launchd will not make the folder
        self.assertEqual(self.calls, [])  # a temp home is not the user's: launchctl never runs
        written = self.plist.read_bytes()
        self.assertEqual(self.install(apply=True), 0)
        self.assertEqual(self.install(), 0)
        self.assertEqual(self.plist.read_bytes(), written)
        self.assertEqual(self.backups(), [])

    def test_the_job_path_has_no_repeats_and_no_empty_entry(self):
        pythons = (('/opt/py/bin/python3', ['/opt/py/bin']), ('/usr/bin/python3', []), ('', []), (None, []))
        for executable, middle in pythons:
            with self.subTest(executable), patch.object(launchd.sys, 'executable', executable):
                wanted = [f'{self.home}/.local/bin', *middle, '/usr/bin', '/bin']
                self.assertEqual(launchd.search_path(self.home), ':'.join(wanted))
                wanted = [f'{self.home}/.local/bin', '/fake/bin', *middle, '/usr/bin', '/bin']
                self.assertEqual(launchd.search_path(self.home, CLAUDE), ':'.join(wanted))
                self.assertEqual(launchd.search_path(self.home, f'{self.home}/.local/bin/claude'),
                                 ':'.join([f'{self.home}/.local/bin', *middle, '/usr/bin', '/bin']))  # no repeat

    def test_claude_is_recorded_as_found_and_made_absolute(self):
        real = self.home / 'versions/1.2.3/claude'
        real.parent.mkdir(parents=True)
        real.write_text('')
        link = self.home / 'bin/claude'
        link.parent.mkdir()
        link.symlink_to(real)
        self.claude = str(link)
        self.install(apply=True)
        folders = self.data()['EnvironmentVariables']['PATH'].split(':')
        self.assertIn(str(link.parent), folders)  # the link's folder, so updates are followed
        self.assertNotIn(str(real.parent), folders)
        self.claude = 'bin/claude'  # found through a relative PATH entry
        self.install(apply=True)
        self.assertTrue(all(os.path.isabs(folder) for folder in self.data()['EnvironmentVariables']['PATH'].split(':')))

    def test_another_claude_rewrites_the_file_and_the_old_one_is_backed_up(self):
        self.install(apply=True)
        old = self.plist.read_bytes()
        self.claude = '/elsewhere/claude'
        self.assertEqual(self.install(), 1)
        self.assertEqual(self.plist.read_bytes(), old)
        self.assertEqual(self.install(apply=True), 1)
        self.assertIn('/elsewhere', self.data()['EnvironmentVariables']['PATH'].split(':'))
        (backup,) = self.backups()
        self.assertEqual((backup / 'Library/LaunchAgents' / self.plist.name).read_bytes(), old)
        self.assertIn(f'Update: {self.plist}', self.output)
        self.assertIn(f'Backup: {backup}', self.output)
        self.assertEqual(self.install(), 0)

    def test_our_plist_changed_by_hand_is_rewritten_whatever_its_format(self):
        for fmt in (plistlib.FMT_XML, plistlib.FMT_BINARY):
            with self.subTest(fmt):
                self.install(apply=True)
                edited = {**self.data(), 'StartCalendarInterval': {'Hour': 9, 'Minute': 0}}
                self.plist.write_bytes(plistlib.dumps(edited, fmt=fmt))
                self.assertEqual(self.install(apply=True), 1)
                self.assertEqual(self.data()['StartCalendarInterval'], {'Hour': 4, 'Minute': 0})
                self.assertEqual(self.install(), 0)

    def test_a_plist_others_can_write_is_put_right(self):
        self.install(apply=True)
        self.plist.chmod(0o666)
        self.assertEqual(self.install(), 1)
        self.assertEqual(self.install(apply=True), 1)
        self.assertEqual(self.plist.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.install(), 0)

    def test_refuses_a_plist_it_did_not_write(self):
        self.plist.parent.mkdir(parents=True)
        for what, data in FOREIGN.items():
            with self.subTest(what):
                self.plist.write_bytes(data)
                for uninstall in (False, True):
                    for apply in (False, True):
                        with self.assertRaisesRegex(ValueError, 'refusing'):
                            self.install(apply, uninstall)
                self.assertEqual(self.plist.read_bytes(), data)
        self.assertFalse((self.home / 'Library/Logs').exists())  # nothing else was made
        self.assertFalse((self.home / installer.STATE).exists())
        self.assertEqual(self.calls, [])

    def test_refuses_a_symlink_or_a_folder_in_its_place(self):
        real = self.home / 'elsewhere.plist'
        real.write_bytes(launchd.content(self.home, CLAUDE))  # even a copy of our own file
        self.plist.parent.mkdir(parents=True)
        self.plist.symlink_to(real)
        for uninstall in (False, True):
            with self.assertRaisesRegex(ValueError, 'symlink.*refusing'):
                self.install(apply=True, uninstall=uninstall)
        self.assertEqual(self.plist.readlink(), real)
        self.assertEqual(real.read_bytes(), launchd.content(self.home, CLAUDE))
        self.plist.unlink()
        self.plist.mkdir()
        for uninstall in (False, True):
            with self.assertRaisesRegex(ValueError, 'not a file.*refusing'):
                self.install(apply=True, uninstall=uninstall)
        self.assertTrue(self.plist.is_dir())
        self.assertEqual(self.calls, [])

    def test_uninstall_removes_the_file_keeps_the_log_and_needs_no_claude(self):
        self.install(apply=True)
        old = self.plist.read_bytes()
        (self.logs / 'daily-log-day.log').write_text('yesterday\n')
        self.claude = None
        self.assertEqual(self.install(uninstall=True), 1)
        self.assertEqual(self.output, f'Would remove: {self.plist}\n')
        self.assertTrue(self.plist.exists())
        self.assertEqual(self.install(apply=True, uninstall=True), 1)
        self.assertIn(f'Remove: {self.plist}', self.output)
        self.assertFalse(self.plist.exists())
        (backup,) = self.backups()
        self.assertEqual((backup / 'Library/LaunchAgents' / self.plist.name).read_bytes(), old)
        self.assertEqual((self.logs / 'daily-log-day.log').read_text(), 'yesterday\n')
        self.assertEqual(self.install(apply=True, uninstall=True), 0)  # idempotent
        self.assertEqual(self.install(uninstall=True), 0)
        self.assertEqual(self.output, '')

    def test_uninstall_with_nothing_installed_does_nothing(self):
        for apply in (False, True):
            self.assertEqual(self.install(apply, uninstall=True), 0)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(self.calls, [])

    def test_without_claude_nothing_is_scheduled(self):
        self.claude = None
        for apply in (False, True):
            self.assertEqual(self.install(apply), 0)
            self.assertEqual(self.output, 'launchd: claude not on PATH; nothing scheduled\n')
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(self.calls, [])

    def test_without_claude_a_plist_already_there_is_left_alone(self):
        self.install(apply=True)
        old = self.plist.read_bytes()
        self.claude = None
        self.assertEqual(self.install(apply=True), 0)
        self.assertEqual(self.plist.read_bytes(), old)

    def test_installing_into_the_real_home_boots_out_then_bootstraps_once(self):
        self.real_home()
        domain = f'gui/{os.getuid()}'
        with patch.object(launchd, 'load', wraps=launchd.load) as spy:
            self.assertEqual(self.install(apply=True), 1)
        spy.assert_called_once_with(self.home, self.plist, False)
        self.assertEqual(self.calls, [['launchctl', 'bootout', f'{domain}/{LABEL}'],
                                      ['launchctl', 'bootstrap', domain, str(self.plist)]])
        self.assertEqual(self.plist_there, [True, True])  # written before it is loaded
        self.assertIn(f'Run: launchctl bootstrap {domain} {self.plist}', self.output)
        self.assertEqual(self.install(apply=True), 0)  # nothing changed: launchd is left alone
        self.assertEqual(len(self.calls), 2)

    def test_uninstalling_from_the_real_home_boots_the_job_out_before_the_file_goes(self):
        self.install(apply=True)
        self.real_home()
        with patch.object(launchd, 'load', wraps=launchd.load) as spy:
            self.assertEqual(self.install(apply=True, uninstall=True), 1)
        spy.assert_called_once_with(self.home, self.plist, True)
        self.assertEqual(self.calls, [['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}']])
        self.assertEqual(self.plist_there, [True])
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.install(apply=True, uninstall=True), 0)
        self.assertEqual(len(self.calls), 1)

    def test_a_preview_never_runs_launchctl(self):
        self.real_home()
        self.assertEqual(self.install(), 1)
        self.assertEqual(self.install(uninstall=True), 0)
        self.assertEqual(self.calls, [])

    def test_load_runs_only_for_the_real_home(self):
        self.assertFalse(launchd.load(self.home, self.plist, False))
        self.assertFalse(launchd.load(self.home, self.plist, True))
        self.assertEqual(self.calls, [])
        self.real_home()
        with redirect_stdout(io.StringIO()):
            self.assertTrue(launchd.load(self.home, self.plist, True))
        self.assertEqual(len(self.calls), 1)

    def test_a_job_that_was_not_loaded_is_no_error_but_a_failed_bootstrap_is(self):
        self.real_home()
        self.statuses = {'bootout': 3}
        self.assertEqual(self.install(apply=True), 1)
        self.assertEqual([call[1] for call in self.calls], ['bootout', 'bootstrap'])
        self.claude = '/elsewhere/claude'
        self.statuses = {'bootstrap': 5}
        with self.assertRaisesRegex(ValueError, r'launchctl bootstrap failed \(exit 5\): Bootstrap failed: 5: '
                                                r'Input/output error; .* is written'):
            self.install(apply=True)

    def test_main_ends_with_the_count_the_healthcheck_reads(self):
        home = str(self.home)
        for args, count, written in ((['--dry-run'], 1, False), ([], 1, True), (['--dry-run'], 0, True),
                                     (['--uninstall', '--dry-run'], 1, True), (['--uninstall'], 1, False)):
            with self.subTest(args, written=written):
                status, out, err = self.run_main('--home', home, *args)
                self.assertEqual((status, err, out.splitlines()[-1]), (0, '', f'launchd: {count} changes'))
                self.assertEqual(self.plist.exists(), written)
        self.assertEqual(self.calls, [])

    def test_main_reports_a_refusal_and_takes_no_target(self):
        self.plist.parent.mkdir(parents=True)
        self.plist.write_bytes(FOREIGN['text'])
        status, out, err = self.run_main('--home', str(self.home))
        self.assertEqual((status, out), (1, ''))
        self.assertRegex(err, r'^launchd: .*refusing')
        with self.assertRaises(SystemExit):
            self.run_main('--home', str(self.home), '--target', 'claude')

    def test_the_source_names_no_machine_path(self):
        source = (ROOT / 'scripts/install/launchd.py').read_text()
        self.assertNotRegex(source, r'/Users/[A-Za-z]|/opt/homebrew|/usr/local/Cellar')


if __name__ == '__main__':
    unittest.main()
