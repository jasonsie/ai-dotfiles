"""lib/install/steps.py: the install steps are one ordered list that install, uninstall, check and --help read."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest import mock

from support import ROOT, registry, where
import launchd
import mcp
import run
import steps

FIXTURE = """
SUMMARY = 'the {name} step'
UNDO = 'the {name} step undone'
{cloud}

def execute(options):
    print(f'ran {name} apply={{options.apply}} uninstall={{options.uninstall}} cloud={{options.cloud}}')
    if {fails}:
        raise ValueError('it broke')
    return 2


def checks(options):
    return [('ok', '{name} is fine'), ('{status}', '{name} again')]
"""


class StepListTest(unittest.TestCase):
    def test_every_listed_step_is_a_module_with_the_interface(self):
        for name, module in zip(steps.STEPS, steps.load()):
            with self.subTest(step=name):
                self.assertTrue((ROOT / 'lib/install' / f'{name}.py').is_file())
                for text in (module.SUMMARY, module.UNDO):
                    self.assertTrue(text.strip() and '\n' not in text)
                self.assertTrue(callable(module.execute) and callable(module.main))
                self.assertTrue(callable(getattr(module, 'checks', print)))
                self.assertIsInstance(getattr(module, 'CLOUD_SKIP', ''), str)

    def test_no_step_module_is_left_out_of_the_list(self):
        modules = {path.stem for path in (ROOT / 'lib/install').glob('*.py')}
        self.assertEqual(modules - set(steps.STEPS), {'installer', 'steps', 'run'} & modules)

    def test_a_cloud_session_leaves_out_plugins_and_launchd_only(self):
        skipped = [module.__name__ for module in steps.load() if getattr(module, 'CLOUD_SKIP', None)]
        self.assertEqual(skipped, ['plugins', 'launchd'])
        for module in steps.load(skipped):
            self.assertTrue(module.CLOUD_SKIP.startswith(f'{module.__name__}: skipped in a cloud session'))

    def test_the_entry_scripts_name_no_step(self):
        """A step is added in steps.py alone: the shell scripts hold no `== name` list."""
        for script in ('install.sh', 'uninstall.sh', 'healthcheck.sh'):
            text = (ROOT / 'scripts' / script).read_text()
            with self.subTest(script=script):
                self.assertNotRegex(text, r'==\s+(' + '|'.join(steps.STEPS) + r')\b')
                self.assertNotRegex(text, r'install/(' + '|'.join(steps.STEPS) + r')\.py')


class RunnerTest(unittest.TestCase):
    """run.py over fixture steps: modules in a temp folder, passed in place of the listed ones."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name).resolve()
        self.home = self.folder / 'home'
        self.home.mkdir()

    def fixture(self, name, cloud_skip=False, fails=False, status='info'):
        path = self.folder / f'{name}.py'
        cloud = f"CLOUD_SKIP = '{name}: skipped in a cloud session'" if cloud_skip else ''
        path.write_text(FIXTURE.format(name=name, cloud=cloud, fails=fails, status=status))
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        module.__name__ = name
        spec.loader.exec_module(module)
        return module

    def main(self, *argv, modules):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = run.main([argv[0], '--home', str(self.home), *argv[1:]] if argv[0] != 'help' else list(argv),
                              modules)
        return status, out.getvalue(), err.getvalue()

    def test_install_runs_the_steps_in_order_and_uninstall_in_reverse(self):
        modules = [self.fixture('first'), self.fixture('second')]
        status, out, _ = self.main('install', '--dry-run', modules=modules)
        self.assertEqual(status, 0)
        self.assertEqual(re.findall(r'^== (\w+)$', out, re.M), ['first', 'second'])
        self.assertIn('ran first apply=False uninstall=False cloud=False', out)
        self.assertIn('first: 2 changes', out)
        self.assertTrue(out.endswith('Preview only: nothing written. Run again without --dry-run to write.\n'))
        status, out, _ = self.main('install', modules=modules)
        self.assertIn('ran second apply=True', out)
        self.assertTrue(out.endswith('Done. Verify: ai-dotfiles check\n'))
        status, out, _ = self.main('uninstall', modules=modules)
        self.assertEqual(re.findall(r'^== (\w+)$', out, re.M), ['second', 'first'])
        self.assertIn('ran first apply=True uninstall=True', out)
        self.assertTrue(out.endswith('Done. Reinstall: bash scripts/install.sh\n'))

    def test_a_failing_step_stops_the_run_with_status_1(self):
        modules = [self.fixture('first'), self.fixture('broken', fails=True), self.fixture('third')]
        status, out, err = self.main('install', modules=modules)
        self.assertEqual(status, 1)
        self.assertIn('broken: it broke', err)
        self.assertNotIn('== third', out)

    def test_a_cloud_run_skips_the_steps_that_say_so_and_targets_claude(self):
        modules = [self.fixture('first'), self.fixture('local', cloud_skip=True)]
        status, out, _ = self.main('install', '--cloud', '--target=codex', modules=modules)
        self.assertEqual(status, 0)
        self.assertIn('ran first apply=True uninstall=False cloud=True', out)
        self.assertIn('local: skipped in a cloud session', out)
        self.assertNotIn('ran local', out)
        self.assertTrue((self.home / '.claude').is_dir())

    def test_instructions_only_stops_after_the_instructions_step(self):
        modules = [self.fixture('instructions'), self.fixture('second')]
        status, out, _ = self.main('install', '--instructions-only', modules=modules)
        self.assertEqual((status, re.findall(r'^== (\w+)$', out, re.M)), (0, ['instructions']))

    def test_check_prints_each_steps_checks_and_fails_on_a_FAIL(self):
        status, out, _ = self.main('check', modules=[self.fixture('first'), self.fixture('second', status='skip')])
        self.assertEqual(status, 0)
        self.assertEqual(out, '-- first\n  ok    first is fine\n  info  first again\n'
                              '-- second\n  ok    second is fine\n  skip  second again\n')
        status, out, _ = self.main('check', modules=[self.fixture('first'), self.fixture('bad', status='FAIL')])
        self.assertEqual(status, 1)
        self.assertIn('  FAIL  bad again', out)

    def test_help_lists_each_step_in_order_for_install_and_reversed_for_uninstall(self):
        modules = [self.fixture('first'), self.fixture('second')]
        _, out, _ = self.main('help', modules=modules)
        self.assertRegex(out, r'1\. first +the first step\n +2\. second +the second step')
        _, out, _ = self.main('help', 'uninstall', modules=modules)
        self.assertRegex(out, r'2\. second +the second step undone\n +1\. first +the first step undone')
        status, helped, _ = self.main('install', '--help', modules=modules)
        self.assertEqual((status, helped), (0, self.main('help', modules=modules)[1]))

    def test_an_unknown_argument_prints_the_usage_and_fails(self):
        status, out, err = self.main('install', '--bogus', modules=[self.fixture('first')])
        self.assertEqual((status, out), (1, ''))
        self.assertTrue(err.startswith('[ERR] Unknown argument: --bogus\n'))
        self.assertIn('Usage:', err)


class StepChecksTest(unittest.TestCase):
    """The checks the healthcheck used to hold in shell: mcp and launchd, as (status, message) lines."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name).resolve()
        self.home = folder / 'home'
        self.home.mkdir()
        self.live = folder / 'live'
        (self.live / 'config').mkdir(parents=True)
        shutil.copy(ROOT / 'config/mcp-servers.json', self.live / 'config')
        registry(self.live / 'config', claude=True, agy=True)
        self.servers = [s['name'] for s in json.loads((ROOT / 'config/mcp-servers.json').read_text())['servers']]
        self.options = steps.Options(home=self.home, live=self.live)

    def test_mcp_reads_antigravitys_file_and_skips_a_cli_that_is_not_on_path(self):
        results = mcp.checks(self.options)
        self.assertIn(('skip', 'agy not set up'), results)
        agy_file = self.home / where('agy', 'mcp')
        agy_file.parent.mkdir(parents=True)
        agy_file.write_text(json.dumps({'mcpServers': {self.servers[0]: {}}}))
        with mock.patch('mcp.shutil.which', return_value=None):
            results = mcp.checks(self.options)
        self.assertIn(('ok', f'agy: {self.servers[0]} (in {agy_file.name})'), results)
        self.assertIn(('skip', 'claude not on PATH'), results)
        agy_file.write_text('{}')
        with mock.patch('mcp.shutil.which', return_value=None):
            self.assertIn(('FAIL', f'agy: {self.servers[0]} not in {agy_file}'), mcp.checks(self.options))

    def test_mcp_asks_a_cli_that_is_on_path_what_it_lists(self):
        def says(output):
            done = mock.Mock(stdout=output)
            return mock.patch.multiple('mcp.subprocess', run=mock.Mock(return_value=done)), mock.patch(
                'mcp.shutil.which', return_value='/bin/claude')
        name = self.servers[0]
        for output, expected in ((f'{name}: ok', ('ok', f'claude: {name}')),
                                 (f'{name}: Disabled', ('ok', f'claude: {name} (configured; disabled in this untrusted folder)')),
                                 ('nothing here', ('FAIL', f'claude: {name} not listed'))):
            run_patch, which_patch = says(output)
            with run_patch, which_patch:
                self.assertIn(expected, mcp.checks(self.options))

    def test_launchd_is_ok_only_when_the_job_is_scheduled_and_loaded(self):
        def checks(platform='darwin', claude='/bin/claude', loaded=0):
            with mock.patch('launchd.sys.platform', platform), mock.patch('launchd.shutil.which', return_value=claude), \
                    mock.patch('launchd.subprocess.run', return_value=mock.Mock(returncode=loaded)):
                return launchd.checks(self.options)
        self.assertEqual(checks('linux'), [('skip', 'not macOS: no launchd')])
        self.assertEqual(checks(claude=None), [('skip', 'claude not on PATH: nothing to schedule')])
        plist = self.home / launchd.PLIST
        self.assertEqual(checks(), [('FAIL', f'not scheduled: {plist} missing (run: ai-dotfiles)')])
        plist.parent.mkdir(parents=True)
        plist.write_text('')
        self.assertEqual(checks(), [('ok', f'{launchd.LABEL} loaded')])
        self.assertEqual(checks(loaded=113), [('FAIL', f'{launchd.LABEL} not loaded (run: ai-dotfiles)')])


if __name__ == '__main__':
    unittest.main()
